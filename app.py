import os
import sqlite3
from datetime import datetime
from functools import wraps
from io import BytesIO

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
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    # Pines
    db.execute("""
        CREATE TABLE IF NOT EXISTS pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            descripcion TEXT,
            lon REAL NOT NULL,
            lat REAL NOT NULL,
            creado_en TEXT NOT NULL
        )
    """)
    # Usuarios
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user'))
        )
    """)
    # Settings
    db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            center_lon REAL NOT NULL DEFAULT -99.1332,
            center_lat REAL NOT NULL DEFAULT 19.4326,
            zoom REAL NOT NULL DEFAULT 12
        )
    """)
    db.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
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
    init_db()
    return render_template("index.html", user=session.get("username"), role=session.get("role"))

# -----------------------
# API Pines
# -----------------------
@app.route("/api/pins", methods=["GET"])
def get_pins():
    db = get_db()
    q = "SELECT id, titulo, descripcion, lon, lat, creado_en FROM pins"
    params, clauses = [], []

    date_str = request.args.get("date")
    start = request.args.get("start")
    end = request.args.get("end")
    month = request.args.get("month")
    year  = request.args.get("year")

    if date_str:
        clauses.append("strftime('%Y-%m-%d', creado_en) = ?")
        try: params.append(datetime.fromisoformat(date_str).date().isoformat())
        except ValueError: return jsonify({"error": "date inválida (YYYY-MM-DD)"}), 400

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
            try: datetime.fromisoformat(start)
            except ValueError: return jsonify({"error": "start inválida (YYYY-MM-DD)"}), 400
            clauses.append("date(creado_en) >= ?"); params.append(start)
        if end:
            try: datetime.fromisoformat(end)
            except ValueError: return jsonify({"error": "end inválida (YYYY-MM-DD)"}), 400
            clauses.append("date(creado_en) <= ?"); params.append(end)

    if clauses: q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY id DESC"
    rows = db.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows]), 200

@app.route("/api/pins", methods=["POST"])
def add_pin():
    payload = request.get_json(force=True)
    lon = payload.get("lon")
    lat = payload.get("lat")
    titulo = (payload.get("titulo") or "").strip()
    descripcion = (payload.get("descripcion") or "").strip()

    if lon is None or lat is None:
        return jsonify({"error": "Faltan coordenadas lon/lat"}), 400

    db = get_db()
    db.execute(
        "INSERT INTO pins (titulo, descripcion, lon, lat, creado_en) VALUES (?, ?, ?, ?, ?)",
        (titulo, descripcion, float(lon), float(lat), datetime.now().isoformat(timespec="seconds"))
    )
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return jsonify({"ok": True, "id": new_id}), 201

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
    db.execute("UPDATE settings SET center_lon=?, center_lat=?, zoom=? WHERE id=1", (lon, lat, zoom))
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
    year  = request.args.get("year")

    base = "SELECT id, titulo, descripcion, lon, lat, creado_en FROM pins"
    params, clauses = [], []

    if date_str:
        try: datetime.fromisoformat(date_str)
        except ValueError: return "date inválida (YYYY-MM-DD)", 400
        clauses.append("strftime('%Y-%m-%d', creado_en) = ?"); params.append(date_str)

    if month:
        try:
            y, m = month.split("-")
            datetime(int(y), int(m), 1)
        except Exception:
            return "month inválido (YYYY-MM)", 400
        clauses.append("strftime('%Y-%m', creado_en) = ?"); params.append(month)

    if year:
        if not (year.isdigit() and len(year) == 4):
            return "year inválido (YYYY)", 400
        clauses.append("strftime('%Y', creado_en) = ?"); params.append(year)

    if start or end:
        if start:
            try: datetime.fromisoformat(start)
            except ValueError: return "start inválida (YYYY-MM-DD)", 400
            clauses.append("date(creado_en) >= ?"); params.append(start)
        if end:
            try: datetime.fromisoformat(end)
            except ValueError: return "end inválida (YYYY-MM-DD)", 400
            clauses.append("date(creado_en) <= ?"); params.append(end)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    df = pd.read_sql_query(base + where + " ORDER BY id", db, params=params)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Pines", index=False)
        ws = writer.sheets["Pines"]
        for i, col in enumerate(df.columns):
            width = min(max([len(str(x)) for x in df[col].astype(str).values] + [len(col)]) + 2, 40)
            ws.set_column(i, i, width)
    output.seek(0)

    kind = (
        f"dia_{date_str}" if date_str else
        f"mes_{month}" if month else
        f"anio_{year}" if year else
        (f"{start}_a_{end}" if (start or end) else "todo")
    )
    filename = f"pines_{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------
# Vistas de administración
# -----------------------
@app.route("/admin")
@admin_required
def admin_panel():
    db = get_db()
    admins = db.execute("SELECT id, username FROM users WHERE role='admin' ORDER BY username").fetchall()
    s = db.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id=1").fetchone()
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
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                   (username, pw_hash, "admin"))
        db.commit()
        flash("Administrador creado.", "ok")
    except sqlite3.IntegrityError:
        flash("Ese usuario ya existe.", "error")
    return redirect(url_for("admin_panel"))

@app.route("/admin/main")
@admin_required
def main_admin():
    db = get_db()
    s = db.execute("SELECT center_lon, center_lat, zoom FROM settings WHERE id=1").fetchone()
    return render_template("main_admin.html", settings=s, user=session.get("username"))

# -----------------------
# Registro/Login
# -----------------------
@app.route("/admin/registro", methods=["GET", "POST"])
def admin_register():
    init_db()
    db = get_db()
    existing_admin = db.execute("SELECT COUNT(1) c FROM users WHERE role='admin'").fetchone()["c"]

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
            db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                       (username, pw_hash, "admin"))
            db.commit()
            flash("Administrador creado. Ya puedes iniciar sesión.", "ok")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Ese usuario ya existe.", "error")

    return render_template("admin_register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    init_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        db = get_db()
        row = db.execute("SELECT id, username, password_hash, role FROM users WHERE username=?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            session["role"] = row["role"]
            flash("Sesión iniciada.", "ok")
            dest = request.args.get("next") or url_for("index")
            return redirect(dest)
        else:
            flash("Usuario o contraseña inválidos.", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("index"))

# -----------------------
# Main
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
