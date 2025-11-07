from sqlalchemy import String, Column
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from database import Base

class User(Base):
    __tablename__ = "users"

    # Asegúrate de que estos campos coincidan con el modelo Pydantic
    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    zoom_user_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    zoom_access_token: Mapped[Optional[str]] = mapped_column(String(1024))
    zoom_refresh_token: Mapped[Optional[str]] = mapped_column(String(1024))