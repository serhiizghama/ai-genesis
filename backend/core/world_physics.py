"""World physics — friction, collisions, boundaries, and forces.

This module provides physics simulation for entities including:
- Friction to slow down entities over time
- Elastic collision resolution between entities
- World boundary enforcement (bounce or wrap)
"""

from __future__ import annotations

import math
from typing import Literal

import structlog

from backend.core.entity import BaseEntity

logger = structlog.get_logger()


class WorldPhysics:
    """Physics engine for the simulation world.

    Handles:
    - Friction and drag forces
    - Elastic collision resolution
    - World boundary enforcement
    - Gravity (if needed for future features)
    """

    def __init__(
        self,
        world_width: int = 2000,
        world_height: int = 2000,
        friction_coefficient: float = 0.98,
        gravity: float = 0.0,
        boundary_mode: Literal["bounce", "wrap"] = "bounce",
    ) -> None:
        """Initialize world physics.

        Args:
            world_width: Width of the world in pixels.
            world_height: Height of the world in pixels.
            friction_coefficient: Friction applied each tick (0.0-1.0).
                Values closer to 1.0 mean less friction.
            gravity: Gravity force applied downward (pixels/tick²).
                Set to 0.0 for top-down view.
            boundary_mode: How to handle entities at world edges.
                "bounce" - entities bounce off walls
                "wrap" - entities wrap to opposite side
        """
        self.world_width = world_width
        self.world_height = world_height
        self.friction_coefficient = friction_coefficient
        self.gravity = gravity
        self.boundary_mode = boundary_mode

    def apply_friction(self, entity: BaseEntity, friction: float | None = None) -> None:
        """Apply friction to slow down an entity.

        Args:
            entity: The entity to apply friction to.
            friction: Optional custom friction coefficient (0.0-1.0).
                If None, uses the world's default friction_coefficient.

        Note:
            This assumes entities have velocity properties (vx, vy).
            For MVP, entities may not have velocity yet, so this is
            a placeholder for when movement traits add velocity.
        """
        if friction is None:
            friction = self.friction_coefficient

        # Check if entity has velocity attributes
        if hasattr(entity, "vx") and hasattr(entity, "vy"):
            entity.vx *= friction
            entity.vy *= friction

            # Stop completely if velocity is very small
            if abs(entity.vx) < 0.01:
                entity.vx = 0.0
            if abs(entity.vy) < 0.01:
                entity.vy = 0.0

    def resolve_collision(self, a: BaseEntity, b: BaseEntity) -> None:
        """Resolve elastic collision between two entities.

        Args:
            a: First entity in collision.
            b: Second entity in collision.

        Note:
            This uses simplified elastic collision physics.
            Assumes equal mass for both entities.
            Updates positions to separate overlapping entities.
        """
        # Calculate collision normal (vector from a to b)
        dx = b.x - a.x
        dy = b.y - a.y
        distance = math.sqrt(dx * dx + dy * dy)

        # Avoid division by zero
        if distance < 0.001:
            distance = 0.001

        # Normalize the collision vector
        nx = dx / distance
        ny = dy / distance

        # Calculate overlap amount
        overlap = (a.radius + b.radius) - distance

        # Only resolve if actually overlapping
        if overlap > 0:
            # Separate entities by moving each half the overlap distance
            separation = overlap / 2.0 + 0.1  # Add small buffer
            a.x -= nx * separation
            a.y -= ny * separation
            b.x += nx * separation
            b.y += ny * separation

            # If entities have velocity, apply elastic collision
            if hasattr(a, "vx") and hasattr(a, "vy") and hasattr(b, "vx") and hasattr(b, "vy"):
                # Calculate relative velocity
                dvx = a.vx - b.vx
                dvy = a.vy - b.vy

                # Calculate relative velocity in collision normal direction
                dot_product = dvx * nx + dvy * ny

                # Only apply impulse if entities are moving toward each other
                # Positive dot product means a is moving toward b
                if dot_product > 0:
                    # Apply impulse (assuming equal mass, simplified)
                    impulse_x = dot_product * nx
                    impulse_y = dot_product * ny

                    a.vx -= impulse_x
                    a.vy -= impulse_y
                    b.vx += impulse_x
                    b.vy += impulse_y

    def apply_bounds(
        self,
        entity: BaseEntity,
        width: int | None = None,
        height: int | None = None,
        mode: Literal["bounce", "wrap"] | None = None,
    ) -> None:
        """Keep entity within world bounds.

        Args:
            entity: The entity to constrain.
            width: Optional custom world width (uses default if None).
            height: Optional custom world height (uses default if None).
            mode: Optional boundary mode override.

        Note:
            In "bounce" mode, entities bounce off walls (velocity reversed).
            In "wrap" mode, entities wrap to opposite side (Pac-Man style).
        """
        if width is None:
            width = self.world_width
        if height is None:
            height = self.world_height
        if mode is None:
            mode = self.boundary_mode

        if mode == "bounce":
            # Check left/right bounds
            if entity.x - entity.radius < 0:
                entity.x = entity.radius
                if hasattr(entity, "vx"):
                    entity.vx = abs(entity.vx)  # Bounce right

            elif entity.x + entity.radius > width:
                entity.x = width - entity.radius
                if hasattr(entity, "vx"):
                    entity.vx = -abs(entity.vx)  # Bounce left

            # Check top/bottom bounds
            if entity.y - entity.radius < 0:
                entity.y = entity.radius
                if hasattr(entity, "vy"):
                    entity.vy = abs(entity.vy)  # Bounce down

            elif entity.y + entity.radius > height:
                entity.y = height - entity.radius
                if hasattr(entity, "vy"):
                    entity.vy = -abs(entity.vy)  # Bounce up

        elif mode == "wrap":
            # Wrap around horizontally
            if entity.x < 0:
                entity.x = width
            elif entity.x > width:
                entity.x = 0

            # Wrap around vertically
            if entity.y < 0:
                entity.y = height
            elif entity.y > height:
                entity.y = 0

    def apply_gravity(self, entity: BaseEntity, gravity: float | None = None) -> None:
        """Apply gravity force to an entity.

        Args:
            entity: The entity to apply gravity to.
            gravity: Optional custom gravity value.
                If None, uses the world's default gravity.

        Note:
            Only applies if entity has vy attribute.
            Gravity is typically 0 for top-down view games.
        """
        if gravity is None:
            gravity = self.gravity

        if gravity != 0.0 and hasattr(entity, "vy"):
            entity.vy += gravity

    def apply_all_physics(
        self,
        entity: BaseEntity,
        apply_friction: bool = True,
        apply_gravity: bool = False,
        apply_bounds: bool = True,
    ) -> None:
        """Apply all physics effects to an entity in one call.

        Args:
            entity: The entity to update.
            apply_friction: Whether to apply friction.
            apply_gravity: Whether to apply gravity.
            apply_bounds: Whether to enforce world boundaries.

        Note:
            This is a convenience method for applying multiple physics
            effects in the correct order.
        """
        if apply_gravity:
            self.apply_gravity(entity)

        if apply_friction:
            self.apply_friction(entity)

        if apply_bounds:
            self.apply_bounds(entity)
