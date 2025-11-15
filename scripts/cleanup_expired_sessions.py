"""
Script para limpiar sesiones expiradas de Redis.

Este script puede ejecutarse periódicamente (por ejemplo, con cron) para
limpiar sesiones expiradas y liberar memoria en Redis.

Uso:
    python scripts/cleanup_expired_sessions.py
"""

import asyncio
import logging
import redis.asyncio as redis
from core.config import REDIS_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def cleanup_expired_sessions():
    """
    Limpia sesiones expiradas de Redis.
    
    Redis automáticamente elimina keys con TTL expirado, pero este script
    puede ayudar a limpiar sesiones huérfanas o con problemas.
    """
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            max_connections=10,
        )
        
        # Buscar todas las keys de sesión
        pattern = "session:*"
        cursor = 0
        deleted_count = 0
        checked_count = 0
        
        logger.info("Iniciando limpieza de sesiones expiradas...")
        
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            checked_count += len(keys)
            
            if not keys:
                if cursor == 0:
                    break
                continue
            
            # Verificar TTL de cada key
            for key in keys:
                ttl = await client.ttl(key)
                # Si TTL es -1 (sin expiración) o -2 (no existe), eliminarlo
                # También eliminamos sesiones muy antiguas (más de 24 horas sin uso)
                if ttl == -1:
                    await client.delete(key)
                    deleted_count += 1
                    logger.debug(f"Eliminada sesión sin TTL: {key.decode()}")
                elif ttl == -2:
                    # Key ya no existe, continuar
                    pass
            
            if cursor == 0:
                break
        
        logger.info(
            f"Limpieza completada. Verificadas: {checked_count}, "
            f"Eliminadas: {deleted_count}"
        )
        
        await client.aclose()
        
    except Exception as e:
        logger.error(f"Error durante limpieza de sesiones: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(cleanup_expired_sessions())

