# repositories/user_repository.py
"""
Repositorio para operaciones de base de datos relacionadas con usuarios.
"""
import uuid
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status

import db_models
import security


class UserRepository:
    """Repositorio para gestionar usuarios en la base de datos."""

    @staticmethod
    async def authenticate_user(
        db: AsyncSession, username: str, password: str
    ) -> Optional[db_models.User]:
        """Autentica un usuario por nombre de usuario y contraseña."""
        try:
            query = select(db_models.User).where(
                db_models.User.username == username, db_models.User.is_active == True
            )
            result = await db.execute(query)
            user = result.scalar_one_or_none()

            if not user:
                return None

            if not security.verify_password(password, user.hashed_password):
                return None

            return user

        except Exception as e:
            print(f"Error de autenticación: {e}")
            await db.rollback()
            raise

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> Optional[db_models.User]:
        """Obtiene un usuario por su ID."""
        return await db.get(db_models.User, user_id)

    @staticmethod
    async def get_all(db: AsyncSession) -> List[db_models.User]:
        """Obtiene todos los usuarios ordenados por nombre de usuario."""
        query = select(db_models.User).order_by(db_models.User.username)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def create(
        db: AsyncSession,
        username: str,
        password: str,
        full_name: str,
        role: str = "user",
    ) -> db_models.User:
        """Crea un nuevo usuario."""
        # Verificar si el usuario ya existe
        query = select(db_models.User).where(db_models.User.username == username)
        result = await db.execute(query)
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nombre de usuario ya existe.",
            )

        hashed_password = security.get_password_hash(password)
        new_user = db_models.User(
            id=str(uuid.uuid4()),
            username=username,
            full_name=full_name,
            hashed_password=hashed_password,
            role=role,
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def delete(
        db: AsyncSession, user_id: str, current_user_id: str
    ) -> bool:
        """Elimina un usuario. No permite auto-eliminación."""
        if user_id == current_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No puedes eliminar tu propio usuario.",
            )

        user = await db.get(db_models.User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado.",
            )

        await db.delete(user)
        await db.commit()
        return True

    @staticmethod
    async def update_zoom_tokens(
        db: AsyncSession,
        user_id: str,
        zoom_user_id: str,
        access_token: str,
        refresh_token: str,
    ):
        """Actualiza los tokens de Zoom para un usuario."""
        user = await db.get(db_models.User, user_id)
        if user:
            user.zoom_user_id = zoom_user_id
            user.zoom_access_token = security.encrypt_token(access_token)
            user.zoom_refresh_token = security.encrypt_token(refresh_token)

            db.add(user)
            await db.commit()
            await db.refresh(user)

    @staticmethod
    async def remove_zoom_tokens(db: AsyncSession, user_id: str):
        """Elimina los tokens de Zoom de un usuario."""
        user = await db.get(db_models.User, user_id)

        if user:
            user.zoom_user_id = None
            user.zoom_access_token = None
            user.zoom_refresh_token = None

            db.add(user)
            await db.commit()
            await db.refresh(user)

    @staticmethod
    async def get_zoom_tokens(
        db: AsyncSession, user_id: str
    ) -> Optional[dict]:
        """Obtiene y descifra los tokens de Zoom de un usuario."""
        user = await db.get(db_models.User, user_id)

        if not user or not user.zoom_access_token or not user.zoom_refresh_token:
            return None

        try:
            access_token = security.decrypt_token(user.zoom_access_token)
            refresh_token = security.decrypt_token(user.zoom_refresh_token)

            return {"access_token": access_token, "refresh_token": refresh_token}

        except security.InvalidToken:
            print(f"Error: No se pudieron descifrar los tokens para el user_id {user_id}.")
            return None

