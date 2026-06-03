import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

try:
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    print("Conexión a la base exitosa.")

    with conn.cursor() as cursor:
        cursor.execute("SELECT DATABASE() AS base_actual;")
        print(cursor.fetchone())

    conn.close()

except Exception as e:
    print("Error:")
    print(e)