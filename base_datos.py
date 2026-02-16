import sqlite3
import pandas as pd
from io import BytesIO

def exportar_base_datos_excel():
    conn = sqlite3.connect("pines.db")

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        tablas = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()

        for (tabla,) in tablas:
            df = pd.read_sql_query(f"SELECT * FROM {tabla}", conn)
            df.to_excel(writer, sheet_name=tabla, index=False)

    conn.close()
    output.seek(0)

    return output
