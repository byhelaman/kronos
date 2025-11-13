# db_models.py
from sqlalchemy import String, Column, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional, Dict, Any
from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user")  # 'user' o 'admin'
    is_active: Mapped[bool] = mapped_column(default=True)
    zoom_user_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    zoom_access_token: Mapped[Optional[str]] = mapped_column(String(1024))
    zoom_refresh_token: Mapped[Optional[str]] = mapped_column(String(1024))


# --- NUEVO MODELO ---
class UserSchedule(Base):
    """
    Almacena el estado completo del schedule_data de un usuario
    (processed_files y all_rows) en un único campo JSON.
    """

    __tablename__ = "user_schedules"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )
    # Almacena la estructura completa {"processed_files": [], "all_rows": []}
    schedule_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
