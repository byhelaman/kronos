# routers/zoom.py
"""
Router para endpoints de integración con Zoom OAuth y asignación automática.
"""
import re
import secrets
from fastapi import (
    APIRouter,
    Request,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    Body,
)
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import List as TypingList
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import pandas as pd
import io

from database import get_db
from models.user_model import User
from repositories.user_repository import UserRepository
from services.zoom_sync_service import ZoomSyncService
from services.zoom_assignment_service import ZoomAssignmentService
from repositories.zoom_repository import ZoomRepository
import zoom_oauth
import security
from core.config import ZOOM_CLIENT_ID

router = APIRouter()
templates = Jinja2Templates(directory="templates")

user_repo = UserRepository()
zoom_sync_service = ZoomSyncService()
zoom_assignment_service = ZoomAssignmentService()
zoom_repo = ZoomRepository()


class AssignmentRequest(BaseModel):
    """Modelo para solicitud de asignaciones."""

    assignments: TypingList[dict]  # Lista de dicts con meeting_id e instructor_email


class ScheduleAssignmentRequest(BaseModel):
    """Modelo para procesar asignaciones desde el horario."""

    schedule_rows: TypingList[dict]  # Lista de filas del horario con Group e Instructor


@router.get("/auth/zoom")
async def zoom_auth_start(
    request: Request, current_user: User = Depends(security.get_current_active_user)
):
    """Inicia el proceso de vinculación con Zoom."""
    if not ZOOM_CLIENT_ID:
        raise HTTPException(500, "Zoom no está configurado en el servidor.")

    # Obtener AMBOS valores de la función
    auth_url, code_verifier = zoom_oauth.get_zoom_auth_url()

    # Generar state token para prevenir CSRF
    state_token = secrets.token_hex(32)

    # Guardar el verifier y state en la sesión ANTES de redirigir
    request.state.session["zoom_code_verifier"] = code_verifier
    request.state.session["zoom_oauth_state"] = state_token

    # Agregar state a la URL
    auth_url += f"&state={state_token}"

    return RedirectResponse(url=auth_url)


@router.post("/auth/zoom/unlink", response_class=RedirectResponse)
async def zoom_unlink(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    """Elimina los tokens de Zoom del usuario actual."""
    await user_repo.remove_zoom_tokens(db, current_user.id)

    # Invalidar cache de usuario para forzar recarga desde BD en el siguiente request
    request.state.session.pop("_cached_user", None)
    request.state.session["_user_cache_expiry"] = 0

    return RedirectResponse(url="/profile?success=zoom_unlinked", status_code=303)


@router.get("/auth/zoom/callback")
async def zoom_auth_callback(
    request: Request,
    code: str,
    state: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Callback de OAuth de Zoom."""
    # Verificamos autenticación
    if not request.state.is_authenticated or not request.state.user:
        return RedirectResponse(url="/login?error=zoom_auth_failed", status_code=303)

    # Validar código OAuth
    if not code:
        return RedirectResponse(url="/profile?error=zoom_auth_failed", status_code=303)

    if len(code) > 500 or not re.match(r"^[a-zA-Z0-9_-]+$", code):
        return RedirectResponse(url="/profile?error=zoom_auth_failed", status_code=303)

    # Validar state token para prevenir CSRF
    stored_state = request.state.session.pop("zoom_oauth_state", None)
    if not stored_state or not state or not secrets.compare_digest(stored_state, state):
        return RedirectResponse(url="/profile?error=zoom_auth_failed", status_code=303)

    current_user = request.state.user
    code_verifier = request.state.session.pop("zoom_code_verifier", None)

    if not code_verifier:
        # Si falla, redirigir al perfil con error
        return RedirectResponse(
            url="/profile?error=zoom_session_expired", status_code=303
        )

    try:
        token_data = await zoom_oauth.exchange_code_for_tokens(code, code_verifier)
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        zoom_user_info = await zoom_oauth.get_zoom_user_info(access_token)
        zoom_user_id = zoom_user_info["id"]

        await user_repo.update_zoom_tokens(
            db=db,
            user_id=current_user.id,
            zoom_user_id=zoom_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        # Invalidar cache de usuario para forzar recarga desde BD en el siguiente request
        request.state.session.pop("_cached_user", None)
        request.state.session["_user_cache_expiry"] = 0

        # Redirigir al perfil con mensaje de éxito
        return RedirectResponse(url="/profile?success=zoom_linked", status_code=303)

    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error en el callback de Zoom: {e}")
        # Redirigir al perfil con mensaje de error
        return RedirectResponse(url="/profile?error=zoom_link_failed", status_code=303)


@router.post("/zoom/sync")
async def sync_zoom_data(
    request: Request,
    force: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Sincroniza datos de Zoom (usuarios y reuniones) con la base de datos local.

    Args:
        force: Si True, fuerza una sincronización completa incluso si hay una reciente
        db: Sesión de base de datos
        current_user: Usuario autenticado

    Returns:
        JSON con estadísticas de la sincronización
    """
    try:
        stats = await zoom_sync_service.sync_data_from_zoom(
            db, current_user.id, force_full_sync=force
        )
        return JSONResponse(
            {
                "success": True,
                "message": "Sincronización completada",
                "stats": stats,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Error en sincronización: {e}")
        raise HTTPException(status_code=500, detail="Error al sincronizar con Zoom")


@router.get("/zoom/sync/status")
async def get_sync_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Obtiene el estado de la última sincronización con Zoom.

    Returns:
        JSON con información del estado de la caché
    """
    last_sync = await zoom_repo.get_config_value(db, "last_sync")
    users_dict = await zoom_repo.get_all_users_as_dict(db, "id")
    meetings_dict = await zoom_repo.get_all_meetings_as_dict(db, "id")

    return JSONResponse(
        {
            "last_sync": last_sync,
            "users_count": len(users_dict),
            "meetings_count": len(meetings_dict),
        }
    )


@router.post("/zoom/assignments/process")
async def process_assignments(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Procesa un archivo Excel con asignaciones de reuniones de Zoom.

    El archivo debe tener columnas 'Group' (nombre de reunión) e 'Instructor' (nombre de instructor).

    Returns:
        JSON con el resultado del procesamiento
    """
    try:
        # Leer archivo Excel
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))

        # Validar columnas requeridas
        if "Group" not in df.columns or "Instructor" not in df.columns:
            raise HTTPException(
                status_code=400,
                detail="El archivo debe contener las columnas 'Group' e 'Instructor'",
            )

        # Cargar caché desde BD
        users, meetings, users_norm, meetings_norm = (
            await zoom_assignment_service.load_cache_from_db(db)
        )

        if not users or not meetings:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Caché vacío. Por favor, sincroniza con Zoom primero.",
                    "requires_sync": True,
                },
                status_code=400,
            )

        # Clasificar filas
        to_update, ok, not_found = zoom_assignment_service.classify_rows(
            df, users, meetings, users_norm, meetings_norm
        )

        return JSONResponse(
            {
                "success": True,
                "summary": {
                    "total": len(df),
                    "to_update": len(to_update),
                    "ok": len(ok),
                    "not_found": len(not_found),
                },
                "to_update": [
                    {
                        "meeting_id": m.id,
                        "meeting_topic": m.topic,
                        "instructor_name": i.display_name,
                        "instructor_email": i.email,
                    }
                    for m, i in to_update
                ],
                "ok": [
                    {
                        "meeting_id": m.id,
                        "meeting_topic": m.topic,
                        "instructor_name": i.display_name,
                        "instructor_email": i.email,
                    }
                    for m, i in ok
                ],
                "not_found": [
                    {
                        "meeting_id": None,
                        "meeting_topic": None,
                        "group": g,
                        "instructor": instr,
                        "instructor_name": instr,
                        "reason": reason,
                    }
                    for g, instr, reason in not_found
                ],
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Error al procesar asignaciones: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error al procesar el archivo: {str(e)}"
        )


@router.post("/zoom/assignments/process-from-schedule")
async def process_assignments_from_schedule(
    request: Request,
    schedule_request: ScheduleAssignmentRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Procesa asignaciones desde el horario actual del usuario.

    Recibe las filas del horario con Group e Instructor y las procesa
    para encontrar las reuniones de Zoom correspondientes.

    Returns:
        JSON con el resultado del procesamiento
    """
    try:
        # Convertir las filas del horario a DataFrame
        if not schedule_request.schedule_rows:
            raise HTTPException(
                status_code=400,
                detail="No hay filas en el horario para procesar",
            )

        # Crear DataFrame desde las filas del horario
        df = pd.DataFrame(schedule_request.schedule_rows)

        # Validar que tenga las columnas necesarias
        if "group" not in df.columns and "Group" not in df.columns:
            raise HTTPException(
                status_code=400,
                detail="El horario debe contener la columna 'group' o 'Group'",
            )
        if "instructor" not in df.columns and "Instructor" not in df.columns:
            raise HTTPException(
                status_code=400,
                detail="El horario debe contener la columna 'instructor' o 'Instructor'",
            )

        # Normalizar nombres de columnas
        if "group" in df.columns:
            df["Group"] = df["group"]
        if "instructor" in df.columns:
            df["Instructor"] = df["instructor"]

        # Cargar caché desde BD
        users, meetings, users_norm, meetings_norm = (
            await zoom_assignment_service.load_cache_from_db(db)
        )

        if not users or not meetings:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Caché vacío. Por favor, sincroniza con Zoom primero.",
                    "requires_sync": True,
                },
                status_code=400,
            )

        # Clasificar filas
        to_update, ok, not_found = zoom_assignment_service.classify_rows(
            df, users, meetings, users_norm, meetings_norm
        )

        return JSONResponse(
            {
                "success": True,
                "summary": {
                    "total": len(df),
                    "to_update": len(to_update),
                    "ok": len(ok),
                    "not_found": len(not_found),
                },
                "to_update": [
                    {
                        "meeting_id": m.id,
                        "meeting_topic": m.topic,
                        "instructor_name": i.display_name,
                        "instructor_email": i.email,
                        "group": m.topic,  # Para referencia
                    }
                    for m, i in to_update
                ],
                "ok": [
                    {
                        "meeting_id": m.id,
                        "meeting_topic": m.topic,
                        "instructor_name": i.display_name,
                        "instructor_email": i.email,
                        "group": m.topic,
                    }
                    for m, i in ok
                ],
                "not_found": [
                    {"group": g, "instructor": instr, "reason": reason}
                    for g, instr, reason in not_found
                ],
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Error al procesar asignaciones desde horario: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error al procesar el horario: {str(e)}"
        )


@router.post("/zoom/assignments/execute")
async def execute_assignments(
    request: Request,
    assignment_request: AssignmentRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Ejecuta las asignaciones de reuniones especificadas.

    Args:
        assignment_request: Objeto con lista de asignaciones (cada una con meeting_id e instructor_email)
        db: Sesión de base de datos
        current_user: Usuario autenticado

    Returns:
        JSON con el resultado de la ejecución
    """
    try:
        # Cargar caché desde BD
        users, meetings, users_norm, meetings_norm = (
            await zoom_assignment_service.load_cache_from_db(db)
        )

        # Crear diccionarios por ID para búsqueda rápida
        meetings_by_id = {m.id: m for m in meetings.values()}
        users_by_email = {u.email: u for u in users.values()}

        to_update = []
        for assignment in assignment_request.assignments:
            meeting_id = assignment.get("meeting_id")
            instructor_email = assignment.get("instructor_email")

            if not meeting_id or not instructor_email:
                continue

            meeting = meetings_by_id.get(meeting_id)
            instructor = users_by_email.get(instructor_email)

            if meeting and instructor:
                to_update.append((meeting, instructor))

        if not to_update:
            return JSONResponse(
                {
                    "success": False,
                    "error": "No hay asignaciones válidas para procesar",
                },
                status_code=400,
            )

        # Procesar asignaciones
        stats = await zoom_assignment_service.process_assignments(
            db, current_user.id, to_update
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Asignaciones procesadas",
                "stats": stats,
            }
        )

    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.error(f"Error al ejecutar asignaciones: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error al ejecutar asignaciones: {str(e)}"
        )


@router.get("/zoom/assignments/history")
async def get_assignment_history(
    request: Request,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user),
):
    """
    Obtiene el historial de asignaciones de reuniones.

    Args:
        limit: Número máximo de registros a retornar

    Returns:
        JSON con el historial de asignaciones
    """
    history = await zoom_repo.get_assignment_history(db, limit=limit)

    return JSONResponse(
        {
            "success": True,
            "history": [
                {
                    "id": h.id,
                    "timestamp": h.timestamp.isoformat(),
                    "meeting_id": h.meeting_id,
                    "meeting_topic": h.meeting_topic,
                    "previous_host_id": h.previous_host_id,
                    "new_host_id": h.new_host_id,
                    "status": h.status,
                }
                for h in history
            ],
        }
    )
