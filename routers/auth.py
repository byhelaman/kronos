"""
Router para endpoints de autenticación y gestión de usuarios.

Este módulo define los endpoints relacionados con:
- Login y logout de usuarios
- Visualización y gestión de perfiles de usuario
- Manejo de sesiones y migración de datos de invitado a usuario autenticado
"""

import uuid
import logging
import hashlib
from typing import Tuple
from fastapi import (
    APIRouter,
    Request,
    Form,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user_model import User
from repositories.user_repository import UserRepository
from repositories.schedule_repository import ScheduleRepository
from services.auth_service import AuthService
from core.templates import render_template
import security

# Logger para eventos de seguridad
security_logger = logging.getLogger("security")

# ============================================================================
# CONFIGURACIÓN DEL ROUTER
# ============================================================================

router = APIRouter()

# Inicializar repositorios y servicios
user_repo = UserRepository()
schedule_repo = ScheduleRepository()
auth_service = AuthService(user_repo, schedule_repo)


# ============================================================================
# VALIDACIÓN DE ENTRADA
# ============================================================================


def validate_login_input(username: str, password: str) -> Tuple[str, str]:
    """
    Valida las entradas de login para prevenir DoS y ataques de inyección.

    Args:
        username: Nombre de usuario a validar
        password: Contraseña a validar

    Returns:
        Tupla con (username, password) validados

    Raises:
        HTTPException: Si las entradas son inválidas
    """
    # Validar username
    if not username or len(username.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credenciales inválidas",
        )
    if len(username) > 100:  # Límite razonable para prevenir DoS
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credenciales inválidas",
        )

    # Validar password
    if not password or len(password) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credenciales inválidas",
        )
    if len(password) > 200:  # Límite razonable para prevenir DoS
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credenciales inválidas",
        )

    return username.strip(), password


# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN
# ============================================================================


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    """
    Muestra el formulario de inicio de sesión.

    Genera un token CSRF para proteger el formulario contra ataques CSRF
    y renderiza la plantilla de login.

    Args:
        request: Objeto Request de FastAPI

    Returns:
        HTMLResponse: Página de login con token CSRF
    """
    token = security.get_or_create_csrf_token(request.state.session)
    return render_template(request, "login.html", {"csrf_token": token})


@router.post("/login", response_class=RedirectResponse)
@security.limiter.limit("3/minute")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    """
    Procesa el inicio de sesión de un usuario.

    Este endpoint:
    1. Valida las entradas y el token CSRF
    2. Autentica las credenciales del usuario
    3. Rota la sesión por seguridad (genera nueva sesión ID)
    4. Migra datos de invitado a usuario autenticado si es necesario
    5. Carga o crea el horario del usuario

    Args:
        request: Objeto Request de FastAPI
        username: Nombre de usuario
        password: Contraseña en texto plano
        db: Sesión de base de datos inyectada
        is_csrf_valid: Validación CSRF (inyectada como dependencia)

    Returns:
        RedirectResponse: Redirección a la página principal si el login es exitoso,
                         o de vuelta al login con mensaje de error si falla
    """
    # Validar Origin/Referer como capa adicional de seguridad CSRF
    if not security.validate_origin(request):
        return RedirectResponse(url="/login?error=invalid_origin", status_code=303)
    
    # Validar entradas antes de procesar
    try:
        validated_username, validated_password = validate_login_input(
            username, password
        )
    except HTTPException:
        # No revelar detalles específicos del error (seguridad)
        return RedirectResponse(url="/login?error=auth_failed", status_code=303)

    # Autenticar usuario con credenciales proporcionadas
    user = await auth_service.authenticate_user(
        db, validated_username, validated_password
    )

    if not user:
        # Log intento de login fallido sin exponer el username completo
        # Usar hash parcial para prevenir enumeración de usuarios
        client_ip = request.client.host if request.client else "unknown"
        username_hash = hashlib.sha256(validated_username.encode()).hexdigest()[:8]
        security_logger.warning(
            f"Failed login attempt - username_hash: {username_hash} - IP: {client_ip}"
        )
        # No revelar si el usuario existe o no (seguridad)
        return RedirectResponse(url="/login?error=auth_failed", status_code=303)

    # Log login exitoso
    client_ip = request.client.host if request.client else "unknown"
    security_logger.info(
        f"Successful login - username: {user.username} - IP: {client_ip}"
    )

    # Rotación de sesión por seguridad (previene session fixation attacks)
    # Se hace antes de actualizar datos para mantener la integridad
    old_session_id = request.state.session_id
    new_session_id = str(uuid.uuid4())
    request.state.session_id = new_session_id
    request.state.session.clear()

    # Manejar el proceso completo de login (migración de datos, carga de horario)
    await auth_service.handle_login(request, db, user)

    # Marcar sesión anterior para limpieza asíncrona
    request.state.old_session_id = old_session_id

    return RedirectResponse(url="/", status_code=303)


@router.get("/logout", response_class=RedirectResponse)
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Cierra la sesión del usuario actual.

    Este endpoint:
    1. Guarda el estado final del horario en la base de datos
    2. Limpia todos los datos de la sesión
    3. Marca la sesión para eliminación en Redis

    Args:
        request: Objeto Request de FastAPI
        db: Sesión de base de datos inyectada

    Returns:
        RedirectResponse: Redirección a la página principal
    """
    await auth_service.handle_logout(request, db)
    return RedirectResponse(url="/", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
@security.limiter.limit("30/minute")
async def user_profile(
    request: Request, current_user: User = Depends(security.get_current_active_user)
):
    """
    Muestra la página de perfil del usuario autenticado.

    Esta página permite al usuario:
    - Ver su información de perfil
    - Gestionar la vinculación con Zoom OAuth
    - Ver el estado de su cuenta

    Args:
        request: Objeto Request de FastAPI
        current_user: Usuario autenticado (obtenido de la dependencia)

    Returns:
        HTMLResponse: Página de perfil con información del usuario

    Raises:
        HTTPException: Si el usuario no está autenticado (manejado por dependencia)
    """
    token = security.get_or_create_csrf_token(request.state.session)

    # Verificar si el usuario tiene una cuenta de Zoom vinculada
    is_zoom_linked = bool(current_user.zoom_user_id)

    return render_template(
        request,
        "profile.html",
        {
            "csrf_token": token,
            "user": current_user,
            "is_zoom_linked": is_zoom_linked,
        },
    )
