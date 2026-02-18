"""Watcher Agent — monitors world state and triggers evolution when anomalies are detected.

The Watcher Agent analyzes telemetry snapshots to detect problems like starvation,
extinction risk, or overpopulation, then publishes evolution triggers for the
Architect Agent to plan solutions.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import structlog
from redis.asyncio import Redis

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import EvolutionTrigger, FeedMessage, MutationRollback
from backend.config import Settings
from backend.core.telemetry import WorldSnapshot

# Sandbox constraints sent to external agents with each task
_SANDBOX_CONSTRAINTS: list[str] = [
    "не использовать циклы > 100 итераций",
    "только: math, random, dataclasses, typing, enum, collections, functools, itertools",
    "определить BaseTrait stub в теле файла, не импортировать из backend.*",
]

_TASK_TTL: dict[str, int] = {"critical": 900, "high": 600}


def _format_task_description(trigger: EvolutionTrigger, snapshot: WorldSnapshot) -> str:
    """Build a human-readable task description from an anomaly trigger."""
    if trigger.problem_type == "starvation":
        return (
            f"Средняя энергия упала до {snapshot.avg_energy:.1f}%. "
            f"Нужен Trait, улучшающий сбор ресурсов."
        )
    if trigger.problem_type == "extinction":
        return (
            f"Популяция критически мала: {snapshot.entity_count} существ. "
            f"Нужен Trait, повышающий выживаемость."
        )
    if trigger.problem_type == "overpopulation":
        return (
            f"Перенаселение: {snapshot.entity_count} существ. "
            f"Нужен Trait для регуляции роста."
        )
    return f"Периодическое улучшение популяции ({trigger.problem_type})."

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
        self._prev_snapshot: Optional[WorldSnapshot] = None
        # Fitness tracking: mutation_id → {trait_name, baseline_count, window_starts_after}
        self._pending_fitness: dict[str, dict] = {}
        self._last_periodic_trigger_time: Optional[float] = None

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

        # Subscribe to mutation applied for fitness tracking
        await self._bus.subscribe(Channels.MUTATION_APPLIED, self._handle_mutation_applied)
        logger.info("watcher_subscribed", channel=Channels.MUTATION_APPLIED)

        # Keep running (the event bus will handle incoming messages)
        try:
            while self._running:
                await asyncio.sleep(1.0)
                await self._maybe_periodic_trigger()
        except Exception as exc:
            logger.error("watcher_agent_error", error=str(exc))
            raise

    def stop(self) -> None:
        """Stop the watcher agent."""
        self._running = False
        logger.info("watcher_agent_stopping")

    async def _handle_telemetry(self, data: dict[str, object]) -> None:
        """Handle incoming telemetry event.

        Args:
            data: Deserialized telemetry event data
                  {tick: int, snapshot_key: str, timestamp: float}
        """
        try:
            tick = int(data["tick"])
            snapshot_key = str(data["snapshot_key"])

            logger.debug("telemetry_received", tick=tick, snapshot_key=snapshot_key)

            # Load full snapshot from Redis
            snapshot = await self._load_snapshot(snapshot_key)
            if snapshot is None:
                logger.warning("snapshot_not_found", key=snapshot_key)
                return

            # Fitness check: evaluate pending mutations
            await self._check_fitness(snapshot)

            # Detect anomalies
            anomalies = detect_anomalies(snapshot, self._settings)

            if anomalies:
                logger.info(
                    "anomalies_detected",
                    count=len(anomalies),
                    types=[a.problem_type for a in anomalies],
                    tick=tick,
                )

                # Generate one cycle_id for the entire detection event
                cycle_id = f"evo_{uuid.uuid4().hex[:12]}"

                # Publish feed messages for each anomaly (T-040)
                for anomaly in anomalies:
                    await self._publish_feed_message(anomaly, snapshot, cycle_id)

                # Check cooldown before triggering evolution
                if self._can_trigger_evolution():
                    # Publish evolution trigger (only the most severe one)
                    most_severe = self._get_most_severe(anomalies)
                    most_severe.cycle_id = cycle_id
                    most_severe.world_context = {
                        "entity_count": snapshot.entity_count,
                        "avg_energy": round(snapshot.avg_energy, 1),
                        "resource_count": snapshot.resource_count,
                        "death_stats": snapshot.death_stats,
                    }
                    await self._bus.publish(Channels.EVOLUTION_TRIGGER, most_severe)
                    self._last_trigger_time = time.time()

                    # Publish task for external agents (Open Mutation API)
                    await self._publish_agent_task(most_severe, snapshot)

                    logger.info(
                        "evolution_triggered",
                        trigger_id=most_severe.trigger_id,
                        cycle_id=cycle_id,
                        problem_type=most_severe.problem_type,
                        severity=most_severe.severity,
                    )
                else:
                    cooldown_remaining = self._get_cooldown_remaining()
                    logger.debug(
                        "evolution_on_cooldown",
                        cooldown_remaining_sec=round(cooldown_remaining, 1),
                    )

            # Track snapshot for next diff computation
            self._prev_snapshot = snapshot

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
        cycle_id: str,
    ) -> None:
        """Publish a feed message for UI display.

        Args:
            anomaly: The detected anomaly
            snapshot: The world snapshot
            cycle_id: Evolution cycle ID shared across all agents in this cycle
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

        metadata: dict[str, object] = {
            "cycle_id": cycle_id,
            "trigger": {
                "problem_type": anomaly.problem_type,
                "severity": anomaly.severity,
            },
            "snapshot": {
                "tick": snapshot.tick,
                "entity_count": snapshot.entity_count,
                "avg_energy": snapshot.avg_energy,
            },
        }

        if self._prev_snapshot is not None:
            metadata["stats_diff"] = {
                "entity_count_before": self._prev_snapshot.entity_count,
                "entity_count_now": snapshot.entity_count,
                "avg_energy_before": self._prev_snapshot.avg_energy,
                "avg_energy_now": snapshot.avg_energy,
            }

        feed_msg = FeedMessage(
            agent="watcher",
            action=f"anomaly_detected_{anomaly.problem_type}",
            message=message,
            metadata=metadata,
        )

        await self._bus.publish(Channels.FEED, feed_msg)

    async def _handle_mutation_applied(self, data: dict[str, object]) -> None:
        """Record baseline population count when a mutation is applied.

        Args:
            data: MutationApplied event data {mutation_id, trait_name, version, registry_version}
        """
        mutation_id = str(data.get("mutation_id", ""))
        trait_name = str(data.get("trait_name", ""))

        if self._prev_snapshot is None:
            logger.debug("fitness_baseline_skipped_no_snapshot", mutation_id=mutation_id)
            return

        self._pending_fitness[mutation_id] = {
            "trait_name": trait_name,
            "baseline_count": self._prev_snapshot.entity_count,
            "window_starts_after": self._prev_snapshot.tick,
        }
        logger.info(
            "fitness_baseline_recorded",
            mutation_id=mutation_id,
            trait_name=trait_name,
            baseline_count=self._prev_snapshot.entity_count,
            window_starts_after=self._prev_snapshot.tick,
        )

    async def _check_fitness(self, snapshot: WorldSnapshot) -> None:
        """Evaluate pending mutation fitness against current snapshot.

        For each pending mutation whose observation window has passed,
        compare current entity_count to baseline and roll back if population
        dropped more than settings.fitness_rollback_threshold.

        Args:
            snapshot: Current world snapshot
        """
        threshold = self._settings.fitness_rollback_threshold
        to_remove: list[str] = []

        for mutation_id, entry in self._pending_fitness.items():
            if snapshot.tick <= entry["window_starts_after"]:
                continue  # Window hasn't passed yet

            baseline: int = entry["baseline_count"]
            trait_name: str = entry["trait_name"]
            to_remove.append(mutation_id)

            if baseline == 0:
                continue  # Avoid division by zero

            delta = (snapshot.entity_count - baseline) / baseline
            logger.info(
                "fitness_evaluated",
                mutation_id=mutation_id,
                trait_name=trait_name,
                baseline=baseline,
                current=snapshot.entity_count,
                delta=round(delta, 3),
            )

            # Write effects for external agent mutations (Open Mutation API)
            verdict = "negative" if delta < -threshold else ("positive" if delta > 0 else "neutral")
            effects_data = {
                "delta": {
                    "entity_count_delta": snapshot.entity_count - baseline,
                    "avg_energy_delta": round(
                        snapshot.avg_energy - (self._prev_snapshot.avg_energy if self._prev_snapshot else snapshot.avg_energy),
                        2,
                    ),
                },
                "verdict": verdict,
            }
            await self._redis.set(
                f"evo:mutation:{mutation_id}:effects",
                json.dumps(effects_data),
                ex=86400 * 7,
            )

            if delta < -threshold:
                pct = abs(round(delta * 100, 1))
                logger.warning(
                    "fitness_rollback_triggered",
                    mutation_id=mutation_id,
                    trait_name=trait_name,
                    fitness_delta=delta,
                )
                await self._bus.publish(
                    Channels.MUTATION_ROLLBACK,
                    MutationRollback(
                        mutation_id=mutation_id,
                        trait_name=trait_name,
                        reason="population_decline",
                        fitness_delta=delta,
                    ),
                )
                logger.info(
                    "mutation_rollback_published",
                    mutation_id=mutation_id,
                    trait_name=trait_name,
                    pct=pct,
                )

        for mid in to_remove:
            del self._pending_fitness[mid]

    async def _maybe_periodic_trigger(self) -> None:
        """Fire a periodic evolution trigger on a fixed interval, independent of anomalies.

        Fires every settings.periodic_evolution_interval_sec regardless of anomaly cooldown.
        Updates _last_trigger_time so anomaly detection won't double-fire right after.
        """
        interval = self._settings.periodic_evolution_interval_sec
        now = time.time()

        if (
            self._last_periodic_trigger_time is not None
            and (now - self._last_periodic_trigger_time) < interval
        ):
            return

        self._last_periodic_trigger_time = now
        self._last_trigger_time = now  # prevent anomaly from firing right after

        cycle_id = f"evo_{uuid.uuid4().hex[:12]}"
        trigger = EvolutionTrigger(
            trigger_id=str(uuid.uuid4()),
            problem_type="periodic_improvement",
            severity="low",
            suggested_area="traits",
            cycle_id=cycle_id,
            world_context={
                "entity_count": self._prev_snapshot.entity_count,
                "avg_energy": round(self._prev_snapshot.avg_energy, 1),
                "resource_count": self._prev_snapshot.resource_count,
                "death_stats": self._prev_snapshot.death_stats,
            } if self._prev_snapshot is not None else {},
        )
        await self._bus.publish(Channels.EVOLUTION_TRIGGER, trigger)
        await self._bus.publish(
            Channels.FEED,
            FeedMessage(
                agent="watcher",
                action="periodic_trigger",
                message="🔁 Watcher: Периодическая эволюция — улучшаем популяцию...",
                metadata={"cycle_id": cycle_id, "interval_sec": interval},
            ),
        )
        # Publish task for external agents
        if self._prev_snapshot is not None:
            await self._publish_agent_task(trigger, self._prev_snapshot)
        logger.info("periodic_evolution_triggered", cycle_id=cycle_id, interval_sec=interval)

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

    async def _publish_agent_task(
        self,
        trigger: EvolutionTrigger,
        snapshot: WorldSnapshot,
    ) -> None:
        """Write a task to Redis for external agents (Open Mutation API).

        Creates:
          - agent:task:{task_id} → task body (with TTL)
          - agent:tasks:queue (Sorted Set, score = expires_at)
          - publishes TaskPublished to ch:agent:tasks for WebSocket subscribers
        """
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        ttl_sec = _TASK_TTL.get(trigger.severity, 300)
        expires_at = time.time() + ttl_sec

        task_body: dict[str, object] = {
            "task_id": task_id,
            "expires_at": expires_at,
            "ttl_remaining_sec": ttl_sec,
            "source": "watcher",
            "problem_type": trigger.problem_type,
            "severity": trigger.severity,
            "description": _format_task_description(trigger, snapshot),
            "suggested_area": trigger.suggested_area,
            "world_context": {
                "entity_count": snapshot.entity_count,
                "avg_energy": round(snapshot.avg_energy, 1),
            },
            "constraints": _SANDBOX_CONSTRAINTS,
        }

        await self._redis.set(
            f"agent:task:{task_id}",
            json.dumps(task_body),
            ex=ttl_sec,
        )
        await self._redis.zadd("agent:tasks:queue", {task_id: expires_at})

        # Notify WebSocket subscribers
        event_payload: dict[str, object] = {
            "event_type": "TaskPublished",
            "task_id": task_id,
            "problem_type": trigger.problem_type,
            "severity": trigger.severity,
            "expires_at": expires_at,
        }
        await self._redis.publish(Channels.AGENT_TASKS, json.dumps(event_payload))

        logger.info(
            "agent_task_published",
            task_id=task_id,
            problem_type=trigger.problem_type,
            severity=trigger.severity,
            ttl_sec=ttl_sec,
        )

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
