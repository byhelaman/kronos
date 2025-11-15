"""
Servicio para sincronizar datos de Zoom con la base de datos local.

Este servicio se conecta a la API de Zoom para obtener usuarios y reuniones,
y los almacena en caché local para facilitar las búsquedas y asignaciones.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from repositories.zoom_repository import ZoomRepository
from repositories.user_repository import UserRepository
import security
from services.zoom_utils import canonical
from core.config import ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
from zoom_oauth import get_http_client, OAUTH_URL

logger = logging.getLogger(__name__)

API_BASE = "https://api.zoom.us/v2"
PAGE_SIZE = 300
MAX_WORKERS = 12

# Roles de Zoom a excluir (0=Basic, 1=Licensed)
EXCLUDED_ROLES = {"0", "1"}


class ZoomSyncService:
    """Servicio para sincronizar datos de Zoom."""

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
            
        Raises:
            ValueError: Si el usuario no tiene tokens de Zoom configurados
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
                await self.user_repo.update_zoom_tokens(
                    db=db,
                    user_id=user_id,
                    zoom_user_id=await self._get_zoom_user_id(db, user_id),
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

    async def _get_zoom_user_id(self, db: AsyncSession, user_id: str) -> str:
        """Obtiene el zoom_user_id de un usuario."""
        user = await self.user_repo.get_by_id(db, user_id)
        return user.zoom_user_id if user else ""

    async def list_all_users(self, token: str) -> List[Dict]:
        """
        Obtiene todos los usuarios de Zoom.
        
        Args:
            token: Token de acceso de Zoom
            
        Returns:
            Lista de usuarios de Zoom
        """
        users = []
        next_page_token = None
        headers = {"Authorization": f"Bearer {token}"}

        client = await get_http_client()
        while True:
            params = {"page_size": PAGE_SIZE}
            if next_page_token:
                params["next_page_token"] = next_page_token

            response = await client.get(f"{API_BASE}/users", headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            users_on_page = data.get("users", [])

            # Filtrar usuarios según roles (opcional, basado en config original)
            filtered_users = []
            for u in users_on_page:
                role = u.get("role_id")
                # Incluir todos los usuarios por ahora
                # Puedes agregar filtros aquí si es necesario
                filtered_users.append(u)

            users.extend(filtered_users)

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break

        return users

    async def fetch_meetings_for_user(
        self, client: httpx.AsyncClient, user_id: str, token: str
    ) -> List[Dict]:
        """
        Obtiene todas las reuniones de un usuario de Zoom.
        
        Args:
            client: Cliente HTTP
            user_id: ID del usuario de Zoom
            token: Token de acceso
            
        Returns:
            Lista de reuniones del usuario
        """
        meetings = []
        next_page_token = None
        headers = {"Authorization": f"Bearer {token}"}

        while True:
            params = {"page_size": PAGE_SIZE, "type": "upcoming"}
            if next_page_token:
                params["next_page_token"] = next_page_token

            try:
                response = await client.get(
                    f"{API_BASE}/users/{user_id}/meetings",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                meetings.extend(data.get("meetings", []))

                next_page_token = data.get("next_page_token")
                if not next_page_token:
                    break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Usuario no tiene reuniones o no existe
                    break
                raise

        return meetings

    async def list_all_meetings(
        self, token: str, user_ids: List[str]
    ) -> List[Dict]:
        """
        Obtiene todas las reuniones de una lista de usuarios.
        
        Args:
            token: Token de acceso de Zoom
            user_ids: Lista de IDs de usuarios de Zoom
            
        Returns:
            Lista de todas las reuniones
        """
        headers = {"Authorization": f"Bearer {token}"}
        sem = asyncio.Semaphore(MAX_WORKERS)

        client = await get_http_client()

        async def sem_fetch(uid):
            async with sem:
                return await self.fetch_meetings_for_user(client, uid, token)

        tasks = [sem_fetch(uid) for uid in user_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        flat_list = []
        for res in results:
            if isinstance(res, list):
                flat_list.extend(res)
            else:
                logger.warning(f"Error al obtener reuniones: {res}")

        return flat_list

    async def sync_data_from_zoom(
        self, db: AsyncSession, user_id: str, force_full_sync: bool = False
    ) -> Dict[str, int]:
        """
        Sincroniza usuarios y reuniones de Zoom con la base de datos local.
        
        Args:
            db: Sesión de base de datos
            user_id: ID del usuario de kronos que realiza la sincronización
            force_full_sync: Si True, fuerza una sincronización completa
            
        Returns:
            Diccionario con estadísticas de la sincronización
        """
        # Verificar si hay una sincronización reciente (menos de 3 horas)
        if not force_full_sync:
            last_sync_str = await self.zoom_repo.get_config_value(db, "last_sync")
            if last_sync_str:
                try:
                    last_sync_time = datetime.fromisoformat(last_sync_str)
                    if (datetime.now() - last_sync_time) < timedelta(hours=3):
                        logger.info("Caché actualizada recientemente, omitiendo sincronización")
                        return {"users": 0, "meetings": 0, "skipped": True}
                except ValueError:
                    pass

        logger.info("Iniciando sincronización con Zoom...")

        # Obtener token de acceso
        token = await self.get_access_token(db, user_id)

        # Sincronizar usuarios
        logger.info("Sincronizando usuarios...")
        raw_users = await self.list_all_users(token)
        users_to_db = [
            {
                "id": u["id"],
                "email": u.get("email", ""),
                "display_name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
                "key_canonical": canonical(
                    f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                ),
            }
            for u in raw_users
        ]
        fresh_user_ids = [u["id"] for u in users_to_db]

        # Sincronizar reuniones
        logger.info("Sincronizando reuniones...")
        user_ids = [u["id"] for u in raw_users]
        raw_meetings = await self.list_all_meetings(token, user_ids)

        # Eliminar duplicados por ID
        unique_meetings_by_id = {str(m["id"]): m for m in raw_meetings}

        meetings_to_db = [
            {
                "id": str(m["id"]),
                "topic": m.get("topic", ""),
                "host_id": m.get("host_id", ""),
                "key_canonical": canonical(m.get("topic", "")),
            }
            for m in unique_meetings_by_id.values()
        ]
        fresh_meeting_ids = list(unique_meetings_by_id.keys())

        # Actualizar base de datos
        logger.info("Actualizando base de datos local...")
        await self.zoom_repo.bulk_upsert_users(db, users_to_db)
        await self.zoom_repo.bulk_upsert_meetings(db, meetings_to_db)

        # Eliminar datos obsoletos
        await self.zoom_repo.prune_stale_users(db, fresh_user_ids)
        await self.zoom_repo.prune_stale_meetings(db, fresh_meeting_ids)

        # Guardar timestamp de sincronización
        await self.zoom_repo.set_config_value(
            db, "last_sync", datetime.now().isoformat()
        )

        logger.info(
            f"Sincronización completa: {len(users_to_db)} usuarios, "
            f"{len(meetings_to_db)} reuniones"
        )

        return {
            "users": len(users_to_db),
            "meetings": len(meetings_to_db),
            "skipped": False,
        }

