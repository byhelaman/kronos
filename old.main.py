import os
import uuid
import json
import pandas as pd
from io import BytesIO
import secrets

import asyncio
import redis.asyncio as redis
from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
    status,
)
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    PlainTextResponse,
    StreamingResponse,
    JSONResponse,
)

from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from typing import List
import tempfile
from dotenv import load_dotenv
from parsers import parse_excel_file
from typing import List, Dict, Any, Set, Tuple
from collections import namedtuple


# --- NUEVAS IMPORTACIONES PARA RATE LIMITING ---
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------

load_dotenv()
limiter = Limiter(key_func=get_remote_address)


async def validate_csrf(request: Request, csrf_token: str = Form(...)):
    """
    Dependencia de FastAPI para validar el token CSRF en formularios POST.
    """
    session = request.state.session
    stored_token = session.get("csrf_token")

    # Comparamos de forma segura para evitar ataques de temporización
    if not stored_token or not secrets.compare_digest(stored_token, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Error de validación CSRF. Intenta recargar la página.",
        )
    return True


def get_or_create_csrf_token(session: dict) -> str:
    """
    Obtiene el token CSRF de la sesión, o crea uno nuevo si no existe.
    """
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


# === FIN LÓGICA ANTI-CSRF ===


MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_SELECTED_IDS_LENGTH = 1048576
ALLOWED_EXTENSIONS = {".xls", ".xlsx"}
ALLOWED_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SESSION_COOKIE_NAME = "file_session_id"


REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("La variable de entorno REDIS_URL no está configurada.")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class RedisSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:

        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = {}
        new_session = False

        if session_id:
            try:
                # Usamos 'await' para la E/S de red (I/O)
                data_json = await redis_client.get(f"session:{session_id}")
                if data_json:
                    session_data = json.loads(data_json)
                else:
                    session_id = None  # La sesión expiró o no se encontró en Redis
            except Exception as e:
                print(f"Error al leer de Redis: {e}")
                session_id = None

        if not session_id:
            new_session = True
            session_id = str(uuid.uuid4())
            # Asegúrate de que esta estructura inicial coincide con lo que tu app espera
            session_data = {
                "schedule_data": {
                    "processed_files": [],
                    "all_rows": [],
                }
            }

        request.state.session = session_data
        request.state.session_id = session_id
        request.state.session_cleared = False  # Flag para el borrado

        response = await call_next(request)

        # Lógica de guardado después de que el endpoint se ejecute
        if getattr(request.state, "session_cleared", False):
            try:
                # Borramos la sesión de Redis
                await redis_client.delete(f"session:{session_id}")
            except Exception as e:
                print(f"Error borrando la sesión de Redis: {e}")
            response.delete_cookie(SESSION_COOKIE_NAME)
        else:
            try:
                # Guardamos la sesión (actualizada) de vuelta en Redis
                data_to_save_json = json.dumps(request.state.session)
                # Seteamos un tiempo de expiración (ej. 7 días)
                # Esto es crucial para que Redis no se llene de sesiones viejas
                await redis_client.set(
                    f"session:{session_id}", data_to_save_json, ex=60 * 60 * 24 * 7
                )
            except Exception as e:
                print(f"Error guardando la sesión en Redis: {e}")

            if new_session:
                response.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    httponly=True,
                    samesite="lax",
                    max_age=60 * 60 * 24 * 7,  # 7 días
                )

        return response


# 5. ¡REGISTRAMOS EL NUEVO MIDDLEWARE!
app.add_middleware(RedisSessionMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    token = get_or_create_csrf_token(request.state.session)
    return templates.TemplateResponse(
        "index.html", {"request": request, "csrf_token": token}
    )


@app.get("/generate-schedule", response_class=HTMLResponse)
async def read_schedule(request: Request):
    schedule_data = request.state.session.get("schedule_data", {})
    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])

    # deleted_rows = schedule_data.get("deleted_rows", [])
    # num_deleted_rows = len(deleted_rows)

    data_to_render = [row for row in all_rows if row.get("status") == "active"]
    num_deleted_rows = len(all_rows) - len(data_to_render)

    # Generar y pasar el token
    token = get_or_create_csrf_token(request.state.session)

    upload_errors = request.state.session.pop("upload_errors", [])

    return templates.TemplateResponse(
        "generate-schedule.html",
        {
            "request": request,
            "title": "Generate Schedule",
            "description": "Extract the schedule information",
            "data": data_to_render,
            "num_deleted": num_deleted_rows,
            "csrf_token": token,
            "upload_errors": upload_errors,
        },
    )


def _get_business_key(row_data: Dict[str, Any]) -> Tuple:
    """
    Crea una tupla (llave única) a partir de los 10 campos de datos
    para la detección de duplicados. Ignora el campo 'id'.
    """
    return (
        row_data.get("date"),
        row_data.get("shift"),
        row_data.get("area"),
        row_data.get("start_time"),
        row_data.get("end_time"),
        row_data.get("code"),
        row_data.get("instructor"),
        row_data.get("group"),
        row_data.get("minutes"),
        row_data.get("units"),
    )


@app.post("/generate-schedule", response_class=RedirectResponse)
@limiter.limit("10/minute")
async def generate_schedule(
    request: Request,
    files: List[UploadFile] = File(...),
    is_csrf_valid: bool = Depends(validate_csrf),
):

    schedule_data = request.state.session.get(
        "schedule_data", {"processed_files": [], "all_rows": []}
    )

    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])
    processed_files_set = set(schedule_data.get("processed_files", []))

    # existing_rows_set: Set[Tuple] = {_get_business_key(row["data"]) for row in all_rows}
    rows_by_key: Dict[Tuple, Dict] = {
        _get_business_key(row["data"]): row for row in all_rows
    }

    new_row_entries = []
    newly_processed_files = []
    upload_errors = []

    EXPECTED_GENERATED_HEADERS = {
        "date",
        "shift",
        "area",
        "start_time",
        "end_time",
        "code",
        "instructor",
        "group",
        "minutes",
        "units",
    }

    # 3. Crear un "emulador" de la clase Schedule
    Schedule = namedtuple("Schedule", EXPECTED_GENERATED_HEADERS)

    for file in files:
        if file.filename in processed_files_set:
            continue

        # === 1. VALIDACIÓN DE EXTENSIÓN ===
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            msg = f"Archivo omitido (extensión inválida): {file.filename}"
            print(msg)
            upload_errors.append(msg)
            continue

        # === 2. VALIDACIÓN DE TIPO MIME ===
        if file.content_type not in ALLOWED_MIME_TYPES:
            msg = f"Archivo omitido (tipo MIME inválido): {file.filename}"
            print(msg)
            upload_errors.append(msg)
            continue

        content = await file.read()

        # === 3. VALIDACIÓN DE TAMAÑO ===
        if len(content) > MAX_FILE_SIZE:
            msg = f"Archivo omitido (excede 5MB): {file.filename}"
            print(msg)
            upload_errors.append(msg)
            continue

        # === FIN DE VALIDACIÓN ===

        engine = "openpyxl" if ext == ".xlsx" else "xlrd"

        # Usar la extensión original para el archivo temporal
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp_file_path = tmp_file.name

        try:
            await asyncio.to_thread(tmp_file.write, content)
            await asyncio.to_thread(tmp_file.close)

            # parse_excel_file devuelve List[Schedule]
            # schedules = await asyncio.to_thread(parse_excel_file, tmp_file_path, engine)

            schedules = []  # Inicializar la lista de schedules

            # --- 4. NUEVA LÓGICA DE DETECCIÓN Y PARSEO ---
            try:
                # 4a. Leer solo la cabecera
                df_header = await asyncio.to_thread(
                    pd.read_excel, tmp_file_path, engine=engine, nrows=0
                )

                # 4b. Comprobar si es un archivo generado
                if EXPECTED_GENERATED_HEADERS.issubset(set(df_header.columns)):
                    # SÍ: Es un archivo generado, usar el parser simple
                    df_generated = await asyncio.to_thread(
                        pd.read_excel, tmp_file_path, engine=engine
                    )

                    # 4c. Convertir el DataFrame de vuelta a objetos Schedule
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

                else:
                    # NO: Es un archivo raw, usar el parser original
                    schedules = await asyncio.to_thread(
                        parse_excel_file, tmp_file_path, engine
                    )

            except Exception as e:
                # Si falla la detección o el parseo, lo marcamos como error
                print(f"Error detectando/parseando el archivo {file.filename}: {e}")
                raise e  # Dejamos que el 'except' exterior lo capture

            # --- FIN DE LA NUEVA LÓGICA ---

            for schedule in schedules:
                # === MODIFICADO: Crear la nueva estructura anidada ===
                inner_data = {
                    "date": schedule.date,
                    "shift": schedule.shift,
                    "area": schedule.area,
                    "start_time": schedule.start_time,
                    "end_time": schedule.end_time,
                    "code": schedule.code,
                    "instructor": schedule.instructor,
                    "group": schedule.group,
                    "minutes": schedule.minutes,
                    "units": schedule.units,
                }

                row_tuple = _get_business_key(inner_data)
                existing_row = rows_by_key.get(row_tuple)

                # if row_tuple not in existing_rows_set:
                #     new_row_entry = {
                #         "id": str(uuid.uuid4()),
                #         "status": "active",  # <-- Nuevo campo de estado
                #         "data": inner_data,  # <-- Datos anidados
                #     }
                #     new_row_entries.append(new_row_entry)
                #     existing_rows_set.add(row_tuple)

                if existing_row:
                    # 2. Si existe Y está marcada como borrada, reactívala
                    if existing_row.get("status") == "deleted":
                        existing_row["status"] = "active"
                    # (Opcional: puedes añadir un contador de filas reactivadas si quieres)
                else:
                    # 3. Si no existe, es una fila nueva. Añádela.
                    new_row_entry = {
                        "id": str(uuid.uuid4()),
                        "status": "active",
                        "data": inner_data,
                    }
                    new_row_entries.append(new_row_entry)
                    # 4. Añádela al diccionario para que sea detectada si se repite en el mismo archivo
                    rows_by_key[row_tuple] = new_row_entry

            newly_processed_files.append(file.filename)

        except Exception as e:
            print(f"Error processing file {file.filename}: {e}")
            upload_errors.append(f"Error al procesar: {file.filename}")
        finally:
            if os.path.exists(tmp_file_path):
                await asyncio.to_thread(os.unlink, tmp_file_path)

    all_rows.extend(new_row_entries)
    processed_files_set.update(newly_processed_files)

    schedule_data["processed_files"] = list(processed_files_set)
    schedule_data["all_rows"] = all_rows

    request.state.session["schedule_data"] = schedule_data
    request.state.session["upload_errors"] = upload_errors
    return RedirectResponse(url="/generate-schedule", status_code=303)


@app.get("/upload-new", response_class=HTMLResponse)
async def show_upload_form(request: Request):
    # """
    # Muestra el formulario de subida y limpia la caché de archivos
    # para permitir una nueva carga de los mismos.
    # """

    schedule_data = request.state.session.get("schedule_data", {})
    schedule_data["processed_files"] = []
    request.state.session["schedule_data"] = schedule_data

    # Generar y pasar el token
    token = get_or_create_csrf_token(request.state.session)

    return templates.TemplateResponse(
        "generate-schedule.html",
        {
            "request": request,
            "title": "Upload New Files",
            "description": "Add new files to the existing schedule",
            "data": None,
            "show_cancel": True,
            "csrf_token": token,
        },
    )


# === MODIFICADO: /delete-rows (AJAX) ===
@app.post("/delete-rows", response_class=JSONResponse)
@limiter.limit("30/minute")
async def delete_selected_rows(
    request: Request,
    selected_ids: str = Form(...),
    is_csrf_valid: bool = Depends(validate_csrf),
):
    if len(selected_ids) > MAX_SELECTED_IDS_LENGTH:
        return JSONResponse(
            {"success": False, "message": "Payload too large."}, status_code=413
        )

    try:
        ids_to_delete = {str(i) for i in selected_ids.split(",")}
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "Invalid ID format."}, status_code=400
        )

    schedule_data = request.state.session.get("schedule_data", {})
    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])

    deleted_count = 0
    # Simplemente cambiamos el estado, no movemos filas
    for row in all_rows:
        if row.get("id") in ids_to_delete and row.get("status") == "active":
            row["status"] = "deleted"
            deleted_count += 1

    # Si no quedan filas activas, limpiar 'processed_files'
    if not any(row["status"] == "active" for row in all_rows):
        schedule_data["processed_files"] = []

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse({"success": True, "message": f"Deleted {deleted_count} rows."})


# === MODIFICADO: /restore-rows (AJAX) ===
@app.post("/restore-rows", response_class=JSONResponse)
@limiter.limit("30/minute")
async def restore_deleted_rows(
    request: Request, is_csrf_valid: bool = Depends(validate_csrf)
):
    schedule_data = request.state.session.get("schedule_data", {})
    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])

    if not all_rows:
        return JSONResponse({"success": True, "message": "No data to restore."})

    # Reconstruir el set de duplicados activos
    active_rows_set: Set[Tuple] = {
        _get_business_key(row["data"]) for row in all_rows if row["status"] == "active"
    }

    restored_count = 0
    for row in all_rows:
        if row.get("status") == "deleted":
            row_tuple = _get_business_key(row["data"])
            # Solo restaurar si no crea un duplicado
            if row_tuple not in active_rows_set:
                row["status"] = "active"
                restored_count += 1
                active_rows_set.add(row_tuple)

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse(
        {"success": True, "message": f"Restored {restored_count} rows."}
    )


# === MODIFICADO: /delete-data (AJAX) ===
@app.post("/delete-data", response_class=JSONResponse)
@limiter.limit("10/minute")
async def delete_data(request: Request, is_csrf_valid: bool = Depends(validate_csrf)):
    request.state.session["schedule_data"] = {
        "processed_files": [],
        "all_rows": [],
    }
    request.state.session_cleared = True
    return JSONResponse({"success": True, "message": "All data cleared."})


@app.get("/schedule", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def get_schedule_tsv(request: Request):
    """
    Devuelve el horario completo (all_rows) desde la sesión
    como texto plano (CSV separado por tabs), sin parsear y sin cabeceras.
    """
    schedule_data = request.state.session.get("schedule_data", {})
    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])

    active_rows_data = [
        row["data"] for row in all_rows if row.get("status") == "active"
    ]
    if not active_rows_data:
        return "No schedule data found."

    # Definir las columnas en el orden deseado
    # Estas coinciden con las claves del diccionario en la sesión
    columns_order = [
        "date",
        "shift",
        "area",
        "start_time",
        "end_time",
        "code",
        "instructor",
        "group",
        "minutes",
        "units",
    ]
    output_lines = []

    # Añadir las filas de datos
    for row in active_rows_data:
        # Extraer valores en el mismo orden que las columnas
        # Se usa str(row.get(h, "")) para obtener los datos tal cual
        # están en la sesión y manejar claves faltantes.
        values = [str(row.get(h, "")) for h in columns_order]
        output_lines.append("\t".join(values))

    # Unir todas las líneas con saltos de línea
    return "\n".join(output_lines)


@app.get("/download-excel")
@limiter.limit("30/minute")
async def download_excel(request: Request):
    schedule_data = request.state.session.get("schedule_data", {})
    all_rows: List[Dict[str, Any]] = schedule_data.get("all_rows", [])

    columns_order = [
        "date",
        "shift",
        "area",
        "start_time",
        "end_time",
        "code",
        "instructor",
        "group",
        "minutes",
        "units",
    ]

    active_rows_data = [
        row["data"] for row in all_rows if row.get("status") == "active"
    ]
    if not active_rows_data:
        df = pd.DataFrame(columns=columns_order)
    else:
        df = pd.DataFrame(active_rows_data)
        df = df[columns_order]

    output_buffer = BytesIO()

    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Schedule")

    output_buffer.seek(0)

    headers = {"Content-Disposition": 'attachment; filename="schedule.xlsx"'}

    # Devolver el archivo usando StreamingResponse
    return StreamingResponse(
        output_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
