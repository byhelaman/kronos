"""
Módulo de seguridad y autenticación.

Proporciona funcionalidades de:
- Cifrado/descifrado de tokens (Fernet)
- Hashing y verificación de contraseñas (bcrypt)
- Validación de tokens CSRF
- Rate limiting
- Dependencias de autenticación y autorización
- Validación de UUIDs
"""
import secrets
import re
from fastapi import Request, Form, HTTPException, Depends, status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from passlib.context import CryptContext

from cryptography.fernet import Fernet, InvalidToken
from core import config
from models.user_model import User

__all__ = ["InvalidToken"]

# ============================================================================
# CONFIGURACIÓN DE CIFRADO Y HASHING
# ============================================================================

# Contexto para hashing de contraseñas usando bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Suite de cifrado Fernet para tokens sensibles (Zoom OAuth tokens)
# Requiere una clave de 32 bytes codificada en base64
try:
    cipher_suite = Fernet(config.ENCRYPTION_KEY.encode())
except Exception as e:
    raise RuntimeError(
        f"Error al inicializar el cifrador Fernet. "
        f"Verifique que ENCRYPTION_KEY sea una clave válida. Error: {e}"
    )


# ============================================================================
# FUNCIONES DE CIFRADO Y DESCIFRADO
# ============================================================================

def encrypt_token(token: str) -> str:
    """
    Cifra un token de texto plano usando Fernet.
    
    Args:
        token: Token en texto plano a cifrar
        
    Returns:
        Token cifrado como string. Retorna string vacío si el token es None/vacío.
    """
    if not token:
        return ""
    encrypted_bytes = cipher_suite.encrypt(token.encode())
    return encrypted_bytes.decode()


def decrypt_token(encrypted_token: str) -> str:
    """
    Descifra un token cifrado usando Fernet.
    
    Args:
        encrypted_token: Token cifrado a descifrar
        
    Returns:
        Token descifrado en texto plano
        
    Raises:
        InvalidToken: Si el token está vacío o es inválido
    """
    if not encrypted_token:
        raise InvalidToken("El token cifrado está vacío.")

    try:
        decrypted_bytes = cipher_suite.decrypt(encrypted_token.encode())
        return decrypted_bytes.decode()
    except InvalidToken as e:
        print(f"Error de descifrado: {e}")
        raise e


# ============================================================================
# VALIDACIÓN DE UUIDs
# ============================================================================

# Patrón regex para validar formato UUID v4 estándar
UUID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
)


def validate_uuid(uuid_str: str) -> bool:
    """
    Valida que un string tenga el formato de un UUID v4 válido.
    
    Args:
        uuid_str: String a validar
        
    Returns:
        True si el string es un UUID válido, False en caso contrario
    """
    return bool(UUID_PATTERN.match(uuid_str))


def validate_uuid_list(uuid_list_str: str, max_ids: int = 1000) -> set[str]:
    """
    Valida y filtra una lista de UUIDs separados por comas.
    
    Esta función es útil para validar listas de IDs enviadas desde el cliente,
    previniendo inyección de datos inválidos y limitando el tamaño de la petición.
    
    Args:
        uuid_list_str: String con UUIDs separados por comas
        max_ids: Número máximo de IDs a procesar (por defecto 1000)
        
    Returns:
        Set con solo los UUIDs válidos encontrados. Set vacío si:
        - La lista está vacía
        - La lista excede 1MB de tamaño
        - No se encuentran UUIDs válidos
    """
    # Validar tamaño máximo de la petición (1MB)
    if not uuid_list_str or len(uuid_list_str) > 1048576:
        return set()

    uuids = uuid_list_str.split(",")
    # Limitar número de IDs para prevenir DoS
    if len(uuids) > max_ids:
        uuids = uuids[:max_ids]

    # Filtrar y validar cada UUID
    return {uid.strip() for uid in uuids if validate_uuid(uid.strip())}


# ============================================================================
# FUNCIONES DE HASHING DE CONTRASEÑAS
# ============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña en texto plano contra su hash bcrypt.
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Hash bcrypt almacenado
        
    Returns:
        True si la contraseña coincide, False en caso contrario
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Genera un hash bcrypt de una contraseña.
    
    El hash incluye automáticamente un salt único para cada contraseña,
    garantizando que dos contraseñas idénticas produzcan hashes diferentes.
    
    Args:
        password: Contraseña en texto plano a hashear
        
    Returns:
        Hash bcrypt de la contraseña
    """
    return pwd_context.hash(password)


# ============================================================================
# CONFIGURACIÓN DE RATE LIMITING
# ============================================================================

# Limiter global que usa la dirección IP del cliente como clave
# Esto previene abuso de la API limitando requests por IP
limiter = Limiter(key_func=get_remote_address)

# Manejador de excepciones para cuando se excede el rate limit
rate_limit_handler = _rate_limit_exceeded_handler

# ============================================================================
# PROTECCIÓN CONTRA CSRF (Cross-Site Request Forgery)
# ============================================================================

async def validate_csrf(request: Request, csrf_token: str = Form(...)):
    """
    Dependencia de FastAPI para validar tokens CSRF en formularios POST.
    
    Esta función:
    1. Valida que el token CSRF enviado coincida con el almacenado en sesión
    2. Usa comparación segura (timing-safe) para prevenir ataques de temporización
    3. Regenera el token después de cada uso exitoso (token rotation)
    
    Args:
        request: Objeto Request de FastAPI
        csrf_token: Token CSRF enviado en el formulario
        
    Returns:
        Nuevo token CSRF generado después de la validación exitosa
        
    Raises:
        HTTPException: Si el token es inválido, está vacío o excede el tamaño máximo
    """
    # Validar longitud del token para prevenir DoS (ataques de denegación de servicio)
    if not csrf_token or len(csrf_token) > 100:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Error de validación CSRF.",
        )

    session = request.state.session
    stored_token = session.get("csrf_token")

    # Comparación segura contra timing attacks usando secrets.compare_digest
    # Esto garantiza que el tiempo de ejecución sea constante independientemente
    # de dónde difieran los tokens
    if not stored_token or not secrets.compare_digest(stored_token, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Error de validación CSRF.",
        )

    # Regenerar token después de uso exitoso (token rotation)
    # Esto previene reutilización de tokens capturados
    new_token = secrets.token_hex(32)
    session["csrf_token"] = new_token

    return new_token


def get_or_create_csrf_token(session: dict) -> str:
    """
    Obtiene el token CSRF de la sesión o crea uno nuevo si no existe.
    
    Esta función se usa para generar tokens CSRF en formularios GET
    y asegurar que cada sesión tenga un token válido.
    
    Args:
        session: Diccionario de sesión del usuario
        
    Returns:
        Token CSRF existente o recién generado
    """
    token = session.get("csrf_token")
    if not token:
        # Generar token criptográficamente seguro de 32 bytes (64 caracteres hex)
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


# ============================================================================
# DEPENDENCIAS DE AUTENTICACIÓN Y AUTORIZACIÓN
# ============================================================================

async def get_current_active_user(request: Request) -> User:
    """
    Dependencia de FastAPI que obtiene el usuario autenticado actual.
    
    Esta función verifica que el usuario esté autenticado y activo.
    Se usa como dependencia en endpoints que requieren autenticación.
    
    Args:
        request: Objeto Request de FastAPI con el estado de la sesión
        
    Returns:
        Modelo User del usuario autenticado
        
    Raises:
        HTTPException: Si el usuario no está autenticado o no está activo
    """
    if not request.state.is_authenticated or not request.state.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Esta acción requiere iniciar sesión.",
        )
    return request.state.user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Dependencia de FastAPI que verifica que el usuario sea administrador.
    
    Esta función debe usarse después de get_current_active_user para
    restringir acceso solo a usuarios con rol 'admin'.
    
    Args:
        current_user: Usuario autenticado obtenido de get_current_active_user
        
    Returns:
        Modelo User del administrador
        
    Raises:
        HTTPException: Si el usuario no tiene rol de administrador
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador.",
        )
    return current_user
