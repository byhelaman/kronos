# auth.py
"""
Este archivo se mantiene por compatibilidad.
El modelo User se ha movido a models/user_model.py
Las funciones de autenticación se han movido a repositories/ y services/
Las dependencias de autenticación están en security.py
"""

# Re-exportar User para compatibilidad con imports existentes
from models.user_model import User

__all__ = ["User"]
