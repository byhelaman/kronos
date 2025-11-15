# routers/admin.py
"""
Router para endpoints de administración de usuarios.
"""
import re
import logging
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
from core.templates import render_template
import security

# Logger para eventos de seguridad
security_logger = logging.getLogger("security")

router = APIRouter()

user_repo = UserRepository()


def validate_username(username: str) -> str:
    """Valida el formato y longitud del nombre de usuario."""
    if not username or len(username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario debe tener al menos 3 caracteres.",
        )
    if len(username) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario no puede exceder 50 caracteres.",
        )
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario solo puede contener letras, números y guiones bajos.",
        )
    return username


def validate_password(password: str) -> str:
    """Valida la política de contraseñas."""
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener al menos 8 caracteres.",
        )
    if len(password) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña no puede exceder 200 caracteres.",
        )
    return password


def validate_full_name(full_name: str) -> str:
    """Valida el nombre completo."""
    if not full_name or len(full_name.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre completo no puede estar vacío.",
        )
    if len(full_name) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre completo no puede exceder 200 caracteres.",
        )
    return full_name.strip()


def validate_role(role: str) -> str:
    """Valida que el rol sea válido."""
    if role not in ["user", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol debe ser 'user' o 'admin'.",
        )
    return role


@router.get("/admin/users", response_class=HTMLResponse)
@security.limiter.limit("30/minute")
async def admin_users_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_admin_user),
    page: int = 1,
    limit: int = 50,
):
    """
    Lista usuarios con paginación (solo para admins).
    
    Args:
        page: Número de página (por defecto 1)
        limit: Usuarios por página (por defecto 50, máximo 100)
    """
    # Validar y limitar parámetros
    page = max(1, page)
    limit = min(max(1, limit), 100)  # Máximo 100 usuarios por página
    offset = (page - 1) * limit
    
    users = await user_repo.get_all(db, limit=limit, offset=offset)
    total_users = await user_repo.count_all(db)
    total_pages = (total_users + limit - 1) // limit if total_users > 0 else 1

    token = security.get_or_create_csrf_token(request.state.session)

    return render_template(
        request,
        "admin_users.html",
        {
            "users": users,
            "current_user": current_user,
            "csrf_token": token,
            "page": page,
            "limit": limit,
            "total_users": total_users,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    )


@router.post("/admin/users", response_class=RedirectResponse)
@security.limiter.limit("10/minute")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_admin_user),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    """Crear nuevo usuario (solo para admins)."""
    try:
        # Validar todas las entradas
        validated_username = validate_username(username)
        validated_password = validate_password(password)
        validated_full_name = validate_full_name(full_name)
        validated_role = validate_role(role)

        await user_repo.create(
            db=db,
            username=validated_username,
            password=validated_password,
            full_name=validated_full_name,
            role=validated_role,
        )
        
        # Log creación de usuario
        security_logger.info(
            f"User created - username: {validated_username} - role: {validated_role} - "
            f"created_by: {current_user.username}"
        )
        
        return RedirectResponse(
            url="/admin/users?success=user_created", status_code=303
        )
    except HTTPException as e:
        # Escapar el mensaje de error para prevenir XSS en la URL
        # Usar urllib.parse.quote para escape seguro de URLs
        from urllib.parse import quote
        error_msg = quote(str(e.detail), safe='')
        return RedirectResponse(
            url=f"/admin/users?error={error_msg}", status_code=303
        )


@router.post("/admin/users/{user_id}/delete", response_class=RedirectResponse)
@security.limiter.limit("10/minute")
async def admin_delete_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_admin_user),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    """Eliminar usuario (solo para admins)."""
    # Validar que el user_id sea un UUID válido
    if not security.validate_uuid(user_id):
        return RedirectResponse(
            url="/admin/users?error=invalid_user_id", status_code=303
        )

    try:
        # Obtener información del usuario antes de eliminarlo para logging
        user_to_delete = await user_repo.get_by_id(db, user_id)
        username_to_delete = user_to_delete.username if user_to_delete else "unknown"
        
        await user_repo.delete(db, user_id, current_user.id)
        
        # Log eliminación de usuario
        security_logger.info(
            f"User deleted - username: {username_to_delete} - "
            f"deleted_by: {current_user.username}"
        )
        
        return RedirectResponse(
            url="/admin/users?success=user_deleted", status_code=303
        )
    except HTTPException as e:
        # Escapar el mensaje de error para prevenir XSS en la URL
        from urllib.parse import quote
        error_msg = quote(str(e.detail), safe='')
        return RedirectResponse(url=f"/admin/users?error={error_msg}", status_code=303)

