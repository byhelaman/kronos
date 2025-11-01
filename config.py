# config.py
import os
from dotenv import load_dotenv
from collections import namedtuple

load_dotenv()

# --- Configuración de la App ---
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise RuntimeError("La variable de entorno REDIS_URL no está configurada.")

SESSION_COOKIE_NAME = "file_session_id"

# --- Constantes de Archivos ---
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