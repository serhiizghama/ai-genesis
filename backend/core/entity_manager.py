"""Entity manager with CRUD operations and spatial hashing for efficient collision detection."""

from __future__ import annotations

import hashlib
import random
import uuid
from collections import defaultdict
from typing import Optional

import structlog

from backend.core.entity import BaseEntity
from backend.core.traits import BaseTrait

logger = structlog.get_logger()


class EntityManager:
    """Manages all entities in the simulation with spatial hashing for efficient queries.

    Provides CRUD operations for entities and spatial queries for collision
    detection and proximity searches.
    """

    # Spatial hash grid cell size (50x50 pixels)
    CELL_SIZE = 50

    def __init__(self, world_width: int = 2000, world_height: int = 2000) -> None:
        """Initialize the entity manager.

        Args:
            world_width: Width of the simulation world in pixels.
            world_height: Height of the simulation world in pixels.
        """
        self._entities: dict[str, BaseEntity] = {}
        self._spatial_grid: dict[tuple[int, int], set[str]] = defaultdict(set)
        self.world_width = world_width
        self.world_height = world_height

    def spawn(
        self,
        x: float,
        y: float,
        traits: list[BaseTrait],
        parent: Optional[BaseEntity] = None,
        generation: int = 0,
        tick: int = 0,
        initial_energy: float = 100.0,
        entity_type: str = "molbot",
        max_energy: float = 100.0,
    ) -> BaseEntity:
        """Spawn a new entity in the simulation.

        Args:
            x: Initial x position.
            y: Initial y position.
            traits: List of trait instances to assign to the entity.
            parent: Optional parent entity (for reproduction).
            generation: Generation number (0 for first generation).
            tick: Current simulation tick (for born_at_tick).
            initial_energy: Starting energy level (default 100.0).
            entity_type: Type of entity — "molbot" or "predator".
            max_energy: Maximum energy cap (default 100.0).

        Returns:
            The newly created entity.
        """
        entity_id = str(uuid.uuid4())

        # Generate DNA hash from traits
        trait_names = sorted([t.__class__.__name__ for t in traits])
        dna_string = "".join(trait_names)
        dna_hash = hashlib.sha256(dna_string.encode()).hexdigest()[:16]

        # Generate random color based on DNA hash
        color = f"#{dna_hash[:6]}"

        # Predators get a fixed red color, overriding DNA-based color
        if entity_type == "predator":
            color = "#cc0000"

        # Create entity
        entity = BaseEntity(
            id=entity_id,
            x=x,
            y=y,
            energy=initial_energy,
            max_energy=max_energy,
            radius=10.0,
            color=color,
            age=0,
            generation=generation,
            dna_hash=dna_hash,
            parent_id=parent.id if parent else None,
            born_at_tick=tick,
            traits=traits,
            state="alive",
            metabolism_rate=1.0,
            entity_type=entity_type,
        )

        # Inject back-reference so traits can call entity_manager methods
        entity._entity_manager = self

        # Add to entities dict
        self._entities[entity_id] = entity

        # Add to spatial grid
        self._add_to_spatial_grid(entity)

        logger.info(
            "entity_spawned",
            entity_id=entity_id,
            x=x,
            y=y,
            generation=generation,
            parent_id=entity.parent_id,
            trait_count=len(traits),
            entity_type=entity_type,
        )

        return entity

    def remove(self, entity: BaseEntity) -> bool:
        """Remove an entity from the simulation.

        Args:
            entity: The entity to remove.

        Returns:
            bool: True if entity was removed, False if it wasn't found.
        """
        if entity.id not in self._entities:
            logger.warning("entity_remove_failed", entity_id=entity.id, reason="not_found")
            return False

        # Remove from spatial grid
        self._remove_from_spatial_grid(entity)

        # Remove from entities dict
        del self._entities[entity.id]

        logger.info("entity_removed", entity_id=entity.id, age=entity.age)
        return True

    def get(self, entity_id: str) -> Optional[BaseEntity]:
        """Get an entity by ID.

        Args:
            entity_id: The ID of the entity to retrieve.

        Returns:
            The entity if found, None otherwise.
        """
        return self._entities.get(entity_id)

    def alive(self) -> list[BaseEntity]:
        """Get all living entities.

        Returns:
            List of entities with state == "alive".
        """
        return [e for e in self._entities.values() if e.is_alive()]

    def count(self) -> int:
        """Get the total number of entities.

        Returns:
            Count of all entities (alive and dead).
        """
        return len(self._entities)

    def count_alive(self) -> int:
        """Get the count of living entities.

        Returns:
            Count of entities with state == "alive".
        """
        return sum(1 for e in self._entities.values() if e.is_alive())

    # -------------------------------------------------------------------------
    # Spatial Hashing (T-015)
    # -------------------------------------------------------------------------

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

    def _add_to_spatial_grid(self, entity: BaseEntity) -> None:
        """Add an entity to the spatial hash grid.

        Args:
            entity: The entity to add.
        """
        cell = self._get_cell_coords(entity.x, entity.y)
        self._spatial_grid[cell].add(entity.id)

    def _remove_from_spatial_grid(self, entity: BaseEntity) -> None:
        """Remove an entity from the spatial hash grid.

        Args:
            entity: The entity to remove.
        """
        cell = self._get_cell_coords(entity.x, entity.y)
        self._spatial_grid[cell].discard(entity.id)

        # Clean up empty cells
        if not self._spatial_grid[cell]:
            del self._spatial_grid[cell]

    def rebuild_spatial_grid(self) -> None:
        """Rebuild the entire spatial hash grid from scratch.

        This should be called each tick after all entity movements to ensure
        the grid is up-to-date for collision detection.
        """
        self._spatial_grid.clear()

        for entity in self._entities.values():
            if entity.is_alive():
                self._add_to_spatial_grid(entity)

    def detect_collisions(self) -> list[tuple[BaseEntity, BaseEntity]]:
        """Detect all colliding entity pairs.

        Returns:
            List of tuples, where each tuple contains two entities that are
            colliding (within sum of their radii).

        Note:
            This method uses the spatial hash grid for efficiency. Make sure
            rebuild_spatial_grid() was called this tick after movements.
        """
        collisions: list[tuple[BaseEntity, BaseEntity]] = []
        checked_pairs: set[tuple[str, str]] = set()

        for entity in self._entities.values():
            if not entity.is_alive():
                continue

            # Get nearby entities using the grid
            nearby = self.nearby_entities(entity.x, entity.y, entity.radius * 3)

            for other in nearby:
                if other.id == entity.id:
                    continue

                # Avoid checking the same pair twice
                pair = tuple(sorted([entity.id, other.id]))
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)

                # Check if entities are actually colliding
                dx = entity.x - other.x
                dy = entity.y - other.y
                distance = (dx * dx + dy * dy) ** 0.5
                collision_distance = entity.radius + other.radius

                if distance < collision_distance:
                    collisions.append((entity, other))

        return collisions

    def nearby_entities(self, x: float, y: float, radius: float) -> list[BaseEntity]:
        """Find all entities within a radius of a point.

        Args:
            x: Center x coordinate.
            y: Center y coordinate.
            radius: Search radius in pixels.

        Returns:
            List of entities within the radius.

        Note:
            This method uses the spatial hash grid for efficiency. It checks
            all cells that overlap with the search circle.
        """
        # Calculate which cells to check
        cell_x_min = int((x - radius) // self.CELL_SIZE)
        cell_x_max = int((x + radius) // self.CELL_SIZE)
        cell_y_min = int((y - radius) // self.CELL_SIZE)
        cell_y_max = int((y + radius) // self.CELL_SIZE)

        # Collect entity IDs from relevant cells
        nearby_ids: set[str] = set()
        for cx in range(cell_x_min, cell_x_max + 1):
            for cy in range(cell_y_min, cell_y_max + 1):
                cell = (cx, cy)
                if cell in self._spatial_grid:
                    nearby_ids.update(self._spatial_grid[cell])

        # Filter to entities actually within radius
        nearby: list[BaseEntity] = []
        radius_squared = radius * radius

        for entity_id in nearby_ids:
            entity = self._entities.get(entity_id)
            if entity and entity.is_alive():
                dx = entity.x - x
                dy = entity.y - y
                distance_squared = dx * dx + dy * dy

                if distance_squared <= radius_squared:
                    nearby.append(entity)

        return nearby

    def get_all_entities(self) -> list[BaseEntity]:
        """Get all entities in the simulation.

        Returns:
            List of all entities (alive and dead).
        """
        return list(self._entities.values())

    def spawn_predator(self, x: float, y: float, tick: int = 0) -> "BaseEntity":
        """Spawn a PredatorEntity with correct defaults and back-references.

        Args:
            x: Initial x position.
            y: Initial y position.
            tick: Current simulation tick (for born_at_tick).

        Returns:
            The newly created PredatorEntity.
        """
        from backend.core.predator import PredatorEntity
        import uuid

        entity = PredatorEntity(
            id=str(uuid.uuid4()),
            x=x,
            y=y,
            energy=200.0,
            max_energy=200.0,
            radius=15.0,
            color="#cc0000",
            generation=0,
            dna_hash="predator",
            parent_id=None,
            born_at_tick=tick,
            traits=[],
            state="alive",
        )
        entity._entity_manager = self
        self._entities[entity.id] = entity
        self._add_to_spatial_grid(entity)
        logger.info("predator_spawned", entity_id=entity.id, x=x, y=y)
        return entity

    def clear(self) -> None:
        """Remove all entities from the simulation."""
        self._entities.clear()
        self._spatial_grid.clear()
        logger.info("entity_manager_cleared")
