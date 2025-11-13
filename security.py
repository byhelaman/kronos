# security.py
import secrets
import re
from fastapi import Request, Form, HTTPException, Depends, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from passlib.context import CryptContext

from cryptography.fernet import Fernet, InvalidToken
import config

__all__ = ["InvalidToken"]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

try:
    cipher_suite = Fernet(config.ENCRYPTION_KEY.encode())
except Exception as e:
    raise RuntimeError(f"Error al inicializar el cifrador Fernet: {e}")


def encrypt_token(token: str) -> str:
    """Cifra un token de texto plano a un string cifrado."""
    if not token:
        return ""
    encrypted_bytes = cipher_suite.encrypt(token.encode())
    return encrypted_bytes.decode()


def decrypt_token(encrypted_token: str) -> str:
    """Descifra un token cifrado de vuelta a texto plano."""
    if not encrypted_token:
        raise InvalidToken("El token cifrado está vacío.")

    try:
        decrypted_bytes = cipher_suite.decrypt(encrypted_token.encode())
        return decrypted_bytes.decode()
    except InvalidToken as e:
        print(f"Error de descifrado: {e}")
        # Re-lanzar para que la función que llama lo maneje
        raise e


# --- Patrón de validación de UUID ---
UUID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
)


def validate_uuid(uuid_str: str) -> bool:
    """Valida que un string sea un UUID válido"""
    return bool(UUID_PATTERN.match(uuid_str))


def validate_uuid_list(uuid_list_str: str, max_ids: int = 1000) -> set[str]:
    """
    Valida y filtra una lista de UUIDs separados por comas.
    Devuelve un set con solo los UUIDs válidos.
    """
    if not uuid_list_str or len(uuid_list_str) > 1048576:  # 1MB max
        return set()

    uuids = uuid_list_str.split(",")
    if len(uuids) > max_ids:
        uuids = uuids[:max_ids]  # Limitar número máximo de IDs

    return {uid.strip() for uid in uuids if validate_uuid(uid.strip())}


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
    REGENERA el token después de una validación exitosa.
    """
    # Validar longitud del token para prevenir DoS
    if not csrf_token or len(csrf_token) > 100:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Error de validación CSRF.",
        )

    session = request.state.session
    stored_token = session.get("csrf_token")

    # Comparamos de forma segura para evitar ataques de temporización
    if not stored_token or not secrets.compare_digest(stored_token, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Error de validación CSRF.",
        )

    # ✅ REGENERAR token después de uso exitoso
    new_token = secrets.token_hex(32)
    session["csrf_token"] = new_token

    return new_token


def get_or_create_csrf_token(session: dict) -> str:
    # --- MODIFICADO ---
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token
    # --- FIN MODIFICACIÓN ---
