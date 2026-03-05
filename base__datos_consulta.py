import sqlite3

# Conectar a la base de datos
conn = sqlite3.connect("pines.db")
cursor = conn.cursor()

# Obtener todas las tablas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tablas = cursor.fetchall()

print("Tablas en la base de datos:\n")

for (tabla,) in tablas:
    print(f"\n===== TABLA: {tabla} =====")

    cursor.execute(f"SELECT * FROM {tabla}")
    filas = cursor.fetchall()

    for fila in filas:
        print(fila)

conn.close()