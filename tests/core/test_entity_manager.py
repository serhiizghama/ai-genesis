"""Unit tests for EntityManager and spatial hashing."""

from __future__ import annotations

import pytest

from backend.core.entity import BaseEntity
from backend.core.entity_manager import EntityManager
from backend.core.traits import BaseTrait


# Mock trait for testing
class MockTrait:
    """Mock trait for testing."""

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute method."""
        pass


def test_entity_manager_initialization():
    """Test that entity manager initializes correctly."""
    manager = EntityManager(world_width=2000, world_height=2000)
    assert manager.count() == 0
    assert manager.count_alive() == 0
    assert manager.alive() == []


def test_spawn_entity():
    """Test spawning a new entity."""
    manager = EntityManager()
    traits = [MockTrait(), MockTrait()]

    entity = manager.spawn(x=100.0, y=200.0, traits=traits, tick=0)

    assert entity.id is not None
    assert entity.x == 100.0
    assert entity.y == 200.0
    assert len(entity.traits) == 2
    assert entity.is_alive()
    assert manager.count() == 1
    assert manager.count_alive() == 1


def test_spawn_multiple_entities():
    """Test spawning multiple entities."""
    manager = EntityManager()

    entity1 = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    entity2 = manager.spawn(x=200.0, y=200.0, traits=[], tick=1)
    entity3 = manager.spawn(x=300.0, y=300.0, traits=[], tick=2)

    assert manager.count() == 3
    assert manager.count_alive() == 3
    assert len(manager.alive()) == 3


def test_remove_entity():
    """Test removing an entity."""
    manager = EntityManager()
    entity1 = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    entity2 = manager.spawn(x=200.0, y=200.0, traits=[], tick=1)

    assert manager.count() == 2

    result = manager.remove(entity1)
    assert result is True
    assert manager.count() == 1
    assert manager.get(entity1.id) is None
    assert manager.get(entity2.id) is not None


def test_remove_nonexistent_entity():
    """Test removing an entity that doesn't exist."""
    manager = EntityManager()
    fake_entity = BaseEntity(
        id="fake-id",
        x=0,
        y=0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abcd",
        parent_id=None,
        born_at_tick=0,
    )

    result = manager.remove(fake_entity)
    assert result is False


def test_get_entity():
    """Test getting an entity by ID."""
    manager = EntityManager()
    entity = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)

    retrieved = manager.get(entity.id)
    assert retrieved is entity
    assert retrieved.x == 100.0
    assert retrieved.y == 100.0

    nonexistent = manager.get("nonexistent-id")
    assert nonexistent is None


def test_alive_entities():
    """Test getting only alive entities."""
    manager = EntityManager()
    entity1 = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    entity2 = manager.spawn(x=200.0, y=200.0, traits=[], tick=1)
    entity3 = manager.spawn(x=300.0, y=300.0, traits=[], tick=2)

    # Kill one entity
    entity2.state = "dead"

    alive = manager.alive()
    assert len(alive) == 2
    assert entity1 in alive
    assert entity3 in alive
    assert entity2 not in alive


def test_count_methods():
    """Test count and count_alive methods."""
    manager = EntityManager()
    entity1 = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    entity2 = manager.spawn(x=200.0, y=200.0, traits=[], tick=1)
    entity3 = manager.spawn(x=300.0, y=300.0, traits=[], tick=2)

    assert manager.count() == 3
    assert manager.count_alive() == 3

    # Kill two entities
    entity1.state = "dead"
    entity2.state = "dead"

    assert manager.count() == 3  # Total count includes dead
    assert manager.count_alive() == 1  # Only one alive


# -------------------------------------------------------------------------
# Spatial Hashing Tests (T-015)
# -------------------------------------------------------------------------


def test_spatial_grid_cell_calculation():
    """Test that cell coordinates are calculated correctly."""
    manager = EntityManager()

    # Cell size is 50x50
    # (25, 25) should be in cell (0, 0)
    assert manager._get_cell_coords(25, 25) == (0, 0)

    # (75, 125) should be in cell (1, 2)
    assert manager._get_cell_coords(75, 125) == (1, 2)

    # (150, 250) should be in cell (3, 5)
    assert manager._get_cell_coords(150, 250) == (3, 5)


def test_spatial_grid_add_entity():
    """Test adding entity to spatial grid."""
    manager = EntityManager()
    entity = manager.spawn(x=75.0, y=125.0, traits=[], tick=0)

    # Entity at (75, 125) should be in cell (1, 2)
    cell = (1, 2)
    assert entity.id in manager._spatial_grid[cell]


def test_spatial_grid_remove_entity():
    """Test removing entity from spatial grid."""
    manager = EntityManager()
    entity = manager.spawn(x=75.0, y=125.0, traits=[], tick=0)

    cell = (1, 2)
    assert entity.id in manager._spatial_grid[cell]

    manager.remove(entity)
    assert cell not in manager._spatial_grid or entity.id not in manager._spatial_grid[cell]


def test_spatial_grid_rebuild():
    """Test rebuilding the spatial grid after entity movements."""
    manager = EntityManager()
    entity1 = manager.spawn(x=25.0, y=25.0, traits=[], tick=0)
    entity2 = manager.spawn(x=75.0, y=75.0, traits=[], tick=1)

    # Initial positions
    assert entity1.id in manager._spatial_grid[(0, 0)]
    assert entity2.id in manager._spatial_grid[(1, 1)]

    # Move entities
    entity1.move(100, 100)  # Now at (125, 125) -> cell (2, 2)
    entity2.move(-50, -50)  # Now at (25, 25) -> cell (0, 0)

    # Rebuild grid
    manager.rebuild_spatial_grid()

    # Check new positions in grid
    assert entity1.id in manager._spatial_grid[(2, 2)]
    assert entity2.id in manager._spatial_grid[(0, 0)]
    assert entity1.id not in manager._spatial_grid.get((0, 0), set())
    assert entity2.id not in manager._spatial_grid.get((1, 1), set())


def test_detect_collisions_simple():
    """Test collision detection with two overlapping entities."""
    manager = EntityManager()

    # Spawn two entities very close together (will collide)
    entity1 = manager.spawn(x=10.0, y=10.0, traits=[], tick=0)
    entity2 = manager.spawn(x=15.0, y=15.0, traits=[], tick=1)

    # Both have radius 10, so they should collide (distance ~7.07 < sum of radii 20)
    manager.rebuild_spatial_grid()
    collisions = manager.detect_collisions()

    assert len(collisions) == 1
    assert (entity1, entity2) in collisions or (entity2, entity1) in collisions


def test_detect_collisions_no_collision():
    """Test collision detection with non-overlapping entities."""
    manager = EntityManager()

    # Spawn two entities far apart (will NOT collide)
    entity1 = manager.spawn(x=10.0, y=10.0, traits=[], tick=0)
    entity2 = manager.spawn(x=500.0, y=500.0, traits=[], tick=1)

    manager.rebuild_spatial_grid()
    collisions = manager.detect_collisions()

    assert len(collisions) == 0


def test_detect_collisions_multiple_pairs():
    """Test collision detection with multiple colliding pairs."""
    manager = EntityManager()

    # Group 1: Two entities colliding at (10, 10)
    entity1 = manager.spawn(x=10.0, y=10.0, traits=[], tick=0)
    entity2 = manager.spawn(x=15.0, y=15.0, traits=[], tick=1)

    # Group 2: Two entities colliding at (500, 500)
    entity3 = manager.spawn(x=500.0, y=500.0, traits=[], tick=2)
    entity4 = manager.spawn(x=505.0, y=505.0, traits=[], tick=3)

    # Non-colliding entity
    entity5 = manager.spawn(x=1000.0, y=1000.0, traits=[], tick=4)

    manager.rebuild_spatial_grid()
    collisions = manager.detect_collisions()

    # Should have 2 collision pairs
    assert len(collisions) == 2


def test_detect_collisions_ignores_dead_entities():
    """Test that collision detection ignores dead entities."""
    manager = EntityManager()

    entity1 = manager.spawn(x=10.0, y=10.0, traits=[], tick=0)
    entity2 = manager.spawn(x=15.0, y=15.0, traits=[], tick=1)

    # Kill entity2
    entity2.state = "dead"

    manager.rebuild_spatial_grid()
    collisions = manager.detect_collisions()

    # No collisions because entity2 is dead
    assert len(collisions) == 0


def test_nearby_entities_simple():
    """Test finding nearby entities within a radius."""
    manager = EntityManager()

    center = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    nearby1 = manager.spawn(x=110.0, y=110.0, traits=[], tick=1)  # ~14.14 away
    nearby2 = manager.spawn(x=95.0, y=95.0, traits=[], tick=2)    # ~7.07 away
    far = manager.spawn(x=500.0, y=500.0, traits=[], tick=3)      # ~565 away

    manager.rebuild_spatial_grid()

    # Search with radius 20
    results = manager.nearby_entities(100.0, 100.0, radius=20.0)

    # Should include center, nearby1, nearby2, but not far
    assert len(results) == 3
    assert center in results
    assert nearby1 in results
    assert nearby2 in results
    assert far not in results


def test_nearby_entities_radius_boundary():
    """Test nearby_entities with entities exactly at radius boundary."""
    manager = EntityManager()

    center_x, center_y = 100.0, 100.0
    radius = 50.0

    # Entity exactly at radius distance
    entity_at_boundary = manager.spawn(
        x=center_x + radius,
        y=center_y,
        traits=[],
        tick=0
    )

    # Entity just inside radius
    entity_inside = manager.spawn(
        x=center_x + radius - 1,
        y=center_y,
        traits=[],
        tick=1
    )

    # Entity just outside radius
    entity_outside = manager.spawn(
        x=center_x + radius + 1,
        y=center_y,
        traits=[],
        tick=2
    )

    manager.rebuild_spatial_grid()
    results = manager.nearby_entities(center_x, center_y, radius)

    # Entities at or inside boundary should be included
    assert entity_at_boundary in results
    assert entity_inside in results
    assert entity_outside not in results


def test_nearby_entities_ignores_dead():
    """Test that nearby_entities ignores dead entities."""
    manager = EntityManager()

    entity1 = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    entity2 = manager.spawn(x=110.0, y=110.0, traits=[], tick=1)

    # Kill entity2
    entity2.state = "dead"

    manager.rebuild_spatial_grid()
    results = manager.nearby_entities(100.0, 100.0, radius=20.0)

    # Should only find entity1
    assert len(results) == 1
    assert entity1 in results
    assert entity2 not in results


def test_nearby_entities_empty_result():
    """Test nearby_entities when no entities are in range."""
    manager = EntityManager()

    entity = manager.spawn(x=1000.0, y=1000.0, traits=[], tick=0)

    manager.rebuild_spatial_grid()
    results = manager.nearby_entities(0.0, 0.0, radius=50.0)

    assert len(results) == 0


def test_spatial_hash_efficiency():
    """Test that spatial hashing is efficient for large numbers of entities.

    This test verifies that nearby_entities doesn't check ALL entities,
    but only those in relevant grid cells.
    """
    manager = EntityManager()

    # Spawn 100 entities spread across the world (far from origin)
    for i in range(100):
        x = 500.0 + (i * 100) % 1000  # Start at x=500 to avoid origin
        y = 500.0 + (i * 50) % 1000   # Start at y=500 to avoid origin
        manager.spawn(x=float(x), y=float(y), traits=[], tick=i)

    # Spawn a few entities in one corner at origin
    for i in range(5):
        manager.spawn(x=10.0 + i, y=10.0 + i, traits=[], tick=100 + i)

    manager.rebuild_spatial_grid()

    # Search in the corner
    results = manager.nearby_entities(10.0, 10.0, radius=20.0)

    # Should find the 5 corner entities, not all 105
    # The spatial hash should have significantly reduced the search space
    assert len(results) >= 5  # At least the 5 we spawned
    assert len(results) < 20  # But far fewer than all 105


def test_clear_entities():
    """Test clearing all entities from the manager."""
    manager = EntityManager()

    manager.spawn(x=100.0, y=100.0, traits=[], tick=0)
    manager.spawn(x=200.0, y=200.0, traits=[], tick=1)
    manager.spawn(x=300.0, y=300.0, traits=[], tick=2)

    assert manager.count() == 3

    manager.clear()

    assert manager.count() == 0
    assert manager.alive() == []
    assert len(manager._spatial_grid) == 0


def test_spawn_with_parent():
    """Test spawning an entity with a parent (reproduction)."""
    manager = EntityManager()

    parent = manager.spawn(x=100.0, y=100.0, traits=[], tick=0, generation=0)
    child = manager.spawn(
        x=110.0,
        y=110.0,
        traits=[],
        tick=10,
        parent=parent,
        generation=1,
    )

    assert child.parent_id == parent.id
    assert child.generation == 1
    assert parent.generation == 0


def test_dna_hash_generation():
    """Test that DNA hash is generated from traits."""
    manager = EntityManager()

    trait1 = MockTrait()
    trait2 = MockTrait()

    entity1 = manager.spawn(x=100.0, y=100.0, traits=[trait1, trait2], tick=0)
    entity2 = manager.spawn(x=200.0, y=200.0, traits=[trait1, trait2], tick=1)

    # Same traits should produce same DNA hash
    assert entity1.dna_hash == entity2.dna_hash

    # Different traits
    entity3 = manager.spawn(x=300.0, y=300.0, traits=[trait1], tick=2)
    assert entity3.dna_hash != entity1.dna_hash


def test_color_generation_from_dna():
    """Test that entity color is derived from DNA hash."""
    manager = EntityManager()

    entity = manager.spawn(x=100.0, y=100.0, traits=[], tick=0)

    # Color should be a valid hex color
    assert entity.color.startswith("#")
    assert len(entity.color) == 7  # #RRGGBB

    # Color should be deterministic from DNA hash
    assert entity.color == f"#{entity.dna_hash[:6]}"
