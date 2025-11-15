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
            response.raise_for_status()
            return {"success": True}

        except httpx.HTTPStatusError as e:
            error_details = e.response.text
            try:
                error_details = e.response.json()
            except Exception:
                pass
            return {
                "success": False,
                "status_code": e.response.status_code,
                "error": str(error_details),
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

        token = await self.get_access_token(db, user_id)
        sem = asyncio.Semaphore(MAX_WORKERS)

        success_count = 0
        error_count = 0

        async def sem_update(meeting: ZoomMeeting, instructor: ZoomUser):
            nonlocal success_count, error_count

            async with sem:
                result = await self.update_meeting_host(
                    token, meeting.id, instructor.email
                )

                if result.get("success"):
                    # Actualizar caché local
                    await self.zoom_repo.update_meeting_host(
                        db, meeting.id, instructor.id
                    )

                    # Registrar en historial
                    await self.zoom_repo.log_assignment(
                        db=db,
                        meeting_id=meeting.id,
                        meeting_topic=meeting.topic,
                        previous_host_id=meeting.host_id,
                        new_host_id=instructor.id,
                        status="SUCCESS",
                        user_id=user_id,
                    )
                    success_count += 1
                else:
                    error_msg = result.get("error", "Desconocido")
                    # Registrar error en historial
                    await self.zoom_repo.log_assignment(
                        db=db,
                        meeting_id=meeting.id,
                        meeting_topic=meeting.topic,
                        previous_host_id=meeting.host_id,
                        new_host_id=instructor.id,
                        status=f"ERROR: {error_msg}",
                        user_id=user_id,
                    )
                    error_count += 1

        await asyncio.gather(
            *(sem_update(m, i) for m, i in to_update), return_exceptions=True
        )

        return {"success": success_count, "errors": error_count}
