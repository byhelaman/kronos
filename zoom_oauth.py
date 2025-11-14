# zoom_oauth.py
# Lógica para manejar el flujo de OAuth 2.0 de Zoom

import httpx
import base64
from fastapi import Request, HTTPException, status
from urllib.parse import urlencode
import os
import hashlib

from core import config

# --- Configuración de URLs de Zoom ---
AUTHORIZATION_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"
USER_INFO_URL = "https://api.zoom.us/v2/users/me"

# --- Cliente HTTP compartido con connection pooling ---
# Reutilizar el cliente HTTP mejora significativamente el rendimiento
# al evitar crear nuevas conexiones TCP para cada request
from typing import Optional

_http_client: Optional[httpx.AsyncClient] = None


async def get_http_client() -> httpx.AsyncClient:
    """
    Obtiene o crea un cliente HTTP compartido con connection pooling.
    Este cliente se reutiliza para todas las requests a la API de Zoom,
    mejorando el rendimiento al mantener conexiones persistentes.
    """
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            http2=True,  # HTTP/2 para mejor rendimiento
        )
    return _http_client


async def close_http_client():
    """Cierra el cliente HTTP compartido. Útil para cleanup al cerrar la app."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def get_zoom_auth_url() -> tuple[str, str]:
    """
    Construye la URL de autorización Y genera las claves PKCE.
    Devuelve: (auth_url, code_verifier)
    Nota: El parámetro 'state' debe agregarse en el router que llama esta función.
    """

    # --- Lógica PKCE (del script CLI) ---
    code_verifier = (
        base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("utf-8")
    )
    challenge_hash = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(challenge_hash).rstrip(b"=").decode("utf-8")
    )
    # --- Fin Lógica PKCE ---

    params = {
        "response_type": "code",
        "client_id": config.ZOOM_CLIENT_ID,
        "redirect_uri": config.ZOOM_REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{AUTHORIZATION_URL}?{urlencode(params)}"

    # Devolvemos ambos valores (el state se agrega en el router)
    return auth_url, code_verifier


async def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """
    Intercambia el 'code' de autorización por un access_token y refresh_token.
    """
    if not config.ZOOM_CLIENT_ID or not config.ZOOM_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Variables de entorno de Zoom no configuradas en el servidor.",
        )

    # Zoom requiere autenticación Básica (Client ID y Client Secret)
    auth_header = f"{config.ZOOM_CLIENT_ID}:{config.ZOOM_CLIENT_SECRET}"
    auth_header_encoded = base64.b64encode(auth_header.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header_encoded}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.ZOOM_REDIRECT_URI,
        # --- Clave PKCE requerida ---
        "code_verifier": code_verifier,
    }

    client = await get_http_client()
    try:
        response = await client.post(TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()  # Lanza error si la respuesta es 4xx o 5xx
        return response.json()

    except httpx.HTTPStatusError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al intercambiar código de Zoom: {e.response.text}")
        # No exponer detalles internos al usuario
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al conectar con Zoom. Por favor, intente más tarde.",
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error inesperado de red: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de red conectando con Zoom. Por favor, intente más tarde.",
        )


async def get_zoom_user_info(access_token: str) -> dict:
    """
    Obtiene la información del usuario de Zoom (como su zoom_user_id)
    usando el access_token.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    client = await get_http_client()
    try:
        response = await client.get(USER_INFO_URL, headers=headers)
        response.raise_for_status()
        user_info = response.json()
        # Devolvemos solo 'id' y 'email' para este ejemplo
        return {"id": user_info.get("id"), "email": user_info.get("email")}

    except httpx.HTTPStatusError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al obtener info de usuario de Zoom: {e.response.text}")
        # No exponer detalles internos al usuario
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener información de Zoom. Por favor, intente más tarde.",
        )
