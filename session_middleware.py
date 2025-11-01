# session_middleware.py
import json
import uuid
import redis.asyncio as redis
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from config import REDIS_URL, SESSION_COOKIE_NAME

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

class RedisSessionMiddleware(BaseHTTPMiddleware):
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
            session_data = {
                "schedule_data": {
                    "processed_files": [],
                    "all_rows": [],
                }
            }

        request.state.session = session_data
        request.state.session_id = session_id
        request.state.session_cleared = False

        response = await call_next(request)

        if getattr(request.state, "session_cleared", False):
            try:
                await redis_client.delete(f"session:{session_id}")
            except Exception as e:
                print(f"Error borrando la sesión de Redis: {e}")
            response.delete_cookie(SESSION_COOKIE_NAME)
        else:
            try:
                data_to_save_json = json.dumps(request.state.session)
                await redis_client.set(
                    f"session:{session_id}", data_to_save_json, ex=60 * 60 * 24 * 7
                )
            except Exception as e:
                print(f"Error guardando la sesión en Redis: {e}")

            if new_session:
                response.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    httponly=True,
                    samesite="lax",
                    max_age=60 * 60 * 24 * 7,
                )

        return response