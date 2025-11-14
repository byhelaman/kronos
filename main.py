"""
Punto de entrada principal de la aplicación FastAPI.

Este módulo configura e inicializa la aplicación FastAPI, incluyendo:
- Configuración de middleware (seguridad, compresión, rate limiting)
- Gestión del ciclo de vida de la base de datos
- Registro de routers para diferentes funcionalidades
- Configuración de archivos estáticos y plantillas
"""
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager

from database import engine, Base
from middleware.security_headers import SecurityHeadersMiddleware
from session_middleware import RedisSessionMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import security

# Importar routers por dominio funcional
from routers import auth, schedule, admin, zoom


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la aplicación y la conexión a la base de datos.
    
    Esta función se ejecuta al iniciar y detener la aplicación:
    - Al iniciar: Crea las tablas de la base de datos si no existen
    - Durante la ejecución: Mantiene el pool de conexiones activo
    - Al detener: Cierra todas las conexiones de forma segura
    
    Args:
        app: Instancia de la aplicación FastAPI
        
    Yields:
        Control al contexto de ejecución de la aplicación
    """
    print("Iniciando pool de conexión a la base de datos...")
    async with engine.begin() as conn:
        # Nota: En producción, usar Alembic para migraciones en lugar de create_all
        # await conn.run_sync(Base.metadata.drop_all)  # Solo para desarrollo/reset
        await conn.run_sync(Base.metadata.create_all)
        print("Tablas de base de datos verificadas/creadas correctamente.")

    # La aplicación se ejecuta aquí
    yield

    print("Cerrando pool de conexión a la base de datos...")
    await engine.dispose()


# ============================================================================
# CONFIGURACIÓN DE LA APLICACIÓN FASTAPI
# ============================================================================

app = FastAPI(lifespan=lifespan)

# Middleware de compresión GZip para respuestas grandes (>1KB)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Middleware de headers de seguridad HTTP (CSP, XSS, etc.)
app.add_middleware(SecurityHeadersMiddleware)

# Configuración de rate limiting para prevenir abuso
app.state.limiter = security.limiter
app.add_exception_handler(RateLimitExceeded, security.rate_limit_handler)

# Montar directorio de archivos estáticos (CSS, JS, imágenes)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración de templates Jinja2 (aunque se usa principalmente en middleware)
templates = Jinja2Templates(directory="templates")

# Middleware de gestión de sesiones con Redis
app.add_middleware(RedisSessionMiddleware, templates=templates)

# ============================================================================
# REGISTRO DE ROUTERS POR DOMINIO FUNCIONAL
# ============================================================================

app.include_router(auth.router)      # Autenticación y gestión de usuarios
app.include_router(schedule.router)  # Gestión de horarios y procesamiento de archivos
app.include_router(admin.router)     # Administración de usuarios (solo admins)
app.include_router(zoom.router)      # Integración OAuth con Zoom
