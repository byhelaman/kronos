"""
Configuración de la base de datos y sesiones SQLAlchemy.

Este módulo configura:
- Motor de base de datos asíncrono (asyncpg para PostgreSQL)
- Pool de conexiones con configuración optimizada
- Factory de sesiones asíncronas
- Clase base para modelos ORM
- Dependencia de FastAPI para inyección de sesiones
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from core import config

# ============================================================================
# CONFIGURACIÓN DEL MOTOR DE BASE DE DATOS
# ============================================================================

# Motor asíncrono usando asyncpg como driver para PostgreSQL
# La configuración del pool está optimizada para aplicaciones web con alta concurrencia
engine = create_async_engine(
    config.DATABASE_URL,
    echo=True,              # Log SQL queries (desactivar en producción)
    pool_pre_ping=True,     # Verificar conexiones antes de usarlas
    pool_recycle=300,       # Reciclar conexiones después de 5 minutos
    pool_size=5,            # Tamaño base del pool de conexiones
    max_overflow=10,        # Conexiones adicionales permitidas (total: 15)
    pool_timeout=30,        # Timeout para obtener conexión del pool (segundos)
)

# ============================================================================
# FACTORY DE SESIONES ASÍNCRONAS
# ============================================================================

# Creador de sesiones SQLAlchemy con configuración estándar para ORM
# - expire_on_commit=False: Mantiene objetos accesibles después del commit
# - autocommit=False: Requiere commits explícitos (estándar para ORM)
# - autoflush=False: Requiere flushes explícitos (mejor control)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ============================================================================
# CLASE BASE PARA MODELOS ORM
# ============================================================================

class Base(DeclarativeBase):
    """
    Clase base para todos los modelos de base de datos.
    
    Todos los modelos SQLAlchemy deben heredar de esta clase para
    obtener funcionalidades de mapeo ORM y declaración de tablas.
    """
    pass


# ============================================================================
# DEPENDENCIA DE FASTAPI PARA SESIONES DE BASE DE DATOS
# ============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependencia de FastAPI que proporciona una sesión de base de datos.
    
    Esta función:
    - Crea una nueva sesión para cada request
    - Hace rollback automático en caso de excepción
    - Cierra la sesión al finalizar el request
    
    Uso:
        @app.get("/endpoint")
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            # Usar db aquí
            pass
    
    Yields:
        AsyncSession: Sesión de base de datos lista para usar
        
    Note:
        La sesión se cierra automáticamente al finalizar el request,
        incluso si ocurre una excepción.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # Rollback automático en caso de error
            await session.rollback()
            raise
        finally:
            # Cerrar sesión siempre, incluso si hubo excepción
            await session.close()
