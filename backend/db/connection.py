"""PostgreSQL connection pool management.

Provides init_db() for startup and get_pool() for global access.
Schema is applied from schema.sql at initialization.
"""

from __future__ import annotations

import json

import asyncpg
import structlog
from pathlib import Path

logger = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def _set_json_codec(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so asyncpg accepts Python dicts directly."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


async def init_db(url: str) -> asyncpg.Pool:
    """Create connection pool and apply schema.

    Args:
        url: PostgreSQL DSN, e.g. postgresql://user:pass@host:5432/db

    Returns:
        Initialized asyncpg connection pool (also stored globally).
    """
    global _pool

    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text()

    _pool = await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=10,
        init=_set_json_codec,
    )

    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)

    logger.info("postgres_initialized", url=url)
    return _pool


def get_pool() -> asyncpg.Pool:
    """Return the global connection pool.

    Raises:
        RuntimeError: If init_db() was not called first.
    """
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db() first")
    return _pool
