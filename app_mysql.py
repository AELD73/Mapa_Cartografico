import os
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
import json
import zipfile

import pandas as pd
import shapefile
import pyproj
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, jsonify, send_file,
    redirect, url_for, session, flash
)
from pymysql.err import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from db import get_db, close_db

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
LAYERS_DIR = os.path.join(BASE_DIR, "static", "layers")
os.makedirs(LAYERS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "Epsilon43$")
app.permanent_session_lifetime = timedelta(minutes=3)


# -----------------------
# DB helpers
# -----------------------
@app.teardown_appcontext
def teardown_db(exception):
    close_db(exception)


def create_index_if_not_exists(cursor, table_name, index_name, columns_sql):
    """
    MySQL 5.7 no soporta CREATE INDEX IF NOT EXISTS.
    Por eso revisamos INFORMATION_SCHEMA antes de crear el índice.
    """
    cursor.execute(
        """
        SELECT COUNT(1) AS total
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    exists = cursor.fetchone()["total"]
    if not exists:
        cursor.execute(f"CREATE INDEX {index_name} ON {table_name} ({columns_sql})")


def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visitas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            edad INT,
            origen TEXT,
            destino TEXT,
            creado_en DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pines (
        id INT AUTO_INCREMENT PRIMARY KEY,
        visita_id INT NOT NULL,
        codigo_pin VARCHAR(20) NOT NULL,
        lat DOUBLE NOT NULL,
        lon DOUBLE NOT NULL,
        nom TEXT,
        idu TEXT,
        dentro_malla TINYINT,
        creado_en DATETIME NOT NULL,
        FOREIGN KEY(visita_id) REFERENCES visitas(id)
    ) """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS catalogo_pines (
            codigo VARCHAR(20) PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL,
            categoria ENUM('movilidad','violencia') NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    catalogo = [
        ('STP', 'Sin transporte público', 'movilidad'),
        ('EVP', 'Estacionamiento en vía pública', 'movilidad'),
        ('DEB', 'Deterioro en banqueta', 'movilidad'),
        ('COV', 'Congestión vehicular', 'movilidad'),
        ('BAP', 'Barrera peatonal', 'movilidad'),
        ('CRI', 'Cruce inseguro', 'movilidad'),
        ('CAI', 'Calle insegura', 'movilidad'),
        ('CME', 'Ciclovía en mal estado', 'movilidad'),
        ('CSC', 'Ciclovía sin conexión', 'movilidad'),
        ('VIP', 'Violencia psicológica', 'violencia'),
        ('AEP', 'Acoso sexual en espacios públicos', 'violencia'),
        ('VIO', 'Violación', 'violencia'),
        ('VFI', 'Violencia física', 'violencia'),
        ('FEM', 'Feminicidio', 'violencia'),
        ('VIN', 'Violencia institucional', 'violencia'),
        ('VPA', 'Violencia patrimonial', 'violencia'),
        ('VCO', 'Violencia comunitaria', 'violencia'),
    ]

    cursor.executemany("""
        INSERT IGNORE INTO catalogo_pines (codigo, nombre, categoria)
        VALUES (%s, %s, %s)
    """, catalogo)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role ENUM('admin','user') NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INT PRIMARY KEY,
            center_lon DOUBLE NOT NULL DEFAULT -99.1332,
            center_lat DOUBLE NOT NULL DEFAULT 19.4326,
            zoom DOUBLE NOT NULL DEFAULT 12
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cursor.execute("INSERT IGNORE INTO settings (id) VALUES (1)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS layers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            filename VARCHAR(255) NOT NULL UNIQUE,
            color VARCHAR(20) DEFAULT '#3388ff',
            icon VARCHAR(255),
            created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    create_index_if_not_exists(cursor, "pines", "idx_pines_visita", "visita_id")
    create_index_if_not_exists(cursor, "pines", "idx_pines_codigo", "codigo_pin")
    create_index_if_not_exists(cursor, "pines", "idx_pines_created", "creado_en")
    create_index_if_not_exists(cursor, "visitas", "idx_visitas_created", "creado_en")

    db.commit()


# -----------------------
# Decoradores
# -----------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Inicia sesión para continuar.", "warn")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Inicia sesión para continuar.", "warn")
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            flash("Requiere rol de administrador.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


EXPIRE_REDIRECT_URL = "https://tu-dominio.com/gracias"
EXPIRE_REDIRECT_ENDPOINT = "login"


@app.before_request
def enforce_idle_timeout():
    if "user_id" not in session and "visita_id" not in session:
        return

    now = datetime.utcnow()
    last = session.get("last_activity")

    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt > app.permanent_session_lifetime:
                session.clear()
                flash("Sesión finalizada por inactividad.", "warn")

                if EXPIRE_REDIRECT_ENDPOINT:
                    return redirect(url_for(EXPIRE_REDIRECT_ENDPOINT))

                return redirect(EXPIRE_REDIRECT_URL)
        except Exception:
            session.pop("last_activity", None)

    session["last_activity"] = now.isoformat()
    session.permanent = True


# -----------------------
# Rutas principales
# -----------------------
@app.route("/")
def index():
    folio = request.args.get("folio")

    if "user_id" in session:
        return render_template(
            "index.html",
            user=session.get("username"),
            role=session.get("role"),
            folio=folio,
        )

    if "visita_id" in session:
        return render_template("index.html", user=None, role=None, folio=folio)

    return render_template("login.html")


# -----------------------
# API Pines
# -----------------------
@app.route("/api/pins", methods=["GET"])
def get_pins():
    db = get_db()
    cursor = db.cursor()

    q = """
        SELECT id, visita_id, codigo_pin, nom, idu, lon, lat, creado_en
        FROM pines
    """
    params = []
    clauses = []

    date_str = request.args.get("date")
    start = request.args.get("start")
    end = request.args.get("end")
    month = request.args.get("month")
    year = request.args.get("year")

    if date_str:
        try:
            params.append(datetime.fromisoformat(date_str).date().isoformat())
        except ValueError:
            return jsonify({"error": "date inválida (YYYY-MM-DD)"}), 400
        clauses.append("DATE(creado_en) = %s")

    if month:
        try:
            y, m = month.split("-")
            datetime(int(y), int(m), 1)
        except Exception:
            return jsonify({"error": "month inválido (YYYY-MM)"}), 400
        clauses.append("DATE_FORMAT(creado_en, '%%Y-%%m') = %s")
        params.append(month)

    if year:
        if not (year.isdigit() and len(year) == 4):
            return jsonify({"error": "year inválido (YYYY)"}), 400
        clauses.append("YEAR(creado_en) = %s")
        params.append(int(year))

    if start or end:
        if start:
            try:
                datetime.fromisoformat(start)
            except ValueError:
                return jsonify({"error": "start inválida (YYYY-MM-DD)"}), 400
            clauses.append("DATE(creado_en) >= %s")
            params.append(start)

        if end:
            try:
                datetime.fromisoformat(end)
            except ValueError:
                return jsonify({"error": "end inválida (YYYY-MM-DD)"}), 400
            clauses.append("DATE(creado_en) <= %s")
            params.append(end)

    if clauses:
        q += " WHERE " + " AND ".join(clauses)

    q += " ORDER BY id DESC"

    cursor.execute(q, params)
    rows = cursor.fetchall()
    return jsonify(rows), 200


@app.route("/api/pins", methods=["POST"])
def add_pin():
    payload = request.get_json(force=True)

    lon = payload.get("lon")
    lat = payload.get("lat")
    codigo_pin = (payload.get("codigo_pin") or "").strip()
    nom = (payload.get("nom") or "").strip()
    idu = (payload.get("idu") or "").strip()

    if lon is None or lat is None:
        return jsonify({"error": "Faltan coordenadas lon/lat"}), 400
    if not codigo_pin:
        return jsonify({"error": "Falta código del pin (codigo_pin)"}), 400

    visita_id = session.get("visita_id")
    if not visita_id:
        return jsonify({"error": "No hay visita activa en la sesión."}), 400

    dentro = point_in_polygon(float(lat), float(lon), polygon_coords)
    dentro_val = 1 if dentro else 0

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """
        INSERT INTO pines (visita_id, codigo_pin, lat, lon, nom, idu, dentro_malla, creado_en)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            int(visita_id),
            codigo_pin,
            float(lat),
            float(lon),
            nom or None,
            idu or None,
            dentro_val,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db.commit()

    return jsonify({"ok": True, "id": cursor.lastrowid}), 201


# -----------------------
# API de Configuración
# -----------------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id = 1")
    row = cursor.fetchone()
    return jsonify(row), 200


@app.route("/api/settings", methods=["POST"])
@admin_required
def save_settings():
    data = request.get_json(force=True)
    try:
        lon = float(data.get("center_lon"))
        lat = float(data.get("center_lat"))
        zoom = float(data.get("zoom"))
    except (TypeError, ValueError):
        return jsonify({"error": "Valores inválidos"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE settings SET center_lon = %s, center_lat = %s, zoom = %s WHERE id = 1",
        (lon, lat, zoom),
    )
    db.commit()
    return jsonify({"ok": True}), 200


# -----------------------
# Exportar Excel
# -----------------------
@app.route("/exportar/excel", methods=["GET"])
@admin_required
def export_excel():
    db = get_db()

    date_str = request.args.get("date")
    start = request.args.get("start")
    end = request.args.get("end")
    month = request.args.get("month")
    year = request.args.get("year")

    base = """
        SELECT id, visita_id, codigo_pin, nom, idu, lon, lat, dentro_malla, creado_en
        FROM pines
    """
    params = []
    clauses = []

    if date_str:
        try:
            datetime.fromisoformat(date_str)
        except ValueError:
            return "date inválida (YYYY-MM-DD)", 400
        clauses.append("DATE(creado_en) = %s")
        params.append(date_str)

    if month:
        try:
            y, m = month.split("-")
            datetime(int(y), int(m), 1)
        except Exception:
            return "month inválido (YYYY-MM)", 400
        clauses.append("DATE_FORMAT(creado_en, '%%Y-%%m') = %s")
        params.append(month)

    if year:
        if not (year.isdigit() and len(year) == 4):
            return "year inválido (YYYY)", 400
        clauses.append("YEAR(creado_en) = %s")
        params.append(int(year))

    if start or end:
        if start:
            try:
                datetime.fromisoformat(start)
            except ValueError:
                return "start inválida (YYYY-MM-DD)", 400
            clauses.append("DATE(creado_en) >= %s")
            params.append(start)

        if end:
            try:
                datetime.fromisoformat(end)
            except ValueError:
                return "end inválida (YYYY-MM-DD)", 400
            clauses.append("DATE(creado_en) <= %s")
            params.append(end)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    df = pd.read_sql_query(base + where + " ORDER BY id", db, params=params)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Pines", index=False)
        ws = writer.sheets["Pines"]
        for i, col in enumerate(df.columns):
            width = min(
                max([len(str(x)) for x in df[col].astype(str).values] + [len(col)]) + 2,
                40,
            )
            ws.set_column(i, i, width)
    output.seek(0)

    kind = (
        f"dia_{date_str}"
        if date_str
        else f"mes_{month}"
        if month
        else f"anio_{year}"
        if year
        else (f"{start}_a_{end}" if (start or end) else "todo")
    )
    filename = f"pines_{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# -----------------------
# Vistas de administración
# -----------------------
@app.route("/admin")
@admin_required
def admin_panel():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, username FROM users WHERE role = 'admin' ORDER BY username")
    admins = cursor.fetchall()

    cursor.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id = 1")
    s = cursor.fetchone()

    cursor.execute("SELECT * FROM layers ORDER BY created_at DESC")
    layers = cursor.fetchall()

    return render_template("panel_administracion.html", admins=admins, settings=s, layers=layers)


@app.route("/admin/create", methods=["POST"])
@admin_required
def admin_create():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username or not password:
        flash("Usuario y contraseña son obligatorios.", "error")
        return redirect(url_for("admin_panel"))

    pw_hash = generate_password_hash(password)
    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, pw_hash, "admin"),
        )
        db.commit()
        flash("Administrador creado.", "ok")
    except IntegrityError:
        db.rollback()
        flash("Ese usuario ya existe.", "error")

    return redirect(url_for("admin_panel"))


@app.route("/admin/main")
@admin_required
def main_admin():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id = 1")
    s = cursor.fetchone()

    return render_template(
        "main_admin.html",
        settings=s,
        user=session.get("username"),
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True
            session["last_activity"] = datetime.utcnow().isoformat()
            flash(f"Bienvenido, {user['username']}", "ok")
            return redirect(url_for("admin_panel"))

        flash("Usuario o contraseña incorrectos", "error")

    return render_template("inicio_sesion_admin.html")


# -----------------------
# Registro/Login de administrador
# -----------------------
@app.route("/admin/registro", methods=["GET", "POST"])
def admin_register():
    init_db()
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(1) AS c FROM users WHERE role = 'admin'")
    existing_admin = cursor.fetchone()["c"]

    if existing_admin > 0 and session.get("role") != "admin":
        flash("Ya existe un administrador. Inicia sesión o pide alta.", "warn")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username or not password:
            flash("Usuario y contraseña son obligatorios.", "error")
            return render_template("registro_admin.html")

        pw_hash = generate_password_hash(password)
        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, pw_hash, "admin"),
            )
            db.commit()
            flash("Administrador creado. Ya puedes iniciar sesión.", "ok")
            return redirect(url_for("login"))
        except IntegrityError:
            db.rollback()
            flash("Ese usuario ya existe.", "error")

    return render_template("registro_admin.html")


# -----------------------
# Login de participantes
# -----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    edad_raw = request.form.get("edad")
    origen = (request.form.get("origen") or "").strip()
    destino = (request.form.get("destino") or "").strip()

    try:
        edad = int(edad_raw)
    except (TypeError, ValueError):
        flash("Edad inválida.", "error")
        return render_template("login.html")

    if not origen or not destino:
        flash("Origen y destino son obligatorios.", "error")
        return render_template("login.html")

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """
        INSERT INTO visitas (edad, origen, destino, creado_en)
        VALUES (%s, %s, %s, %s)
        """,
        (
            edad,
            origen,
            destino,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db.commit()

    visita_id = cursor.lastrowid
    session["visita_id"] = visita_id
    session.permanent = True
    session["last_activity"] = datetime.utcnow().isoformat()

    return redirect(url_for("index", folio=visita_id))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("https://labestudiosurbanos.azc.uam.mx/")


@app.route("/api/pins/bulk", methods=["POST"])
def add_pins_bulk():
    payload = request.get_json(force=True) or {}
    pins = payload.get("pins")

    if not isinstance(pins, list) or len(pins) == 0:
        return jsonify({"error": "No se recibieron pines (pins[])."}), 400

    visita_id = session.get("visita_id")
    if not visita_id:
        return jsonify({"error": "No hay visita activa en la sesión."}), 400

    rows_to_insert = []
    for i, p in enumerate(pins):
        try:
            lon = p.get("lon")
            lat = p.get("lat")
            codigo_pin = (p.get("codigo_pin") or "").strip()
            nom = (p.get("nom") or "").strip()
            idu = (p.get("idu") or "").strip()

            if lon is None or lat is None:
                return jsonify({"error": f"Pin #{i}: faltan coordenadas lon/lat"}), 400
            if not codigo_pin:
                return jsonify({"error": f"Pin #{i}: falta codigo_pin"}), 400

            dentro = point_in_polygon(float(lat), float(lon), polygon_coords)
            dentro_val = 1 if dentro else 0

            rows_to_insert.append((
                int(visita_id),
                codigo_pin,
                float(lat),
                float(lon),
                nom or None,
                idu or None,
                dentro_val,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
        except Exception:
            return jsonify({"error": f"Pin #{i}: datos inválidos"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.executemany(
        """
        INSERT INTO pines (visita_id, codigo_pin, lat, lon, nom, idu, dentro_malla, creado_en)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows_to_insert,
    )
    db.commit()

    return jsonify({"ok": True, "saved": len(rows_to_insert)}), 201


# -----------------------
# Gestión de capas
# -----------------------
@app.route("/admin/upload_layer", methods=["POST"])
@admin_required
def upload_layer():
    if "layer_file" not in request.files:
        flash("No se seleccionó archivo", "error")
        return redirect(url_for("admin_panel"))

    file = request.files["layer_file"]
    if file.filename == "":
        flash("Nombre de archivo vacío", "error")
        return redirect(url_for("admin_panel"))

    name = request.form.get("layer_name") or os.path.splitext(file.filename)[0]
    color = request.form.get("layer_color") or "#3388ff"
    overwrite = request.form.get("overwrite") == "on"

    icon_file = request.files.get("layer_icon")
    icon_filename = None

    if icon_file and icon_file.filename != "":
        if not icon_file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")):
            flash("Icono inválido. Usa PNG, JPG o SVG.", "error")
            return redirect(url_for("admin_panel"))

        ext = os.path.splitext(icon_file.filename)[1].lower()
        icon_name = f"{secure_filename(name)}_icon{ext}"
        icon_path = os.path.join(LAYERS_DIR, icon_name)
        icon_file.save(icon_path)
        icon_filename = icon_name

    if not file.filename.lower().endswith(".zip"):
        flash("Solo se permiten archivos .zip", "error")
        return redirect(url_for("admin_panel"))

    clean_name = secure_filename(name)
    json_filename = f"{clean_name}.json"
    json_path = os.path.join(LAYERS_DIR, json_filename)

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM layers WHERE filename = %s", (json_filename,))
    existing = cursor.fetchone()

    if existing and not overwrite:
        flash("Ya existe una capa con ese nombre. Cambia el nombre o marca sobrescribir.", "error")
        return redirect(url_for("admin_panel"))

    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdirname:
            zip_path = os.path.join(tmpdirname, "upload.zip")
            file.save(zip_path)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(tmpdirname)

            shp_file = None
            for root, dirs, files in os.walk(tmpdirname):
                for f in files:
                    if f.lower().endswith(".shp"):
                        shp_file = os.path.join(root, f)
                        break
                if shp_file:
                    break

            if not shp_file:
                flash("El ZIP no contiene ningún archivo .shp", "error")
                return redirect(url_for("admin_panel"))

            sf = shapefile.Reader(shp_file)
            fields = [x[0] for x in sf.fields][1:]
            records = sf.records()
            shapes = sf.shapes()

            transformer = pyproj.Transformer.from_crs("epsg:32614", "epsg:4326", always_xy=True)

            features = []

            def reproject_coords(coords):
                if isinstance(coords[0], (list, tuple)):
                    return [reproject_coords(c) for c in coords]

                x, y = coords[0], coords[1]
                if x > 180 or x < -180:
                    lon, lat = transformer.transform(x, y)
                    return [lon, lat]
                return [x, y]

            for i, shp in enumerate(shapes):
                rec = records[i]
                geo = shp.__geo_interface__

                if geo["type"] == "Point":
                    geo["coordinates"] = reproject_coords(geo["coordinates"])
                elif geo["type"] in ["Polygon", "LineString", "MultiPolygon", "MultiLineString"]:
                    geo["coordinates"] = reproject_coords(geo["coordinates"])

                props = {}
                for j, field_name in enumerate(fields):
                    val = rec[j]
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    props[field_name] = val

                features.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": geo,
                })

            geojson = {
                "type": "FeatureCollection",
                "features": features,
            }

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(geojson, f)

        if existing:
            update_sql = "UPDATE layers SET created_at = %s, color = %s"
            params = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), color]

            if icon_filename:
                update_sql += ", icon = %s"
                params.append(icon_filename)

            update_sql += " WHERE id = %s"
            params.append(existing["id"])

            cursor.execute(update_sql, params)
            flash("Capa actualizada correctamente.", "ok")
        else:
            cursor.execute(
                """
                INSERT INTO layers (name, filename, color, icon, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    json_filename,
                    color,
                    icon_filename,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            flash("Capa subida y procesada correctamente.", "ok")

        db.commit()

    except Exception as e:
        db.rollback()
        flash(f"Error procesando shapefile: {str(e)}", "error")

    return redirect(url_for("admin_panel"))


@app.route("/admin/delete_layer/<filename>", methods=["POST"])
@admin_required
def delete_layer(filename):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM layers WHERE filename = %s", (filename,))
    db.commit()

    path = os.path.join(LAYERS_DIR, secure_filename(filename))
    if os.path.exists(path):
        os.remove(path)

    flash("Capa eliminada.", "ok")
    return redirect(url_for("admin_panel"))


@app.route("/api/layers")
def get_layers_api():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name, filename, color, icon FROM layers")
    layers = cursor.fetchall()

    data = []
    for l in layers:
        icon_url = url_for("static", filename=f"layers/{l['icon']}") if l["icon"] else None
        data.append({
            "name": l["name"],
            "color": l["color"] or "#3388ff",
            "icon": icon_url,
            "url": url_for("static", filename=f"layers/{l['filename']}"),
        })

    return jsonify(data)


# -----------------------
# Descargar base completa en Excel
# -----------------------
@app.route("/admin/download")
@admin_required
def download_db():
    db = get_db()
    output = BytesIO()

    queries = {
        "visitas": "SELECT * FROM visitas ORDER BY id",
        "pines": "SELECT * FROM pines ORDER BY id",
        "catalogo_pines": "SELECT * FROM catalogo_pines ORDER BY codigo",
        "settings": "SELECT * FROM settings ORDER BY id",
        "layers": "SELECT * FROM layers ORDER BY id",
        "users": "SELECT id, username, role FROM users ORDER BY id",
    }

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        for sheet_name, query in queries.items():
            df = pd.read_sql_query(query, db)
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            ws = writer.sheets[sheet_name[:31]]
            for i, col in enumerate(df.columns):
                width = min(
                    max([len(str(x)) for x in df[col].astype(str).values] + [len(col)]) + 2,
                    40,
                )
                ws.set_column(i, i, width)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="base_completa.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# -----------------------
# Implementación de identificador para la malla
# -----------------------
POLYGON_PATH = os.path.join(BASE_DIR, "static", "layers", "Entorno_Urbano_UAM_A.json")

with open(POLYGON_PATH, encoding="utf-8") as f:
    polygon_data = json.load(f)

polygon_coords = polygon_data["features"][0]["geometry"]["coordinates"][0]


def point_in_polygon(lat, lon, polygon):
    x = lon
    y = lat
    inside = False

    n = len(polygon)
    p1x, p1y = polygon[0]

    for i in range(n + 1):
        p2x, p2y = polygon[i % n]

        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x

                    if p1x == p2x or x <= xinters:
                        inside = not inside

        p1x, p1y = p2x, p2y

    return inside


# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    try:
        with app.app_context():
            init_db()

        app.run(host="0.0.0.0", port=8889, debug=True)

    except OperationalError as e:
        print("No se pudo conectar a MySQL.")
        print("Revisa tu archivo .env, el host, puerto, usuario, contraseña y que tengas acceso a la red.")
        print(e)
