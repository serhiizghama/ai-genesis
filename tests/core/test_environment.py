"""Unit tests for Environment and Resource management."""

from __future__ import annotations

import pytest

from backend.core.entity import BaseEntity
from backend.core.environment import Environment, Resource


def create_test_entity(x: float, y: float) -> BaseEntity:
    """Helper to create a test entity.

    Args:
        x: X position.
        y: Y position.

    Returns:
        A test entity.
    """
    return BaseEntity(
        id="test-entity",
        x=x,
        y=y,
        energy=50.0,
        max_energy=100.0,
        radius=10.0,
        color="#ffffff",
        generation=0,
        dna_hash="test",
        parent_id=None,
        born_at_tick=0,
    )


def test_resource_creation():
    """Test creating a resource."""
    resource = Resource.create(x=100.0, y=200.0, amount=50.0)

    assert resource.id is not None
    assert resource.x == 100.0
    assert resource.y == 200.0
    assert resource.amount == 50.0
    assert resource.resource_type == "food"


def test_environment_initialization():
    """Test that environment initializes with resources."""
    env = Environment(world_width=2000, world_height=2000, initial_resources=50)

    assert env.world_width == 2000
    assert env.world_height == 2000
    assert env.count() == 50


def test_environment_initialization_zero_resources():
    """Test environment with no initial resources."""
    env = Environment(initial_resources=0)

    assert env.count() == 0


def test_respawn_resources_whole_number():
    """Test respawning resources with whole number rate."""
    env = Environment(initial_resources=0)

    spawned = env.respawn_resources(rate=5.0)

    assert spawned == 5
    assert env.count() == 5


def test_respawn_resources_fractional():
    """Test respawning resources with fractional rate.

    Note: This is probabilistic, so we test over multiple iterations.
    """
    env = Environment(initial_resources=0)

    # Spawn with rate 0.5 many times
    total_spawned = 0
    iterations = 100

    for _ in range(iterations):
        spawned = env.respawn_resources(rate=0.5)
        total_spawned += spawned

    # With rate=0.5 over 100 iterations, expect ~50 resources
    # Allow 20% margin for randomness
    assert 40 <= total_spawned <= 60
    assert env.count() == total_spawned


def test_respawn_resources_zero_rate():
    """Test that zero spawn rate spawns nothing."""
    env = Environment(initial_resources=10)

    initial_count = env.count()
    spawned = env.respawn_resources(rate=0.0)

    assert spawned == 0
    assert env.count() == initial_count


def test_nearby_resources_simple():
    """Test finding nearby resources."""
    env = Environment(initial_resources=0)

    # Manually add resources at known positions
    r1 = Resource.create(x=100.0, y=100.0, amount=50.0)
    r2 = Resource.create(x=110.0, y=110.0, amount=50.0)
    r3 = Resource.create(x=500.0, y=500.0, amount=50.0)

    env._resources[r1.id] = r1
    env._resources[r2.id] = r2
    env._resources[r3.id] = r3

    # Rebuild grid after manual insertion
    env.rebuild_spatial_grid()

    # Search near (100, 100) with radius 20
    nearby = env.nearby_resources(100.0, 100.0, radius=20.0)

    # Should find r1 and r2, but not r3
    nearby_ids = {r.id for r in nearby}
    assert r1.id in nearby_ids
    assert r2.id in nearby_ids
    assert r3.id not in nearby_ids


def test_nearby_resources_radius_boundary():
    """Test resources exactly at radius boundary."""
    env = Environment(initial_resources=0)

    center_x, center_y = 100.0, 100.0
    radius = 50.0

    # Resource exactly at radius distance
    at_boundary = Resource.create(
        x=center_x + radius,
        y=center_y,
        amount=50.0,
    )

    # Resource just inside radius
    inside = Resource.create(
        x=center_x + radius - 1,
        y=center_y,
        amount=50.0,
    )

    # Resource just outside radius
    outside = Resource.create(
        x=center_x + radius + 1,
        y=center_y,
        amount=50.0,
    )

    env._resources[at_boundary.id] = at_boundary
    env._resources[inside.id] = inside
    env._resources[outside.id] = outside

    env.rebuild_spatial_grid()
    nearby = env.nearby_resources(center_x, center_y, radius)
    nearby_ids = {r.id for r in nearby}

    # Resources at or inside boundary should be included
    assert at_boundary.id in nearby_ids
    assert inside.id in nearby_ids
    assert outside.id not in nearby_ids


def test_nearby_resources_empty():
    """Test nearby_resources when no resources are in range."""
    env = Environment(initial_resources=0)

    # Add resource far away
    env._resources["far"] = Resource.create(x=1000.0, y=1000.0, amount=50.0)
    env.rebuild_spatial_grid()

    # Search near origin
    nearby = env.nearby_resources(0.0, 0.0, radius=50.0)

    assert len(nearby) == 0


def test_consume_resource():
    """Test entity consuming a resource."""
    env = Environment(initial_resources=0)

    # Create resource
    resource = Resource.create(x=100.0, y=100.0, amount=30.0)
    env._resources[resource.id] = resource
    env._add_to_spatial_grid(resource)

    # Create entity with low energy
    entity = create_test_entity(x=100.0, y=100.0)
    entity.energy = 50.0

    initial_energy = entity.energy
    initial_count = env.count()

    # Consume resource
    result = env.consume_resource(entity, resource)

    assert result is True
    assert entity.energy == initial_energy + 30.0
    assert env.count() == initial_count - 1
    assert resource.id not in env._resources


def test_consume_resource_caps_at_max():
    """Test that consuming resource doesn't exceed max_energy."""
    env = Environment(initial_resources=0)

    # Create resource with lots of energy
    resource = Resource.create(x=100.0, y=100.0, amount=100.0)
    env._resources[resource.id] = resource
    env._add_to_spatial_grid(resource)

    # Create entity already at high energy
    entity = create_test_entity(x=100.0, y=100.0)
    entity.energy = 90.0
    entity.max_energy = 100.0

    # Consume resource
    env.consume_resource(entity, resource)

    # Energy should be capped at max_energy
    assert entity.energy == 100.0


def test_consume_resource_nonexistent():
    """Test consuming a resource that doesn't exist."""
    env = Environment(initial_resources=0)

    # Create fake resource that's not in environment
    fake_resource = Resource.create(x=100.0, y=100.0, amount=50.0)

    entity = create_test_entity(x=100.0, y=100.0)
    initial_energy = entity.energy

    # Try to consume
    result = env.consume_resource(entity, fake_resource)

    assert result is False
    assert entity.energy == initial_energy  # Energy unchanged


def test_resource_density():
    """Test calculating resource density."""
    env = Environment(initial_resources=0)

    # Add 10 resources in a small area
    for i in range(10):
        resource = Resource.create(x=100.0 + i, y=100.0 + i, amount=50.0)
        env._resources[resource.id] = resource

    env.rebuild_spatial_grid()

    # Calculate density near (100, 100)
    density = env.resource_density(100.0, 100.0, radius=50.0)

    # Should be non-zero
    assert density > 0


def test_resource_density_empty_area():
    """Test resource density in empty area."""
    env = Environment(initial_resources=0)

    density = env.resource_density(100.0, 100.0, radius=50.0)

    assert density == 0.0


def test_get_all_resources():
    """Test getting all resources."""
    env = Environment(initial_resources=20)

    all_resources = env.get_all_resources()

    assert len(all_resources) == 20
    assert all(isinstance(r, Resource) for r in all_resources)


def test_count():
    """Test counting resources."""
    env = Environment(initial_resources=15)

    assert env.count() == 15

    # Add more resources
    env.respawn_resources(rate=5.0)

    assert env.count() == 20


def test_clear():
    """Test clearing all resources."""
    env = Environment(initial_resources=50)

    assert env.count() == 50

    env.clear()

    assert env.count() == 0
    assert len(env._spatial_grid) == 0


def test_spatial_grid_integration():
    """Test that spatial grid is maintained correctly."""
    env = Environment(initial_resources=0)

    # Add resource
    resource = Resource.create(x=75.0, y=125.0, amount=50.0)
    env._resources[resource.id] = resource
    env._add_to_spatial_grid(resource)

    # Resource at (75, 125) should be in cell (1, 2)
    cell = env._get_cell_coords(75.0, 125.0)
    assert cell == (1, 2)
    assert resource.id in env._spatial_grid[cell]

    # Remove resource
    env._remove_from_spatial_grid(resource)

    # Cell should be empty or removed
    assert cell not in env._spatial_grid or resource.id not in env._spatial_grid[cell]


def test_rebuild_spatial_grid():
    """Test rebuilding the spatial grid."""
    env = Environment(initial_resources=0)

    # Add resources manually
    for i in range(10):
        resource = Resource.create(x=float(i * 100), y=float(i * 100), amount=50.0)
        env._resources[f"r{i}"] = resource

    # Rebuild grid
    env.rebuild_spatial_grid()

    # All resources should be in the grid
    total_in_grid = sum(len(cell_set) for cell_set in env._spatial_grid.values())
    assert total_in_grid == 10


def test_random_distribution():
    """Test that spawned resources are distributed across the world."""
    env = Environment(initial_resources=100)

    resources = env.get_all_resources()

    # Check that resources are spread across different areas
    x_positions = [r.x for r in resources]
    y_positions = [r.y for r in resources]

    # Should have variety in positions (not all in same spot)
    assert len(set(int(x) for x in x_positions)) > 10
    assert len(set(int(y) for y in y_positions)) > 10

    # Should be within world bounds
    assert all(0 <= x <= 2000 for x in x_positions)
    assert all(0 <= y <= 2000 for y in y_positions)


def test_spatial_efficiency():
    """Test that spatial queries are efficient with many resources.

    This verifies that nearby_resources doesn't check ALL resources,
    but only those in relevant grid cells.
    """
    env = Environment(initial_resources=0)

    # Spawn 200 resources spread across the world
    for i in range(200):
        x = float((i * 100) % 2000)
        y = float((i * 50) % 2000)
        resource = Resource.create(x=x, y=y, amount=50.0)
        env._resources[f"r{i}"] = resource

    env.rebuild_spatial_grid()

    # Search in small area
    nearby = env.nearby_resources(100.0, 100.0, radius=30.0)

    # Should find only a few nearby resources, not all 200
    assert len(nearby) < 20


def test_multiple_consume_operations():
    """Test consuming multiple resources in sequence."""
    env = Environment(initial_resources=5)

    entity = create_test_entity(x=1000.0, y=1000.0)
    entity.energy = 10.0

    # Find and consume all nearby resources
    consumed_count = 0
    initial_count = env.count()

    for resource in env.nearby_resources(1000.0, 1000.0, radius=2000.0):
        if env.consume_resource(entity, resource):
            consumed_count += 1

    # Should have consumed some resources
    assert consumed_count <= initial_count
    assert env.count() == initial_count - consumed_count
    assert entity.energy > 10.0  # Gained energy


def test_resource_respawn_maintains_grid():
    """Test that respawning maintains spatial grid integrity."""
    env = Environment(initial_resources=0)

    # Spawn resources
    env.respawn_resources(rate=10.0)

    # Verify all resources are in the grid
    total_in_grid = sum(len(cell_set) for cell_set in env._spatial_grid.values())
    assert total_in_grid == env.count()

    # Spawn more
    env.respawn_resources(rate=5.0)

    # Grid should still be consistent
    total_in_grid = sum(len(cell_set) for cell_set in env._spatial_grid.values())
    assert total_in_grid == env.count()
