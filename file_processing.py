# file_processing.py
import os
import tempfile
import asyncio
import pandas as pd
from fastapi import UploadFile
from typing import List, Dict, Any
from parsers import parse_excel_file
from config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
    EXPECTED_GENERATED_HEADERS,
    Schedule,
)

def validate_file(file: UploadFile, content: bytes) -> str | None:
    """
    Valida la extensión, tipo MIME y tamaño del archivo.
    Devuelve un mensaje de error si es inválido, o None si es válido.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Archivo omitido (extensión inválida): {file.filename}"

    if file.content_type not in ALLOWED_MIME_TYPES:
        return f"Archivo omitido (tipo MIME inválido): {file.filename}"

    if len(content) > MAX_FILE_SIZE:
        return f"Archivo omitido (excede 5MB): {file.filename}"
        
    return None

async def _parse_generated_file(path: str, engine: str) -> List[Schedule]:
    """Parsea un archivo que ya tiene el formato de salida."""
    schedules = []
    df_generated = await asyncio.to_thread(pd.read_excel, path, engine=engine)
    
    for _, row in df_generated.iterrows():
        schedules.append(
            Schedule(
                date=str(row.get("date", "")),
                shift=str(row.get("shift", "")),
                area=str(row.get("area", "")),
                start_time=str(row.get("start_time", "")),
                end_time=str(row.get("end_time", "")),
                code=str(row.get("code", "")),
                instructor=str(row.get("instructor", "")),
                group=str(row.get("group", "")),
                minutes=str(row.get("minutes", 0)),
                units=int(row.get("units", 0)),
            )
        )
    return schedules

async def _parse_raw_file(path: str, engine: str) -> List[Schedule]:
    """Parsea un archivo 'raw' usando el parser personalizado."""
    # parse_excel_file debe devolver List[Schedule]
    return await asyncio.to_thread(parse_excel_file, path, engine)

async def process_single_file(file: UploadFile, content: bytes) -> List[Schedule]:
    """
    Procesa un solo archivo: lo guarda temporalmente, detecta su tipo,
    lo parsea y devuelve una lista de objetos Schedule.
    """
    ext = os.path.splitext(file.filename)[1].lower()
    engine = "openpyxl" if ext == ".xlsx" else "xlrd"

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_file_path = tmp_file.name

    try:
        await asyncio.to_thread(tmp_file.write, content)
        await asyncio.to_thread(tmp_file.close)

        # 1. Leer solo la cabecera para detectar el tipo
        df_header = await asyncio.to_thread(
            pd.read_excel, tmp_file_path, engine=engine, nrows=0
        )

        # 2. Comprobar si es un archivo generado
        if EXPECTED_GENERATED_HEADERS.issubset(set(df_header.columns)):
            schedules = await _parse_generated_file(tmp_file_path, engine)
        else:
            schedules = await _parse_raw_file(tmp_file_path, engine)
        
        return schedules

    except Exception as e:
        print(f"Error detectando/parseando el archivo {file.filename}: {e}")
        # Re-lanzamos la excepción para que el endpoint la capture
        raise e
    finally:
        if os.path.exists(tmp_file_path):
            await asyncio.to_thread(os.unlink, tmp_file_path)