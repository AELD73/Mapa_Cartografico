import os
import sqlite3
import pandas as pd
from datetime import datetime

def export_sqlite_to_excel(db_path: str, output_xlsx: str | None = None):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"No existe la base de datos: {db_path}")

    # Nombre por defecto del Excel
    if output_xlsx is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_xlsx = f"export_bd_{ts}.xlsx"

    conn = sqlite3.connect(db_path)

    try:
        # Traer lista de tablas reales (evita sqlite_sequence, etc.)
        tables_df = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """,
            conn
        )

        tables = tables_df["name"].tolist()
        if not tables:
            raise RuntimeError("No se encontraron tablas en la base de datos.")

        with pd.ExcelWriter(output_xlsx, engine="xlsxwriter") as writer:
            for t in tables:
                # Leer tabla completa
                df = pd.read_sql_query(f"SELECT * FROM '{t}';", conn)

                # Excel limita el nombre de hoja a 31 caracteres
                sheet_name = t[:31]

                # Escribir a hoja
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                # (Opcional) Ajustar ancho de columnas
                worksheet = writer.sheets[sheet_name]
                for col_idx, col_name in enumerate(df.columns):
                    # ancho basado en nombre de columna y contenido
                    max_len = max(
                        [len(str(col_name))] +
                        ([df[col_name].astype(str).map(len).max()] if len(df) else [0])
                    )
                    worksheet.set_column(col_idx, col_idx, min(max_len + 2, 60))

        print(f"✅ Exportación lista: {output_xlsx}")
        print("Tablas exportadas:", ", ".join(tables))

    finally:
        conn.close()


if __name__ == "__main__":
    # Ajusta esta ruta a tu proyecto
    DB_PATH = "pines.db"
    export_sqlite_to_excel(DB_PATH)
