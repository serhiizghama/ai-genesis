"""Unit tests for WorldPhysics."""

from __future__ import annotations

import pytest

from backend.core.entity import BaseEntity
from backend.core.world_physics import WorldPhysics


def create_test_entity(x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> BaseEntity:
    """Helper to create a test entity with velocity.

    Args:
        x: X position.
        y: Y position.
        vx: X velocity.
        vy: Y velocity.

    Returns:
        A test entity with position and velocity.
    """
    entity = BaseEntity(
        id="test-entity",
        x=x,
        y=y,
        energy=100.0,
        max_energy=100.0,
        radius=10.0,
        color="#ffffff",
        generation=0,
        dna_hash="test",
        parent_id=None,
        born_at_tick=0,
    )
    # Add velocity attributes (not in base entity by default)
    entity.vx = vx  # type: ignore
    entity.vy = vy  # type: ignore
    return entity


def test_physics_initialization():
    """Test that WorldPhysics initializes with correct defaults."""
    physics = WorldPhysics(world_width=2000, world_height=2000)
    assert physics.world_width == 2000
    assert physics.world_height == 2000
    assert physics.friction_coefficient == 0.98
    assert physics.gravity == 0.0
    assert physics.boundary_mode == "bounce"


def test_apply_friction():
    """Test that friction slows down entities."""
    physics = WorldPhysics(friction_coefficient=0.9)
    entity = create_test_entity(x=100, y=100, vx=10.0, vy=5.0)

    physics.apply_friction(entity)

    # Velocity should be reduced by friction coefficient
    assert entity.vx == 9.0  # 10.0 * 0.9
    assert entity.vy == 4.5  # 5.0 * 0.9


def test_apply_friction_multiple_ticks():
    """Test friction over multiple ticks."""
    physics = WorldPhysics(friction_coefficient=0.9)
    entity = create_test_entity(x=100, y=100, vx=10.0, vy=10.0)

    # Apply friction 5 times
    for _ in range(5):
        physics.apply_friction(entity)

    # Velocity should decay exponentially
    expected = 10.0 * (0.9 ** 5)
    assert abs(entity.vx - expected) < 0.001
    assert abs(entity.vy - expected) < 0.001


def test_apply_friction_stops_at_low_velocity():
    """Test that friction stops entities completely at very low velocities."""
    physics = WorldPhysics(friction_coefficient=0.98)
    entity = create_test_entity(x=100, y=100, vx=0.005, vy=0.005)

    physics.apply_friction(entity)

    # Very small velocities should be set to zero
    assert entity.vx == 0.0
    assert entity.vy == 0.0


def test_apply_bounds_bounce_left():
    """Test entity bouncing off left wall."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="bounce")
    entity = create_test_entity(x=-5.0, y=100.0, vx=-5.0, vy=0.0)

    physics.apply_bounds(entity)

    # Entity should be pushed inside bounds
    assert entity.x == entity.radius  # At left edge
    assert entity.vx > 0  # Velocity should reverse (bounce right)


def test_apply_bounds_bounce_right():
    """Test entity bouncing off right wall."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="bounce")
    entity = create_test_entity(x=2005.0, y=100.0, vx=5.0, vy=0.0)

    physics.apply_bounds(entity)

    # Entity should be pushed inside bounds
    assert entity.x == 2000 - entity.radius  # At right edge
    assert entity.vx < 0  # Velocity should reverse (bounce left)


def test_apply_bounds_bounce_top():
    """Test entity bouncing off top wall."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="bounce")
    entity = create_test_entity(x=100.0, y=-5.0, vx=0.0, vy=-5.0)

    physics.apply_bounds(entity)

    # Entity should be pushed inside bounds
    assert entity.y == entity.radius  # At top edge
    assert entity.vy > 0  # Velocity should reverse (bounce down)


def test_apply_bounds_bounce_bottom():
    """Test entity bouncing off bottom wall."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="bounce")
    entity = create_test_entity(x=100.0, y=2005.0, vx=0.0, vy=5.0)

    physics.apply_bounds(entity)

    # Entity should be pushed inside bounds
    assert entity.y == 2000 - entity.radius  # At bottom edge
    assert entity.vy < 0  # Velocity should reverse (bounce up)


def test_apply_bounds_wrap_horizontal():
    """Test entity wrapping horizontally."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="wrap")

    # Test wrap from right to left
    entity = create_test_entity(x=2005.0, y=100.0)
    physics.apply_bounds(entity)
    assert entity.x == 0.0

    # Test wrap from left to right
    entity = create_test_entity(x=-5.0, y=100.0)
    physics.apply_bounds(entity)
    assert entity.x == 2000.0


def test_apply_bounds_wrap_vertical():
    """Test entity wrapping vertically."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="wrap")

    # Test wrap from bottom to top
    entity = create_test_entity(x=100.0, y=2005.0)
    physics.apply_bounds(entity)
    assert entity.y == 0.0

    # Test wrap from top to bottom
    entity = create_test_entity(x=100.0, y=-5.0)
    physics.apply_bounds(entity)
    assert entity.y == 2000.0


def test_resolve_collision_separation():
    """Test that colliding entities are separated."""
    physics = WorldPhysics()

    # Create two overlapping entities
    entity_a = create_test_entity(x=100.0, y=100.0)
    entity_b = create_test_entity(x=105.0, y=105.0)  # Only 7.07 pixels apart, radii=10 each

    # Record original positions
    orig_ax, orig_ay = entity_a.x, entity_a.y
    orig_bx, orig_by = entity_b.x, entity_b.y

    physics.resolve_collision(entity_a, entity_b)

    # Entities should be pushed apart
    assert entity_a.x != orig_ax or entity_a.y != orig_ay
    assert entity_b.x != orig_bx or entity_b.y != orig_by

    # Calculate new distance
    dx = entity_b.x - entity_a.x
    dy = entity_b.y - entity_a.y
    new_distance = (dx * dx + dy * dy) ** 0.5

    # Entities should no longer be overlapping
    assert new_distance >= entity_a.radius + entity_b.radius


def test_resolve_collision_velocity_reversal():
    """Test that collision reverses velocities (elastic collision)."""
    physics = WorldPhysics()

    # Create two entities overlapping and moving toward each other
    # Distance between centers: 10 pixels (both radius=10, so heavily overlapping)
    entity_a = create_test_entity(x=100.0, y=100.0, vx=5.0, vy=0.0)
    entity_b = create_test_entity(x=110.0, y=100.0, vx=-5.0, vy=0.0)

    # Record original velocities
    orig_vax = entity_a.vx
    orig_bvx = entity_b.vx

    physics.resolve_collision(entity_a, entity_b)

    # Entities should be separated (x positions changed significantly)
    assert entity_a.x < 95.0  # Pushed left
    assert entity_b.x > 115.0  # Pushed right

    # Velocities should have changed due to elastic collision
    # (the exact values depend on the impulse calculation)
    assert entity_a.vx != orig_vax or entity_b.vx != orig_bvx


def test_resolve_collision_no_overlap():
    """Test that non-overlapping entities are not affected."""
    physics = WorldPhysics()

    # Create two entities far apart
    entity_a = create_test_entity(x=100.0, y=100.0, vx=5.0, vy=0.0)
    entity_b = create_test_entity(x=500.0, y=500.0, vx=-5.0, vy=0.0)

    # Record original state
    orig_ax, orig_vax = entity_a.x, entity_a.vx
    orig_bx, orig_vbx = entity_b.x, entity_b.vx

    physics.resolve_collision(entity_a, entity_b)

    # Nothing should change
    assert entity_a.x == orig_ax
    assert entity_a.vx == orig_vax
    assert entity_b.x == orig_bx
    assert entity_b.vx == orig_vbx


def test_apply_gravity():
    """Test that gravity increases downward velocity."""
    physics = WorldPhysics(gravity=0.5)
    entity = create_test_entity(x=100.0, y=100.0, vx=0.0, vy=0.0)

    physics.apply_gravity(entity)

    # Velocity should increase downward
    assert entity.vy == 0.5


def test_apply_gravity_accumulates():
    """Test that gravity accumulates over time."""
    physics = WorldPhysics(gravity=0.5)
    entity = create_test_entity(x=100.0, y=100.0, vx=0.0, vy=0.0)

    # Apply gravity 5 times
    for _ in range(5):
        physics.apply_gravity(entity)

    # Velocity should accumulate
    assert entity.vy == 2.5  # 0.5 * 5


def test_apply_all_physics():
    """Test applying all physics effects together."""
    physics = WorldPhysics(
        world_width=2000,
        world_height=2000,
        friction_coefficient=0.9,
        gravity=0.1,
        boundary_mode="bounce",
    )

    entity = create_test_entity(x=100.0, y=100.0, vx=10.0, vy=5.0)

    physics.apply_all_physics(
        entity,
        apply_friction=True,
        apply_gravity=True,
        apply_bounds=True,
    )

    # Friction should reduce horizontal velocity
    assert entity.vx == 9.0  # 10.0 * 0.9

    # Gravity should increase vertical velocity, then friction applied
    # vy = (5.0 + 0.1) * 0.9 = 4.59
    assert abs(entity.vy - 4.59) < 0.001

    # Entity should still be in bounds
    assert 0 <= entity.x <= 2000
    assert 0 <= entity.y <= 2000


def test_custom_boundary_mode():
    """Test using custom boundary mode override."""
    physics = WorldPhysics(world_width=2000, world_height=2000, boundary_mode="bounce")

    # Override with wrap mode
    entity = create_test_entity(x=2005.0, y=100.0)
    physics.apply_bounds(entity, mode="wrap")

    # Should wrap instead of bounce
    assert entity.x == 0.0


def test_entity_without_velocity():
    """Test that physics works on entities without velocity attributes."""
    physics = WorldPhysics()

    # Create entity without velocity (base entity doesn't have vx/vy by default)
    entity = BaseEntity(
        id="test",
        x=100.0,
        y=100.0,
        energy=100.0,
        max_energy=100.0,
        radius=10.0,
        color="#ffffff",
        generation=0,
        dna_hash="test",
        parent_id=None,
        born_at_tick=0,
    )

    # These should not crash even without velocity
    physics.apply_friction(entity)
    physics.apply_gravity(entity)
    physics.apply_bounds(entity)

    # Position should still be constrained
    assert 0 <= entity.x <= 2000
    assert 0 <= entity.y <= 2000
