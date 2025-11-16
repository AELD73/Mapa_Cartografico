import sqlite3
import os
from datetime import datetime

# ----------------------------------------
# CONFIGURACIÓN DE LA BASE DE DATOS
# ----------------------------------------
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "pines.db")


def get_connection():
    """Regresa una conexión a la base de datos."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------
# FUNCIONES DE CONSULTA
# ----------------------------------------

def obtener_todas_las_visitas():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, edad, origen, destino, creado_en
        FROM visitas
        ORDER BY creado_en DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def contar_visitas():
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) AS total FROM visitas").fetchone()
    conn.close()
    return row["total"]


def visitas_por_dia():
    conn = get_connection()
    rows = conn.execute("""
        SELECT DATE(creado_en) AS dia,
               COUNT(*) AS total
        FROM visitas
        GROUP BY DATE(creado_en)
        ORDER BY dia DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def visitas_con_pines():
    conn = get_connection()
    rows = conn.execute("""
        SELECT v.id AS visita_id,
               v.edad,
               v.origen,
               v.destino,
               v.creado_en AS visita_creada,
               p.id AS pin_id,
               p.codigo_pin,
               p.lat,
               p.lon,
               p.creado_en AS pin_creado
        FROM visitas v
        LEFT JOIN pines p ON p.visita_id = v.id
        ORDER BY v.id, p.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resumen_pines_por_visita():
    conn = get_connection()
    rows = conn.execute("""
        SELECT v.id AS visita_id,
               v.edad,
               v.origen,
               v.destino,
               COUNT(p.id) AS total_pines
        FROM visitas v
        LEFT JOIN pines p ON p.visita_id = v.id
        GROUP BY v.id
        ORDER BY total_pines DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------------------
# EJEMPLOS DE USO CUANDO EJECUTAS EL SCRIPT
# ----------------------------------------
if __name__ == "__main__":
    print("=== CONSULTA DE VISITAS (USUARIOS) ===\n")

    print("Total de visitas registradas:")
    print(contar_visitas())
    print("\n------------------------------\n")

    print("Últimas visitas:")
    for v in obtener_todas_las_visitas()[:10]:
        print(v)
    print("\n------------------------------\n")

    print("Visitas por día:")
    for v in visitas_por_dia():
        print(v)
    print("\n------------------------------\n")

    print("Visitas con sus pines:")
    for v in visitas_con_pines()[:10]:
        print(v)
    print("\n------------------------------\n")

    print("Resumen de pines por visita:")
    for r in resumen_pines_por_visita():
        print(r)
