"""Unit tests for BaseEntity."""

from __future__ import annotations

import pytest

from backend.core.entity import BaseEntity
from backend.core.traits import BaseTrait, TraitExecutor


# Mock trait for testing
class MockTrait:
    """Mock trait that increments a counter when executed."""

    def __init__(self) -> None:
        """Initialize mock trait."""
        self.execute_count = 0

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute - increment counter."""
        self.execute_count += 1


class FailingTrait:
    """Mock trait that raises an error."""

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute that always fails."""
        raise RuntimeError("Intentional test error")


def test_entity_initialization():
    """Test that entity initializes with correct default values."""
    entity = BaseEntity(
        id="test-id",
        x=100.0,
        y=200.0,
        energy=80.0,
        max_energy=100.0,
        radius=10.0,
        color="#FF5733",
        age=0,
        generation=1,
        dna_hash="abc123",
        parent_id="parent-id",
        born_at_tick=50,
    )

    assert entity.id == "test-id"
    assert entity.x == 100.0
    assert entity.y == 200.0
    assert entity.energy == 80.0
    assert entity.max_energy == 100.0
    assert entity.radius == 10.0
    assert entity.color == "#FF5733"
    assert entity.age == 0
    assert entity.generation == 1
    assert entity.dna_hash == "abc123"
    assert entity.parent_id == "parent-id"
    assert entity.born_at_tick == 50
    assert entity.state == "alive"
    assert entity.metabolism_rate == 1.0
    assert len(entity.traits) == 0
    assert len(entity.deactivated_traits) == 0


def test_entity_is_alive():
    """Test is_alive() method."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        state="alive",
    )

    assert entity.is_alive() is True

    entity.state = "dead"
    assert entity.is_alive() is False

    entity.state = "reproducing"
    assert entity.is_alive() is False


def test_entity_move():
    """Test entity movement."""
    entity = BaseEntity(
        id="test-id",
        x=100.0,
        y=200.0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    entity.move(50.0, -30.0)
    assert entity.x == 150.0
    assert entity.y == 170.0

    entity.move(-100.0, 100.0)
    assert entity.x == 50.0
    assert entity.y == 270.0


def test_entity_consume_resource():
    """Test consuming resources increases energy."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=50.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    entity.consume_resource(30.0)
    assert entity.energy == 80.0

    # Test energy cap at max_energy
    entity.consume_resource(50.0)
    assert entity.energy == 100.0  # Capped at max_energy


def test_entity_consume_resource_when_full():
    """Test consuming resource when already at max energy."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    entity.consume_resource(50.0)
    assert entity.energy == 100.0  # Still capped


def test_entity_deactivate_trait():
    """Test deactivating a trait."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    assert len(entity.deactivated_traits) == 0

    entity.deactivate_trait("BadTrait")
    assert "BadTrait" in entity.deactivated_traits

    entity.deactivate_trait("AnotherBadTrait")
    assert "AnotherBadTrait" in entity.deactivated_traits
    assert len(entity.deactivated_traits) == 2


def test_entity_activate_trait():
    """Test reactivating a deactivated trait."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    entity.deactivate_trait("TestTrait")
    assert "TestTrait" in entity.deactivated_traits

    entity.activate_trait("TestTrait")
    assert "TestTrait" not in entity.deactivated_traits


@pytest.mark.asyncio
async def test_entity_update_with_traits():
    """Test entity update executes traits."""
    trait1 = MockTrait()
    trait2 = MockTrait()

    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        traits=[trait1, trait2],
        metabolism_rate=2.0,
    )

    executor = TraitExecutor(timeout_sec=1.0, tick_budget_sec=10.0)

    await entity.update(executor)

    # Verify traits were executed
    assert trait1.execute_count == 1
    assert trait2.execute_count == 1

    # Verify age incremented
    assert entity.age == 1

    # Verify metabolism consumed energy
    assert entity.energy == 98.0  # 100 - 2.0


@pytest.mark.asyncio
async def test_entity_update_multiple_ticks():
    """Test entity update over multiple ticks."""
    trait = MockTrait()

    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        traits=[trait],
        metabolism_rate=1.0,
    )

    executor = TraitExecutor(timeout_sec=1.0, tick_budget_sec=10.0)

    # Run 5 ticks
    for _ in range(5):
        await entity.update(executor)

    assert entity.age == 5
    assert entity.energy == 95.0  # 100 - (1.0 * 5)
    assert trait.execute_count == 5


@pytest.mark.asyncio
async def test_entity_dies_when_energy_depleted():
    """Test entity state changes to dead when energy <= 0."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=2.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        metabolism_rate=1.0,
    )

    executor = TraitExecutor(timeout_sec=1.0, tick_budget_sec=10.0)

    # Tick 1: energy 2.0 -> 1.0
    await entity.update(executor)
    assert entity.is_alive()
    assert entity.energy == 1.0

    # Tick 2: energy 1.0 -> 0.0 -> dead
    await entity.update(executor)
    assert entity.energy == 0.0
    assert entity.state == "dead"
    assert not entity.is_alive()


@pytest.mark.asyncio
async def test_entity_update_with_no_traits():
    """Test entity update with no traits."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        traits=[],
        metabolism_rate=1.0,
    )

    executor = TraitExecutor(timeout_sec=1.0, tick_budget_sec=10.0)

    await entity.update(executor)

    # Should still age and consume energy
    assert entity.age == 1
    assert entity.energy == 99.0


@pytest.mark.asyncio
async def test_entity_with_failing_trait():
    """Test entity handles failing traits gracefully."""
    good_trait = MockTrait()
    bad_trait = FailingTrait()

    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100.0,
        max_energy=100.0,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
        traits=[good_trait, bad_trait],
        metabolism_rate=1.0,
    )

    executor = TraitExecutor(timeout_sec=1.0, tick_budget_sec=10.0)

    # Update should not crash even though bad_trait fails
    await entity.update(executor)

    # Good trait should have executed
    assert good_trait.execute_count == 1

    # Bad trait should be deactivated
    assert "FailingTrait" in entity.deactivated_traits


def test_entity_default_values():
    """Test entity default values for optional fields."""
    entity = BaseEntity(
        id="test-id",
        x=0,
        y=0,
        energy=100,
        max_energy=100,
        radius=10,
        color="#ffffff",
        generation=0,
        dna_hash="abc",
        parent_id=None,
        born_at_tick=0,
    )

    assert entity.age == 0
    assert entity.state == "alive"
    assert entity.traits == []
    assert entity.deactivated_traits == set()
    assert entity.metabolism_rate == 1.0
