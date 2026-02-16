"""Tests for Watcher Agent anomaly detection and evolution triggering."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from backend.agents.watcher import WatcherAgent, detect_anomalies
from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import EvolutionTrigger, FeedMessage
from backend.config import Settings
from backend.core.telemetry import WorldSnapshot


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        min_population=20,
        max_entities=500,
        evolution_cooldown_sec=60,
    )


@pytest.fixture
def normal_snapshot() -> WorldSnapshot:
    """Create a normal snapshot with no anomalies."""
    return WorldSnapshot(
        tick=1000,
        entity_count=100,
        avg_energy=50.0,
        resource_count=50,
        death_stats={},
        timestamp=time.time(),
    )


@pytest.fixture
def starvation_snapshot() -> WorldSnapshot:
    """Create a snapshot with starvation (low avg_energy)."""
    return WorldSnapshot(
        tick=1001,
        entity_count=100,
        avg_energy=15.0,  # Below 20.0 threshold
        resource_count=10,
        death_stats={"starvation": 25},
        timestamp=time.time(),
    )


@pytest.fixture
def extinction_snapshot() -> WorldSnapshot:
    """Create a snapshot with extinction risk (low entity count)."""
    return WorldSnapshot(
        tick=1002,
        entity_count=25,  # Below min_population * 1.5 = 30
        avg_energy=40.0,
        resource_count=50,
        death_stats={"old_age": 15},
        timestamp=time.time(),
    )


@pytest.fixture
def overpopulation_snapshot() -> WorldSnapshot:
    """Create a snapshot with overpopulation (high entity count)."""
    return WorldSnapshot(
        tick=1003,
        entity_count=480,  # Above max_entities * 0.95 = 475
        avg_energy=60.0,
        resource_count=100,
        death_stats={},
        timestamp=time.time(),
    )


class TestDetectAnomalies:
    """Test suite for detect_anomalies pure function."""

    def test_no_anomalies(self, normal_snapshot: WorldSnapshot, settings: Settings) -> None:
        """Test that normal conditions produce no anomalies."""
        anomalies = detect_anomalies(normal_snapshot, settings)
        assert len(anomalies) == 0

    def test_starvation_detection(
        self,
        starvation_snapshot: WorldSnapshot,
        settings: Settings,
    ) -> None:
        """Test that low avg_energy triggers starvation anomaly."""
        anomalies = detect_anomalies(starvation_snapshot, settings)

        assert len(anomalies) == 1
        assert anomalies[0].problem_type == "starvation"
        assert anomalies[0].severity in ["high", "critical"]
        assert anomalies[0].suggested_area == "traits"
        assert "ws:snapshot:1001" in anomalies[0].snapshot_key

    def test_extinction_detection(
        self,
        extinction_snapshot: WorldSnapshot,
        settings: Settings,
    ) -> None:
        """Test that low entity count triggers extinction anomaly."""
        anomalies = detect_anomalies(extinction_snapshot, settings)

        assert len(anomalies) == 1
        assert anomalies[0].problem_type == "extinction"
        assert anomalies[0].severity in ["high", "critical"]
        assert anomalies[0].suggested_area == "environment"

    def test_overpopulation_detection(
        self,
        overpopulation_snapshot: WorldSnapshot,
        settings: Settings,
    ) -> None:
        """Test that high entity count triggers overpopulation anomaly."""
        anomalies = detect_anomalies(overpopulation_snapshot, settings)

        assert len(anomalies) == 1
        assert anomalies[0].problem_type == "overpopulation"
        assert anomalies[0].severity in ["high", "critical"]
        assert anomalies[0].suggested_area == "physics"

    def test_multiple_anomalies(self, settings: Settings) -> None:
        """Test that multiple anomalies can be detected simultaneously."""
        # Create a snapshot with both starvation AND extinction
        multi_anomaly_snapshot = WorldSnapshot(
            tick=1004,
            entity_count=25,  # Extinction
            avg_energy=15.0,  # Starvation
            resource_count=5,
            death_stats={"starvation": 50},
            timestamp=time.time(),
        )

        anomalies = detect_anomalies(multi_anomaly_snapshot, settings)

        assert len(anomalies) == 2
        problem_types = {a.problem_type for a in anomalies}
        assert "starvation" in problem_types
        assert "extinction" in problem_types

    def test_critical_severity_starvation(self, settings: Settings) -> None:
        """Test that very low energy triggers critical severity."""
        critical_snapshot = WorldSnapshot(
            tick=1005,
            entity_count=100,
            avg_energy=5.0,  # Very low, < 10.0 (50% of threshold)
            resource_count=5,
            death_stats={},
            timestamp=time.time(),
        )

        anomalies = detect_anomalies(critical_snapshot, settings)

        assert len(anomalies) == 1
        assert anomalies[0].severity == "critical"

    def test_boundary_conditions(self, settings: Settings) -> None:
        """Test edge cases at exact threshold boundaries."""
        # Exactly at starvation threshold (should trigger)
        snapshot_at_threshold = WorldSnapshot(
            tick=1006,
            entity_count=100,
            avg_energy=19.9,  # Just below 20.0
            resource_count=50,
            death_stats={},
            timestamp=time.time(),
        )

        anomalies = detect_anomalies(snapshot_at_threshold, settings)
        assert any(a.problem_type == "starvation" for a in anomalies)

        # Just above threshold (should not trigger)
        snapshot_above_threshold = WorldSnapshot(
            tick=1007,
            entity_count=100,
            avg_energy=20.1,  # Just above 20.0
            resource_count=50,
            death_stats={},
            timestamp=time.time(),
        )

        anomalies = detect_anomalies(snapshot_above_threshold, settings)
        assert not any(a.problem_type == "starvation" for a in anomalies)


class TestWatcherAgent:
    """Test suite for WatcherAgent class."""

    @pytest_asyncio.fixture
    async def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock()
        return redis

    @pytest_asyncio.fixture
    async def mock_event_bus(self) -> AsyncMock:
        """Create a mock EventBus."""
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        return bus

    @pytest_asyncio.fixture
    async def watcher(
        self,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
        settings: Settings,
    ) -> WatcherAgent:
        """Create a WatcherAgent instance with mocks."""
        return WatcherAgent(
            redis=mock_redis,
            event_bus=mock_event_bus,
            settings=settings,
        )

    @pytest.mark.asyncio
    async def test_cooldown_prevents_spam(
        self,
        watcher: WatcherAgent,
        starvation_snapshot: WorldSnapshot,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """Test that cooldown prevents repeated evolution triggers."""
        # Setup: snapshot returns starvation data
        mock_redis.get.return_value = json.dumps({
            "tick": 1001,
            "entity_count": 100,
            "avg_energy": 15.0,
            "resource_count": 10,
            "death_stats": {},
            "timestamp": time.time(),
        })

        # First telemetry event should trigger evolution
        await watcher._handle_telemetry({
            "tick": 1001,
            "snapshot_key": "ws:snapshot:1001",
            "timestamp": time.time(),
        })

        # Verify evolution trigger was published
        evolution_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.EVOLUTION_TRIGGER
        ]
        assert len(evolution_calls) == 1

        # Second telemetry event (immediately after) should NOT trigger due to cooldown
        await watcher._handle_telemetry({
            "tick": 1002,
            "snapshot_key": "ws:snapshot:1001",
            "timestamp": time.time(),
        })

        # Still only 1 evolution trigger (no new ones)
        evolution_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.EVOLUTION_TRIGGER
        ]
        assert len(evolution_calls) == 1

    @pytest.mark.asyncio
    async def test_feed_messages_published(
        self,
        watcher: WatcherAgent,
        starvation_snapshot: WorldSnapshot,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """Test that feed messages are published for anomalies."""
        # Setup: snapshot returns starvation data
        mock_redis.get.return_value = json.dumps({
            "tick": 1001,
            "entity_count": 100,
            "avg_energy": 15.0,
            "resource_count": 10,
            "death_stats": {},
            "timestamp": time.time(),
        })

        # Handle telemetry
        await watcher._handle_telemetry({
            "tick": 1001,
            "snapshot_key": "ws:snapshot:1001",
            "timestamp": time.time(),
        })

        # Verify feed message was published
        feed_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.FEED
        ]
        assert len(feed_calls) >= 1

        # Check feed message content
        feed_event = feed_calls[0][0][1]
        assert isinstance(feed_event, FeedMessage)
        assert feed_event.agent == "watcher"
        assert "голод" in feed_event.message.lower() or "starvation" in feed_event.action

    @pytest.mark.asyncio
    async def test_snapshot_not_found(
        self,
        watcher: WatcherAgent,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """Test graceful handling when snapshot is not in Redis."""
        # Setup: Redis returns None (key not found)
        mock_redis.get.return_value = None

        # Should not raise exception
        await watcher._handle_telemetry({
            "tick": 9999,
            "snapshot_key": "ws:snapshot:9999",
            "timestamp": time.time(),
        })

        # No evolution triggers should be published
        evolution_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.EVOLUTION_TRIGGER
        ]
        assert len(evolution_calls) == 0

    @pytest.mark.asyncio
    async def test_most_severe_anomaly_selected(
        self,
        watcher: WatcherAgent,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
    ) -> None:
        """Test that only the most severe anomaly triggers evolution."""
        # Setup: snapshot with multiple anomalies
        mock_redis.get.return_value = json.dumps({
            "tick": 1004,
            "entity_count": 25,  # Extinction (high severity)
            "avg_energy": 15.0,  # Starvation (high/critical severity)
            "resource_count": 5,
            "death_stats": {},
            "timestamp": time.time(),
        })

        # Handle telemetry
        await watcher._handle_telemetry({
            "tick": 1004,
            "snapshot_key": "ws:snapshot:1004",
            "timestamp": time.time(),
        })

        # Only ONE evolution trigger should be published (most severe)
        evolution_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.EVOLUTION_TRIGGER
        ]
        assert len(evolution_calls) == 1

        # Multiple feed messages should still be published
        feed_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.FEED
        ]
        assert len(feed_calls) >= 2

    @pytest.mark.asyncio
    async def test_cooldown_expires(
        self,
        watcher: WatcherAgent,
        mock_redis: AsyncMock,
        mock_event_bus: AsyncMock,
        settings: Settings,
    ) -> None:
        """Test that evolution can be triggered again after cooldown expires."""
        # Reduce cooldown for testing
        settings.evolution_cooldown_sec = 0.1

        # Setup: snapshot with anomaly
        mock_redis.get.return_value = json.dumps({
            "tick": 1001,
            "entity_count": 100,
            "avg_energy": 15.0,
            "resource_count": 10,
            "death_stats": {},
            "timestamp": time.time(),
        })

        # First trigger
        await watcher._handle_telemetry({
            "tick": 1001,
            "snapshot_key": "ws:snapshot:1001",
            "timestamp": time.time(),
        })

        # Wait for cooldown to expire
        await asyncio.sleep(0.15)

        # Second trigger (after cooldown)
        await watcher._handle_telemetry({
            "tick": 1002,
            "snapshot_key": "ws:snapshot:1001",
            "timestamp": time.time(),
        })

        # Should have 2 evolution triggers now
        evolution_calls = [
            call for call in mock_event_bus.publish.call_args_list
            if call[0][0] == Channels.EVOLUTION_TRIGGER
        ]
        assert len(evolution_calls) == 2
