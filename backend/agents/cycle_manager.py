"""Evolution Cycle Manager — Redis-backed mutex for serialising evolution cycles.

Prevents the Architect from launching a new plan while a previous mutation
cycle is still in progress, using an atomic Redis SETNX lock with a TTL
safety valve.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from backend.bus.events import EvolutionTrigger
    from backend.config import Settings

logger = structlog.get_logger()

# Redis keys
_LOCK_KEY = "evo:cycle:lock"
_DATA_KEY = "evo:cycle:current"

# Cycle stage constants
STAGE_PLANNING = "planning"
STAGE_CODING = "coding"
STAGE_PATCHING = "patching"
STAGE_DONE = "done"
STAGE_FAILED = "failed"


class EvolutionCycleManager:
    """Serialises evolution cycles with a Redis mutex.

    Only one cycle can be active at a time.  The lock is acquired via
    ``SET NX EX`` (atomic) so concurrent trigger deliveries are safe.

    The ``evo:cycle:current`` hash stores human-readable state that can be
    inspected with ``redis-cli HGETALL evo:cycle:current``.

    Attributes:
        redis: Async Redis client.
        settings: Application settings (used for TTL calculation).
    """

    def __init__(self, redis: Optional[Redis], settings: Settings) -> None:
        """Initialise the cycle manager.

        Args:
            redis: Async Redis connection.  If ``None``, the manager becomes a
                   no-op (all ``start_cycle`` calls return ``True``).
            settings: Application settings.
        """
        self._redis = redis
        self._settings = settings
        # TTL = cooldown + generous buffer so long LLM calls don't expire it
        self._ttl_sec: int = max(60, settings.evolution_cooldown_sec * 3)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_cycle(self, trigger: EvolutionTrigger) -> bool:
        """Try to acquire the evolution cycle lock.

        Args:
            trigger: The trigger that wants to start a new cycle.

        Returns:
            ``True`` if the lock was acquired (safe to proceed).
            ``False`` if another cycle is already running (caller should skip).
        """
        if self._redis is None:
            return True  # no-op without Redis

        # Atomic SET NX EX — only succeeds if key doesn't exist
        acquired = await self._redis.set(
            _LOCK_KEY,
            trigger.trigger_id,
            nx=True,
            ex=self._ttl_sec,
        )

        if not acquired:
            # Lock already held — find out who holds it
            holder = await self._redis.get(_LOCK_KEY)
            logger.warning(
                "evolution_cycle_locked",
                trigger_id=trigger.trigger_id,
                held_by=holder,
            )
            return False

        # Record cycle metadata in an inspectable hash
        await self._redis.hset(
            _DATA_KEY,
            mapping={
                "trigger_id": trigger.trigger_id,
                "problem_type": trigger.problem_type,
                "severity": trigger.severity,
                "stage": STAGE_PLANNING,
                "started_at": str(time.time()),
                "updated_at": str(time.time()),
            },
        )
        await self._redis.expire(_DATA_KEY, self._ttl_sec)

        logger.info(
            "evolution_cycle_started",
            trigger_id=trigger.trigger_id,
            ttl_sec=self._ttl_sec,
        )
        return True

    async def update_stage(self, stage: str) -> None:
        """Update the current cycle stage in Redis.

        Args:
            stage: New stage name (use the ``STAGE_*`` constants).
        """
        if self._redis is None:
            return

        await self._redis.hset(
            _DATA_KEY,
            mapping={
                "stage": stage,
                "updated_at": str(time.time()),
            },
        )
        logger.debug("evolution_cycle_stage_updated", stage=stage)

    async def complete_cycle(self) -> None:
        """Mark the cycle as done and release the lock."""
        if self._redis is None:
            return

        await self.update_stage(STAGE_DONE)
        await self._redis.delete(_LOCK_KEY)
        logger.info("evolution_cycle_completed")

    async def fail_cycle(self, error: str) -> None:
        """Mark the cycle as failed and release the lock.

        Args:
            error: Human-readable reason for the failure.
        """
        if self._redis is None:
            return

        await self._redis.hset(
            _DATA_KEY,
            mapping={
                "stage": STAGE_FAILED,
                "error": error,
                "updated_at": str(time.time()),
            },
        )
        await self._redis.delete(_LOCK_KEY)
        logger.warning("evolution_cycle_failed", error=error)
