from __future__ import annotations
from dataclasses import dataclass
from backend.core.entity import BaseEntity
from backend.core.traits import TraitExecutor


@dataclass
class PredatorEntity(BaseEntity):
    """Predator entity — hunts molbots, ages, and starves."""
    entity_type: str = "predator"
    max_age: int = 8000       # ~2 min at 62 TPS → forces oscillation
    max_energy: float = 200.0
    metabolism_rate: float = 2.5  # faster starvation than molbots
    radius: float = 15.0
    color: str = "#cc0000"

    async def update(self, trait_executor: TraitExecutor) -> None:
        self.age += 1
        self.energy -= self.metabolism_rate
        if self.max_age > 0 and self.age >= self.max_age:
            self.state = "dead"
        if self.energy <= 0:
            self.state = "dead"
