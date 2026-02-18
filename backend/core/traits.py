"""Trait system — protocol and executor for entity behaviors."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Optional, Protocol

import structlog

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

logger = structlog.get_logger()


class BaseTrait(Protocol):
    """Protocol defining the interface for all Traits.

    All LLM-generated mutations must implement this protocol.
    """

    async def execute(self, entity: BaseEntity) -> None:
        """Execute the trait's behavior on an entity.

        Args:
            entity: The entity to modify or interact with.

        Note:
            This method MUST complete within the configured timeout
            (default 5ms) or it will be forcibly cancelled.
        """
        ...


class TraitExecutor:
    """Executor for running traits with timeout protection and error handling.

    Ensures that misbehaving traits (timeouts, exceptions) don't crash
    the simulation loop.
    """

    def __init__(
        self,
        timeout_sec: float,
        tick_budget_sec: float,
        on_trait_error: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        """Initialize the trait executor.

        Args:
            timeout_sec: Hard timeout per trait execution (e.g., 0.005 = 5ms).
            tick_budget_sec: Total time budget for all trait executions in a tick (e.g., 0.014 = 14ms).
            on_trait_error: Optional callback(entity_id, trait_name, error_str) called on first
                            error per trait_name. Used by the engine to publish errors to the feed.
        """
        self.timeout_sec = timeout_sec
        self.tick_budget_sec = tick_budget_sec
        self.on_trait_error = on_trait_error

    async def execute_trait(
        self,
        trait: BaseTrait,
        entity: BaseEntity,
    ) -> bool:
        """Execute a single trait with timeout protection.

        Args:
            trait: The trait instance to execute.
            entity: The entity to pass to the trait.

        Returns:
            bool: True if execution succeeded, False if it failed or timed out.

        Note:
            Failures are logged but don't raise exceptions.
        """
        trait_name = trait.__class__.__name__

        try:
            await asyncio.wait_for(
                trait.execute(entity),
                timeout=self.timeout_sec,
            )
            return True

        except asyncio.TimeoutError:
            logger.warning(
                "trait_timeout",
                trait=trait_name,
                entity_id=entity.id,
                timeout_sec=self.timeout_sec,
            )
            return False

        except Exception as exc:
            error_str = str(exc)
            logger.error(
                "trait_error",
                trait=trait_name,
                entity_id=entity.id,
                error=error_str,
                error_type=type(exc).__name__,
            )
            if self.on_trait_error is not None:
                self.on_trait_error(entity.id, trait_name, error_str)
            return False

    async def execute_traits(
        self,
        entity: BaseEntity,
    ) -> None:
        """Execute all active traits for an entity with tick budget protection.

        Args:
            entity: The entity whose traits should be executed.

        Note:
            If a trait times out or raises an exception, it's added to the
            entity's deactivated_traits set to prevent repeated failures.
        """
        if not entity.traits:
            return

        tick_start = asyncio.get_event_loop().time()

        for trait in entity.traits:
            # Check if we've exceeded tick budget
            elapsed = asyncio.get_event_loop().time() - tick_start
            if elapsed >= self.tick_budget_sec:
                logger.warning(
                    "tick_budget_exceeded",
                    entity_id=entity.id,
                    elapsed_sec=elapsed,
                    budget_sec=self.tick_budget_sec,
                )
                break

            # Skip deactivated traits
            trait_name = trait.__class__.__name__
            if trait_name in entity.deactivated_traits:
                continue

            # Execute trait
            success = await self.execute_trait(trait, entity)

            # Deactivate trait on failure
            if not success:
                entity.deactivated_traits.add(trait_name)
                logger.info(
                    "trait_deactivated",
                    trait=trait_name,
                    entity_id=entity.id,
                )
