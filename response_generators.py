# response_generators.py
import pandas as pd
from io import BytesIO
from typing import List, Dict, Any
from fastapi.responses import PlainTextResponse, StreamingResponse

# Columnas y orden para los archivos de salida
COLUMNS_ORDER = [
    "date", "shift", "area", "start_time", "end_time",
    "code", "instructor", "group", "minutes", "units",
]

def generate_tsv_response(active_rows_data: List[Dict[str, Any]]) -> PlainTextResponse:
    """Genera una respuesta de texto plano (TSV) desde los datos activos."""
    if not active_rows_data:
        return PlainTextResponse("No schedule data found.")

    output_lines = []
    for row in active_rows_data:
        values = [str(row.get(h, "")) for h in COLUMNS_ORDER]
        output_lines.append("\t".join(values))
    
    return PlainTextResponse("\n".join(output_lines))


def generate_excel_response(active_rows_data: List[Dict[str, Any]]) -> StreamingResponse:
    """Genera una respuesta de archivo Excel (XLSX) desde los datos activos."""
    if not active_rows_data:
        df = pd.DataFrame(columns=COLUMNS_ORDER)
    else:
        df = pd.DataFrame(active_rows_data)
        df = df[COLUMNS_ORDER] # Asegurar el orden de las columnas

    output_buffer = BytesIO()
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Schedule")
    output_buffer.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="schedule.xlsx"'}
    
    return StreamingResponse(
        output_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )