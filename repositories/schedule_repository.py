# repositories/schedule_repository.py
"""
Repositorio para operaciones de base de datos relacionadas con horarios.
"""
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

import db_models


class ScheduleRepository:
    """Repositorio para gestionar horarios de usuarios en la base de datos."""

    @staticmethod
    async def get_by_user_id(
        db: AsyncSession, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Recupera el schedule_data de un usuario desde la BD."""
        schedule_obj = await db.get(db_models.UserSchedule, user_id)
        if schedule_obj:
            return schedule_obj.schedule_data
        return None

    @staticmethod
    async def save(
        db: AsyncSession, user_id: str, schedule_data: Dict[str, Any]
    ):
        """
        Guarda (actualiza o crea) el schedule_data para un usuario en la BD.
        Esta función hace un "upsert" de forma atómica usando merge.
        """
        schedule_to_merge = db_models.UserSchedule(
            user_id=user_id, schedule_data=schedule_data
        )

        await db.merge(schedule_to_merge)

        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            print(f"Error en save_schedule_to_db (merge): {e}")
            raise e

