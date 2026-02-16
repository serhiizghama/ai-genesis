"""Watcher Agent — monitors world state and triggers evolution when anomalies are detected.

The Watcher Agent analyzes telemetry snapshots to detect problems like starvation,
extinction risk, or overpopulation, then publishes evolution triggers for the
Architect Agent to plan solutions.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import structlog
from redis.asyncio import Redis

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import EvolutionTrigger, FeedMessage
from backend.config import Settings
from backend.core.telemetry import WorldSnapshot

logger = structlog.get_logger()

# Typical max energy for entities (from entity_manager.py entity creation)
TYPICAL_MAX_ENERGY = 100.0


def detect_anomalies(
    snapshot: WorldSnapshot,
    settings: Settings,
) -> list[EvolutionTrigger]:
    """Detect anomalies in world state using heuristic rules.

    Args:
        snapshot: Current world state snapshot
        settings: Application settings with thresholds

    Returns:
        List of EvolutionTrigger events for detected anomalies.
        Empty list if no anomalies detected.

    Heuristics:
        - Starvation: avg_energy < TYPICAL_MAX_ENERGY * 0.2 (< 20.0)
        - Extinction: entity_count < min_population * 1.5
        - Overpopulation: entity_count > max_entities * 0.95

    Note:
        This is a pure function with no side effects.
        It only analyzes data and returns triggers.
    """
    triggers: list[EvolutionTrigger] = []

    # Check for starvation
    starvation_threshold = TYPICAL_MAX_ENERGY * 0.2
    if snapshot.avg_energy < starvation_threshold:
        severity = "critical" if snapshot.avg_energy < starvation_threshold * 0.5 else "high"
        triggers.append(
            EvolutionTrigger(
                trigger_id=str(uuid.uuid4()),
                problem_type="starvation",
                severity=severity,
                affected_entities=[],  # Affects all entities
                suggested_area="traits",
                snapshot_key=f"ws:snapshot:{snapshot.tick}",
            )
        )

    # Check for extinction risk
    extinction_threshold = settings.min_population * 1.5
    if snapshot.entity_count < extinction_threshold:
        severity = "critical" if snapshot.entity_count <= settings.min_population else "high"
        triggers.append(
            EvolutionTrigger(
                trigger_id=str(uuid.uuid4()),
                problem_type="extinction",
                severity=severity,
                affected_entities=[],  # Population-level issue
                suggested_area="environment",
                snapshot_key=f"ws:snapshot:{snapshot.tick}",
            )
        )

    # Check for overpopulation
    overpopulation_threshold = settings.max_entities * 0.95
    if snapshot.entity_count > overpopulation_threshold:
        severity = "high" if snapshot.entity_count < settings.max_entities else "critical"
        triggers.append(
            EvolutionTrigger(
                trigger_id=str(uuid.uuid4()),
                problem_type="overpopulation",
                severity=severity,
                affected_entities=[],  # Population-level issue
                suggested_area="physics",
                snapshot_key=f"ws:snapshot:{snapshot.tick}",
            )
        )

    return triggers


class WatcherAgent:
    """Observes telemetry data and triggers evolution when anomalies are detected.

    The WatcherAgent subscribes to the telemetry channel, loads snapshots from Redis,
    runs anomaly detection, and publishes evolution triggers with cooldown protection
    to prevent spamming the system.
    """

    def __init__(
        self,
        redis: Redis,
        event_bus: EventBus,
        settings: Settings,
    ) -> None:
        """Initialize the Watcher Agent.

        Args:
            redis: Redis client for loading snapshots
            event_bus: Event bus for pub/sub communication
            settings: Application settings
        """
        self._redis = redis
        self._bus = event_bus
        self._settings = settings
        self._last_trigger_time: Optional[float] = None
        self._running = False

    async def run(self) -> None:
        """Start the watcher agent loop.

        Subscribes to ch:telemetry and processes incoming telemetry events.
        This method runs indefinitely until stopped.
        """
        self._running = True
        logger.info("watcher_agent_starting")

        # Subscribe to telemetry channel
        await self._bus.subscribe(Channels.TELEMETRY, self._handle_telemetry)
        logger.info("watcher_subscribed", channel=Channels.TELEMETRY)

        # Keep running (the event bus will handle incoming messages)
        try:
            while self._running:
                await asyncio.sleep(1.0)
        except Exception as exc:
            logger.error("watcher_agent_error", error=str(exc))
            raise

    def stop(self) -> None:
        """Stop the watcher agent."""
        self._running = False
        logger.info("watcher_agent_stopping")

    async def _handle_telemetry(self, data: dict[str, Any]) -> None:
        """Handle incoming telemetry event.

        Args:
            data: Deserialized telemetry event data
                  {tick: int, snapshot_key: str, timestamp: float}
        """
        try:
            tick = data["tick"]
            snapshot_key = data["snapshot_key"]

            logger.debug("telemetry_received", tick=tick, snapshot_key=snapshot_key)

            # Load full snapshot from Redis
            snapshot = await self._load_snapshot(snapshot_key)
            if snapshot is None:
                logger.warning("snapshot_not_found", key=snapshot_key)
                return

            # Detect anomalies
            anomalies = detect_anomalies(snapshot, self._settings)

            if anomalies:
                logger.info(
                    "anomalies_detected",
                    count=len(anomalies),
                    types=[a.problem_type for a in anomalies],
                    tick=tick,
                )

                # Publish feed messages for each anomaly (T-040)
                for anomaly in anomalies:
                    await self._publish_feed_message(anomaly, snapshot)

                # Check cooldown before triggering evolution
                if self._can_trigger_evolution():
                    # Publish evolution trigger (only the most severe one)
                    most_severe = self._get_most_severe(anomalies)
                    await self._bus.publish(Channels.EVOLUTION_TRIGGER, most_severe)
                    self._last_trigger_time = time.time()

                    logger.info(
                        "evolution_triggered",
                        trigger_id=most_severe.trigger_id,
                        problem_type=most_severe.problem_type,
                        severity=most_severe.severity,
                    )
                else:
                    cooldown_remaining = self._get_cooldown_remaining()
                    logger.debug(
                        "evolution_on_cooldown",
                        cooldown_remaining_sec=round(cooldown_remaining, 1),
                    )

        except Exception as exc:
            logger.error(
                "telemetry_handler_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _load_snapshot(self, snapshot_key: str) -> Optional[WorldSnapshot]:
        """Load a snapshot from Redis.

        Args:
            snapshot_key: Redis key for the snapshot (e.g., "ws:snapshot:90300")

        Returns:
            WorldSnapshot if found, None otherwise
        """
        try:
            raw_data = await self._redis.get(snapshot_key)
            if raw_data is None:
                return None

            data = json.loads(raw_data)
            return WorldSnapshot(**data)
        except Exception as exc:
            logger.error(
                "snapshot_load_error",
                key=snapshot_key,
                error=str(exc),
            )
            return None

    async def _publish_feed_message(
        self,
        anomaly: EvolutionTrigger,
        snapshot: WorldSnapshot,
    ) -> None:
        """Publish a feed message for UI display.

        Args:
            anomaly: The detected anomaly
            snapshot: The world snapshot
        """
        # Create human-readable message based on anomaly type
        if anomaly.problem_type == "starvation":
            message = f"⚠️ Обнаружен голод! Средняя энергия упала до {snapshot.avg_energy:.1f}%."
        elif anomaly.problem_type == "extinction":
            message = f"🚨 Риск вымирания! Осталось только {snapshot.entity_count} существ."
        elif anomaly.problem_type == "overpopulation":
            message = f"📈 Перенаселение! Количество существ достигло {snapshot.entity_count}."
        else:
            message = f"⚠️ Обнаружена аномалия: {anomaly.problem_type}"

        feed_msg = FeedMessage(
            agent="watcher",
            action=f"anomaly_detected_{anomaly.problem_type}",
            message=message,
            metadata={
                "trigger_id": anomaly.trigger_id,
                "severity": anomaly.severity,
                "tick": snapshot.tick,
            },
        )

        await self._bus.publish(Channels.FEED, feed_msg)

    def _can_trigger_evolution(self) -> bool:
        """Check if enough time has passed since last evolution trigger.

        Returns:
            True if evolution can be triggered, False if on cooldown
        """
        if self._last_trigger_time is None:
            return True

        elapsed = time.time() - self._last_trigger_time
        return elapsed >= self._settings.evolution_cooldown_sec

    def _get_cooldown_remaining(self) -> float:
        """Get remaining cooldown time in seconds.

        Returns:
            Seconds remaining on cooldown, 0.0 if ready
        """
        if self._last_trigger_time is None:
            return 0.0

        elapsed = time.time() - self._last_trigger_time
        remaining = self._settings.evolution_cooldown_sec - elapsed
        return max(0.0, remaining)

    def _get_most_severe(self, anomalies: list[EvolutionTrigger]) -> EvolutionTrigger:
        """Select the most severe anomaly from a list.

        Args:
            anomalies: List of detected anomalies

        Returns:
            The anomaly with highest severity
        """
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}

        return max(
            anomalies,
            key=lambda a: severity_order.get(a.severity, 0),
        )


# Import asyncio here (after the module-level definitions)
import asyncio
