"""Dynamic trait registry with thread-safe snapshot mechanism.

This module provides a registry for all dynamically loaded Trait classes.
The registry uses atomic dict replacement to ensure thread safety during
hot-reload operations.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional, Type

import structlog

from backend.core.traits import BaseTrait

logger = structlog.get_logger()


def canonical_name(name: str) -> str:
    """Normalize a trait name to snake_case, stripping optional 'Trait' suffix.

    Examples:
        ResourceDiversifier      → resource_diversifier
        ResourceDiversifierTrait → resource_diversifier
        resource_diversifier     → resource_diversifier
        EnergyPulseTrait         → energy_pulse
    """
    # Strip 'Trait' suffix
    name = re.sub(r"Trait$", "", name)
    # Handle consecutive uppercase runs (e.g. HTTPSHandler → https_handler)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    # Insert underscore between lowercase/digit and uppercase
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return name.lower().strip("_")


class DynamicRegistry:
    """Thread-safe registry for dynamically loaded Trait classes.

    Uses atomic dict replacement instead of in-place mutation to prevent
    race conditions during hot-reload when traits are being registered
    while entities are spawning.

    Canonical name normalization ensures that PascalCase and snake_case
    registrations for the same trait land on the same registry key.
    Family tracking keeps at most `max_versions` file paths per trait family
    and returns the evicted paths so callers can delete them from disk.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._traits: dict[str, Type[BaseTrait]] = {}
        self._sources: dict[str, str] = {}  # canonical_name -> source code
        self._usage_counter: Counter[str] = Counter()
        # canonical_name -> ordered list of file paths (oldest first)
        self._family_files: dict[str, list[str]] = {}
        # Monotonically increasing; increments on every register/unregister.
        self._version: int = 0

    @property
    def version(self) -> int:
        """Registry mutation counter — use this to detect any change."""
        return self._version

    def register(
        self,
        name: str,
        cls: Type[BaseTrait],
        file_path: Optional[str] = None,
        max_versions: int = 3,
    ) -> list[str]:
        """Register a trait class in the registry.

        Args:
            name: Trait name (snake_case or PascalCase — normalized internally).
            cls: The trait class to register (must implement BaseTrait protocol).
            file_path: Optional path to the source file on disk. Used for
                       family version GC: once more than max_versions files
                       have been registered for the same family the oldest
                       is evicted and its path returned for deletion.
            max_versions: How many file versions to keep per family.

        Returns:
            List of file paths that should be deleted (evicted old versions).

        Note:
            Uses atomic dict replacement to ensure thread safety.
        """
        canon = canonical_name(name)
        files_to_delete: list[str] = []

        # Track file path per family and evict old versions
        if file_path:
            if canon not in self._family_files:
                self._family_files[canon] = []
            self._family_files[canon].append(file_path)
            while len(self._family_files[canon]) > max_versions:
                old_file = self._family_files[canon].pop(0)
                files_to_delete.append(old_file)

        # Atomic replacement
        new_traits = self._traits.copy()
        new_traits[canon] = cls
        self._traits = new_traits
        self._version += 1

        logger.info(
            "trait_registered",
            trait_name=canon,
            original_name=name,
            class_name=cls.__name__,
            files_evicted=len(files_to_delete),
        )
        return files_to_delete

    def register_source(self, name: str, source_code: str) -> None:
        """Store the source code for a registered trait.

        Args:
            name: Trait name (normalized to canonical form internally).
            source_code: Full Python source code of the trait.
        """
        self._sources[canonical_name(name)] = source_code

    def get_source(self, name: str) -> Optional[str]:
        """Get the source code for a registered trait.

        Args:
            name: Trait name (normalized internally).

        Returns:
            Source code string, or None if not found.
        """
        return self._sources.get(canonical_name(name))

    def unregister(self, name: str) -> bool:
        """Remove a trait from the registry.

        Args:
            name: Name of the trait to remove (normalized internally).

        Returns:
            bool: True if trait was removed, False if it wasn't in the registry.

        Note:
            Uses atomic dict replacement to ensure thread safety.
        """
        canon = canonical_name(name)
        if canon not in self._traits:
            logger.warning("trait_unregister_failed", trait_name=canon, reason="not_found")
            return False

        # Create new dict without the trait
        new_traits = self._traits.copy()
        del new_traits[canon]

        # Atomic replacement
        self._traits = new_traits
        self._version += 1

        logger.info("trait_unregistered", trait_name=canon)
        return True

    def get_trait(self, name: str) -> Optional[Type[BaseTrait]]:
        """Get a trait class by name.

        Args:
            name: Name of the trait to retrieve (normalized internally).

        Returns:
            The trait class if found, None otherwise.
        """
        return self._traits.get(canonical_name(name))

    def get_all_traits(self) -> dict[str, Type[BaseTrait]]:
        """Get all registered traits.

        Returns:
            Dictionary mapping canonical trait names to trait classes.

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
            trait_name: Name of the trait that was used (normalized internally).

        Note:
            This is used for analytics and most_common_trait() reporting.
        """
        self._usage_counter[canonical_name(trait_name)] += 1

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
