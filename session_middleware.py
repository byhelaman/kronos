import json
import uuid
import redis.asyncio as redis
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from fastapi.templating import Jinja2Templates

from config import REDIS_URL, SESSION_COOKIE_NAME
import auth
import schedule_service
from database import AsyncSessionLocal

logger = logging.getLogger(__name__)

redis_client = redis.from_url(REDIS_URL, decode_responses=True)


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
        session_user_id = session_data.get("user_id")
        if session_data.get("is_authenticated") and session_user_id:
            try:
                async with AsyncSessionLocal() as db_session:
                    user_db_model = await auth.get_user_from_db(
                        db_session, session_user_id
                    )

                    if user_db_model and user_db_model.is_active:
                        request.state.user = auth.User.model_validate(user_db_model)
                        request.state.is_authenticated = True
                        logger.debug(f"Usuario autenticado: {user_db_model.username}")

                        # --- INICIO: LÓGICA DE CARGA DE HORARIO ---
                        # Cargar el horario AUTORITATIVO desde la BD
                        db_schedule = await auth.get_schedule_from_db(
                            db_session, user_db_model.id
                        )
                        if db_schedule:
                            session_data["schedule_data"] = db_schedule
                        else:
                            # El usuario está logueado pero no tiene horario guardado
                            session_data["schedule_data"] = (
                                schedule_service.get_empty_schedule_data()
                            )
                        # --- FIN: LÓGICA DE CARGA DE HORARIO ---

                    else:
                        # Usuario no existe o inactivo, limpiar sesión
                        session_data["user_id"] = None
                        session_data["is_authenticated"] = False
                        logger.warning(
                            f"Usuario inactivo o no encontrado: {session_user_id}"
                        )

                        # Mantener los datos del horario de la sesión (ahora es un invitado)
                        if "schedule_data" not in session_data:
                            session_data["schedule_data"] = (
                                schedule_service.get_empty_schedule_data()
                            )

            except Exception as e:
                logger.error(f"Error de BD al buscar usuario {session_user_id}: {e}")
                session_data["user_id"] = None
                session_data["is_authenticated"] = False
                request.state.user = None
                request.state.is_authenticated = False

                if "schedule_data" not in session_data:
                    session_data["schedule_data"] = (
                        schedule_service.get_empty_schedule_data()
                    )
        else:
            # Es un invitado, asegurarse que tenga una estructura de horario
            if "schedule_data" not in session_data:
                session_data["schedule_data"] = (
                    schedule_service.get_empty_schedule_data()
                )

        # Inyección global para templates
        if self.templates:
            self.templates.env.globals["current_user"] = request.state.user
            self.templates.env.globals["is_authenticated"] = (
                request.state.is_authenticated
            )

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

                data_to_save_json = json.dumps(request.state.session)
                await redis_client.set(
                    f"session:{session_id}",
                    data_to_save_json,
                    ex=60 * 60 * 8,  # 8 horas
                )
            except Exception as e:
                logger.error(f"Error guardando la sesión en Redis: {e}")

            if new_session:
                response.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    httponly=True,
                    samesite="lax",
                    secure=True,  # ¡IMPORTANTE: Solo sobre HTTPS!
                    max_age=60 * 60 * 8,  # 8 horas
                )

        return response
