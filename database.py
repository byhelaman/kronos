# database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

import config

# 1. Configuración del motor
# Usamos el modo asíncrono con asyncpg
engine = create_async_engine(
    config.DATABASE_URL,
    echo=True,  # Activa el log de SQL (útil para debug)
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)

# 2. Creador de sesiones asíncronas
# autocommit=False y autoflush=False es el estándar para ORM
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# 3. Clase Base para los modelos
# Nuestros modelos de tabla heredarán de esta clase
class Base(DeclarativeBase):
    pass


# 4. Dependencia de FastAPI
# Esto inyectará una sesión de base de datos en nuestros endpoints
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI para obtener una sesión de BD."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
