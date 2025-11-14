"""
Modelos de base de datos SQLAlchemy.

Define las tablas y relaciones de la base de datos usando el ORM de SQLAlchemy.
Todos los modelos heredan de Base (declarative base) para mapeo automático.
"""

from sqlalchemy import String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any
from database import Base


class User(Base):
    """
    Modelo de usuario del sistema.

    Representa un usuario autenticado con sus credenciales, rol y
    tokens de integración con Zoom (si está vinculado).

    Attributes:
        id: UUID único del usuario (clave primaria)
        username: Nombre de usuario único para login
        full_name: Nombre completo del usuario
        hashed_password: Hash bcrypt de la contraseña
        role: Rol del usuario ('user' o 'admin')
        is_active: Indica si la cuenta está activa
        zoom_user_id: ID del usuario en Zoom (si está vinculado)
        zoom_access_token: Token de acceso de Zoom cifrado
        zoom_refresh_token: Token de refresco de Zoom cifrado
    """

    __tablename__ = "users"

    # UUID v4 como string (36 caracteres incluyendo guiones)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)

    # Nombre de usuario único e indexado para búsquedas rápidas
    username: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )

    # Nombre completo (opcional)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)

    # Hash bcrypt de la contraseña (nunca almacenar contraseñas en texto plano)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)

    # Rol del usuario: 'user' (usuario normal) o 'admin' (administrador)
    role: Mapped[str] = mapped_column(String(20), default="user")

    # Estado de la cuenta (permite desactivar sin eliminar)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Integración con Zoom OAuth
    zoom_user_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    zoom_access_token: Mapped[Optional[str]] = mapped_column(String(1024))
    zoom_refresh_token: Mapped[Optional[str]] = mapped_column(String(1024))


class UserSchedule(Base):
    """
    Modelo para almacenar el estado completo del horario de un usuario.

    Almacena toda la información del horario procesado por un usuario,
    incluyendo archivos procesados y todas las filas (activas y eliminadas).
    Esto permite persistir el estado entre sesiones.

    Attributes:
        user_id: ID del usuario (clave primaria y foránea a users.id)
        schedule_data: Diccionario JSON con la estructura:
            {
                "processed_files": [lista de nombres de archivos],
                "all_rows": [lista de filas con estructura {id, status, data}]
            }
    """

    __tablename__ = "user_schedules"

    # Clave primaria que también es clave foránea a users.id
    # Relación 1:1 (un usuario tiene un schedule)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )

    # Datos del horario en formato JSON
    # Estructura: {"processed_files": [...], "all_rows": [...]}
    schedule_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
