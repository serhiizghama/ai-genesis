"""Tests for telemetry snapshot collection and storage."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.telemetry import (
    WorldSnapshot,
    collect_snapshot,
    save_snapshot_to_redis,
)


@pytest.fixture
def mock_engine() -> MagicMock:
    """Create a mock CoreEngine for testing."""
    engine = MagicMock()
    engine.tick_counter = 300

    # Mock entity_manager
    mock_entity_1 = MagicMock()
    mock_entity_1.energy = 80.0
    mock_entity_2 = MagicMock()
    mock_entity_2.energy = 60.0
    mock_entity_3 = MagicMock()
    mock_entity_3.energy = 70.0

    engine.entity_manager.alive.return_value = [
        mock_entity_1,
        mock_entity_2,
        mock_entity_3,
    ]

    # Mock environment
    engine.environment.count.return_value = 150

    # Mock death_stats
    engine.death_stats = {"starvation": 5, "old_age": 2}

    return engine


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock Redis client for testing."""
    redis = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    return redis


def test_world_snapshot_creation() -> None:
    """Test WorldSnapshot dataclass creation."""
    snapshot = WorldSnapshot(
        tick=100,
        entity_count=50,
        avg_energy=75.5,
        resource_count=120,
        death_stats={"starvation": 3},
        timestamp=1234567890.0,
    )

    assert snapshot.tick == 100
    assert snapshot.entity_count == 50
    assert snapshot.avg_energy == 75.5
    assert snapshot.resource_count == 120
    assert snapshot.death_stats == {"starvation": 3}
    assert snapshot.timestamp == 1234567890.0


def test_collect_snapshot(mock_engine: MagicMock) -> None:
    """Test snapshot collection from engine state."""
    snapshot = collect_snapshot(mock_engine)

    # Verify snapshot data
    assert snapshot.tick == 300
    assert snapshot.entity_count == 3
    assert snapshot.avg_energy == 70.0  # (80 + 60 + 70) / 3
    assert snapshot.resource_count == 150
    assert snapshot.death_stats == {"starvation": 5, "old_age": 2}
    assert isinstance(snapshot.timestamp, float)


def test_collect_snapshot_empty_world(mock_engine: MagicMock) -> None:
    """Test snapshot collection when world is empty."""
    # No entities
    mock_engine.entity_manager.alive.return_value = []
    mock_engine.environment.count.return_value = 0
    mock_engine.death_stats = {}

    snapshot = collect_snapshot(mock_engine)

    assert snapshot.tick == 300
    assert snapshot.entity_count == 0
    assert snapshot.avg_energy == 0.0
    assert snapshot.resource_count == 0
    assert snapshot.death_stats == {}


@pytest.mark.asyncio
async def test_save_snapshot_to_redis(mock_redis: AsyncMock) -> None:
    """Test saving snapshot to Redis."""
    snapshot = WorldSnapshot(
        tick=300,
        entity_count=50,
        avg_energy=75.5,
        resource_count=120,
        death_stats={"starvation": 3},
        timestamp=1234567890.0,
    )

    key = await save_snapshot_to_redis(mock_redis, snapshot, ttl_seconds=300)

    # Verify key format
    assert key == "ws:snapshot:300"

    # Verify Redis call
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args

    # Check key
    assert call_args[0][0] == "ws:snapshot:300"

    # Check TTL
    assert call_args[0][1] == 300

    # Check payload is valid JSON
    payload = call_args[0][2]
    data = json.loads(payload)
    assert data["tick"] == 300
    assert data["entity_count"] == 50
    assert data["avg_energy"] == 75.5
    assert data["resource_count"] == 120
    assert data["death_stats"] == {"starvation": 3}


@pytest.mark.asyncio
async def test_save_snapshot_default_ttl(mock_redis: AsyncMock) -> None:
    """Test saving snapshot with default TTL."""
    snapshot = WorldSnapshot(
        tick=600,
        entity_count=25,
        avg_energy=50.0,
        resource_count=80,
        death_stats={},
        timestamp=1234567890.0,
    )

    await save_snapshot_to_redis(mock_redis, snapshot)

    # Verify default TTL is 300 seconds (5 minutes)
    call_args = mock_redis.setex.call_args
    assert call_args[0][1] == 300
