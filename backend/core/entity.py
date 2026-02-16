"""Entity model — dataclass for Molbots with traits and state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.core.traits import BaseTrait, TraitExecutor


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
    state: str = "alive"  # alive, dead, reproducing

    # Behavior
    traits: list[BaseTrait] = field(default_factory=list)
    deactivated_traits: set[str] = field(default_factory=set)
    metabolism_rate: float = 1.0  # energy consumed per tick

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

        # Consume energy for metabolism
        self.energy -= self.metabolism_rate

        # Execute all traits
        await trait_executor.execute_traits(self)

        # Check for death
        if self.energy <= 0:
            self.state = "dead"

    def move(self, dx: float, dy: float) -> None:
        """Move the entity by a delta vector.

        Args:
            dx: Change in x position.
            dy: Change in y position.

        Note:
            Does not enforce world boundaries. The physics system
            should handle boundary checks.
        """
        self.x += dx
        self.y += dy

    def consume_resource(self, amount: float) -> None:
        """Add energy from consuming a resource.

        Args:
            amount: Amount of energy to add.

        Note:
            Energy is capped at max_energy.
        """
        self.energy = min(self.energy + amount, self.max_energy)

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
