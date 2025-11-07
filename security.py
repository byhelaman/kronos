# security.py
import secrets
from fastapi import Request, Form, HTTPException, Depends, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña plana contra un hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Genera un hash bcrypt de una contraseña."""
    return pwd_context.hash(password)


# --- Rate Limiter ---
limiter = Limiter(key_func=get_remote_address)
rate_limit_handler = _rate_limit_exceeded_handler

# --- Lógica Anti-CSRF ---


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
