"""Dynamic trait registry with thread-safe snapshot mechanism.

This module provides a registry for all dynamically loaded Trait classes.
The registry uses atomic dict replacement to ensure thread safety during
hot-reload operations.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional, Type

import structlog

from backend.core.traits import BaseTrait

logger = structlog.get_logger()


class DynamicRegistry:
    """Thread-safe registry for dynamically loaded Trait classes.

    Uses atomic dict replacement instead of in-place mutation to prevent
    race conditions during hot-reload when traits are being registered
    while entities are spawning.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._traits: dict[str, Type[BaseTrait]] = {}
        self._sources: dict[str, str] = {}  # trait_name -> source code
        self._usage_counter: Counter[str] = Counter()

    def register(self, name: str, cls: Type[BaseTrait]) -> None:
        """Register a trait class in the registry.

        Args:
            name: Unique name for the trait (usually class name).
            cls: The trait class to register (must implement BaseTrait protocol).

        Note:
            Uses atomic dict replacement to ensure thread safety.
        """
        # Create new dict with the new trait
        new_traits = self._traits.copy()
        new_traits[name] = cls

        # Atomic replacement
        self._traits = new_traits

        logger.info("trait_registered", trait_name=name, class_name=cls.__name__)

    def register_source(self, name: str, source_code: str) -> None:
        """Store the source code for a registered trait.

        Args:
            name: Trait name (same key used in register()).
            source_code: Full Python source code of the trait.
        """
        self._sources[name] = source_code

    def get_source(self, name: str) -> Optional[str]:
        """Get the source code for a registered trait.

        Args:
            name: Trait name.

        Returns:
            Source code string, or None if not found.
        """
        return self._sources.get(name)

    def unregister(self, name: str) -> bool:
        """Remove a trait from the registry.

        Args:
            name: Name of the trait to remove.

        Returns:
            bool: True if trait was removed, False if it wasn't in the registry.

        Note:
            Uses atomic dict replacement to ensure thread safety.
        """
        if name not in self._traits:
            logger.warning("trait_unregister_failed", trait_name=name, reason="not_found")
            return False

        # Create new dict without the trait
        new_traits = self._traits.copy()
        del new_traits[name]

        # Atomic replacement
        self._traits = new_traits

        logger.info("trait_unregistered", trait_name=name)
        return True

    def get_trait(self, name: str) -> Optional[Type[BaseTrait]]:
        """Get a trait class by name.

        Args:
            name: Name of the trait to retrieve.

        Returns:
            The trait class if found, None otherwise.
        """
        return self._traits.get(name)

    def get_all_traits(self) -> dict[str, Type[BaseTrait]]:
        """Get all registered traits.

        Returns:
            Dictionary mapping trait names to trait classes.

        Warning:
            Returns a reference to the internal dict. For spawn operations,
            use get_snapshot() instead to avoid race conditions.
        """
        return self._traits

    def get_snapshot(self) -> dict[str, Type[BaseTrait]]:
        """Get an immutable snapshot of all registered traits.

        Returns:
            A copy of the trait registry at this moment in time.

        Note:
            This is the CRITICAL method for avoiding race conditions during
            hot-reload. When spawning entities, always use this method to
            get a consistent view of available traits, even if the Patcher
            is updating the registry mid-spawn.
        """
        return self._traits.copy()

    def unique_trait_count(self) -> int:
        """Get the number of unique registered traits.

        Returns:
            Count of unique traits in the registry.
        """
        return len(self._traits)

    def record_trait_usage(self, trait_name: str) -> None:
        """Record that a trait was assigned to an entity.

        Args:
            trait_name: Name of the trait that was used.

        Note:
            This is used for analytics and most_common_trait() reporting.
        """
        self._usage_counter[trait_name] += 1

    def most_common_trait(self) -> Optional[str]:
        """Get the name of the most commonly used trait.

        Returns:
            Name of the most frequently assigned trait, or None if no
            traits have been assigned.
        """
        if not self._usage_counter:
            return None

        most_common = self._usage_counter.most_common(1)
        return most_common[0][0] if most_common else None

    def get_usage_stats(self) -> dict[str, int]:
        """Get usage statistics for all traits.

        Returns:
            Dictionary mapping trait names to usage counts.
        """
        return dict(self._usage_counter)

    def clear_usage_stats(self) -> None:
        """Reset all usage statistics to zero."""
        self._usage_counter.clear()
        logger.info("trait_usage_stats_cleared")
