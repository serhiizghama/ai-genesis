"""Event bus infrastructure — Redis Pub/Sub, connection management."""

from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

from backend.config import Settings
from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus import events

# Singleton Redis connection instance
_redis_client: Optional[Redis] = None


async def get_redis(settings: Optional[Settings] = None) -> Redis:
    """Get or create async Redis connection (singleton pattern).

    Args:
        settings: Optional Settings instance. If None, creates new Settings.

    Returns:
        Redis: Async Redis client instance.

    Note:
        This is a singleton factory. Multiple calls return the same connection.
        Connection is lazy-initialized on first call.
    """
    global _redis_client

    if _redis_client is None:
        if settings is None:
            settings = Settings()
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection if it exists.

    Should be called during application shutdown.
    """
    global _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


__all__ = [
    "get_redis",
    "close_redis",
    "EventBus",
    "Channels",
    "events",
]
