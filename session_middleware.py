# session_middleware.py
import json
import uuid
import redis.asyncio as redis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from fastapi.templating import Jinja2Templates

# --- IMPORTACIONES CORREGIDAS ---
from config import REDIS_URL, SESSION_COOKIE_NAME
import auth  # Importamos el módulo de autenticación
from database import AsyncSessionLocal  # <-- ¡NUEVA IMPORTACIÓN!

# --------------------------------

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
            except Exception as e:
                print(f"Error al leer de Redis: {e}")
                session_id = None

        if not session_id:
            new_session = True
            session_id = str(uuid.uuid4())
            # Estado inicial de la sesión
            session_data = {
                "schedule_data": {
                    "processed_files": [],
                    "all_rows": [],
                },
                "user_id": None,  # ID de nuestro sistema
                "is_authenticated": False,
            }

        # --- LÓGICA DE AUTENTICACIÓN MEJORADA ---
        # Poblamos el estado de la request
        request.state.session = session_data
        request.state.session_id = session_id
        request.state.session_cleared = False

        # Valores por defecto (INVITADO)
        request.state.user = None
        request.state.is_authenticated = False

        # Si la sesión dice que el usuario está logueado,
        # intentamos cargarlo desde nuestra "BD"
        session_user_id = session_data.get("user_id")
        if session_data.get("is_authenticated") and session_user_id:

            # --- INICIO DE LA CORRECCIÓN ---
            # El middleware debe crear su propia sesión de BD
            # ya que no puede usar la inyección de dependencias de FastAPI.
            try:
                async with AsyncSessionLocal() as db_session:
                    # 1. Llamamos a la función con la sesión
                    user_db_model = await auth.get_user_from_db(
                        db_session, session_user_id
                    )

                    if user_db_model:
                        # 2. Convertimos el modelo de BD (db_models.User)
                        # al modelo Pydantic (auth.User) para el request.state
                        request.state.user = auth.User.model_validate(user_db_model)
                        request.state.is_authenticated = True
                    else:
                        # El usuario no existe o fue borrado, limpiamos la sesión
                        session_data["user_id"] = None
                        session_data["is_authenticated"] = False

            except Exception as e:
                # Si hay un error de BD, deslogueamos al usuario por seguridad
                print(
                    f"Error de BD en middleware al buscar usuario {session_user_id}: {e}"
                )
                session_data["user_id"] = None
                session_data["is_authenticated"] = False
                request.state.user = None
                request.state.is_authenticated = False
            # --- FIN DE LA CORRECCIÓN ---

        # 3. ¡MOVER LA LÓGICA DE INYECCIÓN GLOBAL AQUÍ!
        # Esto sucede DESPUÉS de identificar al usuario,
        # pero ANTES de que se ejecute el endpoint.
        if self.templates:
            self.templates.env.globals["current_user"] = request.state.user
            self.templates.env.globals["is_authenticated"] = (
                request.state.is_authenticated
            )
        # ----------------------------------------

        response = await call_next(request)

        # Guardamos la sesión en Redis
        if getattr(request.state, "session_cleared", False):
            try:
                await redis_client.delete(f"session:{session_id}")
            except Exception as e:
                print(f"Error borrando la sesión de Redis: {e}")
            response.delete_cookie(SESSION_COOKIE_NAME)
        else:
            try:
                # Asegurarnos que la data de usuario no se guarde en la sesión, solo el ID
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
                print(f"Error guardando la sesión en Redis: {e}")

            if new_session:
                response.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    httponly=True,
                    samesite="lax",
                    max_age=60 * 60 * 8,  # 8 horas
                )

        return response
