# main.py
import asyncio
from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    Depends,
    HTTPException,
    status
)
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from typing import List, Dict, Any

# --- Importaciones de nuestros módulos refactorizados ---
import config
import security
import schedule_service
import file_processing
import response_generators
from session_middleware import RedisSessionMiddleware
# --------------------------------------------------------

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configuración de Rate Limiter
app.state.limiter = security.limiter
app.add_exception_handler(RateLimitExceeded, security.rate_limit_handler)

# Configuración del Middleware de Sesión
app.add_middleware(RedisSessionMiddleware)

# Montar archivos estáticos y plantillas
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- Endpoints de la Aplicación ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    token = security.get_or_create_csrf_token(request.state.session)
    return templates.TemplateResponse(
        "index.html", {"request": request, "csrf_token": token}
    )


@app.get("/generate-schedule", response_class=HTMLResponse)
async def read_schedule(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    data_to_render = schedule_service.filter_active_rows(all_rows)
    num_deleted_rows = schedule_service.get_deleted_rows_count(all_rows)
    
    token = security.get_or_create_csrf_token(request.state.session)
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


@app.post("/generate-schedule", response_class=RedirectResponse)
@security.limiter.limit("10/minute")
async def generate_schedule(
    request: Request,
    files: List[UploadFile] = File(...),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])
    processed_files_set = set(schedule_data.get("processed_files", []))

    newly_processed_files = []
    upload_errors = []

    for file in files:
        if file.filename in processed_files_set:
            continue

        content = await file.read()
        
        # 1. Validar archivo (Lógica en file_processing)
        error = file_processing.validate_file(file, content)
        if error:
            upload_errors.append(error)
            continue
        
        # 2. Parsear archivo (Lógica en file_processing)
        try:
            new_schedules = await file_processing.process_single_file(file, content)
            
            # 3. Fusionar datos (Lógica en schedule_service)
            all_rows = schedule_service.merge_new_schedules(all_rows, new_schedules)
            
            newly_processed_files.append(file.filename)

        except Exception as e:
            print(f"Error processing file {file.filename}: {e}")
            upload_errors.append(f"Error al procesar: {file.filename}")

    # 4. Actualizar estado de la sesión
    processed_files_set.update(newly_processed_files)
    schedule_data["processed_files"] = list(processed_files_set)
    schedule_data["all_rows"] = all_rows

    request.state.session["schedule_data"] = schedule_data
    request.state.session["upload_errors"] = upload_errors
    
    return RedirectResponse(url="/generate-schedule", status_code=303)


@app.get("/upload-new", response_class=HTMLResponse)
async def show_upload_form(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    schedule_data["processed_files"] = []
    request.state.session["schedule_data"] = schedule_data

    token = security.get_or_create_csrf_token(request.state.session)

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


@app.post("/delete-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def delete_selected_rows(
    request: Request,
    selected_ids: str = Form(...),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    if len(selected_ids) > config.MAX_SELECTED_IDS_LENGTH:
        return JSONResponse(
            {"success": False, "message": "Payload too large."}, status_code=413
        )
    try:
        ids_to_delete = {str(i) for i in selected_ids.split(",")}
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "Invalid ID format."}, status_code=400
        )

    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    # Usar el servicio para la lógica de borrado
    all_rows, deleted_count = schedule_service.delete_rows_by_id(all_rows, ids_to_delete)

    # Lógica de sesión restante
    if not schedule_service.filter_active_rows(all_rows):
        schedule_data["processed_files"] = []

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse({"success": True, "message": f"Deleted {deleted_count} rows."})


@app.post("/restore-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def restore_deleted_rows(
    request: Request, is_csrf_valid: bool = Depends(security.validate_csrf)
):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    if not all_rows:
        return JSONResponse({"success": True, "message": "No data to restore."})

    # Usar el servicio para la lógica de restauración
    all_rows, restored_count = schedule_service.restore_deleted_rows(all_rows)

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse(
        {"success": True, "message": f"Restored {restored_count} rows."}
    )


@app.post("/delete-data", response_class=JSONResponse)
@security.limiter.limit("10/minute")
async def delete_data(request: Request, is_csrf_valid: bool = Depends(security.validate_csrf)):
    # Usar el servicio para obtener un estado vacío
    request.state.session["schedule_data"] = schedule_service.get_empty_schedule_data()
    request.state.session_cleared = True
    return JSONResponse({"success": True, "message": "All data cleared."})


@app.get("/schedule")
@security.limiter.limit("60/minute")
async def get_schedule_tsv(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])
    
    active_rows = schedule_service.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]
    
    # Usar el generador de respuestas
    return response_generators.generate_tsv_response(active_rows_data)


@app.get("/download-excel")
@security.limiter.limit("30/minute")
async def download_excel(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])
    
    active_rows = schedule_service.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]
    
    # Usar el generador de respuestas
    return response_generators.generate_excel_response(active_rows_data)