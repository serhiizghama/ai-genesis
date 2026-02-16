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

from backend.config import Settings
from backend.core.dynamic_registry import DynamicRegistry
from backend.core.entity_manager import EntityManager
from backend.core.environment import Environment
from backend.core.traits import TraitExecutor
from backend.core.world_physics import WorldPhysics

if TYPE_CHECKING:
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

        # Create trait executor with configured timeouts
        self.trait_executor = TraitExecutor(
            timeout_sec=settings.trait_timeout_sec,
            tick_budget_sec=settings.tick_time_budget_sec,
        )

        # Tick counter
        self.tick_counter = 0

        # Statistics tracking
        self.stats_interval = 100  # Log stats every 100 ticks
        self.running = False

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
                await self._handle_spawning()
                self._respawn_resources()

                # T-020: Statistics and logging
                if self.tick_counter % self.stats_interval == 0:
                    self._log_statistics()

                # T-029: Broadcast world state every 2 ticks (30 FPS)
                if self.ws_manager and self.tick_counter % 2 == 0:
                    await self._broadcast_world_state()

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
        """
        entities = self.entity_manager.get_all_entities()
        dead_entities = [e for e in entities if not e.is_alive()]

        for entity in dead_entities:
            self.entity_manager.remove(entity)

        if dead_entities:
            logger.info(
                "entities_died",
                tick=self.tick_counter,
                count=len(dead_entities),
            )

    async def _handle_spawning(self) -> None:
        """Spawn new entities if population is below minimum.

        Uses DynamicRegistry.get_snapshot() to get available traits
        for new entities.
        """
        current_count = self.entity_manager.count_alive()

        if current_count < self.settings.min_population:
            needed = self.settings.min_population - current_count
            spawned = 0

            for _ in range(needed):
                # Don't exceed max entities
                if self.entity_manager.count_alive() >= self.settings.max_entities:
                    break

                # Spawn entity at random position
                x = random.uniform(0, self.settings.world_width)
                y = random.uniform(0, self.settings.world_height)

                # Get available traits from registry
                trait_snapshot = self.registry.get_snapshot()
                traits = []

                # For MVP: spawn entities with no traits
                # In future phases, entities will be spawned with random traits
                # from the registry or inherited from parents
                if trait_snapshot:
                    # Could add logic to randomly select traits here
                    pass

                self.entity_manager.spawn(
                    x=x,
                    y=y,
                    traits=traits,
                    generation=0,
                    tick=self.tick_counter,
                )
                spawned += 1

            if spawned > 0:
                logger.info(
                    "entities_spawned",
                    tick=self.tick_counter,
                    count=spawned,
                    reason="min_population",
                )

    def _respawn_resources(self) -> None:
        """Respawn resources in the environment.

        Uses a fixed spawn rate for MVP. In future phases, this could
        be dynamic based on consumption rates or world conditions.
        """
        # Spawn 1 resource every 2 ticks (rate = 0.5)
        spawn_rate = 0.5
        self.environment.respawn_resources(spawn_rate)

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

        # TODO: Send telemetry to event bus for Watcher agent
        # await self.redis.publish(
        #     Channels.TELEMETRY,
        #     TelemetryEvent(
        #         tick=self.tick_counter,
        #         entity_count=entity_count,
        #         avg_energy=avg_energy,
        #         resource_count=resource_count,
        #     )
        # )

    async def _spawn_initial_population(self) -> None:
        """Spawn initial population at simulation start."""
        logger.info(
            "spawning_initial_population",
            target_count=self.settings.min_population,
        )

        for _ in range(self.settings.min_population):
            x = random.uniform(0, self.settings.world_width)
            y = random.uniform(0, self.settings.world_height)

            self.entity_manager.spawn(
                x=x,
                y=y,
                traits=[],
                generation=0,
                tick=self.tick_counter,
            )

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

        # Build binary frame
        frame = build_world_frame(self.tick_counter, entities)

        # Broadcast to all connected clients
        if self.ws_manager:
            await self.ws_manager.broadcast_bytes(frame)

    def stop(self) -> None:
        """Stop the simulation loop gracefully.

        Sets the running flag to False, which will cause the loop
        to exit on the next iteration.
        """
        logger.info("engine_stopping", tick=self.tick_counter)
        self.running = False
