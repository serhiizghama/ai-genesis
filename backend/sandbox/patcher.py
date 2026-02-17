"""Runtime code patcher with hot-reload and rollback capabilities.

This module provides safe hot-reloading of LLM-generated Trait mutations
during simulation runtime. It validates, loads, and registers new code
while handling failures gracefully.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Type

import structlog

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import FeedMessage, MutationApplied, MutationFailed, MutationReady
from backend.core.dynamic_registry import DynamicRegistry
from backend.core.traits import BaseTrait
from backend.sandbox.validator import CodeValidator, ValidationResult

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()


class RuntimePatcher:
    """Hot-reload patcher for dynamically loading Trait mutations.

    The patcher listens for MutationReady events, validates the code,
    loads it as a Python module, and registers the new Trait class
    in the DynamicRegistry. If any step fails, it publishes MutationFailed
    and leaves the registry unchanged.

    This implements a simple rollback mechanism: if module loading or
    registration fails, the registry remains in its previous state.
    """

    def __init__(
        self,
        event_bus: EventBus,
        registry: DynamicRegistry,
        validator: CodeValidator,
    ) -> None:
        """Initialize the runtime patcher.

        Args:
            event_bus: EventBus for listening to MutationReady events
            registry: DynamicRegistry for registering new trait classes
            validator: CodeValidator for double-checking mutations
        """
        self._event_bus = event_bus
        self._registry = registry
        self._validator = validator
        self._registry_version = 0

    async def run(self) -> None:
        """Start listening for MutationReady events.

        This method subscribes to the mutation channel and should be
        run as a background task.
        """
        await self._event_bus.subscribe(Channels.MUTATION_READY, self._handle_mutation_ready)
        logger.info("runtime_patcher_listening", channel=Channels.MUTATION_READY)

    async def _handle_mutation_ready(self, event_data: dict[str, object]) -> None:
        """Handle incoming MutationReady event.

        Args:
            event_data: Deserialized MutationReady event data
        """
        mutation_id = str(event_data.get("mutation_id", "unknown"))
        file_path = str(event_data.get("file_path", ""))
        trait_name = str(event_data.get("trait_name", ""))
        version = int(event_data.get("version", 0))
        cycle_id = str(event_data.get("cycle_id", ""))

        logger.info(
            "mutation_ready_received",
            mutation_id=mutation_id,
            cycle_id=cycle_id,
            file_path=file_path,
            trait_name=trait_name,
            version=version,
        )

        # Step 1: Validate the file (double-check)
        try:
            validation_result = await self._validate_mutation(file_path)
            if not validation_result:
                # Validation failed, _validate_mutation already published MutationFailed
                await self._publish_feed_failure(
                    mutation_id=mutation_id,
                    trait_name=trait_name,
                    version=version,
                    cycle_id=cycle_id,
                    error="Validation failed",
                    rollback_to=None,
                )
                return
        except Exception as exc:
            logger.error(
                "validation_exception",
                mutation_id=mutation_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._publish_failure(
                mutation_id=mutation_id,
                error=f"Validation exception: {exc}",
                stage="validation",
            )
            await self._publish_feed_failure(
                mutation_id=mutation_id,
                trait_name=trait_name,
                version=version,
                cycle_id=cycle_id,
                error=f"Validation exception: {exc}",
                rollback_to=None,
            )
            return

        # Step 2: Load the module
        try:
            trait_class = self._load_module(file_path, validation_result.trait_class_name)
            if not trait_class:
                # Loading failed, _load_module already published MutationFailed
                await self._publish_feed_failure(
                    mutation_id=mutation_id,
                    trait_name=trait_name,
                    version=version,
                    cycle_id=cycle_id,
                    error="Module load failed",
                    rollback_to=None,
                )
                return
        except Exception as exc:
            logger.error(
                "module_load_exception",
                mutation_id=mutation_id,
                file_path=file_path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._publish_failure(
                mutation_id=mutation_id,
                error=f"Module load exception: {exc}",
                stage="import",
            )
            await self._publish_feed_failure(
                mutation_id=mutation_id,
                trait_name=trait_name,
                version=version,
                cycle_id=cycle_id,
                error=f"Module load exception: {exc}",
                rollback_to=None,
            )
            return

        # Step 3: Register the trait class
        try:
            self._registry.register(trait_name, trait_class)
            self._registry_version += 1

            # Store source code in registry so the API can serve it
            source_code = Path(file_path).read_text()
            self._registry.register_source(trait_name, source_code)

            # Mark the mutation as used in validator to prevent duplicates
            if validation_result.code_hash:
                await self._validator.mark_as_used(validation_result.code_hash)

            logger.info(
                "mutation_applied_success",
                mutation_id=mutation_id,
                cycle_id=cycle_id,
                trait_name=trait_name,
                version=version,
                registry_version=self._registry_version,
            )

            # Publish typed success event
            await self._event_bus.publish(
                Channels.MUTATION_APPLIED,
                MutationApplied(
                    mutation_id=mutation_id,
                    trait_name=trait_name,
                    version=version,
                    registry_version=self._registry_version,
                ),
            )

            # Publish success feed message per spec section 2.2
            await self._event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="patcher",
                    action="mutation_applied",
                    message=f"Мутация {trait_name} v{version} успешно применена",
                    metadata={
                        "cycle_id": cycle_id,
                        "mutation": {
                            "mutation_id": mutation_id,
                            "trait_name": trait_name,
                            "version": version,
                        },
                        "registry": {
                            "registry_version": self._registry_version,
                            "rollback_to": None,
                        },
                    },
                ),
            )

        except Exception as exc:
            logger.error(
                "registration_exception",
                mutation_id=mutation_id,
                trait_name=trait_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._publish_failure(
                mutation_id=mutation_id,
                error=f"Registration exception: {exc}",
                stage="execution",
            )
            await self._publish_feed_failure(
                mutation_id=mutation_id,
                trait_name=trait_name,
                version=version,
                cycle_id=cycle_id,
                error=f"Registration exception: {exc}",
                rollback_to=None,
            )

    async def _validate_mutation(self, file_path: str) -> Optional[ValidationResult]:
        """Re-validate the mutation file as a security double-check.

        Args:
            file_path: Path to the mutation file

        Returns:
            ValidationResult if valid, None if invalid
        """
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error("mutation_file_not_found", file_path=file_path)
                await self._publish_failure(
                    mutation_id="unknown",
                    error=f"File not found: {file_path}",
                    stage="validation",
                )
                return None

            source_code = path.read_text()
            result = await self._validator.validate(source_code)

            if not result.is_valid:
                logger.warning(
                    "mutation_validation_failed",
                    file_path=file_path,
                    error=result.error,
                )
                await self._publish_failure(
                    mutation_id="unknown",
                    error=result.error or "Validation failed",
                    stage="validation",
                )
                return None

            return result

        except Exception as exc:
            logger.error(
                "validation_read_error",
                file_path=file_path,
                error=str(exc),
            )
            await self._publish_failure(
                mutation_id="unknown",
                error=f"Failed to read file: {exc}",
                stage="validation",
            )
            return None

    def _load_module(
        self,
        file_path: str,
        trait_class_name: Optional[str],
    ) -> Optional[Type[BaseTrait]]:
        """Load a Python module from file and extract the Trait class.

        Args:
            file_path: Path to the Python file
            trait_class_name: Name of the Trait class to extract

        Returns:
            The Trait class if successful, None otherwise

        Note:
            This method uses importlib.util to load modules from file paths.
            If the module raises an exception during import, that's caught
            and treated as a failure (simple rollback).
        """
        try:
            path = Path(file_path)
            module_name = f"mutation_{path.stem}"

            # If module was previously loaded, remove it to force reload
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Load module using importlib.util
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                logger.error(
                    "module_spec_failed",
                    file_path=file_path,
                    error="Could not create module spec",
                )
                return None

            module = importlib.util.module_from_spec(spec)

            # Execute the module (this runs the code)
            # If code has errors, exec_module will raise an exception
            spec.loader.exec_module(module)

            # Extract the trait class
            if not trait_class_name:
                logger.error(
                    "no_trait_class_name",
                    file_path=file_path,
                )
                return None

            trait_class = getattr(module, trait_class_name, None)
            if not trait_class:
                logger.error(
                    "trait_class_not_found",
                    file_path=file_path,
                    class_name=trait_class_name,
                )
                return None

            logger.info(
                "module_loaded_success",
                file_path=file_path,
                class_name=trait_class_name,
            )

            return trait_class  # type: ignore

        except Exception as exc:
            logger.error(
                "module_load_failed",
                file_path=file_path,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # Return None - registry not updated (rollback)
            return None

    async def _publish_feed_failure(
        self,
        mutation_id: str,
        trait_name: str,
        version: int,
        cycle_id: str,
        error: str,
        rollback_to: Optional[str],
    ) -> None:
        """Publish a failure FeedMessage with spec-compliant metadata.

        Args:
            mutation_id: ID of the failed mutation.
            trait_name: Trait name (may be empty if unavailable).
            version: Trait version number.
            cycle_id: Evolution cycle ID.
            error: Human-readable error description.
            rollback_to: Optional mutation_id rolled back to, or None.
        """
        label = f"{trait_name} v{version}" if trait_name else mutation_id
        await self._event_bus.publish(
            Channels.FEED,
            FeedMessage(
                agent="patcher",
                action="mutation_failed",
                message=f"Ошибка при применении мутации {label}",
                metadata={
                    "cycle_id": cycle_id,
                    "mutation": {
                        "mutation_id": mutation_id,
                        "trait_name": trait_name,
                        "version": version,
                    },
                    "registry": {
                        "registry_version": self._registry_version,
                        "rollback_to": rollback_to,
                    },
                    "error": error,
                },
            ),
        )

    async def _publish_failure(
        self,
        mutation_id: str,
        error: str,
        stage: str,
    ) -> None:
        """Publish a MutationFailed event.

        Args:
            mutation_id: ID of the failed mutation
            error: Error message
            stage: Stage where failure occurred ('validation', 'import', 'execution')
        """
        await self._event_bus.publish(
            Channels.MUTATION_FAILED,
            MutationFailed(
                mutation_id=mutation_id,
                error=error,
                stage=stage,
            ),
        )
        logger.warning(
            "mutation_failed_published",
            mutation_id=mutation_id,
            stage=stage,
            error=error,
        )
