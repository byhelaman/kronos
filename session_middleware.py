import json
import uuid
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

logger = logging.getLogger(__name__)

# Cliente Redis con connection pooling optimizado
# max_connections: número máximo de conexiones en el pool
# retry_on_timeout: reintentar automáticamente en timeouts
# health_check_interval: verificar salud de conexiones periódicamente
redis_client = redis.from_url(
    REDIS_URL,
    decode_responses=True,
    max_connections=50,  # Pool de conexiones para mejor rendimiento
    retry_on_timeout=True,  # Reintentar automáticamente en timeouts
    health_check_interval=30,  # Verificar salud de conexiones cada 30s
)


class RedisSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, templates: Jinja2Templates = None, **kwargs):
        super().__init__(app)
        self.templates = templates

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:

        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = {}
        new_session = False

        if session_id:
            try:
                data_json = await redis_client.get(f"session:{session_id}")
                if data_json:
                    # Usar orjson si está disponible para mejor rendimiento
                    if _USE_ORJSON:
                        session_data = orjson.loads(data_json)
                    else:
                        session_data = json.loads(data_json)
                else:
                    session_id = None
                    logger.info("Sesión no encontrada en Redis")
            except Exception as e:
                logger.error(f"Error al leer de Redis: {e}")
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
            cached_user = session_data.get("_cached_user")
            needs_refresh = session_data.get("_user_cache_expiry", 0) < 0
            
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
                                "full_name": user_db_model.full_name if user_db_model.full_name else "",
                                "role": user_db_model.role,
                                "is_active": user_db_model.is_active,
                                "zoom_user_id": user_db_model.zoom_user_id,
                            }
                            session_data["_cached_user"] = user_dict
                            session_data["_user_cache_expiry"] = 300  # Cache por 5 minutos
                            
                            request.state.user = User.model_validate(user_db_model)
                            request.state.is_authenticated = True
                            logger.debug(f"Usuario autenticado: {user_db_model.username}")

                            # --- OPTIMIZACIÓN: Solo cargar horario si no existe en sesión ---
                            # El horario se carga una vez y se mantiene en sesión
                            # Se actualiza solo cuando se guarda explícitamente
                            if "schedule_data" not in session_data or not session_data.get("schedule_data"):
                                db_schedule = await schedule_repo.get_by_user_id(
                                    db_session, user_db_model.id
                                )
                                if db_schedule:
                                    session_data["schedule_data"] = db_schedule
                                else:
                                    session_data["schedule_data"] = (
                                        schedule_service.get_empty_schedule_data()
                                    )

                        else:
                            # Usuario no existe o inactivo, limpiar sesión
                            session_data["user_id"] = None
                            session_data["is_authenticated"] = False
                            session_data.pop("_cached_user", None)
                            logger.warning(
                                f"Usuario inactivo o no encontrado: {session_user_id}"
                            )

                            if "schedule_data" not in session_data:
                                session_data["schedule_data"] = (
                                    schedule_service.get_empty_schedule_data()
                                )
                except Exception as e:
                    logger.error(f"Error de BD al buscar usuario {session_user_id}: {e}")
                    session_data["user_id"] = None
                    session_data["is_authenticated"] = False
                    session_data.pop("_cached_user", None)
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
                # Decrementar contador de expiración
                session_data["_user_cache_expiry"] = session_data.get("_user_cache_expiry", 300) - 1

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

                # Usar orjson si está disponible para mejor rendimiento
                if _USE_ORJSON:
                    data_to_save_json = orjson.dumps(request.state.session).decode()
                else:
                    data_to_save_json = json.dumps(request.state.session)
                await redis_client.set(
                    f"session:{session_id}",
                    data_to_save_json,
                    ex=60 * 60 * 8,  # 8 horas
                )
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
