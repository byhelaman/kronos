"""
Módulo compartido para la configuración de templates Jinja2.

Este módulo configura el entorno de templates y proporciona funciones helper
para renderizar templates con el contexto de autenticación incluido automáticamente.
"""

from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import HTMLResponse
from typing import Dict, Any

templates = Jinja2Templates(directory="templates")


def render_template(
    request: Request, template_name: str, context: Dict[str, Any] = None
) -> HTMLResponse:
    """
    Renderiza un template con el contexto de autenticación incluido automáticamente.

    Esta función asegura que las variables `current_user` e `is_authenticated`
    estén siempre disponibles en todos los templates, reflejando el estado actual
    de la sesión del usuario.

    Args:
        request: Objeto Request de FastAPI
        template_name: Nombre del template a renderizar (ej: "index.html")
        context: Diccionario con variables adicionales para el template

    Returns:
        HTMLResponse: Respuesta HTML con el template renderizado
    """
    if context is None:
        context = {}

    # Siempre incluir variables de autenticación desde request.state
    # Esto asegura que estén actualizadas en cada renderizado
    context["current_user"] = getattr(request.state, "user", None)
    context["is_authenticated"] = getattr(request.state, "is_authenticated", False)

    # Asegurar que request esté en el contexto
    context["request"] = request

    return templates.TemplateResponse(template_name, context)
