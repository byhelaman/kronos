"""
Servicio para procesar asignaciones de reuniones de Zoom desde archivos Excel.

Este servicio lee archivos Excel con asignaciones, las clasifica y ejecuta
las reasignaciones de hosts de reuniones en Zoom.
"""

import asyncio
import logging
from typing import List, Dict, Tuple, Optional
import pandas as pd
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from repositories.zoom_repository import ZoomRepository
from repositories.user_repository import UserRepository
import security
from services.zoom_utils import canonical, normalizar_cadena, fuzzy_find
from zoom_oauth import get_http_client

logger = logging.getLogger(__name__)

API_BASE = "https://api.zoom.us/v2"
MAX_WORKERS = 12


class ZoomUser:
    """Modelo simple para representar un usuario de Zoom."""

    def __init__(self, id: str, email: str, display_name: str, key_canonical: str):
        self.id = id
        self.email = email
        self.display_name = display_name
        self.key_canonical = key_canonical


class ZoomMeeting:
    """Modelo simple para representar una reunión de Zoom."""

    def __init__(self, id: str, topic: str, host_id: str, key_canonical: str):
        self.id = id
        self.topic = topic
        self.host_id = host_id
        self.key_canonical = key_canonical


class ZoomAssignmentService:
    """Servicio para procesar asignaciones de reuniones de Zoom."""

    def __init__(self):
        self.zoom_repo = ZoomRepository()
        self.user_repo = UserRepository()

    async def get_access_token(self, db: AsyncSession, user_id: str) -> str:
        """
        Obtiene un token de acceso válido para la API de Zoom.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario de kronos

        Returns:
            Token de acceso de Zoom
        """
        tokens = await self.user_repo.get_zoom_tokens(db, user_id)
        if not tokens:
            raise ValueError(
                "El usuario no tiene tokens de Zoom configurados. "
                "Por favor, vincula tu cuenta de Zoom primero."
            )

        refresh_token = tokens["refresh_token"]

        # Renovar token si es necesario
        import base64
        from core.config import ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
        from zoom_oauth import OAUTH_URL

        auth_header = base64.b64encode(
            f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {auth_header}"}
        params = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        client = await get_http_client()
        try:
            response = await client.post(OAUTH_URL, headers=headers, params=params)
            response.raise_for_status()
            new_tokens = response.json()

            # Actualizar tokens en la base de datos
            if new_refresh_token := new_tokens.get("refresh_token"):
                user = await self.user_repo.get_by_id(db, user_id)
                await self.user_repo.update_zoom_tokens(
                    db=db,
                    user_id=user_id,
                    zoom_user_id=user.zoom_user_id,
                    access_token=new_tokens["access_token"],
                    refresh_token=new_refresh_token,
                )

            return new_tokens["access_token"]

        except httpx.HTTPStatusError as e:
            logger.error(f"Error al renovar token de Zoom: {e.response.text}")
            raise ValueError(
                "No se pudo renovar la conexión con Zoom. "
                "Por favor, vincula tu cuenta de Zoom nuevamente."
            )

    async def load_cache_from_db(self, db: AsyncSession) -> Tuple[
        Dict[str, ZoomUser],
        Dict[str, ZoomMeeting],
        Dict[str, ZoomUser],
        Dict[str, ZoomMeeting],
    ]:
        """
        Carga usuarios y reuniones desde la base de datos.

        Returns:
            Tupla con (users, meetings, users_norm, meetings_norm)
        """
        users_from_db = await self.zoom_repo.get_all_users_as_dict(db, "key_canonical")
        meetings_from_db = await self.zoom_repo.get_all_meetings_as_dict(
            db, "key_canonical"
        )

        users: Dict[str, ZoomUser] = {
            k: ZoomUser(**v) for k, v in users_from_db.items()
        }
        meetings: Dict[str, ZoomMeeting] = {
            k: ZoomMeeting(**v) for k, v in meetings_from_db.items()
        }

        # Crear diccionarios normalizados para fuzzy matching
        users_norm = {normalizar_cadena(u.display_name): u for u in users.values()}
        meetings_norm = {normalizar_cadena(m.topic): m for m in meetings.values()}

        return users, meetings, users_norm, meetings_norm

    def classify_rows(
        self,
        df: pd.DataFrame,
        users: Dict[str, ZoomUser],
        meetings: Dict[str, ZoomMeeting],
        users_norm: Dict[str, ZoomUser],
        meetings_norm: Dict[str, ZoomMeeting],
    ) -> Tuple[
        List[Tuple[ZoomMeeting, ZoomUser]],
        List[Tuple[ZoomMeeting, ZoomUser]],
        List[Tuple[str, str, str]],
    ]:
        """
        Clasifica las filas del Excel en tres categorías:
        - to_update: Reuniones que necesitan reasignación
        - ok: Reuniones que ya están correctamente asignadas
        - not_found: Reuniones o instructores no encontrados

        Args:
            df: DataFrame con las filas del Excel
            users: Diccionario de usuarios indexado por key_canonical
            meetings: Diccionario de reuniones indexado por key_canonical
            users_norm: Diccionario de usuarios indexado por nombre normalizado
            meetings_norm: Diccionario de reuniones indexado por topic normalizado

        Returns:
            Tupla con (to_update, ok, not_found)
        """
        to_update = []
        ok = []
        not_found = []

        for _, row in df.iterrows():
            raw_group = str(row.get("Group", ""))
            raw_instr = str(row.get("Instructor", ""))

            key_t = canonical(raw_group)
            key_i = canonical(raw_instr)

            # Buscar reunión
            meeting = meetings.get(key_t)
            if not meeting:
                meeting = fuzzy_find(raw_group, meetings_norm)

            # Buscar instructor
            instructor = users.get(key_i)
            if not instructor:
                instructor = fuzzy_find(raw_instr, users_norm)

            if not meeting or not instructor:
                reason = "Meeting not found" if not meeting else "Instructor not found"
                not_found.append((raw_group, raw_instr, reason))
                continue

            if meeting.host_id == instructor.id:
                ok.append((meeting, instructor))
            else:
                to_update.append((meeting, instructor))

        return to_update, ok, not_found

    def _extract_zoom_error_message(self, error_response) -> str:
        """
        Extrae un mensaje de error claro del response de Zoom.

        Args:
            error_response: Respuesta de error de Zoom (string, dict, o cualquier otro tipo)

        Returns:
            Mensaje de error legible
        """
        try:
            error_dict = None

            if isinstance(error_response, str):
                import json
                import ast

                # Primero intentar parsear como JSON
                try:
                    error_dict = json.loads(error_response)
                except json.JSONDecodeError:
                    # Si no es JSON válido, intentar parsearlo como dict literal de Python
                    try:
                        # Reemplazar comillas simples por dobles para JSON
                        normalized = error_response.replace("'", '"')
                        error_dict = json.loads(normalized)
                    except:
                        # Si falla, intentar con ast.literal_eval (más seguro que eval)
                        try:
                            error_dict = ast.literal_eval(error_response)
                        except:
                            # Si todo falla, retornar el string original
                            pass
            elif isinstance(error_response, dict):
                error_dict = error_response

            # Extraer mensaje del dict parseado
            if isinstance(error_dict, dict):
                # Zoom devuelve errores en formato: {"code": X, "message": "..."}
                if "message" in error_dict:
                    return str(error_dict["message"])
                elif "error" in error_dict:
                    if isinstance(error_dict["error"], dict):
                        if "message" in error_dict["error"]:
                            return str(error_dict["error"]["message"])
                        return str(error_dict["error"])
                    return str(error_dict["error"])

            # Si no se pudo parsear, retornar el string original
            return str(error_response)
        except Exception:
            return str(error_response)

    async def update_meeting_host(
        self, token: str, meeting_id: str, new_host_email: str
    ) -> Dict:
        """
        Actualiza el host de una reunión en Zoom.

        Args:
            token: Token de acceso de Zoom
            meeting_id: ID de la reunión
            new_host_email: Email del nuevo host

        Returns:
            Diccionario con el resultado de la operación
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {"schedule_for": new_host_email}

        client = await get_http_client()
        try:
            response = await client.patch(
                f"{API_BASE}/meetings/{meeting_id}", headers=headers, json=payload
            )

            # Verificar si el código de estado es exitoso (2xx)
            if 200 <= response.status_code < 300:
                return {"success": True}

            # Si no es exitoso, tratar como error
            error_details = None
            try:
                error_details = response.json()
            except Exception:
                # Si no es JSON, usar el texto de la respuesta
                error_details = response.text

            return {
                "success": False,
                "status_code": response.status_code,
                "error": error_details,
            }

        except httpx.HTTPStatusError as e:
            error_details = None
            try:
                error_details = e.response.json()
            except Exception:
                # Si no es JSON, usar el texto de la respuesta
                error_details = e.response.text

            return {
                "success": False,
                "status_code": e.response.status_code,
                "error": error_details,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def process_assignments(
        self,
        db: AsyncSession,
        user_id: str,
        to_update: List[Tuple[ZoomMeeting, ZoomUser]],
    ) -> Dict[str, int]:
        """
        Procesa una lista de asignaciones de reuniones.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario de kronos que realiza las asignaciones
            to_update: Lista de tuplas (meeting, instructor) a actualizar

        Returns:
            Diccionario con estadísticas del procesamiento
        """
        if not to_update:
            return {"success": 0, "errors": 0}

        try:
            token = await self.get_access_token(db, user_id)
        except Exception as e:
            logger.error(f"Error obteniendo token de acceso: {e}", exc_info=True)
            raise

        sem = asyncio.Semaphore(MAX_WORKERS)

        success_count = 0
        error_count = 0
        error_summary = {}  # Para agrupar errores por tipo
        history_logs = []  # Acumular logs para commit masivo
        cache_updates = []  # Acumular actualizaciones de caché para commit masivo

        async def sem_update(meeting: ZoomMeeting, instructor: ZoomUser):
            nonlocal success_count, error_count, error_summary, history_logs, cache_updates

            try:
                async with sem:
                    result = await self.update_meeting_host(
                        token, meeting.id, instructor.email
                    )

                    # Verificar explícitamente si fue exitoso
                    if result and result.get("success") is True:
                        # Acumular actualización de caché (se aplicará masivamente después)
                        cache_updates.append(
                            {
                                "meeting_id": meeting.id,
                                "new_host_id": instructor.id,
                            }
                        )

                        # Agregar log al historial (se commiteará masivamente después)
                        history_logs.append(
                            {
                                "meeting_id": meeting.id,
                                "meeting_topic": meeting.topic,
                                "previous_host_id": meeting.host_id,
                                "new_host_id": instructor.id,
                                "status": "SUCCESS",
                                "user_id": user_id,
                            }
                        )
                        success_count += 1
                    else:
                        error_msg = result.get("error", "Desconocido")
                        status_code = result.get("status_code")

                        # Extraer mensaje de error más claro si es de Zoom
                        zoom_error_msg = self._extract_zoom_error_message(error_msg)

                        # Agrupar errores por tipo para estadísticas
                        error_key = str(status_code) if status_code else "Unknown"
                        if error_key not in error_summary:
                            error_summary[error_key] = {
                                "count": 0,
                                "status_code": status_code,
                                "sample_error": zoom_error_msg,
                            }
                        error_summary[error_key]["count"] += 1

                        # Agregar log de error al historial (se commiteará masivamente después)
                        history_logs.append(
                            {
                                "meeting_id": meeting.id,
                                "meeting_topic": meeting.topic,
                                "previous_host_id": meeting.host_id,
                                "new_host_id": instructor.id,
                                "status": f"ERROR: {zoom_error_msg}",
                                "user_id": user_id,
                            }
                        )
                        error_count += 1
            except Exception as e:
                # Manejar excepciones inesperadas
                logger.error(
                    f"Error procesando asignación {meeting.id} -> {instructor.email}: {e}",
                    exc_info=True,
                )
                error_msg = str(e)

                # Agregar log de error al historial (se commiteará masivamente después)
                history_logs.append(
                    {
                        "meeting_id": meeting.id,
                        "meeting_topic": meeting.topic,
                        "previous_host_id": meeting.host_id,
                        "new_host_id": instructor.id,
                        "status": f"ERROR: {error_msg}",
                        "user_id": user_id,
                    }
                )
                error_count += 1

        results = await asyncio.gather(
            *(sem_update(m, i) for m, i in to_update), return_exceptions=True
        )

        # Verificar si hay excepciones no manejadas en los resultados
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Excepción no manejada en asignación {i}: {result}", exc_info=True
                )

        # Commit masivo de todos los logs del historial y actualizaciones de caché
        if history_logs or cache_updates:
            try:
                from datetime import datetime
                from sqlalchemy.future import select
                import db_models

                # Actualizar caché masivamente (evita conflictos de transacciones concurrentes)
                if cache_updates:
                    # Obtener todas las reuniones que necesitan actualizarse
                    meeting_ids = [cu["meeting_id"] for cu in cache_updates]
                    query = select(db_models.ZoomMeetingCache).where(
                        db_models.ZoomMeetingCache.id.in_(meeting_ids)
                    )
                    result = await db.execute(query)
                    meetings_to_update = {m.id: m for m in result.scalars().all()}

                    # Actualizar todas las reuniones
                    for cache_update in cache_updates:
                        meeting = meetings_to_update.get(cache_update["meeting_id"])
                        if meeting:
                            meeting.host_id = cache_update["new_host_id"]

                # Agregar logs del historial
                for log_entry in history_logs:
                    history_entry = db_models.ZoomAssignmentHistory(
                        timestamp=datetime.now(),
                        meeting_id=log_entry["meeting_id"],
                        meeting_topic=log_entry["meeting_topic"],
                        previous_host_id=log_entry["previous_host_id"],
                        new_host_id=log_entry["new_host_id"],
                        status=log_entry["status"],
                        user_id=log_entry["user_id"],
                    )
                    db.add(history_entry)

                await db.commit()
            except Exception as commit_error:
                logger.error(
                    f"Error haciendo commit masivo: {commit_error}",
                    exc_info=True,
                )
                # Intentar rollback
                try:
                    await db.rollback()
                except Exception:
                    pass

        final_stats = {
            "success": success_count,
            "errors": error_count,
            "error_summary": error_summary,
        }

        if error_count > 0:
            logger.warning(
                f"Procesamiento completado con {error_count} error(es) de {len(to_update)} asignación(es)"
            )

        return final_stats
