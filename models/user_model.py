# models/user_model.py
"""
Modelo de usuario Pydantic para la aplicación.
"""
from pydantic import BaseModel
from typing import Optional


class User(BaseModel):
    """Modelo de usuario para la aplicación."""
    id: str
    username: str
    full_name: str
    role: str
    is_active: bool
    zoom_user_id: Optional[str] = None

    class Config:
        from_attributes = True

