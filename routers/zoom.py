# routers/zoom.py
"""
Router para endpoints de integración con Zoom OAuth.
"""
from fastapi import (
    APIRouter,
    Request,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user_model import User
from repositories.user_repository import UserRepository
import zoom_oauth
import security
from core.config import ZOOM_CLIENT_ID

router = APIRouter()

user_repo = UserRepository()


@router.get("/auth/zoom")
async def zoom_auth_start(
    request: Request, current_user: User = Depends(security.get_current_active_user)
):
    """Inicia el proceso de vinculación con Zoom."""
    if not ZOOM_CLIENT_ID:
        raise HTTPException(500, "Zoom no está configurado en el servidor.")

    # Obtener AMBOS valores de la función
    auth_url, code_verifier = zoom_oauth.get_zoom_auth_url()

    # Guardar el verifier en la sesión ANTES de redirigir
    request.state.session["zoom_code_verifier"] = code_verifier

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

    return RedirectResponse(url="/profile?success=zoom_unlinked", status_code=303)


@router.get("/auth/zoom/callback")
async def zoom_auth_callback(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Callback de OAuth de Zoom."""
    # Verificamos autenticación
    if not request.state.is_authenticated or not request.state.user:
        return RedirectResponse(url="/login?error=zoom_auth_failed", status_code=303)

    current_user = request.state.user
    code_verifier = request.state.session.pop("zoom_code_verifier", None)

    if not code_verifier:
        # Si falla, cerramos el popup y recargamos la principal con error
        return HTMLResponse(
            """
            <script>
                if (window.opener) {
                    window.opener.location.href = '/profile?error=zoom_session_expired';
                    window.close();
                } else {
                    window.location.href = '/profile?error=zoom_session_expired';
                }
            </script>
            """
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

        # Devolvemos un script JS para actualizar la ventana PADRE y cerrar el POPUP
        return HTMLResponse(
            """
            <script>
                if (window.opener) {
                    window.opener.location.href = '/profile?success=zoom_linked';
                    window.close();
                } else {
                    window.location.href = '/profile?success=zoom_linked';
                }
            </script>
            """
        )

    except Exception as e:
        print(f"Error en el callback de Zoom: {e}")
        return HTMLResponse(
            """
            <script>
                if (window.opener) {
                    window.opener.location.href = '/profile?error=zoom_link_failed';
                    window.close();
                } else {
                    window.location.href = '/profile?error=zoom_link_failed';
                }
            </script>
            """
        )

