import json
import uuid
import time
import redis.asyncio as redis
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from fastapi.templating import Jinja2Templates

# Optimización: usar orjson si está disponible para serialización JSON más rápida
try:
    import orjson

    _USE_ORJSON = True
except ImportError:
    _USE_ORJSON = False

from core.config import REDIS_URL, SESSION_COOKIE_NAME
from models.user_model import User
from services import schedule_service
from database import AsyncSessionLocal
from repositories.user_repository import UserRepository
from repositories.schedule_repository import ScheduleRepository
import security

logger = logging.getLogger(__name__)

# Cliente Redis con connection pooling optimizado
# max_connections: número máximo de conexiones en el pool
# retry_on_timeout: reintentar automáticamente en timeouts
# health_check_interval: verificar salud de conexiones periódicamente
redis_client = redis.from_url(
    REDIS_URL,
    decode_responses=False,  # Cambiar a False para usar bytes directamente (más eficiente)
    max_connections=50,  # Pool de conexiones para mejor rendimiento
    retry_on_timeout=True,  # Reintentar automáticamente en timeouts
    health_check_interval=30,  # Verificar salud de conexiones cada 30s
)

# Circuit breaker simple para Redis
_redis_failure_count = 0
_redis_last_failure_time = 0
REDIS_CIRCUIT_BREAKER_THRESHOLD = 5  # Número de fallos antes de abrir el circuito
REDIS_CIRCUIT_BREAKER_TIMEOUT = 60  # Segundos antes de intentar reconectar


class RedisSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, templates: Jinja2Templates = None, **kwargs):
        super().__init__(app)
        self.templates = templates

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Declarar variables globales al inicio de la función
        global _redis_failure_count, _redis_last_failure_time
        import time

        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = {}
        new_session = False
        current_time = time.time()

        # Validar formato del session_id para prevenir inyección
        if session_id:
            # Validar que sea un UUID válido (36 caracteres con formato UUID)
            if not security.validate_uuid(session_id):
                logger.warning(f"Invalid session_id format: {session_id[:20]}...")
                session_id = None
            else:
                # Circuit breaker: verificar si Redis está disponible
                
                # Si el circuito está abierto, verificar si podemos intentar reconectar
                if _redis_failure_count >= REDIS_CIRCUIT_BREAKER_THRESHOLD:
                    if (current_time - _redis_last_failure_time) < REDIS_CIRCUIT_BREAKER_TIMEOUT:
                        logger.warning("Redis circuit breaker is OPEN, skipping session read")
                        session_id = None
                    else:
                        # Intentar resetear el circuito
                        _redis_failure_count = 0
                        logger.info("Redis circuit breaker reset, attempting connection")
                
                if session_id:  # Solo intentar si aún tenemos session_id válido
                    try:
                        data_bytes = await redis_client.get(f"session:{session_id}")
                        if data_bytes:
                            # Usar orjson si está disponible para mejor rendimiento
                            if _USE_ORJSON:
                                session_data = orjson.loads(data_bytes)
                            else:
                                session_data = json.loads(data_bytes.decode('utf-8'))
                            # Resetear contador de fallos en caso de éxito
                            _redis_failure_count = 0
                        else:
                            session_id = None
                            logger.info("Sesión no encontrada en Redis")
                    except Exception as e:
                        logger.error(f"Error al leer de Redis: {e}")
                        _redis_failure_count += 1
                        _redis_last_failure_time = current_time
                        session_id = None

        if not session_id:
            new_session = True
            session_id = str(uuid.uuid4())
            # Estado inicial de la sesión (para invitados)
            session_data = {
                # Usar el servicio para el estado inicial
                "schedule_data": schedule_service.get_empty_schedule_data(),
                "user_id": None,
                "is_authenticated": False,
            }

        # Poblamos el estado de la request
        request.state.session = session_data
        request.state.session_id = session_id
        request.state.session_cleared = False

        # Valores por defecto (INVITADO)
        request.state.user = None
        request.state.is_authenticated = False

        # Manejar rotación de sesión (login)
        old_session_id = getattr(request.state, "old_session_id", None)
        if old_session_id:
            try:
                await redis_client.delete(f"session:{old_session_id}")
            except Exception as e:
                logger.error(f"Error eliminando sesión anterior: {e}")

        # Si la sesión dice que el usuario está logueado, cargarlo desde BD
        # OPTIMIZACIÓN: Solo consultar BD si no hay datos de usuario en cache o si necesita refrescarse
        session_user_id = session_data.get("user_id")
        if session_data.get("is_authenticated") and session_user_id:
            # Verificar si tenemos datos de usuario en cache (evita query innecesario)
            # OPTIMIZACIÓN: Usar timestamp en lugar de contador para mejor rendimiento
            cached_user = session_data.get("_cached_user")
            cache_timestamp = session_data.get("_user_cache_timestamp", 0)
            CACHE_TTL_SECONDS = 300  # Cache por 5 minutos
            needs_refresh = (current_time - cache_timestamp) > CACHE_TTL_SECONDS

            if not cached_user or needs_refresh:
                try:
                    async with AsyncSessionLocal() as db_session:
                        user_repo = UserRepository()
                        schedule_repo = ScheduleRepository()

                        user_db_model = await user_repo.get_by_id(
                            db_session, session_user_id
                        )

                        if user_db_model and user_db_model.is_active:
                            # Cachear datos del usuario en la sesión (evita queries repetidas)
                            # IMPORTANTE: Los campos deben coincidir exactamente con el modelo User de Pydantic
                            # El modelo User requiere: id, username, full_name, role, is_active, zoom_user_id
                            user_dict = {
                                "id": user_db_model.id,
                                "username": user_db_model.username,
                                "full_name": (
                                    user_db_model.full_name
                                    if user_db_model.full_name
                                    else ""
                                ),
                                "role": user_db_model.role,
                                "is_active": user_db_model.is_active,
                                "zoom_user_id": user_db_model.zoom_user_id,
                            }
                            session_data["_cached_user"] = user_dict
                            session_data["_user_cache_timestamp"] = current_time

                            request.state.user = User.model_validate(user_db_model)
                            request.state.is_authenticated = True
                            logger.debug(
                                f"Usuario autenticado: {user_db_model.username}"
                            )

                            # --- OPTIMIZACIÓN: Carga lazy de schedule_data ---
                            # Solo cargar schedule si se marca explícitamente como necesario
                            # o si no existe en sesión. Esto evita cargar datos grandes innecesariamente
                            schedule_data = session_data.get("schedule_data")
                            schedule_loaded = session_data.get("_schedule_loaded", False)
                            
                            # Solo cargar si no está cargado o está vacío
                            if not schedule_loaded or not schedule_data or not schedule_data.get("all_rows"):
                                db_schedule = await schedule_repo.get_by_user_id(
                                    db_session, user_db_model.id
                                )
                                if db_schedule:
                                    session_data["schedule_data"] = db_schedule
                                    session_data["_schedule_loaded"] = True
                                else:
                                    session_data["schedule_data"] = (
                                        schedule_service.get_empty_schedule_data()
                                    )
                                    session_data["_schedule_loaded"] = True

                        else:
                            # Usuario no existe o inactivo, limpiar sesión
                            session_data["user_id"] = None
                            session_data["is_authenticated"] = False
                            session_data.pop("_cached_user", None)
                            session_data.pop("_user_cache_timestamp", None)
                            logger.warning(
                                f"Usuario inactivo o no encontrado: {session_user_id}"
                            )

                            if "schedule_data" not in session_data:
                                session_data["schedule_data"] = (
                                    schedule_service.get_empty_schedule_data()
                                )
                except Exception as e:
                    logger.error(
                        f"Error de BD al buscar usuario {session_user_id}: {e}"
                    )
                    session_data["user_id"] = None
                    session_data["is_authenticated"] = False
                    session_data.pop("_cached_user", None)
                    session_data.pop("_user_cache_timestamp", None)
                    request.state.user = None
                    request.state.is_authenticated = False

                    if "schedule_data" not in session_data:
                        session_data["schedule_data"] = (
                            schedule_service.get_empty_schedule_data()
                        )
            else:
                # Usar datos cacheados (evita query a BD)
                request.state.user = User(**cached_user)
                request.state.is_authenticated = True
                # No necesitamos actualizar el timestamp aquí, se mantiene hasta que expire

        else:
            # Es un invitado, asegurarse que tenga una estructura de horario
            if "schedule_data" not in session_data:
                session_data["schedule_data"] = (
                    schedule_service.get_empty_schedule_data()
                )

        # Las variables de autenticación se inyectan dinámicamente
        # a través del context processor en core/templates.py
        # Esto asegura que siempre reflejen el estado actual de la request

        response = await call_next(request)

        # Guardar sesión en Redis
        if getattr(request.state, "session_cleared", False):
            try:
                await redis_client.delete(f"session:{session_id}")
                logger.info(f"Sesión eliminada: {session_id}")
            except Exception as e:
                logger.error(f"Error borrando la sesión de Redis: {e}")
            response.delete_cookie(SESSION_COOKIE_NAME)
        else:
            try:
                # Sincronizar estado de autenticación
                if request.state.is_authenticated and request.state.user:
                    request.state.session["user_id"] = request.state.user.id
                    request.state.session["is_authenticated"] = True
                elif not request.state.is_authenticated:
                    request.state.session["user_id"] = None
                    request.state.session["is_authenticated"] = False

                # Validar tamaño de sesión antes de guardar
                from core.config import MAX_SESSION_SIZE
                import sys
                
                # Calcular tamaño aproximado de la sesión
                session_size = sys.getsizeof(str(request.state.session))
                if session_size > MAX_SESSION_SIZE:
                    logger.warning(f"Sesión excede tamaño máximo ({session_size} bytes), truncando schedule_data")
                    # Truncar schedule_data si es muy grande
                    if "schedule_data" in request.state.session:
                        schedule_data = request.state.session["schedule_data"]
                        if sys.getsizeof(str(schedule_data)) > MAX_SESSION_SIZE // 2:
                            # Limpiar schedule_data grande, se cargará desde BD cuando se necesite
                            request.state.session["schedule_data"] = schedule_service.get_empty_schedule_data()
                            request.state.session["_schedule_loaded"] = False
                
                # Usar orjson si está disponible para mejor rendimiento
                # Redis puede aceptar bytes directamente, evitando decode innecesario
                if _USE_ORJSON:
                    data_to_save = orjson.dumps(request.state.session)
                else:
                    data_to_save = json.dumps(request.state.session).encode('utf-8')
                
                try:
                    await redis_client.set(
                        f"session:{session_id}",
                        data_to_save,
                        ex=60 * 60 * 8,  # 8 horas
                    )
                    # Resetear contador de fallos en caso de éxito
                    _redis_failure_count = 0
                except Exception as e:
                    logger.error(f"Error guardando la sesión en Redis: {e}")
                    _redis_failure_count += 1
                    _redis_last_failure_time = current_time
            except Exception as e:
                logger.error(f"Error guardando la sesión en Redis: {e}")

            if new_session:
                from core.config import IS_PRODUCTION

                response.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    httponly=True,
                    samesite="lax",
                    secure=IS_PRODUCTION,  # Solo HTTPS en producción
                    max_age=60 * 60 * 8,  # 8 horas
                )

        return response
