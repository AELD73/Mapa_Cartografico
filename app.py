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
    # Tabla de pines
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
    # Tabla de usuarios con rol
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user'))
        )
    """)
    db.commit()

# -----------------------
# Decoradores de auth
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
# Rutas
# -----------------------
@app.route("/")
def index():
    init_db()
    return render_template("index.html", user=session.get("username"), role=session.get("role"))

# --- API pins públicas (colocar pines y verlos)
@app.route("/api/pins", methods=["GET"])
def get_pins():
    db = get_db()
    rows = db.execute("SELECT id, titulo, descripcion, lon, lat, creado_en FROM pins ORDER BY id DESC").fetchall()
    data = [dict(r) for r in rows]
    return jsonify(data), 200

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

# --- Exportar Excel (solo admin)
@app.route("/exportar/excel", methods=["GET"])
@admin_required
def export_excel():
    db = get_db()
    df = pd.read_sql_query("SELECT id, titulo, descripcion, lon, lat, creado_en FROM pins ORDER BY id", db)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Pines", index=False)
        wb = writer.book
        ws = writer.sheets["Pines"]
        for idx, col in enumerate(df.columns):
            max_len = max([len(str(x)) for x in df[col].astype(str).values] + [len(col)])
            ws.set_column(idx, idx, min(max_len + 2, 40))
    output.seek(0)

    filename = f"pines_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --- Auth: registro admin, login, logout
@app.route("/admin/registro", methods=["GET", "POST"])
def admin_register():
    """
    Registra un ADMIN. Política:
      - Si NO existe ningún admin, cualquiera puede crear el primero.
      - Si ya existe admin, solo un admin logueado puede crear más admins.
    """
    init_db()
    db = get_db()
    existing_admin = db.execute("SELECT COUNT(1) c FROM users WHERE role='admin'").fetchone()["c"]

    if existing_admin > 0 and session.get("role") != "admin":
        flash("Ya existe un administrador. Pídele que te cree una cuenta o inicia sesión.", "warn")
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
                (username, pw_hash, "admin")
            )
            db.commit()
            flash("Administrador creado correctamente. Ahora puedes iniciar sesión.", "ok")
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
