# routers/schedule.py
"""
Router para endpoints relacionados con horarios.
"""
from fastapi import (
    APIRouter,
    Request,
    UploadFile,
    File,
    Form,
    Depends,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db
from repositories.user_repository import UserRepository
from repositories.schedule_repository import ScheduleRepository
from services.auth_service import AuthService
from services import schedule_service as schedule_business_logic
from core.templates import render_template
import file_processing
import response_generators
import security

router = APIRouter()

# Inicializar servicios
user_repo = UserRepository()
schedule_repo = ScheduleRepository()
auth_service = AuthService(user_repo, schedule_repo)


@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Página principal."""
    token = security.get_or_create_csrf_token(request.state.session)
    return render_template(request, "index.html", {"csrf_token": token})


@router.get("/generate-schedule", response_class=HTMLResponse)
async def read_schedule(request: Request):
    """Muestra la página de generación de horarios."""
    
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    data_to_render = schedule_business_logic.filter_active_rows(all_rows)
    num_deleted_rows = schedule_business_logic.get_deleted_rows_count(all_rows)

    token = security.get_or_create_csrf_token(request.state.session)
    upload_errors = request.state.session.pop("upload_errors", [])

    return render_template(
        request,
        "generate-schedule.html",
        {
            "title": "Generate Schedule",
            "description": "Extract the schedule information",
            "data": data_to_render,
            "num_deleted": num_deleted_rows,
            "csrf_token": token,
            "upload_errors": upload_errors,
        },
    )


@router.post("/generate-schedule", response_class=RedirectResponse)
@security.limiter.limit("10/minute")
async def generate_schedule(
    request: Request,
    files: List[UploadFile] = File(...),
    is_csrf_valid: bool = Depends(security.validate_csrf),
    db: AsyncSession = Depends(get_db),
):
    """Procesa archivos subidos y genera el horario."""
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])
    processed_files_set = set(schedule_data.get("processed_files", []))

    newly_processed_files = []
    upload_errors = []

    for file in files:
        if file.filename in processed_files_set:
            continue

        # Leer archivo en chunks y validar tamaño antes de leer completamente
        from core.config import MAX_FILE_SIZE
        content = b""
        size = 0
        chunk_size = 8192  # 8KB chunks
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                upload_errors.append(f"Archivo omitido (excede 5MB): {file.filename}")
                break
            content += chunk
        
        # Si el archivo excedió el tamaño, continuar con el siguiente
        if size > MAX_FILE_SIZE:
            continue

        # 1. Validar archivo
        error = file_processing.validate_file(file, content)
        if error:
            upload_errors.append(error)
            continue

        # 2. Parsear archivo
        try:
            new_schedules = await file_processing.process_single_file(file, content)

            # 3. Fusionar datos
            all_rows = schedule_business_logic.merge_new_schedules(all_rows, new_schedules)

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

    # Guardar en BD si el usuario está autenticado
    if request.state.is_authenticated and request.state.user:
        try:
            await schedule_repo.save(db, request.state.user.id, schedule_data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error guardando schedule en BD tras subida: {e}")

    return RedirectResponse(url="/generate-schedule", status_code=303)


@router.get("/upload-new", response_class=HTMLResponse)
async def show_upload_form(request: Request):
    """Muestra el formulario para subir nuevos archivos."""
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    schedule_data["processed_files"] = []
    request.state.session["schedule_data"] = schedule_data

    token = security.get_or_create_csrf_token(request.state.session)

    return render_template(
        request,
        "generate-schedule.html",
        {
            "title": "Upload New Files",
            "description": "Add new files to the existing schedule",
            "data": None,
            "show_cancel": True,
            "csrf_token": token,
        },
    )


@router.post("/delete-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def delete_selected_rows(
    request: Request,
    selected_ids: str = Form(...),
    new_csrf_token: str = Depends(security.validate_csrf),
    db: AsyncSession = Depends(get_db),
):
    """Elimina (marca) filas seleccionadas."""
    # Validar y filtrar UUIDs
    ids_to_delete = security.validate_uuid_list(selected_ids)

    if not ids_to_delete:
        return JSONResponse(
            {"success": False, "message": "No valid IDs provided."}, status_code=400
        )

    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    # Usar el servicio para la lógica de borrado
    all_rows, deleted_count = schedule_business_logic.delete_rows_by_id(
        all_rows, ids_to_delete
    )

    # Lógica de sesión restante
    if not schedule_business_logic.filter_active_rows(all_rows):
        schedule_data["processed_files"] = []

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    # Persistir el cambio en la BD si el usuario está logueado
    if request.state.is_authenticated and request.state.user:
        try:
            await schedule_repo.save(db, request.state.user.id, schedule_data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error guardando schedule en BD tras borrado: {e}")
            return JSONResponse(
                {"success": False, "message": "Error al guardar en BD."},
                status_code=500,
            )

    return JSONResponse(
        {
            "success": True,
            "message": f"Deleted {deleted_count} rows.",
            "new_csrf_token": new_csrf_token,
        }
    )


@router.post("/restore-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def restore_deleted_rows(
    request: Request,
    new_csrf_token: str = Depends(security.validate_csrf),
    db: AsyncSession = Depends(get_db),
):
    """Restaura todas las filas borradas."""
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    if not all_rows:
        return JSONResponse(
            {
                "success": True,
                "message": "No data to restore.",
                "new_csrf_token": new_csrf_token,
            }
        )

    # Usar el servicio para la lógica de restauración
    all_rows, restored_count = schedule_business_logic.restore_deleted_rows(all_rows)

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    # Persistir el cambio en la BD si el usuario está logueado
    if request.state.is_authenticated and request.state.user:
        try:
            await schedule_repo.save(db, request.state.user.id, schedule_data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error guardando schedule en BD tras restaurar: {e}")
            return JSONResponse(
                {"success": False, "message": "Error al guardar en BD."},
                status_code=500,
            )

    return JSONResponse(
        {
            "success": True,
            "message": f"Restored {restored_count} rows.",
            "new_csrf_token": new_csrf_token,
        }
    )


@router.post("/delete-data", response_class=JSONResponse)
@security.limiter.limit("10/minute")
async def delete_data(
    request: Request,
    new_csrf_token: str = Depends(security.validate_csrf),
    db: AsyncSession = Depends(get_db),
):
    """Limpia todos los datos del horario actual."""
    # Usar el servicio para obtener un estado vacío
    empty_schedule_data = schedule_business_logic.get_empty_schedule_data()
    request.state.session["schedule_data"] = empty_schedule_data

    # Persistir el estado vacío en la BD si el usuario está logueado
    if request.state.is_authenticated and request.state.user:
        try:
            await schedule_repo.save(
                db, request.state.user.id, empty_schedule_data
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error guardando schedule en BD tras limpiar datos: {e}")
            return JSONResponse(
                {"success": False, "message": "Error al guardar en BD."},
                status_code=500,
            )

    return JSONResponse(
        {
            "success": True,
            "message": "All data cleared.",
            "new_csrf_token": new_csrf_token,
        }
    )


@router.get("/schedule")
@security.limiter.limit("60/minute")
async def get_schedule_tsv(request: Request):
    """Descarga el horario en formato TSV."""
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    active_rows = schedule_business_logic.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]

    return response_generators.generate_tsv_response(active_rows_data)


@router.get("/download-excel")
@security.limiter.limit("30/minute")
async def download_excel(request: Request):
    """Descarga el horario en formato Excel."""
    schedule_data = request.state.session.get(
        "schedule_data", schedule_business_logic.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    active_rows = schedule_business_logic.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]

    return response_generators.generate_excel_response(active_rows_data)

