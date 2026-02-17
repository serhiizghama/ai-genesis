"""Tests for EvolutionCycleManager — Redis mutex for evolution cycles.

Uses an in-memory fake Redis to verify lock acquisition, rejection of
duplicate triggers, stage updates, and cycle completion / failure paths.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.cycle_manager import (
    STAGE_CODING,
    STAGE_DONE,
    STAGE_FAILED,
    EvolutionCycleManager,
)
from backend.bus.events import EvolutionTrigger
from backend.config import Settings


# ---------------------------------------------------------------------------
# Minimal in-memory fake Redis
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async Redis fake that supports SET NX EX, HSET, EXPIRE, DEL, GET."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key].update(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def expire(self, key: str, seconds: int) -> None:
        pass  # TTLs not tracked in the fake

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                deleted += 1
            if key in self._hashes:
                del self._hashes[key]
        return deleted


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def manager(fake_redis: FakeRedis, settings: Settings) -> EvolutionCycleManager:
    return EvolutionCycleManager(redis=fake_redis, settings=settings)  # type: ignore


def make_trigger(trigger_id: str = "trig_001") -> EvolutionTrigger:
    return EvolutionTrigger(
        trigger_id=trigger_id,
        problem_type="starvation",
        severity="high",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEvolutionCycleManager:
    @pytest.mark.asyncio
    async def test_start_cycle_acquires_lock(
        self,
        manager: EvolutionCycleManager,
        fake_redis: FakeRedis,
    ) -> None:
        """First trigger acquires the lock and writes metadata hash."""
        trigger = make_trigger("t1")
        acquired = await manager.start_cycle(trigger)

        assert acquired is True
        assert await fake_redis.get("evo:cycle:lock") == "t1"

        data = await fake_redis.hgetall("evo:cycle:current")
        assert data["trigger_id"] == "t1"
        assert data["stage"] == "planning"

    @pytest.mark.asyncio
    async def test_second_trigger_is_rejected(
        self,
        manager: EvolutionCycleManager,
    ) -> None:
        """Second trigger while a cycle is running must be rejected."""
        await manager.start_cycle(make_trigger("t1"))
        rejected = await manager.start_cycle(make_trigger("t2"))

        assert rejected is False

    @pytest.mark.asyncio
    async def test_update_stage(
        self,
        manager: EvolutionCycleManager,
        fake_redis: FakeRedis,
    ) -> None:
        """update_stage writes new stage to the hash."""
        await manager.start_cycle(make_trigger("t1"))
        await manager.update_stage(STAGE_CODING)

        data = await fake_redis.hgetall("evo:cycle:current")
        assert data["stage"] == STAGE_CODING

    @pytest.mark.asyncio
    async def test_complete_cycle_releases_lock(
        self,
        manager: EvolutionCycleManager,
        fake_redis: FakeRedis,
    ) -> None:
        """complete_cycle sets stage=done and deletes the lock key."""
        await manager.start_cycle(make_trigger("t1"))
        await manager.complete_cycle()

        assert await fake_redis.get("evo:cycle:lock") is None
        data = await fake_redis.hgetall("evo:cycle:current")
        assert data["stage"] == STAGE_DONE

    @pytest.mark.asyncio
    async def test_fail_cycle_releases_lock(
        self,
        manager: EvolutionCycleManager,
        fake_redis: FakeRedis,
    ) -> None:
        """fail_cycle records the error and deletes the lock key."""
        await manager.start_cycle(make_trigger("t1"))
        await manager.fail_cycle("LLM timeout")

        assert await fake_redis.get("evo:cycle:lock") is None
        data = await fake_redis.hgetall("evo:cycle:current")
        assert data["stage"] == STAGE_FAILED
        assert data["error"] == "LLM timeout"

    @pytest.mark.asyncio
    async def test_new_cycle_after_complete(
        self,
        manager: EvolutionCycleManager,
    ) -> None:
        """After completing a cycle, a new trigger can start a fresh one."""
        await manager.start_cycle(make_trigger("t1"))
        await manager.complete_cycle()

        acquired = await manager.start_cycle(make_trigger("t2"))
        assert acquired is True

    @pytest.mark.asyncio
    async def test_no_op_without_redis(self, settings: Settings) -> None:
        """Manager without Redis always grants lock (graceful degradation)."""
        mgr = EvolutionCycleManager(redis=None, settings=settings)
        assert await mgr.start_cycle(make_trigger()) is True
        # These should not raise
        await mgr.update_stage(STAGE_CODING)
        await mgr.complete_cycle()
        await mgr.fail_cycle("test")


class TestArchitectWithCycleManager:
    """Verify that ArchitectAgent rejects duplicate triggers via cycle lock."""

    @pytest.mark.asyncio
    async def test_architect_rejects_second_trigger(
        self,
        settings: Settings,
        fake_redis: FakeRedis,
    ) -> None:
        """Second trigger while cycle is locked must be skipped."""
        from unittest.mock import AsyncMock

        from backend.agents.architect import ArchitectAgent
        from backend.agents.cycle_manager import EvolutionCycleManager

        cycle_manager = EvolutionCycleManager(redis=fake_redis, settings=settings)  # type: ignore

        mock_llm = AsyncMock()
        mock_llm.generate_json = AsyncMock(
            return_value={
                "trait_name": "test_trait",
                "description": "A test trait",
                "action_type": "new_trait",
            }
        )

        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock()

        architect = ArchitectAgent(
            event_bus=mock_bus,
            llm_client=mock_llm,
            settings=settings,
            cycle_manager=cycle_manager,
        )

        trigger1 = make_trigger("t1")
        trigger2 = make_trigger("t2")

        # Process first trigger — should succeed
        plan1 = await architect._create_plan(trigger1)
        await cycle_manager.start_cycle(trigger1)  # simulate lock acquired by run()

        # Now try second trigger — start_cycle should reject
        acquired = await cycle_manager.start_cycle(trigger2)
        assert acquired is False

        # plan1 was created, plan2 is blocked
        assert plan1 is not None
