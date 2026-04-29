import asyncio
import logging

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from intelligent_search_agent.core.config import get_settings

logger = logging.getLogger(__name__)

_pool: pool.ThreadedConnectionPool | None = None
_pool_lock = asyncio.Lock()


def _create_pool(settings) -> pool.ThreadedConnectionPool:
    kwargs: dict[str, object] = {
        "minconn": 2,
        "maxconn": 10,
        "host": settings.db_host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "cursor_factory": RealDictCursor,
        "options": "-c hnsw.ef_search=200",
    }
    if settings.db_sslmode:
        kwargs["sslmode"] = settings.db_sslmode
    return pool.ThreadedConnectionPool(**kwargs)


async def get_pool(settings=None) -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = _create_pool(settings or get_settings())
                logger.info("Database connection pool created")
    return _pool


def get_pool_sync(settings=None) -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = _create_pool(settings or get_settings())
        logger.info("Database connection pool created")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")
