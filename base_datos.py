import sqlite3

# Conexión a la base de datos correcta
conn = sqlite3.connect("pines.db")
cursor = conn.cursor()

# Ver las tablas disponibles
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tablas disponibles:", cursor.fetchall())

# Consultar los usuarios
cursor.execute("SELECT * FROM pins")
usuarios = cursor.fetchall()

print("\nUsuarios registrados:")
for usuario in usuarios:
    print(usuario)

conn.close()
