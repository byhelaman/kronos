"""
Servicio de autenticación y gestión de usuarios.

Este servicio encapsula la lógica de negocio relacionada con:
- Autenticación de usuarios
- Gestión del ciclo de vida de sesiones (login/logout)
- Migración de datos entre sesiones de invitado y usuario autenticado
- Persistencia de horarios de usuarios
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from repositories.user_repository import UserRepository
from repositories.schedule_repository import ScheduleRepository
from models.user_model import User
from services import schedule_service

logger = logging.getLogger(__name__)


class AuthService:
    """
    Servicio para lógica de autenticación y gestión de usuarios.

    Coordina las operaciones entre repositorios y maneja la lógica
    de negocio relacionada con autenticación y sesiones.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        schedule_repo: ScheduleRepository,
    ):
        """
        Inicializa el servicio con los repositorios necesarios.

        Args:
            user_repo: Repositorio para operaciones de usuarios
            schedule_repo: Repositorio para operaciones de horarios
        """
        self.user_repo = user_repo
        self.schedule_repo = schedule_repo

    async def authenticate_user(
        self, db: AsyncSession, username: str, password: str
    ) -> Optional[User]:
        """
        Autentica un usuario con nombre de usuario y contraseña.

        Verifica las credenciales y retorna el modelo User si son válidas.
        Retorna None si las credenciales son incorrectas o el usuario no existe.

        Args:
            db: Sesión de base de datos
            username: Nombre de usuario
            password: Contraseña en texto plano

        Returns:
            Modelo User si la autenticación es exitosa, None en caso contrario
        """
        user_db = await self.user_repo.authenticate_user(db, username, password)
        if user_db:
            return User.model_validate(user_db)
        return None

    async def handle_login(
        self, request: Request, db: AsyncSession, user: User
    ) -> None:
        """
        Maneja el proceso completo de login después de la autenticación.

        Esta función gestiona la migración de datos entre sesiones de invitado
        y usuario autenticado:

        - Si el invitado tenía datos: Los datos del invitado se guardan en la BD
          del usuario (conversión de invitado a usuario)
        - Si el invitado no tenía datos: Se cargan los datos guardados del usuario
          desde la BD, o se crea un horario vacío si no existe

        Args:
            request: Objeto Request de FastAPI con el estado de la sesión
            db: Sesión de base de datos
            user: Usuario ya autenticado (obtenido de authenticate_user)
        """
        # Capturar el estado del horario del invitado antes de modificar la sesión
        guest_schedule_data = request.state.session.get(
            "schedule_data", schedule_service.get_empty_schedule_data()
        )
        has_guest_data = bool(guest_schedule_data.get("all_rows"))

        # Determinar qué datos usar para la nueva sesión autenticada
        schedule_for_new_session = {}

        if has_guest_data:
            # CASO 1: El invitado tenía datos procesados
            # Guardar los datos del invitado en la BD del usuario
            # Esto permite que un usuario pueda trabajar como invitado y luego
            # convertir su trabajo en una cuenta permanente
            await self.schedule_repo.save(db, user.id, guest_schedule_data)
            schedule_for_new_session = guest_schedule_data
        else:
            # CASO 2: El invitado no tenía datos (sesión nueva o expirada)
            # Cargar los datos guardados del usuario desde la BD
            existing_schedule = await self.schedule_repo.get_by_user_id(db, user.id)
            if existing_schedule:
                schedule_for_new_session = existing_schedule
            else:
                # Usuario nuevo sin datos guardados
                schedule_for_new_session = schedule_service.get_empty_schedule_data()

        # Actualizar el estado de la sesión con los datos correctos
        request.state.session["schedule_data"] = schedule_for_new_session
        request.state.session["user_id"] = user.id
        request.state.session["is_authenticated"] = True
        request.state.user = user
        request.state.is_authenticated = True

    async def handle_logout(self, request: Request, db: AsyncSession):
        """
        Maneja el proceso de logout del usuario.

        Esta función:
        1. Guarda el estado final del horario en la base de datos
        2. Limpia todos los datos de autenticación de la sesión
        3. Marca la sesión para eliminación

        Args:
            request: Objeto Request de FastAPI con el estado de la sesión
            db: Sesión de base de datos
        """
        # Guardar el estado final del horario antes de cerrar sesión
        if request.state.is_authenticated and request.state.user:
            current_schedule_data = request.state.session.get("schedule_data")
            if current_schedule_data:
                try:
                    await self.schedule_repo.save(
                        db, request.state.user.id, current_schedule_data
                    )
                except Exception as e:
                    # Log del error pero no fallar el logout
                    logger.error(f"Error guardando schedule en BD durante logout: {e}")

        # Limpiar todos los datos de autenticación de la sesión
        request.state.session["user_id"] = None
        request.state.session["is_authenticated"] = False
        request.state.user = None
        request.state.is_authenticated = False
        request.state.session_cleared = True

    async def save_user_schedule(
        self, db: AsyncSession, user_id: str, schedule_data: dict
    ):
        """
        Guarda el horario de un usuario en la base de datos.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario
            schedule_data: Diccionario con los datos del horario
        """
        await self.schedule_repo.save(db, user_id, schedule_data)

    async def get_user_schedule(self, db: AsyncSession, user_id: str) -> Optional[dict]:
        """
        Obtiene el horario guardado de un usuario desde la base de datos.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario

        Returns:
            Diccionario con los datos del horario, o None si no existe
        """
        return await self.schedule_repo.get_by_user_id(db, user_id)
