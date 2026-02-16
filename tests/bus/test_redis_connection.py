"""Tests for Redis connection helper."""

from __future__ import annotations

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from backend.bus import close_redis, get_redis
from backend.config import Settings


@pytest.mark.asyncio
async def test_get_redis_returns_redis_instance() -> None:
    """Test that get_redis returns a Redis instance."""
    settings = Settings(redis_url="redis://localhost:6379/15")  # Use test DB 15
    redis = await get_redis(settings)

    assert isinstance(redis, Redis)

    await close_redis()


@pytest.mark.asyncio
async def test_get_redis_singleton_pattern() -> None:
    """Test that get_redis returns the same instance on multiple calls."""
    settings = Settings(redis_url="redis://localhost:6379/15")

    redis1 = await get_redis(settings)
    redis2 = await get_redis(settings)

    assert redis1 is redis2, "Should return the same instance (singleton)"

    await close_redis()


@pytest.mark.asyncio
async def test_redis_set_get_operations(redis_client: Redis) -> None:
    """Test that Redis SET and GET operations work correctly.

    Args:
        redis_client: Pytest fixture providing Redis connection.
    """
    # Test basic SET/GET
    await redis_client.set("test:key", "test_value")
    value = await redis_client.get("test:key")

    assert value == "test_value"

    # Cleanup
    await redis_client.delete("test:key")


@pytest.mark.asyncio
async def test_redis_ping(redis_client: Redis) -> None:
    """Test that Redis connection is alive with PING.

    Args:
        redis_client: Pytest fixture providing Redis connection.
    """
    response = await redis_client.ping()
    assert response is True


@pytest.mark.asyncio
async def test_close_redis() -> None:
    """Test that close_redis properly closes the connection."""
    settings = Settings(redis_url="redis://localhost:6379/15")

    # Create connection
    redis = await get_redis(settings)
    assert redis is not None

    # Close connection
    await close_redis()

    # Next call should create a new connection
    redis_new = await get_redis(settings)
    assert redis_new is not None

    await close_redis()


# Pytest fixture for Redis client
@pytest_asyncio.fixture
async def redis_client() -> Redis:
    """Provide a Redis client for testing with cleanup.

    Uses test database 15 to avoid conflicts with development data.
    """
    settings = Settings(redis_url="redis://localhost:6379/15")
    redis = await get_redis(settings)

    yield redis

    # Cleanup: flush test database and close connection
    await redis.flushdb()
    await close_redis()
