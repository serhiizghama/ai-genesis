"""Environment — resource management and world conditions.

This module provides:
- Resource entities (food) that entities can consume
- Resource spawning and respawning mechanics
- Spatial queries for finding nearby resources
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import structlog

from backend.core.entity import BaseEntity

logger = structlog.get_logger()


@dataclass
class Resource:
    """A consumable resource (food) in the world.

    Resources provide energy to entities when consumed.
    """

    id: str
    x: float
    y: float
    amount: float
    resource_type: str = "food"  # For future expansion (water, minerals, etc.)

    @classmethod
    def create(cls, x: float, y: float, amount: float = 50.0) -> Resource:
        """Factory method to create a new resource.

        Args:
            x: X position in world.
            y: Y position in world.
            amount: Energy value of the resource.

        Returns:
            A new Resource instance.
        """
        return cls(
            id=str(uuid.uuid4()),
            x=x,
            y=y,
            amount=amount,
        )


class Environment:
    """World environment manager.

    Handles:
    - Resource (food) spawning and distribution
    - Resource consumption by entities
    - Spatial queries for nearby resources
    - Resource density tracking
    """

    # Spatial hash grid cell size (50x50 pixels, same as EntityManager)
    CELL_SIZE = 50

    def __init__(
        self,
        world_width: int = 2000,
        world_height: int = 2000,
        initial_resources: int = 100,
        resource_energy: float = 50.0,
    ) -> None:
        """Initialize the environment.

        Args:
            world_width: Width of the world in pixels.
            world_height: Height of the world in pixels.
            initial_resources: Number of resources to spawn initially.
            resource_energy: Energy amount per resource.
        """
        self.world_width = world_width
        self.world_height = world_height
        self.resource_energy = resource_energy

        # Resource storage
        self._resources: dict[str, Resource] = {}
        self._spatial_grid: dict[tuple[int, int], set[str]] = defaultdict(set)

        # Spawn initial resources
        for _ in range(initial_resources):
            self._spawn_single_resource()

    def _get_cell_coords(self, x: float, y: float) -> tuple[int, int]:
        """Convert world coordinates to grid cell coordinates.

        Args:
            x: World x coordinate.
            y: World y coordinate.

        Returns:
            Tuple of (cell_x, cell_y).
        """
        cell_x = int(x // self.CELL_SIZE)
        cell_y = int(y // self.CELL_SIZE)
        return (cell_x, cell_y)

    def _add_to_spatial_grid(self, resource: Resource) -> None:
        """Add a resource to the spatial hash grid.

        Args:
            resource: The resource to add.
        """
        cell = self._get_cell_coords(resource.x, resource.y)
        self._spatial_grid[cell].add(resource.id)

    def _remove_from_spatial_grid(self, resource: Resource) -> None:
        """Remove a resource from the spatial hash grid.

        Args:
            resource: The resource to remove.
        """
        cell = self._get_cell_coords(resource.x, resource.y)
        self._spatial_grid[cell].discard(resource.id)

        # Clean up empty cells
        if not self._spatial_grid[cell]:
            del self._spatial_grid[cell]

    def _spawn_single_resource(self) -> Resource:
        """Spawn a single resource at a random location.

        Returns:
            The newly spawned resource.
        """
        x = random.uniform(0, self.world_width)
        y = random.uniform(0, self.world_height)
        resource = Resource.create(x, y, self.resource_energy)

        self._resources[resource.id] = resource
        self._add_to_spatial_grid(resource)

        return resource

    def respawn_resources(self, rate: float) -> int:
        """Spawn new resources based on a spawn rate.

        Args:
            rate: Spawn rate (resources per tick).
                For example, 0.5 means spawn 1 resource every 2 ticks.

        Returns:
            Number of resources actually spawned this call.

        Note:
            Uses probabilistic spawning for fractional rates.
            For rate=0.5, there's a 50% chance to spawn 1 resource.
        """
        # Fractional spawning using probability
        spawned = 0
        whole_part = int(rate)
        fractional_part = rate - whole_part

        # Spawn whole number of resources
        for _ in range(whole_part):
            self._spawn_single_resource()
            spawned += 1

        # Probabilistically spawn one more resource
        if fractional_part > 0 and random.random() < fractional_part:
            self._spawn_single_resource()
            spawned += 1

        if spawned > 0:
            logger.debug("resources_spawned", count=spawned, total=len(self._resources))

        return spawned

    def nearby_resources(self, x: float, y: float, radius: float) -> list[Resource]:
        """Find all resources within a radius of a point.

        Args:
            x: Center x coordinate.
            y: Center y coordinate.
            radius: Search radius in pixels.

        Returns:
            List of resources within the radius.

        Note:
            Uses spatial hash grid for efficient queries.
        """
        # Calculate which cells to check
        cell_x_min = int((x - radius) // self.CELL_SIZE)
        cell_x_max = int((x + radius) // self.CELL_SIZE)
        cell_y_min = int((y - radius) // self.CELL_SIZE)
        cell_y_max = int((y + radius) // self.CELL_SIZE)

        # Collect resource IDs from relevant cells
        nearby_ids: set[str] = set()
        for cx in range(cell_x_min, cell_x_max + 1):
            for cy in range(cell_y_min, cell_y_max + 1):
                cell = (cx, cy)
                if cell in self._spatial_grid:
                    nearby_ids.update(self._spatial_grid[cell])

        # Filter to resources actually within radius
        nearby: list[Resource] = []
        radius_squared = radius * radius

        for resource_id in nearby_ids:
            resource = self._resources.get(resource_id)
            if resource:
                dx = resource.x - x
                dy = resource.y - y
                distance_squared = dx * dx + dy * dy

                if distance_squared <= radius_squared:
                    nearby.append(resource)

        return nearby

    def consume_resource(self, entity: BaseEntity, resource: Resource) -> bool:
        """Transfer energy from a resource to an entity.

        Args:
            entity: The entity consuming the resource.
            resource: The resource being consumed.

        Returns:
            bool: True if resource was consumed, False if it doesn't exist.

        Note:
            The resource is completely removed after consumption.
            Energy is transferred to the entity (capped at max_energy).
        """
        # Check if resource still exists
        if resource.id not in self._resources:
            return False

        # Transfer energy to entity
        entity.consume_resource(resource.amount)

        # Remove resource from world
        self._remove_from_spatial_grid(resource)
        del self._resources[resource.id]

        logger.debug(
            "resource_consumed",
            resource_id=resource.id,
            entity_id=entity.id,
            energy_gained=resource.amount,
        )

        return True

    def resource_density(self, x: float, y: float, radius: float = 200.0) -> float:
        """Calculate resource density in an area.

        Args:
            x: Center x coordinate.
            y: Center y coordinate.
            radius: Area radius to measure.

        Returns:
            Resource density (resources per 10,000 square pixels).

        Note:
            Useful for analytics and AI decision making.
        """
        resources = self.nearby_resources(x, y, radius)
        area = 3.14159 * radius * radius
        density = (len(resources) / area) * 10000  # Per 10k pixels

        return density

    def get_all_resources(self) -> list[Resource]:
        """Get all resources in the environment.

        Returns:
            List of all resources.
        """
        return list(self._resources.values())

    def count(self) -> int:
        """Get the total number of resources.

        Returns:
            Count of all resources.
        """
        return len(self._resources)

    def clear(self) -> None:
        """Remove all resources from the environment."""
        self._resources.clear()
        self._spatial_grid.clear()
        logger.info("environment_cleared")

    def rebuild_spatial_grid(self) -> None:
        """Rebuild the entire spatial hash grid from scratch.

        Note:
            Resources are static (don't move), so this is only needed
            if resources are moved manually or after bulk operations.
        """
        self._spatial_grid.clear()

        for resource in self._resources.values():
            self._add_to_spatial_grid(resource)
