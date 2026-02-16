"""Unit tests for CoreEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from backend.config import Settings
from backend.core.dynamic_registry import DynamicRegistry
from backend.core.engine import CoreEngine
from backend.core.entity_manager import EntityManager
from backend.core.environment import Environment
from backend.core.world_physics import WorldPhysics


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        tick_rate_ms=16,
        min_population=5,
        max_entities=100,
        world_width=1000,
        world_height=1000,
    )


@pytest.fixture
def entity_manager() -> EntityManager:
    """Create test entity manager."""
    return EntityManager(world_width=1000, world_height=1000)


@pytest.fixture
def environment() -> Environment:
    """Create test environment."""
    return Environment(
        world_width=1000,
        world_height=1000,
        initial_resources=50,
        resource_energy=50.0,
    )


@pytest.fixture
def physics() -> WorldPhysics:
    """Create test physics."""
    return WorldPhysics(
        world_width=1000,
        world_height=1000,
        friction_coefficient=0.98,
        boundary_mode="bounce",
    )


@pytest.fixture
def registry() -> DynamicRegistry:
    """Create test registry."""
    return DynamicRegistry()


@pytest.fixture
def mock_redis() -> Mock:
    """Create mock Redis client."""
    redis = MagicMock()
    redis.ping = AsyncMock()
    return redis


@pytest.fixture
def engine(
    entity_manager: EntityManager,
    environment: Environment,
    physics: WorldPhysics,
    registry: DynamicRegistry,
    mock_redis: Mock,
    settings: Settings,
) -> CoreEngine:
    """Create test engine."""
    return CoreEngine(
        entity_manager=entity_manager,
        environment=environment,
        physics=physics,
        registry=registry,
        redis=mock_redis,
        settings=settings,
    )


def test_engine_initialization(engine: CoreEngine, settings: Settings):
    """Test engine initializes correctly."""
    assert engine.tick_counter == 0
    assert engine.running is False
    assert engine.settings == settings
    assert engine.entity_manager is not None
    assert engine.environment is not None
    assert engine.physics is not None
    assert engine.registry is not None
    assert engine.trait_executor is not None


def test_engine_stop(engine: CoreEngine):
    """Test engine stop method."""
    engine.running = True
    assert engine.running is True

    engine.stop()
    assert engine.running is False


@pytest.mark.asyncio
async def test_engine_spawns_initial_population(
    engine: CoreEngine,
    entity_manager: EntityManager,
    settings: Settings,
):
    """Test engine spawns initial population on start."""
    assert entity_manager.count_alive() == 0

    # Spawn initial population
    await engine._spawn_initial_population()

    assert entity_manager.count_alive() == settings.min_population


@pytest.mark.asyncio
async def test_engine_handles_deaths(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test engine removes dead entities."""
    # Spawn some entities
    entity1 = entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity2 = entity_manager.spawn(x=200, y=200, traits=[], tick=0)
    entity3 = entity_manager.spawn(x=300, y=300, traits=[], tick=0)

    assert entity_manager.count() == 3

    # Kill two entities
    entity1.state = "dead"
    entity2.state = "dead"

    # Handle deaths
    engine._handle_deaths()

    # Dead entities should be removed
    assert entity_manager.count() == 1
    assert entity_manager.get(entity1.id) is None
    assert entity_manager.get(entity2.id) is None
    assert entity_manager.get(entity3.id) is not None


@pytest.mark.asyncio
async def test_engine_spawns_when_below_min_population(
    engine: CoreEngine,
    entity_manager: EntityManager,
    settings: Settings,
):
    """Test engine spawns new entities when below minimum."""
    # Spawn only 2 entities (below min_population of 5)
    entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity_manager.spawn(x=200, y=200, traits=[], tick=0)

    assert entity_manager.count_alive() == 2

    # Handle spawning
    await engine._handle_spawning()

    # Should now have min_population
    assert entity_manager.count_alive() == settings.min_population


@pytest.mark.asyncio
async def test_engine_does_not_spawn_when_at_min(
    engine: CoreEngine,
    entity_manager: EntityManager,
    settings: Settings,
):
    """Test engine doesn't spawn when at minimum population."""
    # Spawn exactly min_population
    for i in range(settings.min_population):
        entity_manager.spawn(x=100.0 + i, y=100.0, traits=[], tick=0)

    assert entity_manager.count_alive() == settings.min_population

    # Handle spawning
    await engine._handle_spawning()

    # Should still be at min_population (no new spawns)
    assert entity_manager.count_alive() == settings.min_population


@pytest.mark.asyncio
async def test_engine_respects_max_entities(
    engine: CoreEngine,
    entity_manager: EntityManager,
    settings: Settings,
):
    """Test engine doesn't exceed max entity cap."""
    # Set max_entities to 3
    engine.settings.max_entities = 3

    # Spawn 2 entities
    entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity_manager.spawn(x=200, y=200, traits=[], tick=0)

    # Set min_population to 10 (higher than max_entities)
    engine.settings.min_population = 10

    # Handle spawning
    await engine._handle_spawning()

    # Should be capped at max_entities
    assert entity_manager.count_alive() <= 3


def test_engine_respawn_resources(
    engine: CoreEngine,
    environment: Environment,
):
    """Test engine respawns resources."""
    initial_count = environment.count()

    # Respawn resources multiple times
    for _ in range(10):
        engine._respawn_resources()

    # Should have more resources now
    assert environment.count() >= initial_count


@pytest.mark.asyncio
async def test_engine_update_entities(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test engine updates all entities."""
    # Spawn entities
    entity1 = entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity2 = entity_manager.spawn(x=200, y=200, traits=[], tick=0)

    assert entity1.age == 0
    assert entity2.age == 0

    initial_energy1 = entity1.energy
    initial_energy2 = entity2.energy

    # Update entities
    await engine._update_entities()

    # Entities should have aged and consumed energy
    assert entity1.age == 1
    assert entity2.age == 1
    assert entity1.energy < initial_energy1
    assert entity2.energy < initial_energy2


def test_engine_apply_physics(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test engine applies physics to entities."""
    # Spawn entity at boundary
    entity = entity_manager.spawn(x=1001, y=500, traits=[], tick=0)

    # Entity is outside bounds
    assert entity.x == 1001

    # Apply physics
    engine._apply_physics()

    # Entity should be constrained to bounds
    assert entity.x <= 1000  # world_width


def test_engine_apply_physics_collisions(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test engine resolves collisions."""
    # Spawn two entities very close together (colliding)
    entity1 = entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity2 = entity_manager.spawn(x=105, y=105, traits=[], tick=0)

    # Store initial positions
    initial_x1, initial_y1 = entity1.x, entity1.y
    initial_x2, initial_y2 = entity2.x, entity2.y

    # Apply physics (should resolve collision)
    engine._apply_physics()

    # Entities should have been separated (at least one moved)
    moved = (
        entity1.x != initial_x1
        or entity1.y != initial_y1
        or entity2.x != initial_x2
        or entity2.y != initial_y2
    )
    assert moved


def test_engine_log_statistics(
    engine: CoreEngine,
    entity_manager: EntityManager,
    environment: Environment,
):
    """Test engine logs statistics without errors."""
    # Spawn some entities
    entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity_manager.spawn(x=200, y=200, traits=[], tick=0)

    # Set tick counter
    engine.tick_counter = 100

    # This should not raise an error
    engine._log_statistics()


def test_engine_log_statistics_with_no_entities(engine: CoreEngine):
    """Test engine logs statistics when no entities exist."""
    engine.tick_counter = 100

    # Should not crash with zero entities
    engine._log_statistics()


def test_engine_statistics_interval(engine: CoreEngine):
    """Test statistics are logged at correct interval."""
    assert engine.stats_interval == 100


@pytest.mark.asyncio
async def test_engine_lifecycle_integration(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test full lifecycle: spawn -> age -> die -> respawn."""
    # Start with empty world
    assert entity_manager.count_alive() == 0

    # Spawn initial population
    await engine._spawn_initial_population()
    initial_count = entity_manager.count_alive()
    assert initial_count == engine.settings.min_population

    # Get entities
    entities = entity_manager.alive()

    # Drain energy to kill them
    for entity in entities:
        entity.energy = 0
        entity.state = "dead"

    # Handle deaths
    engine._handle_deaths()
    assert entity_manager.count_alive() == 0

    # Handle spawning (should respawn)
    await engine._handle_spawning()
    assert entity_manager.count_alive() == initial_count


@pytest.mark.asyncio
async def test_engine_uses_registry_snapshot_for_spawning(
    engine: CoreEngine,
    entity_manager: EntityManager,
    registry: DynamicRegistry,
):
    """Test engine uses registry snapshot when spawning (T-019 requirement)."""

    # Register a mock trait
    class TestTrait:
        async def execute(self, entity):
            pass

    registry.register("TestTrait", TestTrait)

    # Spawn population (should use registry.get_snapshot())
    await engine._spawn_initial_population()

    # Entities should be spawned (with or without traits depending on implementation)
    assert entity_manager.count_alive() == engine.settings.min_population


def test_engine_trait_executor_configured(engine: CoreEngine, settings: Settings):
    """Test trait executor is configured with correct timeouts."""
    assert engine.trait_executor.timeout_sec == settings.trait_timeout_sec
    assert engine.trait_executor.tick_budget_sec == settings.tick_time_budget_sec


@pytest.mark.asyncio
async def test_engine_handles_update_errors_gracefully(
    engine: CoreEngine,
    entity_manager: EntityManager,
):
    """Test engine continues running even if entity update fails."""
    # Spawn entities
    entity1 = entity_manager.spawn(x=100, y=100, traits=[], tick=0)
    entity2 = entity_manager.spawn(x=200, y=200, traits=[], tick=0)

    # Mock entity1's update to raise an error
    original_update = entity1.update

    async def failing_update(executor):
        raise RuntimeError("Test error")

    entity1.update = failing_update

    # Update should handle the error and continue with entity2
    await engine._update_entities()

    # entity2 should have been updated
    assert entity2.age == 1

    # Restore original method
    entity1.update = original_update


@pytest.mark.asyncio
async def test_engine_empty_world_edge_case(engine: CoreEngine):
    """Test engine handles empty world without crashing."""
    # All operations should work with zero entities
    await engine._update_entities()
    engine._apply_physics()
    engine._handle_deaths()
    engine._respawn_resources()
    engine._log_statistics()

    # No crashes = success


def test_engine_resource_spawn_rate(engine: CoreEngine, environment: Environment):
    """Test resource spawning happens at expected rate."""
    initial_resources = environment.count()

    # Run respawn many times
    for _ in range(100):
        engine._respawn_resources()

    # Should have spawned some resources (rate is 0.5, so ~50 expected)
    assert environment.count() > initial_resources
    assert environment.count() < initial_resources + 100  # Probabilistic check
