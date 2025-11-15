"""
Modelos de base de datos SQLAlchemy.

Define las tablas y relaciones de la base de datos usando el ORM de SQLAlchemy.
Todos los modelos heredan de Base (declarative base) para mapeo automático.
"""

from sqlalchemy import String, ForeignKey, JSON, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any
from datetime import datetime
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


class ZoomUserCache(Base):
    """
    Modelo para almacenar usuarios de Zoom en caché local.
    
    Esta tabla almacena una copia local de los usuarios de Zoom para
    facilitar las búsquedas y asignaciones sin necesidad de consultar
    la API de Zoom en cada operación.
    
    Attributes:
        id: ID único del usuario en Zoom (clave primaria)
        email: Email del usuario en Zoom
        display_name: Nombre completo del usuario
        key_canonical: Clave canónica normalizada para búsquedas rápidas
    """
    
    __tablename__ = "zoom_users_cache"
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_canonical: Mapped[str] = mapped_column(String(255), index=True)


class ZoomMeetingCache(Base):
    """
    Modelo para almacenar reuniones de Zoom en caché local.
    
    Esta tabla almacena una copia local de las reuniones de Zoom para
    facilitar las búsquedas y asignaciones sin necesidad de consultar
    la API de Zoom en cada operación.
    
    Attributes:
        id: ID único de la reunión en Zoom (clave primaria)
        topic: Título/tema de la reunión
        host_id: ID del usuario host actual de la reunión
        key_canonical: Clave canónica normalizada para búsquedas rápidas
    """
    
    __tablename__ = "zoom_meetings_cache"
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    host_id: Mapped[str] = mapped_column(String(100), index=True)
    key_canonical: Mapped[str] = mapped_column(String(500), index=True)


class ZoomAssignmentHistory(Base):
    """
    Modelo para almacenar el historial de asignaciones de reuniones de Zoom.
    
    Registra todas las operaciones de reasignación de hosts de reuniones,
    incluyendo el estado (éxito o error) para auditoría y debugging.
    
    Attributes:
        id: ID autoincremental del registro
        timestamp: Fecha y hora de la asignación
        meeting_id: ID de la reunión reasignada
        meeting_topic: Título de la reunión
        previous_host_id: ID del host anterior
        new_host_id: ID del nuevo host
        status: Estado de la operación (SUCCESS o mensaje de error)
        user_id: ID del usuario de kronos que realizó la asignación
    """
    
    __tablename__ = "zoom_assignment_history"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    meeting_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    meeting_topic: Mapped[str] = mapped_column(String(500), nullable=False)
    previous_host_id: Mapped[str] = mapped_column(String(100), nullable=False)
    new_host_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )


class ZoomSyncConfig(Base):
    """
    Modelo para almacenar configuración de sincronización con Zoom.
    
    Almacena metadatos sobre la última sincronización realizada,
    permitiendo optimizar las sincronizaciones futuras.
    
    Attributes:
        key: Clave única de configuración (clave primaria)
        value: Valor de la configuración (JSON o texto)
    """
    
    __tablename__ = "zoom_sync_config"
    
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000), nullable=False)
