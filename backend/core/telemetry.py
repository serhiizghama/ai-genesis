"""Telemetry system for collecting and storing world state snapshots.

This module provides snapshot collection logic that captures the current
state of the simulation for monitoring, analysis, and AI decision-making.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

if TYPE_CHECKING:
    from backend.core.engine import CoreEngine

logger = structlog.get_logger()


@dataclass
class WorldSnapshot:
    """Immutable snapshot of world state at a specific tick.

    Attributes:
        tick: Simulation tick number when snapshot was taken
        entity_count: Number of living entities
        avg_energy: Average energy across all living entities
        resource_count: Number of resources available in the environment
        death_stats: Dictionary of death causes and their counts since last snapshot
        timestamp: Unix timestamp when snapshot was collected
    """

    tick: int
    entity_count: int
    avg_energy: float
    resource_count: int
    death_stats: dict[str, int]
    timestamp: float


def collect_snapshot(engine: CoreEngine) -> WorldSnapshot:
    """Collect a snapshot of the current world state.

    Args:
        engine: The CoreEngine instance to collect data from

    Returns:
        WorldSnapshot with current simulation metrics

    Note:
        This function reads data from entity_manager and environment but
        does NOT reset death_stats. The caller is responsible for resetting
        stats after the snapshot is saved.
    """
    # Get all living entities
    entities = engine.entity_manager.alive()
    entity_count = len(entities)

    # Calculate average energy
    avg_energy = 0.0
    if entity_count > 0:
        total_energy = sum(e.energy for e in entities)
        avg_energy = total_energy / entity_count

    # Get resource count
    resource_count = engine.environment.count()

    # Copy death stats (don't modify the original yet)
    death_stats = dict(engine.death_stats)

    # Create snapshot
    snapshot = WorldSnapshot(
        tick=engine.tick_counter,
        entity_count=entity_count,
        avg_energy=round(avg_energy, 2),
        resource_count=resource_count,
        death_stats=death_stats,
        timestamp=time.time(),
    )

    return snapshot


async def save_snapshot_to_redis(
    redis: Redis,
    snapshot: WorldSnapshot,
    ttl_seconds: int = 300,
) -> str:
    """Save a snapshot to Redis with TTL.

    Args:
        redis: Redis connection
        snapshot: WorldSnapshot to save
        ttl_seconds: Time-to-live in seconds (default: 5 minutes)

    Returns:
        Redis key where snapshot was saved (e.g., "ws:snapshot:90300")

    Note:
        Snapshots are saved as JSON with automatic expiration to prevent
        Redis from filling up with old telemetry data.
    """
    # Generate Redis key
    key = f"ws:snapshot:{snapshot.tick}"

    # Serialize snapshot to JSON
    payload = json.dumps(asdict(snapshot), default=str)

    # Save to Redis with TTL
    await redis.setex(key, ttl_seconds, payload)

    logger.debug(
        "snapshot_saved",
        key=key,
        tick=snapshot.tick,
        entity_count=snapshot.entity_count,
        ttl_seconds=ttl_seconds,
    )

    return key
