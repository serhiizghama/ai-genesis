"""Entity model — dataclass for Molbots with traits and state."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from backend.core.traits import BaseTrait, TraitExecutor

if TYPE_CHECKING:
    from backend.core.environment import Environment
    from backend.core.entity_manager import EntityManager


@dataclass
class BaseEntity:
    """Represents a single entity (Molbot) in the simulation.

    Entities have physical properties (position, energy) and behavioral
    properties (traits, state). Traits are executed each tick via the
    TraitExecutor.
    """

    # Identity
    id: str
    generation: int
    dna_hash: str
    parent_id: Optional[str]
    born_at_tick: int

    # Physical properties
    x: float
    y: float
    energy: float
    max_energy: float
    radius: float
    color: str  # Hex color string, e.g., "#FF5733"

    # Lifecycle
    age: int = 0  # in ticks
    max_age: int = 0  # 0 = immortal; die when age >= max_age
    state: str = "alive"  # alive, dead, reproducing

    # Entity type & infection
    entity_type: str = "molbot"  # "molbot" | "predator"
    infected: bool = False
    infection_timer: int = 0  # ticks remaining until recovery

    # Behavior
    traits: list[BaseTrait] = field(default_factory=list)
    deactivated_traits: set[str] = field(default_factory=set)
    metabolism_rate: float = 1.0  # energy consumed per tick

    # Environment reference — set by engine after spawn, not part of data model
    _environment: Optional[Environment] = field(
        default=None, init=False, repr=False, compare=False, hash=False
    )
    _entity_manager: Optional["EntityManager"] = field(
        default=None, init=False, repr=False, compare=False, hash=False
    )
    # Tracks energy gained via eat_nearby() during trait execution (for trait sandboxing)
    _trait_energy_gain: float = field(
        default=0.0, init=False, repr=False, compare=False, hash=False
    )

    async def update(self, trait_executor: TraitExecutor) -> None:
        """Update entity state and execute all active traits.

        Args:
            trait_executor: The executor responsible for running traits
                with timeout protection.

        Note:
            This method is called every tick by the engine.
            - Increments age
            - Consumes energy based on metabolism
            - Executes all active traits
        """
        # Age the entity
        self.age += 1

        if self.max_age > 0 and self.age >= self.max_age:
            self.state = "dead"

        # Consume energy for metabolism
        self.energy -= self.metabolism_rate

        # Infection penalty: extra energy drain
        if self.infected:
            self.energy -= 2.0

        # Execute all traits inside a sandbox:
        # - age is saved/restored so traits cannot corrupt it
        # - energy is saved; only gains from eat_nearby() (via _receive_energy) are kept
        # - metabolism_rate is saved/restored so traits cannot reduce it
        _age_snapshot = self.age
        _energy_snapshot = self.energy
        _metabolism_snapshot = self.metabolism_rate
        self._trait_energy_gain = 0.0

        await trait_executor.execute_traits(self)

        self.age = _age_snapshot
        self.energy = min(_energy_snapshot + self._trait_energy_gain, self.max_energy)
        self.metabolism_rate = _metabolism_snapshot

        # Check for death
        if self.energy <= 0:
            self.state = "dead"

    # Maximum displacement allowed per tick — prevents LLM-generated traits from
    # teleporting entities across the world by passing absolute coords as deltas.
    _MAX_MOVE_PER_TICK: float = 20.0

    def move(self, dx: float, dy: float) -> None:
        """Move the entity by a delta vector, clamped to _MAX_MOVE_PER_TICK.

        Args:
            dx: Change in x position.
            dy: Change in y position.

        Note:
            Movement is clamped so no single tick can displace an entity
            by more than _MAX_MOVE_PER_TICK pixels. This prevents buggy
            trait code (e.g. passing absolute coords as deltas) from
            teleporting entities to world boundaries.
            World boundary enforcement is handled by WorldPhysics.
        """
        magnitude = math.sqrt(dx * dx + dy * dy)
        if magnitude > self._MAX_MOVE_PER_TICK:
            scale = self._MAX_MOVE_PER_TICK / magnitude
            dx *= scale
            dy *= scale
        self.x += dx
        self.y += dy

    def _receive_energy(self, amount: float) -> None:
        """Internal: add energy after a real resource was consumed by environment.

        Called only by Environment.consume_resource(). Traits must use
        eat_nearby() instead — this method does NOT check for real resources.
        Gains are tracked via _trait_energy_gain so the trait sandbox in
        update() can apply only legitimate energy gains.
        """
        self._trait_energy_gain += amount
        self.energy = min(self.energy + amount, self.max_energy)

    def eat_nearby(self, radius: float = 30.0) -> bool:
        """Consume the nearest real resource within radius.

        This is the correct way for traits to gain energy — it actually
        removes a resource from the world. Returns False if no food nearby
        or environment is not available.

        Args:
            radius: Search radius in world pixels (default 30).

        Returns:
            True if a resource was found and consumed, False otherwise.
        """
        if self._environment is None:
            return False
        resources = self._environment.nearby_resources(self.x, self.y, radius)
        if not resources:
            return False
        # Eat the closest one
        closest = min(resources, key=lambda r: (r.x - self.x) ** 2 + (r.y - self.y) ** 2)
        return self._environment.consume_resource(self, closest)

    def attack_nearby(self, radius: float = 30.0, damage: float = 20.0) -> bool:
        """Attack nearest predator within radius. For use in LLM-generated traits."""
        if self._entity_manager is None:
            return False
        nearby = self._entity_manager.nearby_entities(self.x, self.y, radius)
        predators = [e for e in nearby
                     if getattr(e, "entity_type", "molbot") == "predator"
                     and e.is_alive() and e.id != self.id]
        if not predators:
            return False
        closest = min(predators, key=lambda p: (p.x - self.x)**2 + (p.y - self.y)**2)
        closest.energy -= damage
        if closest.energy <= 0:
            closest.state = "dead"
        return True

    def is_alive(self) -> bool:
        """Check if the entity is alive.

        Returns:
            bool: True if state is "alive", False otherwise.
        """
        return self.state == "alive"

    def deactivate_trait(self, trait_name: str) -> None:
        """Mark a trait as deactivated (e.g., due to error or timeout).

        Args:
            trait_name: Name of the trait class to deactivate.
        """
        self.deactivated_traits.add(trait_name)

    def activate_trait(self, trait_name: str) -> None:
        """Reactivate a previously deactivated trait.

        Args:
            trait_name: Name of the trait class to reactivate.
        """
        self.deactivated_traits.discard(trait_name)
