"""
Repositorio para operaciones de base de datos relacionadas con Zoom.

Gestiona el caché de usuarios y reuniones de Zoom, así como el historial
de asignaciones y la configuración de sincronización.
"""
import logging
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

import db_models

logger = logging.getLogger(__name__)


class ZoomRepository:
    """Repositorio para gestionar datos de Zoom en la base de datos."""

    @staticmethod
    async def get_all_users_as_dict(
        db: AsyncSession, key_column: str = "key_canonical"
    ) -> Dict[str, Dict]:
        """
        Obtiene todos los usuarios de Zoom en caché como diccionario.
        
        Args:
            db: Sesión de base de datos
            key_column: Columna a usar como clave del diccionario
            
        Returns:
            Diccionario con usuarios indexados por la columna especificada
        """
        query = select(db_models.ZoomUserCache)
        result = await db.execute(query)
        users = result.scalars().all()
        
        if key_column == "key_canonical":
            return {u.key_canonical: {"id": u.id, "email": u.email, "display_name": u.display_name, "key_canonical": u.key_canonical} for u in users}
        elif key_column == "id":
            return {u.id: {"id": u.id, "email": u.email, "display_name": u.display_name, "key_canonical": u.key_canonical} for u in users}
        else:
            raise ValueError(f"Columna no válida: {key_column}")

    @staticmethod
    async def get_all_meetings_as_dict(
        db: AsyncSession, key_column: str = "key_canonical"
    ) -> Dict[str, Dict]:
        """
        Obtiene todas las reuniones de Zoom en caché como diccionario.
        
        Args:
            db: Sesión de base de datos
            key_column: Columna a usar como clave del diccionario
            
        Returns:
            Diccionario con reuniones indexadas por la columna especificada
        """
        query = select(db_models.ZoomMeetingCache)
        result = await db.execute(query)
        meetings = result.scalars().all()
        
        if key_column == "key_canonical":
            return {m.key_canonical: {"id": m.id, "topic": m.topic, "host_id": m.host_id, "key_canonical": m.key_canonical} for m in meetings}
        elif key_column == "id":
            return {m.id: {"id": m.id, "topic": m.topic, "host_id": m.host_id, "key_canonical": m.key_canonical} for m in meetings}
        else:
            raise ValueError(f"Columna no válida: {key_column}")

    @staticmethod
    async def bulk_upsert_users(
        db: AsyncSession, users_data: List[Dict[str, str]]
    ):
        """
        Inserta o actualiza usuarios de Zoom en lote.
        
        Args:
            db: Sesión de base de datos
            users_data: Lista de diccionarios con datos de usuarios
        """
        if not users_data:
            return

        for user_data in users_data:
            # Buscar si existe
            query = select(db_models.ZoomUserCache).where(
                db_models.ZoomUserCache.id == user_data["id"]
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if existing:
                # Actualizar
                existing.email = user_data.get("email", "")
                existing.display_name = user_data.get("display_name", "")
                existing.key_canonical = user_data.get("key_canonical", "")
            else:
                # Crear nuevo
                new_user = db_models.ZoomUserCache(
                    id=user_data["id"],
                    email=user_data.get("email", ""),
                    display_name=user_data.get("display_name", ""),
                    key_canonical=user_data.get("key_canonical", ""),
                )
                db.add(new_user)

        await db.commit()

    @staticmethod
    async def bulk_upsert_meetings(
        db: AsyncSession, meetings_data: List[Dict[str, str]]
    ):
        """
        Inserta o actualiza reuniones de Zoom en lote.
        
        Args:
            db: Sesión de base de datos
            meetings_data: Lista de diccionarios con datos de reuniones
        """
        if not meetings_data:
            return

        for meeting_data in meetings_data:
            # Buscar si existe
            query = select(db_models.ZoomMeetingCache).where(
                db_models.ZoomMeetingCache.id == meeting_data["id"]
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()

            if existing:
                # Actualizar
                existing.topic = meeting_data.get("topic", "")
                existing.host_id = meeting_data.get("host_id", "")
                existing.key_canonical = meeting_data.get("key_canonical", "")
            else:
                # Crear nuevo
                new_meeting = db_models.ZoomMeetingCache(
                    id=meeting_data["id"],
                    topic=meeting_data.get("topic", ""),
                    host_id=meeting_data.get("host_id", ""),
                    key_canonical=meeting_data.get("key_canonical", ""),
                )
                db.add(new_meeting)

        await db.commit()

    @staticmethod
    async def prune_stale_users(db: AsyncSession, fresh_ids: List[str]):
        """
        Elimina usuarios que ya no existen en Zoom.
        
        Args:
            db: Sesión de base de datos
            fresh_ids: Lista de IDs de usuarios que aún existen
        """
        if not fresh_ids:
            return

        stmt = delete(db_models.ZoomUserCache).where(
            ~db_models.ZoomUserCache.id.in_(fresh_ids)
        )
        await db.execute(stmt)
        await db.commit()

    @staticmethod
    async def prune_stale_meetings(db: AsyncSession, fresh_ids: List[str]):
        """
        Elimina reuniones que ya no existen en Zoom.
        
        Args:
            db: Sesión de base de datos
            fresh_ids: Lista de IDs de reuniones que aún existen
        """
        if not fresh_ids:
            return

        stmt = delete(db_models.ZoomMeetingCache).where(
            ~db_models.ZoomMeetingCache.id.in_(fresh_ids)
        )
        await db.execute(stmt)
        await db.commit()

    @staticmethod
    async def update_meeting_host(
        db: AsyncSession, meeting_id: str, new_host_id: str
    ):
        """
        Actualiza el host de una reunión en el caché.
        
        Args:
            db: Sesión de base de datos
            meeting_id: ID de la reunión
            new_host_id: ID del nuevo host
        """
        query = select(db_models.ZoomMeetingCache).where(
            db_models.ZoomMeetingCache.id == meeting_id
        )
        result = await db.execute(query)
        meeting = result.scalar_one_or_none()

        if meeting:
            meeting.host_id = new_host_id
            await db.commit()
            await db.refresh(meeting)

    @staticmethod
    async def log_assignment(
        db: AsyncSession,
        meeting_id: str,
        meeting_topic: str,
        previous_host_id: str,
        new_host_id: str,
        status: str,
        user_id: Optional[str] = None,
    ):
        """
        Registra una asignación en el historial.
        
        Args:
            db: Sesión de base de datos
            meeting_id: ID de la reunión
            meeting_topic: Título de la reunión
            previous_host_id: ID del host anterior
            new_host_id: ID del nuevo host
            status: Estado de la operación
            user_id: ID del usuario que realizó la asignación
        """
        history_entry = db_models.ZoomAssignmentHistory(
            timestamp=datetime.now(),
            meeting_id=meeting_id,
            meeting_topic=meeting_topic,
            previous_host_id=previous_host_id,
            new_host_id=new_host_id,
            status=status,
            user_id=user_id,
        )
        db.add(history_entry)
        await db.commit()

    @staticmethod
    async def get_assignment_history(
        db: AsyncSession, limit: int = 100
    ) -> List[db_models.ZoomAssignmentHistory]:
        """
        Obtiene el historial de asignaciones.
        
        Args:
            db: Sesión de base de datos
            limit: Número máximo de registros a retornar
            
        Returns:
            Lista de registros de historial ordenados por fecha descendente
        """
        query = (
            select(db_models.ZoomAssignmentHistory)
            .order_by(db_models.ZoomAssignmentHistory.timestamp.desc())
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_config_value(db: AsyncSession, key: str) -> Optional[str]:
        """
        Obtiene un valor de configuración.
        
        Args:
            db: Sesión de base de datos
            key: Clave de configuración
            
        Returns:
            Valor de la configuración o None si no existe
        """
        query = select(db_models.ZoomSyncConfig).where(
            db_models.ZoomSyncConfig.key == key
        )
        result = await db.execute(query)
        config = result.scalar_one_or_none()
        return config.value if config else None

    @staticmethod
    async def set_config_value(db: AsyncSession, key: str, value: str):
        """
        Establece un valor de configuración.
        
        Args:
            db: Sesión de base de datos
            key: Clave de configuración
            value: Valor a establecer
        """
        query = select(db_models.ZoomSyncConfig).where(
            db_models.ZoomSyncConfig.key == key
        )
        result = await db.execute(query)
        config = result.scalar_one_or_none()

        if config:
            config.value = value
        else:
            new_config = db_models.ZoomSyncConfig(key=key, value=value)
            db.add(new_config)

        await db.commit()

