"""
Configuración centralizada de la aplicación.

Este módulo carga y valida todas las variables de entorno y constantes
necesarias para el funcionamiento de la aplicación. Todas las configuraciones
sensible se cargan desde variables de entorno mediante python-dotenv.
"""

import os
from dotenv import load_dotenv
from collections import namedtuple
import base64

# Cargar variables de entorno desde archivo .env
load_dotenv()

# ============================================================================
# CONFIGURACIÓN DE INFRAESTRUCTURA
# ============================================================================

# URL de conexión a Redis para gestión de sesiones
REDIS_URL = os.getenv("REDIS_URL")

# URL de conexión a la base de datos PostgreSQL (asyncpg)
DATABASE_URL = os.getenv("DATABASE_URL")

# Clave de cifrado para tokens (debe ser una clave Fernet válida en base64)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Configuración de logging de queries SQL (False en producción para mejor rendimiento)
# En desarrollo puede ser útil tenerlo en True para debugging
DB_ECHO = os.getenv("DB_ECHO", "False").lower() == "true"

# Validar que todas las variables críticas estén configuradas
if not all([REDIS_URL, DATABASE_URL, ENCRYPTION_KEY]):
    raise RuntimeError(
        "Error en la configuración del entorno. "
        "Verifique que REDIS_URL, DATABASE_URL y ENCRYPTION_KEY estén definidas."
    )

# Validar formato de la clave de cifrado (debe ser base64 y decodificar a 32 bytes)
try:
    decoded_key = base64.urlsafe_b64decode(ENCRYPTION_KEY.encode())
    if len(decoded_key) != 32:
        raise ValueError("La clave debe decodificar a exactamente 32 bytes")
except Exception as e:
    raise TypeError(
        f"Clave de cifrado inválida. Debe ser una clave Fernet válida en base64. Error: {e}"
    )

# Nombre de la cookie de sesión
SESSION_COOKIE_NAME = "file_session_id"

# Configuración de entorno (development, staging, production)
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

# ============================================================================
# CONFIGURACIÓN DE INTEGRACIÓN CON ZOOM
# ============================================================================

# Credenciales OAuth 2.0 de Zoom
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")

# URI de redirección para el callback de OAuth (por defecto localhost)
ZOOM_REDIRECT_URI = os.getenv(
    "ZOOM_REDIRECT_URI", "http://127.0.0.1:8000/auth/zoom/callback"
)

# ============================================================================
# CONFIGURACIÓN DE VALIDACIÓN DE ARCHIVOS
# ============================================================================

# Tamaño máximo permitido para archivos subidos (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

# Longitud máxima para lista de IDs seleccionados (1 MB)
MAX_SELECTED_IDS_LENGTH = 1048576

# Tamaño máximo de sesión en Redis (10 MB)
MAX_SESSION_SIZE = 10 * 1024 * 1024

# Tamaño máximo de schedule_data en sesión (5 MB)
MAX_SCHEDULE_DATA_SIZE = 5 * 1024 * 1024

# TTL para tokens CSRF (1 hora)
CSRF_TOKEN_TTL_SECONDS = 3600

# Extensiones de archivo permitidas para procesamiento
ALLOWED_EXTENSIONS = {".xls", ".xlsx"}

# Tipos MIME permitidos para validación adicional
ALLOWED_MIME_TYPES = {
    "application/vnd.ms-excel",  # Excel 97-2003 (.xls)
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # Excel 2007+ (.xlsx)
}

# ============================================================================
# CONSTANTES DE LÓGICA DE NEGOCIO
# ============================================================================

# Columnas esperadas en archivos Excel generados por el sistema
# Estas columnas definen la estructura estándar de los horarios
EXPECTED_GENERATED_HEADERS = {
    "date",  # Fecha
    "shift",  # Turno
    "area",  # Área o departamento
    "start_time",  # Hora de inicio
    "end_time",  # Hora de fin
    "code",  # Código del instructor
    "instructor",  # Nombre del instructor
    "group",  # Programa
    "minutes",  # Duración
    "units",  # Unidades
}

# Estructura de datos inmutable para representar un horario parseado
# Usa namedtuple para garantizar consistencia en los datos procesados
Schedule = namedtuple("Schedule", EXPECTED_GENERATED_HEADERS)
