# routers/admin.py
"""
Router para endpoints de administración de usuarios.
"""
from fastapi import (
    APIRouter,
    Request,
    Form,
    Depends,
    HTTPException,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user_model import User
from repositories.user_repository import UserRepository
from core.templates import render_template
import security

router = APIRouter()

user_repo = UserRepository()


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(security.get_current_admin_user),
):
    """Lista todos los usuarios (solo para admins)."""
    users = await user_repo.get_all(db)

    token = security.get_or_create_csrf_token(request.state.session)

    return render_template(
        request,
        "admin_users.html",
        {
            "users": users,
            "current_user": current_user,
            "csrf_token": token,
        },
    )


@router.post("/admin/users", response_class=RedirectResponse)
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
        await user_repo.create(
            db=db, username=username, password=password, full_name=full_name, role=role
        )
        return RedirectResponse(
            url="/admin/users?success=user_created", status_code=303
        )
    except HTTPException as e:
        return RedirectResponse(url=f"/admin/users?error={e.detail}", status_code=303)


@router.post("/admin/users/{user_id}/delete", response_class=RedirectResponse)
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
        await user_repo.delete(db, user_id, current_user.id)
        return RedirectResponse(
            url="/admin/users?success=user_deleted", status_code=303
        )
    except HTTPException as e:
        return RedirectResponse(url=f"/admin/users?error={e.detail}", status_code=303)

