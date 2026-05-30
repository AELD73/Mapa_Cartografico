import sqlite3

# Conectar a la base de datos
conn = sqlite3.connect("pines.db")
cursor = conn.cursor()

# Obtener todas las tablas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tablas = cursor.fetchall()

output = "Tablas en la base de datos:\n"

for (tabla,) in tablas:
    output += f"\n===== TABLA: {tabla} =====\n"

    cursor.execute(f"SELECT * FROM {tabla}")
    filas = cursor.fetchall()

    for fila in filas:
        output += str(fila) + "\n"

conn.close()

# Guardar en archivo .txt
with open("pines_export.txt", "w", encoding="utf-8") as archivo:
    archivo.write(output)

print("Exportación completada: pines_export.txt")