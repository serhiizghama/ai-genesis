"""Unit tests for DynamicRegistry."""

from __future__ import annotations

import pytest

from backend.core.dynamic_registry import DynamicRegistry
from backend.core.entity import BaseEntity
from backend.core.traits import BaseTrait


# Mock trait classes for testing
class MockTraitA:
    """Mock trait A for testing."""

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute method."""
        pass


class MockTraitB:
    """Mock trait B for testing."""

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute method."""
        pass


class MockTraitC:
    """Mock trait C for testing."""

    async def execute(self, entity: BaseEntity) -> None:
        """Mock execute method."""
        pass


def test_registry_initialization():
    """Test that registry initializes empty."""
    registry = DynamicRegistry()
    assert registry.unique_trait_count() == 0
    assert registry.get_all_traits() == {}
    assert registry.most_common_trait() is None


def test_register_trait():
    """Test registering a trait."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)

    assert registry.unique_trait_count() == 1
    assert registry.get_trait("MockTraitA") == MockTraitA


def test_register_multiple_traits():
    """Test registering multiple traits."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)
    registry.register("MockTraitB", MockTraitB)
    registry.register("MockTraitC", MockTraitC)

    assert registry.unique_trait_count() == 3
    assert "MockTraitA" in registry.get_all_traits()
    assert "MockTraitB" in registry.get_all_traits()
    assert "MockTraitC" in registry.get_all_traits()


def test_unregister_trait():
    """Test unregistering a trait."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)
    registry.register("MockTraitB", MockTraitB)

    assert registry.unique_trait_count() == 2

    result = registry.unregister("MockTraitA")
    assert result is True
    assert registry.unique_trait_count() == 1
    assert registry.get_trait("MockTraitA") is None
    assert registry.get_trait("MockTraitB") == MockTraitB


def test_unregister_nonexistent_trait():
    """Test unregistering a trait that doesn't exist."""
    registry = DynamicRegistry()
    result = registry.unregister("NonexistentTrait")
    assert result is False


def test_get_trait():
    """Test getting a trait by name."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)

    trait_cls = registry.get_trait("MockTraitA")
    assert trait_cls == MockTraitA

    nonexistent = registry.get_trait("NonexistentTrait")
    assert nonexistent is None


def test_get_snapshot():
    """Test that get_snapshot returns an independent copy."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)
    registry.register("MockTraitB", MockTraitB)

    # Get snapshot
    snapshot = registry.get_snapshot()
    assert len(snapshot) == 2
    assert "MockTraitA" in snapshot
    assert "MockTraitB" in snapshot

    # Modify registry
    registry.register("MockTraitC", MockTraitC)

    # Snapshot should be unchanged
    assert len(snapshot) == 2
    assert "MockTraitC" not in snapshot

    # But registry should have the new trait
    assert registry.unique_trait_count() == 3


def test_get_snapshot_prevents_race_condition():
    """Test that snapshot is independent of registry changes during spawn."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)
    registry.register("MockTraitB", MockTraitB)

    # Simulate spawn operation that holds a snapshot
    spawn_snapshot = registry.get_snapshot()

    # Simulate hot-reload that modifies registry mid-spawn
    registry.unregister("MockTraitA")
    registry.register("MockTraitC", MockTraitC)

    # Spawn operation should still see the original snapshot
    assert "MockTraitA" in spawn_snapshot
    assert "MockTraitB" in spawn_snapshot
    assert "MockTraitC" not in spawn_snapshot

    # But current registry should reflect changes
    assert registry.get_trait("MockTraitA") is None
    assert registry.get_trait("MockTraitC") == MockTraitC


def test_trait_usage_tracking():
    """Test tracking trait usage statistics."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)
    registry.register("MockTraitB", MockTraitB)

    # Record some usage
    registry.record_trait_usage("MockTraitA")
    registry.record_trait_usage("MockTraitA")
    registry.record_trait_usage("MockTraitA")
    registry.record_trait_usage("MockTraitB")

    # Check stats
    stats = registry.get_usage_stats()
    assert stats["MockTraitA"] == 3
    assert stats["MockTraitB"] == 1

    # Most common should be MockTraitA
    assert registry.most_common_trait() == "MockTraitA"


def test_most_common_trait_empty():
    """Test most_common_trait returns None when no usage recorded."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)

    assert registry.most_common_trait() is None


def test_clear_usage_stats():
    """Test clearing usage statistics."""
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)

    registry.record_trait_usage("MockTraitA")
    registry.record_trait_usage("MockTraitA")

    assert registry.get_usage_stats()["MockTraitA"] == 2

    registry.clear_usage_stats()

    assert registry.get_usage_stats() == {}
    assert registry.most_common_trait() is None


def test_atomic_dict_replacement():
    """Test that register/unregister use atomic dict replacement.

    This is a critical feature for thread safety during hot-reload.
    The implementation should create a new dict and replace the old one,
    rather than mutating the existing dict in place.
    """
    registry = DynamicRegistry()
    registry.register("MockTraitA", MockTraitA)

    # Get reference to internal dict
    original_dict = registry._traits

    # Register another trait
    registry.register("MockTraitB", MockTraitB)

    # The internal dict should be a NEW object (atomic replacement)
    assert registry._traits is not original_dict
    assert "MockTraitB" in registry._traits

    # Save reference again
    second_dict = registry._traits

    # Unregister a trait
    registry.unregister("MockTraitA")

    # Again, should be a new dict
    assert registry._traits is not second_dict
    assert "MockTraitA" not in registry._traits
