"""Core simulation engine — world loop, entities, physics, traits."""

from backend.core.engine import CoreEngine
from backend.core.entity import BaseEntity
from backend.core.traits import BaseTrait, TraitExecutor

__all__ = ["CoreEngine", "BaseEntity", "BaseTrait", "TraitExecutor"]
