from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import sqlite3, os, datetime, io, jwt, openpyxl, json, sys

SECRET = os.getenv("ADMIN_SECRET", "cambia-esto")
DB_PATH = "db.sqlite"
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

app = Flask(__name__, static_folder=None)  # desactivamos static por defecto
CORS(app)

def init_db():
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with sqlite3.connect(DB_PATH) as con:
        with open(schema_path, "r", encoding="utf-8") as f:
            con.executescript(f.read())

def query_db(q, args=(), one=False):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.execute(q, args)
    rv = cur.fetchall()
    cur.close()
    con.commit()
    con.close()
    return (rv[0] if rv else None) if one else rv

# ---- Rutas de prueba / salud ----
@app.route("/health")
def health():
    return {"ok": True, "web_dir": WEB_DIR, "exists": os.path.isfile(os.path.join(WEB_DIR, "index.html"))}

# ---- Frontend (sirve la SPA desde /web) ----
@app.route("/")
def root():
    # sirve .../web/index.html explícitamente
    return send_from_directory(WEB_DIR, "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    # sirve cualquier archivo dentro de /web (index.html, app.js, admin.html, etc.)
    return send_from_directory(WEB_DIR, filename)

# ---- API ----
@app.route("/config", methods=["GET"])
def get_config():
    row = query_db("SELECT center_lat, center_lng, zoom FROM config WHERE id=1", one=True)
    return jsonify(dict(row))

def require_admin_token():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
        return True
    except Exception:
        return False

@app.route("/admin/config", methods=["POST"])
def update_config():
    if not require_admin_token():
        return jsonify({"error":"invalid token"}), 401
    data = request.json
    query_db("UPDATE config SET center_lat=?, center_lng=?, zoom=?, updated_at=datetime('now') WHERE id=1",
             (data["center_lat"], data["center_lng"], data["zoom"]))
    return {"ok": True}

@app.route("/pins", methods=["GET"])
def get_pins():
    rows = query_db("SELECT * FROM pins")
    return jsonify([dict(r) for r in rows])

@app.route("/pins", methods=["POST"])
def add_pin():
    d = request.json
    meta_json = json.dumps(d.get("meta", {}), ensure_ascii=False)
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("INSERT INTO pins(type,lat,lng,meta) VALUES(?,?,?,?)",
                          (d["type"], d["lat"], d["lng"], meta_json))
        pid = cur.lastrowid
        con.commit()
    return {"id": pid}

@app.route("/pins/<int:pid>", methods=["PUT"])
def update_pin(pid):
    d = request.json
    meta = d.get("meta")
    meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
    query_db("UPDATE pins SET type=COALESCE(?,type), lat=COALESCE(?,lat), lng=COALESCE(?,lng), meta=COALESCE(?,meta) WHERE id=?",
             (d.get("type"), d.get("lat"), d.get("lng"), meta_json, pid))
    return {"ok": True}

@app.route("/visit", methods=["POST"])
def add_visit():
    d = request.json
    query_db("INSERT INTO visits(user_hash,name,age,date,device_hint) VALUES(?,?,?,?,?)",
             (d["user_hash"], d["name"], d["age"], d["date"], d.get("device_hint","")))
    return {"ok": True}

@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = request.json.get("password")
    if password == SECRET:
        token = jwt.encode({"role":"admin","exp":datetime.datetime.utcnow()+datetime.timedelta(hours=8)},
                           SECRET, algorithm="HS256")
        return {"token": token}
    return {"error":"bad password"}, 401

@app.route("/admin/export/<string:what>.xlsx", methods=["GET"])
def export_excel(what):
    if not require_admin_token():
        return {"error":"invalid token"}, 401

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    if what=="visits":
        cur.execute("SELECT * FROM visits ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM pins ORDER BY id DESC")
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    con.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = what
    ws.append(cols)
    for r in rows:
        ws.append(list(r))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{what}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---- 404 handler con pista en consola ----
@app.errorhandler(404)
def not_found(e):
    # imprime pista en consola
    print(f"[404] No encontrado. WEB_DIR={WEB_DIR} index_exists={os.path.isfile(os.path.join(WEB_DIR,'index.html'))}", file=sys.stderr, flush=True)
    return "404 Not Found", 404

if __name__=="__main__":
    # Inicializa BD y muestra info útil
    init_db()
    print(f"WEB_DIR: {WEB_DIR}")
    print(f"index.html existe? {os.path.isfile(os.path.join(WEB_DIR, 'index.html'))}")
    app.run(host="0.0.0.0", port=3000, debug=True)
