"""Core simulation engine — world loop, entities, physics, traits."""

from backend.core.entity import BaseEntity
from backend.core.traits import BaseTrait, TraitExecutor

__all__ = ["BaseEntity", "BaseTrait", "TraitExecutor"]
