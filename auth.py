# auth.py
# Este módulo simula un sistema de autenticación de usuarios.
# En una aplicación real, esto interactuaría con tu base de datos de usuarios.

from fastapi import Request, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession  # NUEVO
from sqlalchemy.future import select  # NUEVO


# --- NUEVO: Importaciones de DB y Seguridad ---
from database import get_db
import db_models  # Importamos nuestros modelos SQL
import security  # Importamos las funciones de hashing


# --- Modelo de Usuario Simulado ---
class User(BaseModel):
    id: str
    username: str
    full_name: str
    zoom_user_id: Optional[str] = None

    class Config:
        from_attributes = True  # Cambiar orm_mode por from_attributes


# --- Base de Datos de Usuarios Falsa ---
# Simulamos una base de datos de usuarios creados por un admin
# FAKE_USER_DB: Dict[str, User] = {
#     "6c94d1ce": User(id="6c94d1ce", username="support", full_name="Support"),
#     "75989a0a": User(id="75989a0a", username="user", full_name="User"),
# }


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[db_models.User]:  # Devuelve el modelo de la BD
    """
    Busca un usuario por username y verifica su contraseña.
    """
    # 1. Buscar al usuario por username
    query = select(db_models.User).where(db_models.User.username == username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        return None  # Usuario no encontrado

    # 2. Verificar la contraseña
    if not security.verify_password(password, user.hashed_password):
        return None  # Contraseña incorrecta

    return user


async def get_user_from_db(
    db: AsyncSession, user_id: str
) -> Optional[db_models.User]:  # Devuelve el modelo de la BD
    """Obtiene un usuario por su ID desde la BD."""
    # .get() es la forma más rápida de buscar por clave primaria
    user = await db.get(db_models.User, user_id)
    return user


async def save_zoom_tokens_for_user(
    db: AsyncSession,
    user_id: str,
    zoom_user_id: str,
    access_token: str,
    refresh_token: str,
):
    """
    Guarda los tokens de Zoom para un usuario específico en la BD.
    """
    user = await db.get(db_models.User, user_id)
    if user:
        user.zoom_user_id = zoom_user_id
        user.zoom_access_token = access_token
        user.zoom_refresh_token = refresh_token

        db.add(user)  # Añade el objeto a la sesión
        await db.commit()  # Guarda los cambios
        await db.refresh(user)  # Refresca el objeto

        print(
            f"Tokens de Zoom guardados para el usuario {user.username} (ID: {user_id})"
        )
    else:
        print(f"ERROR: No se pudo encontrar al usuario {user_id} para guardar tokens")


# --- Dependencia de Seguridad (MODIFICADA) ---


# async def get_current_active_user(
#     request: Request, db: AsyncSession = Depends(get_db)
# ) -> User:  # Devuelve el modelo Pydantic
#     """
#     Dependencia que comprueba la sesión Y carga al usuario desde la BD.
#     """
#     if not request.state.is_authenticated or not request.state.user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="No autenticado. Esta acción requiere iniciar sesión.",
#         )

#     user_id = request.state.session.get("user_id")
#     if not user_id:
#         raise HTTPException(status_code=401, detail="Sesión corrupta.")

#     user_db = await get_user_from_db(db, user_id)

#     if not user_db:
#         # El usuario existía en la sesión pero fue borrado de la BD
#         request.state.session["user_id"] = None
#         request.state.session["is_authenticated"] = False
#         raise HTTPException(status_code=401, detail="Usuario no encontrado.")

#     # Convertimos el modelo de BD (db_models.User)
#     # al modelo Pydantic (auth.User)
#     return User.from_orm(user_db)


async def get_current_active_user(
    request: Request,
) -> User:  # <-- Pista de tipo corregida a auth.User
    """
    Dependencia que obtiene al usuario activo desde el estado
    (poblado por el middleware).
    """
    if not request.state.is_authenticated or not request.state.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Esta acción requiere iniciar sesión.",
        )

    return request.state.user