# config.py
import os
from dotenv import load_dotenv
from collections import namedtuple
import base64

load_dotenv()

# --- Configuración de la App ---
REDIS_URL = os.getenv("REDIS_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Validación básica sin exponer detalles sensibles
if not all([REDIS_URL, DATABASE_URL, ENCRYPTION_KEY]):
    raise RuntimeError("Error en la configuración del entorno.")

try:
    decoded_key = base64.urlsafe_b64decode(ENCRYPTION_KEY.encode())
    if len(decoded_key) != 32:
        raise ValueError
except Exception:
    raise TypeError("Clave de cifrado inválida.")

SESSION_COOKIE_NAME = "file_session_id"

ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_REDIRECT_URI = os.getenv(
    "ZOOM_REDIRECT_URI", "http://127.0.0.1:8000/auth/zoom/callback"
)


MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_SELECTED_IDS_LENGTH = 1048576
ALLOWED_EXTENSIONS = {".xls", ".xlsx"}
ALLOWED_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# --- Constantes de Lógica de Negocio ---
EXPECTED_GENERATED_HEADERS = {
    "date",
    "shift",
    "area",
    "start_time",
    "end_time",
    "code",
    "instructor",
    "group",
    "minutes",
    "units",
}

# Definición de la estructura de datos que esperamos del parser
Schedule = namedtuple("Schedule", EXPECTED_GENERATED_HEADERS)
