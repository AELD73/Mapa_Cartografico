import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
import json

import pandas as pd
from flask import (
    Flask, render_template, request, jsonify, send_file, g,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "pines.db")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "cambia_esta_llave_supersecreta")

# -----------------------
# DB helpers
# -----------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    cursor = db.cursor()

    # Tabla para las visitas (datos del formulario login.html)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visitas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edad INTEGER,
            origen TEXT,
            destino TEXT,
            creado_en TEXT NOT NULL
        )
    """)

    # Pins colocados en el mapa, ligados a una visita
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visita_id INTEGER NOT NULL,
        codigo_pin TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        nom TEXT,
        idu TEXT,
        creado_en TEXT NOT NULL,
        FOREIGN KEY(visita_id) REFERENCES visitas(id)
        )
    """)


    # Catálogo de tipos de pines (movilidad / violencia)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS catalogo_pines (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            categoria TEXT NOT NULL CHECK(categoria IN ('movilidad','violencia'))
        )
    """)

    cursor.executemany("""
        INSERT OR IGNORE INTO catalogo_pines (codigo, nombre, categoria)
        VALUES (?, ?, ?)
    """, [
        ('STP','Sin transporte público','movilidad'),
        ('EVP','Estacionamiento en vía pública','movilidad'),
        ('DEB','Deterioro en banqueta','movilidad'),
        ('COV','Congestión vehicular','movilidad'),
        ('BAP','Barrera peatonal','movilidad'),
        ('CRI','Cruce inseguro','movilidad'),
        ('CAI','Calle insegura','movilidad'),
        ('CME','Ciclovía en mal estado','movilidad'),
        ('CSC','Ciclovía sin conexión','movilidad'),
        ('VIP','Violencia psicológica','violencia'),
        ('AEP','Acoso sexual en espacios públicos','violencia'),
        ('VIO','Violación','violencia'),
        ('VFI','Violencia física','violencia'),
        ('FEM','Feminicidio','violencia'),
        ('VIN','Violencia institucional','violencia'),
        ('VPA','Violencia patrimonial','violencia'),
        ('VCO','Violencia comunitaria','violencia')
    ])

    # Usuarios (para panel de administración)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user'))
        )
    """)

    # Configuración del mapa
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            center_lon REAL NOT NULL DEFAULT -99.1332,
            center_lat REAL NOT NULL DEFAULT 19.4326,
            zoom REAL NOT NULL DEFAULT 12
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")

    # Índices para acelerar consultas
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pines_visita ON pines(visita_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pines_codigo ON pines(codigo_pin)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pines_created ON pines(creado_en)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_visitas_created ON visitas(creado_en)")

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


# -----------------------
# Rutas principales
# -----------------------
@app.route("/")
def index():
    """
    # Si hay admin logueado
    if "user_id" in session:
        return render_template("index.html", user=session.get("username"), role=session.get("role"))

    # Si hay una visita registrada (participante normal)
    if "visita_id" in session:
        return render_template("index.html", user=None, role=None)

    # Si no ha llenado formulario, mostrar login.html (encuesta)
    return render_template("login.html")
    """
    return render_template("index.html")
    


# -----------------------
# API Pines
# -----------------------
@app.route("/api/pins", methods=["GET"])
def get_pins():
    db = get_db()
    # Usamos la tabla pines (con e) que definimos en init_db
    q = """
        SELECT id, visita_id, codigo_pin, nom, idu, lon, lat, creado_en
        FROM pines
    """
    params, clauses = [], []

    date_str = request.args.get("date")
    start = request.args.get("start")
    end = request.args.get("end")
    month = request.args.get("month")
    year = request.args.get("year")

    if date_str:
        clauses.append("strftime('%Y-%m-%d', creado_en) = ?")
        try:
            params.append(datetime.fromisoformat(date_str).date().isoformat())
        except ValueError:
            return jsonify({"error": "date inválida (YYYY-MM-DD)"}), 400

    if month:
        try:
            y, m = month.split("-")
            datetime(int(y), int(m), 1)
        except Exception:
            return jsonify({"error": "month inválido (YYYY-MM)"}), 400
        clauses.append("strftime('%Y-%m', creado_en) = ?")
        params.append(month)

    if year:
        if not (year.isdigit() and len(year) == 4):
            return jsonify({"error": "year inválido (YYYY)"}), 400
        clauses.append("strftime('%Y', creado_en) = ?")
        params.append(year)

    if start or end:
        if start:
            try:
                datetime.fromisoformat(start)
            except ValueError:
                return jsonify({"error": "start inválida (YYYY-MM-DD)"}), 400
            clauses.append("date(creado_en) >= ?")
            params.append(start)
        if end:
            try:
                datetime.fromisoformat(end)
            except ValueError:
                return jsonify({"error": "end inválida (YYYY-MM-DD)"}), 400
            clauses.append("date(creado_en) <= ?")
            params.append(end)

    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY id DESC"

    rows = db.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows]), 200


@app.route("/api/pins", methods=["POST"])
def add_pin():
    # Intentamos leer JSON primero
    payload = request.get_json(silent=True)
    if payload is None:
        # Si no viene JSON, intentamos con form data
        if request.form:
            payload = request.form.to_dict()
        else:
            payload = request.values.to_dict()

    print("DEBUG /api/pins payload:", payload)

    if not payload:
        print("DEBUG /api/pins: payload vacío")
        return jsonify({"ok": False, "error": "Payload vacío"}), 400

    # Aceptamos lon o lng (muchos mapas usan lng)
    lon = payload.get("lon")
    if lon is None:
        lon = payload.get("lng")

    lat = payload.get("lat")

    # Soportamos tanto formato nuevo (codigo_pin, nom, idu)
    # como el viejo (titulo, descripcion)
    codigo_pin = (payload.get("codigo_pin")
                  or payload.get("titulo")
                  or "").strip()
    nom = (payload.get("nom")
           or payload.get("descripcion")
           or "").strip()
    idu = (payload.get("idu") or "").strip()

    if lon is None or lat is None:
        print("DEBUG /api/pins: faltan coordenadas", lon, lat)
        return jsonify({
            "ok": False,
            "error": "Faltan coordenadas lon/lat o lng/lat",
            "payload": payload
        }), 400

    # Si no llega ningún código/título, le ponemos uno genérico
    if not codigo_pin:
        print("DEBUG /api/pins: no vino codigo_pin/titulo, usando 'SIN_CODIGO'")
        codigo_pin = "SIN_CODIGO"

    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError) as e:
        print("DEBUG /api/pins: error convirtiendo lon/lat a float:", e)
        return jsonify({"ok": False, "error": "Coordenadas inválidas", "payload": payload}), 400

    db = get_db()
    cursor = db.cursor()

    # Intentamos recuperar visita_id desde la sesión
    visita_id = session.get("visita_id")

    # Si no hay visita_id, creamos una visita genérica para no perder el pin
    if not visita_id:
        print("DEBUG /api/pins: no hay visita_id en sesión, creando visita genérica")
        cursor.execute(
            """
            INSERT INTO visitas (edad, origen, destino, creado_en)
            VALUES (?, ?, ?, ?)
            """,
            (None, "Desconocido", "Desconocido",
             datetime.now().isoformat(timespec="seconds"))
        )
        db.commit()
        visita_id = cursor.lastrowid
        session["visita_id"] = visita_id

    # Insertamos el pin ligado a la visita
    try:
        cursor.execute(
            """
            INSERT INTO pines (visita_id, codigo_pin, lat, lon, nom, idu, creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(visita_id),
                codigo_pin,
                lat_f,
                lon_f,
                nom or None,
                idu or None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.commit()
    except Exception as e:
        import traceback
        print("DEBUG /api/pins: EXCEPCIÓN al insertar pin")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

    new_id = cursor.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    print("DEBUG /api/pins: insertado pin_id =", new_id, "para visita_id =", visita_id)

    return jsonify({"ok": True, "id": new_id, "visita_id": visita_id}), 201

# -----------------------
# API Settings
# -----------------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    db = get_db()
    row = db.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id=1").fetchone()
    return jsonify(dict(row)), 200


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
    db.execute(
        "UPDATE settings SET center_lon=?, center_lat=?, zoom=? WHERE id=1",
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
        SELECT id, visita_id, codigo_pin, nom, idu, lon, lat, creado_en
        FROM pines
    """
    params, clauses = [], []

    if date_str:
        try:
            datetime.fromisoformat(date_str)
        except ValueError:
            return "date inválida (YYYY-MM-DD)", 400
        clauses.append("strftime('%Y-%m-%d', creado_en) = ?")
        params.append(date_str)

    if month:
        try:
            y, m = month.split("-")
            datetime(int(y), int(m), 1)
        except Exception:
            return "month inválido (YYYY-MM)", 400
        clauses.append("strftime('%Y-%m', creado_en) = ?")
        params.append(month)

    if year:
        if not (year.isdigit() and len(year) == 4):
            return "year inválido (YYYY)", 400
        clauses.append("strftime('%Y', creado_en) = ?")
        params.append(year)

    if start or end:
        if start:
            try:
                datetime.fromisoformat(start)
            except ValueError:
                return "start inválida (YYYY-MM-DD)", 400
            clauses.append("date(creado_en) >= ?")
            params.append(start)
        if end:
            try:
                datetime.fromisoformat(end)
            except ValueError:
                return "end inválida (YYYY-MM-DD)", 400
            clauses.append("date(creado_en) <= ?")
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
    admins = db.execute(
        "SELECT id, username FROM users WHERE role='admin' ORDER BY username"
    ).fetchall()
    s = db.execute(
        "SELECT center_lon, center_lat, zoom FROM settings WHERE id=1"
    ).fetchone()
    return render_template("admin_panel.html", admins=admins, settings=s)


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
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            (username, pw_hash, "admin"),
        )
        db.commit()
        flash("Administrador creado.", "ok")
    except sqlite3.IntegrityError:
        flash("Ese usuario ya existe.", "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/main")
@admin_required
def main_admin():
    db = get_db()
    s = db.execute(
        "SELECT center_lon, center_lat, zoom FROM settings WHERE id=1"
    ).fetchone()
    return render_template(
        "main_admin.html", settings=s, user=session.get("username")
    )


# -----------------------
# Registro/Login de administrador
# -----------------------
@app.route("/admin/registro", methods=["GET", "POST"])
def admin_register():
    init_db()
    db = get_db()
    existing_admin = db.execute(
        "SELECT COUNT(1) c FROM users WHERE role='admin'"
    ).fetchone()["c"]

    if existing_admin > 0 and session.get("role") != "admin":
        flash("Ya existe un administrador. Inicia sesión o pide alta.", "warn")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Usuario y contraseña son obligatorios.", "error")
            return render_template("admin_register.html")

        pw_hash = generate_password_hash(password)
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                (username, pw_hash, "admin"),
            )
            db.commit()
            flash("Administrador creado. Ya puedes iniciar sesión.", "ok")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.", "error")

    return render_template("admin_register.html")


# -----------------------
# Login de participantes (formulario login.html)
# -----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Muestra el formulario (edad, origen, destino, etc.)
        return render_template("login.html")

    # POST: viene del formulario login.html
    edad_raw = request.form.get("edad")
    origen = (request.form.get("origen") or "").strip()
    destino = (request.form.get("destino") or "").strip()

    # Validaciones básicas (ajusta según tu HTML)
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
        VALUES (?, ?, ?, ?)
        """,
        (edad, origen, destino, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()

    visita_id = cursor.lastrowid
    session["visita_id"] = visita_id

    flash(f"Gracias por tu participación. Tu folio es: {visita_id}", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("https://desarrollophp2.azc.uam.mx/labestudiosurbanos/index.html"))


# -----------------------
# Main
# -----------------------
# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    # Inicializamos la BD al arrancar la app
    with app.app_context():
        init_db()

    app.run(host="0.0.0.0", port=3000, debug=True)

