# middleware/security_headers.py
"""
Middleware para agregar headers de seguridad HTTP.
"""
import secrets
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware que agrega headers de seguridad esenciales a todas las respuestas."""

    async def dispatch(self, request, call_next):
        # Generar nonce único por request para CSP (Content Security Policy)
        # El nonce permite ejecutar scripts inline específicos de forma segura
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # Headers de seguridad esenciales
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Headers de seguridad adicionales (recomendados por OWASP)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
        )
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Content Security Policy mejorada con nonces
        # Nota: 'unsafe-inline' se mantiene solo para estilos legacy, pero scripts
        # deben usar nonces exclusivamente para máxima seguridad
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'nonce-{nonce}' 'unsafe-inline' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; "
            f"connect-src 'self'; "
            f"form-action 'self'; "
            f"base-uri 'self'; "
            f"frame-ancestors 'none';"
        )

        # OPTIMIZACIÓN: Agregar headers de cache para archivos estáticos
        # Esto mejora significativamente los tiempos de carga en visitas subsecuentes
        path = request.url.path
        if path.startswith("/static/"):
            # Determinar el tipo de archivo basado en la extensión
            static_extensions = [
                ".css",
                ".js",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".woff",
                ".woff2",
                ".ttf",
                ".eot",
                ".ico",
            ]
            if any(path.endswith(ext) for ext in static_extensions):
                # Archivos estáticos: cache por 1 hora, revalidar después
                response.headers["Cache-Control"] = (
                    "public, max-age=3600, must-revalidate"
                )
                response.headers["Vary"] = "Accept-Encoding"
            else:
                # Otros archivos: cache corto (5 minutos)
                response.headers["Cache-Control"] = "public, max-age=300"

        return response
