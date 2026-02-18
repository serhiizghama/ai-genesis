"""Core simulation engine — main loop and lifecycle management.

This module provides the CoreEngine class which orchestrates the entire
simulation tick loop including entity updates, physics, lifecycle management,
and telemetry.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional, TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from backend.bus.channels import Channels
from backend.bus.events import FeedMessage, TelemetryEvent
from backend.config import Settings
from backend.core.dynamic_registry import DynamicRegistry, canonical_name
from backend.core.entity_manager import EntityManager
from backend.core.environment import Environment
from backend.core.telemetry import WorldSnapshot, collect_snapshot, save_snapshot_to_redis
from backend.core.traits import TraitExecutor
from backend.core.world_physics import WorldPhysics

if TYPE_CHECKING:
    import asyncpg
    from backend.api.ws_handler import ConnectionManager

logger = structlog.get_logger()


class CoreEngine:
    """Main simulation engine that runs the world tick loop.

    Coordinates:
    - Entity lifecycle (spawn, death, updates)
    - Physics simulation
    - Resource management
    - Statistics collection
    """

    def __init__(
        self,
        entity_manager: EntityManager,
        environment: Environment,
        physics: WorldPhysics,
        registry: DynamicRegistry,
        redis: Redis,
        settings: Settings,
        ws_manager: Optional[ConnectionManager] = None,
        db_pool: Optional[asyncpg.Pool] = None,
    ) -> None:
        """Initialize the core engine.

        Args:
            entity_manager: Manages all entities in the simulation.
            environment: Manages resources (food) in the world.
            physics: Handles physics simulation (collisions, boundaries).
            registry: Dynamic trait registry for entity spawning.
            redis: Redis connection for event bus.
            settings: Application settings.
            ws_manager: WebSocket connection manager for real-time streaming.
        """
        self.entity_manager = entity_manager
        self.environment = environment
        self.physics = physics
        self.registry = registry
        self.redis = redis
        self.settings = settings
        self.ws_manager = ws_manager
        self._db_pool = db_pool

        # Checkpoint interval: ~60 sec at 62.5 TPS
        self._checkpoint_interval_ticks = 3750

        # Trait errors to report to feed (dedup by trait_name)
        self._reported_trait_errors: set[str] = set()

        # Create trait executor with configured timeouts
        self.trait_executor = TraitExecutor(
            timeout_sec=settings.trait_timeout_sec,
            tick_budget_sec=settings.tick_time_budget_sec,
            on_trait_error=self._on_trait_error,
        )

        # Tick counter
        self.tick_counter = 0

        # Statistics tracking
        self.stats_interval = 100  # Log stats every 100 ticks
        self.running = False

        # Death statistics (reset after each snapshot)
        self.death_stats: dict[str, int] = {}
        self.last_snapshot_tick = 0

        # Track registry version to detect new mutations and apply them to living entities
        self._known_registry_version = 0

        # Cumulative kill/death counters (never reset, shown in header)
        self._predator_kill_count = 0   # molbots killed by predators
        self._virus_kill_count = 0      # molbots killed by virus
        self._predator_death_count = 0  # predators that died (any cause)

        # Virus state
        self._virus_active = False
        self._virus_ticks_remaining = 0

    async def run(self) -> None:
        """Main simulation loop.

        Runs indefinitely until stopped, executing one tick per iteration:
        1. Update all entities (age, metabolism, trait execution)
        2. Apply physics (boundaries, collisions)
        3. Handle lifecycle (death, spawning)
        4. Respawn resources
        5. Collect and log statistics
        6. Sleep until next tick

        Note:
            This loop never exits normally. It should be cancelled externally
            or interrupted by the user.
        """
        self.running = True
        logger.info("engine_starting", tick_rate_ms=self.settings.tick_rate_ms)

        # Spawn initial population if world is empty
        if self.entity_manager.count_alive() == 0:
            await self._spawn_initial_population()

        while self.running:
            self.tick_counter += 1
            tick_start = asyncio.get_event_loop().time()

            try:
                # T-018: Core update logic
                await self._update_entities()
                self._apply_physics()

                # T-019: Lifecycle management
                self._handle_deaths()
                await self._handle_predators()
                await self._handle_virus()

                # Apply any new mutations from registry to all living entities
                self._apply_new_registry_traits()

                # T-029: Broadcast BEFORE respawning so clients see real population dips
                if self.ws_manager and self.tick_counter % 2 == 0:
                    await self._broadcast_world_state()

                await self._handle_spawning()
                self._respawn_resources()

                # T-020: Statistics and logging
                if self.tick_counter % self.stats_interval == 0:
                    self._log_statistics()

                # T-036/T-037: Telemetry snapshot collection
                if self.tick_counter % self.settings.snapshot_interval_ticks == 0:
                    await self._collect_and_send_telemetry()

                # PostgreSQL world checkpoint (every ~60 sec)
                if (
                    self._db_pool is not None
                    and self.tick_counter % self._checkpoint_interval_ticks == 0
                ):
                    asyncio.create_task(self._save_checkpoint_async())

            except Exception as exc:
                # Never let the simulation loop crash
                logger.error(
                    "tick_error",
                    tick=self.tick_counter,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

            # Calculate tick duration and sleep
            tick_duration = asyncio.get_event_loop().time() - tick_start
            sleep_time = max(0.0, (self.settings.tick_rate_ms / 1000.0) - tick_duration)

            if tick_duration > (self.settings.tick_rate_ms / 1000.0):
                logger.warning(
                    "tick_overrun",
                    tick=self.tick_counter,
                    duration_ms=tick_duration * 1000,
                    budget_ms=self.settings.tick_rate_ms,
                )

            await asyncio.sleep(sleep_time)

    async def _update_entities(self) -> None:
        """Update all living entities.

        Calls entity.update() for each alive entity, which handles:
        - Age increment
        - Metabolism (energy consumption)
        - Trait execution
        """
        entities = self.entity_manager.alive()

        for entity in entities:
            try:
                await entity.update(self.trait_executor)
            except Exception as exc:
                logger.error(
                    "entity_update_error",
                    entity_id=entity.id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    def _apply_physics(self) -> None:
        """Apply physics to all entities.

        Handles:
        - World boundary enforcement
        - Collision detection and resolution (if needed)
        - Spatial grid rebuilding
        """
        entities = self.entity_manager.alive()

        # Apply boundary constraints to all entities
        for entity in entities:
            self.physics.apply_bounds(entity)

        # Rebuild spatial grid for collision detection
        self.entity_manager.rebuild_spatial_grid()

        # Detect and resolve collisions
        collisions = self.entity_manager.detect_collisions()
        for entity_a, entity_b in collisions:
            self.physics.resolve_collision(entity_a, entity_b)

    def _handle_deaths(self) -> None:
        """Remove entities that have died (energy <= 0).

        Entities with state == "dead" are removed from the simulation.
        Death causes are tracked in self.death_stats for telemetry.
        """
        entities = self.entity_manager.get_all_entities()
        dead_entities = [e for e in entities if not e.is_alive()]

        for entity in dead_entities:
            # Track death cause
            if entity.entity_type == "predator":
                death_cause = "predator_death"
                self._predator_death_count += 1
            elif getattr(entity, "infected", False):
                death_cause = "virus"
                self._virus_kill_count += 1
            else:
                death_cause = "starvation"
            self.death_stats[death_cause] = self.death_stats.get(death_cause, 0) + 1

            # Remove from simulation
            self.entity_manager.remove(entity)

        if dead_entities:
            logger.info(
                "entities_died",
                tick=self.tick_counter,
                count=len(dead_entities),
            )

    # Max entities to spawn per tick — limits refill rate so population dips
    # are visible in the graph rather than being instantly hidden.
    _SPAWN_BATCH_SIZE = 2

    async def _handle_spawning(self) -> None:
        """Spawn new entities based on population floor and organic growth.

        - Below min_population: always refill (up to _SPAWN_BATCH_SIZE per tick)
        - Above min_population: grow organically when avg energy is high
          (simulates reproduction driven by resource availability)
        """
        current_count = self.entity_manager.count_alive()

        # Calculate avg energy to drive organic growth
        alive = self.entity_manager.alive()
        avg_energy_pct = 0.0
        if alive:
            avg_energy_pct = sum(e.energy / e.max_energy for e in alive) / len(alive) * 100

        # How many to spawn this tick
        to_spawn = 0

        if current_count < self.settings.min_population:
            # Floor maintenance: refill up to batch size
            to_spawn = min(self.settings.min_population - current_count, self._SPAWN_BATCH_SIZE)
        elif current_count < self.settings.max_entities:
            # Organic growth: spawn when entities are thriving
            # avg_energy > 70% → 1 extra, avg_energy > 85% → 2 extra
            if avg_energy_pct >= 85:
                to_spawn = 2
            elif avg_energy_pct >= 70:
                to_spawn = 1

        spawned = 0
        trait_snapshot = self.registry.get_snapshot()
        generation = self.tick_counter // 75

        for _ in range(to_spawn):
            if self.entity_manager.count_alive() >= self.settings.max_entities:
                break

            x = random.uniform(0, self.settings.world_width)
            y = random.uniform(0, self.settings.world_height)
            traits = [cls() for cls in trait_snapshot.values()]

            entity = self.entity_manager.spawn(
                x=x,
                y=y,
                traits=traits,
                generation=generation,
                tick=self.tick_counter,
            )
            entity._environment = self.environment
            entity._entity_manager = self.entity_manager
            spawned += 1

        if spawned > 0:
            reason = "min_population" if current_count < self.settings.min_population else "organic_growth"
            logger.info(
                "entities_spawned",
                tick=self.tick_counter,
                count=spawned,
                total=self.entity_manager.count_alive(),
                avg_energy_pct=round(avg_energy_pct, 1),
                reason=reason,
            )

    def _respawn_resources(self) -> None:
        """Respawn resources in the environment.

        Uses a fixed spawn rate for MVP. In future phases, this could
        be dynamic based on consumption rates or world conditions.
        """
        self.environment.respawn_resources(self.settings.spawn_rate)

    def _log_statistics(self) -> None:
        """Collect and log simulation statistics.

        Logs:
        - Current tick
        - Entity count
        - Average energy
        - Resource count

        Also prepares telemetry for future event bus integration.
        """
        entities = self.entity_manager.alive()
        entity_count = len(entities)

        # Calculate average energy
        avg_energy = 0.0
        if entity_count > 0:
            total_energy = sum(e.energy for e in entities)
            avg_energy = total_energy / entity_count

        # Get resource count
        resource_count = self.environment.count()

        # Log to console (T-020)
        logger.info(
            "simulation_stats",
            tick=self.tick_counter,
            entities=entity_count,
            avg_energy=round(avg_energy, 1),
            resources=resource_count,
        )

    async def _collect_and_send_telemetry(self) -> None:
        """Collect world snapshot and publish telemetry event (T-036, T-037).

        This method:
        1. Collects a WorldSnapshot with current simulation metrics
        2. Saves snapshot to Redis with 5-minute TTL
        3. Publishes TelemetryEvent to the event bus
        4. Resets death_stats for next period
        5. Logs telemetry event

        Note:
            This is called every settings.snapshot_interval_ticks (e.g., 300 ticks).
            The Watcher Agent subscribes to the TELEMETRY channel and analyzes
            these snapshots for anomaly detection.
        """
        # Collect snapshot from current world state
        snapshot = collect_snapshot(self)

        # Save snapshot to Redis with 5-minute TTL
        snapshot_key = await save_snapshot_to_redis(
            self.redis,
            snapshot,
            ttl_seconds=300,
        )

        # Publish TelemetryEvent to event bus
        event = TelemetryEvent(
            tick=snapshot.tick,
            snapshot_key=snapshot_key,
        )

        # Serialize and publish event (using same pattern as EventBus.publish)
        import json
        from dataclasses import asdict

        payload = json.dumps(asdict(event), default=str)
        await self.redis.publish(Channels.TELEMETRY, payload)

        # Reset death stats for next snapshot period
        self.death_stats.clear()
        self.last_snapshot_tick = self.tick_counter

        # Log telemetry event
        logger.info(
            "telemetry_sent",
            tick=snapshot.tick,
            snapshot_key=snapshot_key,
            entity_count=snapshot.entity_count,
            avg_energy=snapshot.avg_energy,
            resource_count=snapshot.resource_count,
            death_stats=snapshot.death_stats,
        )

    def _apply_new_registry_traits(self) -> None:
        """Apply any newly registered traits to all living entities.

        Uses the registry version counter to detect changes (increments on
        every register/unregister, so it also catches same-family updates).

        For each registry entry:
        - If the entity already has a trait in the same canonical family,
          replace it in-place (upgrades old version → new version).
        - Otherwise add the trait, respecting max_active_traits cap.
        """
        current_version = self.registry.version
        if current_version <= self._known_registry_version:
            return

        trait_snapshot = self.registry.get_snapshot()
        for entity in self.entity_manager.alive():
            # Build map: canonical_family_name → index in entity.traits
            entity_canonical: dict[str, int] = {}
            for i, t in enumerate(entity.traits):
                entity_canonical[canonical_name(t.__class__.__name__)] = i

            for canon_name, trait_cls in trait_snapshot.items():
                if canon_name in entity_canonical:
                    # Replace old family version in-place
                    idx = entity_canonical[canon_name]
                    try:
                        entity.traits[idx] = trait_cls()
                    except Exception as exc:
                        logger.warning(
                            "trait_replace_failed",
                            entity_id=entity.id,
                            trait_name=canon_name,
                            error=str(exc),
                        )
                elif len(entity.traits) < self.settings.max_active_traits:
                    # Add new trait if under the per-entity cap
                    try:
                        entity.traits.append(trait_cls())
                        logger.info(
                            "trait_applied_to_entity",
                            entity_id=entity.id,
                            trait_name=canon_name,
                        )
                    except Exception as exc:
                        logger.warning(
                            "trait_apply_failed",
                            entity_id=entity.id,
                            trait_name=canon_name,
                            error=str(exc),
                        )

        self._known_registry_version = current_version
        logger.info(
            "registry_traits_applied_to_population",
            registry_version=current_version,
            entity_count=self.entity_manager.count_alive(),
        )

    async def _spawn_initial_population(self) -> None:
        """Spawn initial population at simulation start."""
        logger.info(
            "spawning_initial_population",
            target_count=self.settings.min_population,
        )

        for _ in range(self.settings.min_population):
            x = random.uniform(0, self.settings.world_width)
            y = random.uniform(0, self.settings.world_height)

            # Randomize starting energy so entities don't all die at the same tick.
            # This staggers deaths and makes the population graph show real movement.
            initial_energy = random.uniform(50.0, 100.0)

            entity = self.entity_manager.spawn(
                x=x,
                y=y,
                traits=[],
                generation=0,
                tick=self.tick_counter,
                initial_energy=initial_energy,
            )
            entity._environment = self.environment
            entity._entity_manager = self.entity_manager

    async def _broadcast_world_state(self) -> None:
        """Broadcast current world state to all WebSocket clients.

        Uses binary protocol for efficient transmission:
        - Header: tick (uint32) + entity_count (uint16)
        - Body: entity data (ID, X, Y, radius, color) - 20 bytes each

        This is called every 2 ticks to achieve 30 FPS streaming.
        """
        # Avoid circular import
        from backend.api.ws_handler import build_world_frame

        entities = self.entity_manager.alive()
        resources = self.environment.get_all_resources()

        # Build binary frame
        frame = build_world_frame(self.tick_counter, entities, resources)

        # Broadcast to all connected clients
        if self.ws_manager:
            await self.ws_manager.broadcast_bytes(frame)

    async def _save_checkpoint_async(self) -> None:
        """Persist a world checkpoint to PostgreSQL without blocking the tick loop."""
        from backend.db.repository import save_checkpoint

        try:
            entities = self.entity_manager.alive()
            avg_energy = 0.0
            if entities:
                avg_energy = sum(e.energy for e in entities) / len(entities)

            params = {
                "tick_rate_ms": self.settings.tick_rate_ms,
                "max_entities": self.settings.max_entities,
                "min_population": self.settings.min_population,
                "world_width": self.settings.world_width,
                "world_height": self.settings.world_height,
            }

            await save_checkpoint(
                pool=self._db_pool,
                tick=self.tick_counter,
                params=params,
                entities=entities,
                avg_energy=avg_energy,
                resource_count=self.environment.count(),
            )
        except Exception as exc:
            logger.warning("checkpoint_save_failed", tick=self.tick_counter, error=str(exc))

    def _on_trait_error(self, entity_id: str, trait_name: str, error_str: str) -> None:
        """Sync callback invoked by TraitExecutor on first error for a trait.

        Deduplicates by trait_name and schedules an async feed message.
        """
        if trait_name in self._reported_trait_errors:
            return
        self._reported_trait_errors.add(trait_name)
        asyncio.create_task(self._publish_trait_error_to_feed(entity_id, trait_name, error_str))

    async def _publish_trait_error_to_feed(
        self, entity_id: str, trait_name: str, error_str: str
    ) -> None:
        """Publish a trait runtime error to the evolution feed."""
        import json
        from dataclasses import asdict

        error_short = error_str[:200]
        msg = FeedMessage(
            agent="engine",
            action="trait_error",
            message=f"❌ Трейт {trait_name} упал: {error_short}",
            metadata={
                "trait_name": trait_name,
                "error": error_str,
                "entity_id": entity_id,
            },
        )
        try:
            payload = json.dumps(asdict(msg), default=str)
            await self.redis.publish(Channels.FEED, payload)
        except Exception as exc:
            logger.warning("trait_error_feed_publish_failed", error=str(exc))

    async def _handle_predators(self) -> None:
        """Spawn and update predators as population autoregulators.

        - Spawns a new predator when molbots exceed predator_spawn_threshold
          and predator count is below max_predators.
        - Each predator hunts the nearest molbot, moves toward it, and kills
          it on contact (gaining energy).
        """
        all_alive = self.entity_manager.alive()
        molbots = [e for e in all_alive if e.entity_type == "molbot"]
        predators = [e for e in all_alive if e.entity_type == "predator"]

        molbot_count = len(molbots)
        predator_count = len(predators)

        # Spawn a new predator if population is high enough
        if (
            molbot_count > self.settings.predator_spawn_threshold
            and predator_count < self.settings.max_predators
        ):
            px = random.uniform(0, self.settings.world_width)
            py = random.uniform(0, self.settings.world_height)
            predator = self.entity_manager.spawn_predator(px, py, tick=self.tick_counter)
            predator._environment = self.environment
            logger.info(
                "predator_spawned",
                tick=self.tick_counter,
                total_molbots=molbot_count,
                total_predators=predator_count + 1,
            )

        # Each predator hunts the nearest molbot
        for predator in predators:
            nearby = self.entity_manager.nearby_entities(predator.x, predator.y, 200.0)
            targets = [e for e in nearby if e.entity_type == "molbot" and e.is_alive()]

            if not targets:
                continue

            # Find nearest molbot
            target = min(
                targets,
                key=lambda m: (m.x - predator.x) ** 2 + (m.y - predator.y) ** 2,
            )

            dx = target.x - predator.x
            dy = target.y - predator.y
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > 0:
                # Move toward target (capped by _MAX_MOVE_PER_TICK inside move())
                speed = 20.0
                predator.move(dx / dist * speed, dy / dist * speed)

            # Kill on contact
            if dist < (predator.radius + target.radius):
                target.state = "dead"
                predator.energy = min(predator.energy + 80.0, predator.max_energy)
                self._predator_kill_count += 1

    async def _handle_virus(self) -> None:
        """Spread a virus through the molbot population as an autoregulator.

        - Triggers when molbot count exceeds virus_spawn_threshold (random chance).
        - Infected entities: extra energy drain, spread to neighbors each tick.
        - Clears automatically when no infected entities remain.
        """
        molbots = [e for e in self.entity_manager.alive() if e.entity_type == "molbot"]
        molbot_count = len(molbots)

        if not self._virus_active:
            # Try to trigger virus outbreak
            if (
                molbot_count > self.settings.virus_spawn_threshold
                and random.random() < 0.001
            ):
                # Pick a random molbot as patient zero
                patient_zero = random.choice(molbots)
                patient_zero.infected = True
                patient_zero.infection_timer = self.settings.virus_duration_ticks
                self._virus_active = True
                self._virus_ticks_remaining = self.settings.virus_duration_ticks
                logger.info("virus_started", tick=self.tick_counter, patient_zero=patient_zero.id)
                asyncio.create_task(self._publish_virus_start_feed())
            return

        # Virus is active — spread and tick down
        infected = [e for e in molbots if e.infected]

        for entity in infected:
            # Spread to nearby molbots
            neighbors = self.entity_manager.nearby_entities(entity.x, entity.y, 40.0)
            for neighbor in neighbors:
                if neighbor.entity_type == "molbot" and not neighbor.infected and neighbor.is_alive():
                    if random.random() < 0.25:
                        neighbor.infected = True
                        neighbor.infection_timer = self.settings.virus_duration_ticks

            # Tick down infection timer
            entity.infection_timer -= 1
            if entity.infection_timer <= 0:
                entity.infected = False
                entity.infection_timer = 0

        # Check if virus is over
        still_infected = [e for e in molbots if e.infected]
        if not still_infected:
            self._virus_active = False
            logger.info("virus_ended", tick=self.tick_counter)
            asyncio.create_task(self._publish_virus_end_feed())

    async def _publish_virus_start_feed(self) -> None:
        """Publish virus outbreak start to the evolution feed."""
        import json
        from dataclasses import asdict

        msg = FeedMessage(
            agent="engine",
            action="virus_start",
            message="🦠 Вирус начался",
            metadata={"tick": self.tick_counter},
        )
        try:
            payload = json.dumps(asdict(msg), default=str)
            await self.redis.publish(Channels.FEED, payload)
        except Exception as exc:
            logger.warning("virus_feed_publish_failed", error=str(exc))

    async def _publish_virus_end_feed(self) -> None:
        """Publish virus extinction to the evolution feed."""
        import json
        from dataclasses import asdict

        msg = FeedMessage(
            agent="engine",
            action="virus_end",
            message="🦠 Вирус погас",
            metadata={"tick": self.tick_counter},
        )
        try:
            payload = json.dumps(asdict(msg), default=str)
            await self.redis.publish(Channels.FEED, payload)
        except Exception as exc:
            logger.warning("virus_feed_publish_failed", error=str(exc))

    def stop(self) -> None:
        """Stop the simulation loop gracefully.

        Sets the running flag to False, which will cause the loop
        to exit on the next iteration.
        """
        logger.info("engine_stopping", tick=self.tick_counter)
        self.running = False
