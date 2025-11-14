# routers/zoom.py
"""
Router para endpoints de integración con Zoom OAuth.
"""
import re
import secrets
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

        # Invalidar cache de usuario para forzar recarga desde BD en el siguiente request
        request.state.session.pop("_cached_user", None)
        request.state.session["_user_cache_expiry"] = 0

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
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error en el callback de Zoom: {e}")
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

