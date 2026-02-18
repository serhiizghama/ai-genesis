"""Coder Agent — generates Python code for new traits.

Listens to evolution plans, generates trait code using LLM, validates,
and saves to mutations directory.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING, Optional

import structlog

from backend.agents.entity_api import ALLOWED_ENTITY_ATTRS, ENTITY_API_TEXT
from backend.agents.llm_client import LLMClient, extract_code_block
from backend.bus.channels import Channels
from backend.bus.events import EvolutionPlan, FeedMessage, MutationReady
from backend.sandbox.mutations_registry import MutationRegistry

if TYPE_CHECKING:
    import asyncpg
    from backend.bus.event_bus import EventBus
    from backend.config import Settings
    from backend.sandbox.validator import CodeValidator

logger = structlog.get_logger()

_SNIPPET_MAX_LINES: int = 20


def _extract_snippet(file_path: str) -> str:
    """Read the first N lines from a generated code file for feed display.

    Args:
        file_path: Path to the Python file on disk.

    Returns:
        Stripped string of up to _SNIPPET_MAX_LINES lines, or "" on error.
    """
    try:
        with open(file_path) as fh:
            lines: list[str] = []
            for i, line in enumerate(fh):
                if i >= _SNIPPET_MAX_LINES:
                    break
                lines.append(line)
        return "".join(lines).strip()
    except OSError:
        return ""


class CoderAgent:
    """Agent that generates Python code for new traits.

    Listens to evolution plans, uses LLM to write code, validates it,
    and saves to the mutations directory.
    """

    def __init__(
        self,
        event_bus: EventBus,
        llm_client: LLMClient,
        validator: CodeValidator,
        settings: Settings,
        mutation_registry: Optional[MutationRegistry] = None,
        db_pool: Optional[asyncpg.Pool] = None,
    ) -> None:
        """Initialize the Coder Agent.

        Args:
            event_bus: Event bus for pub/sub communication.
            llm_client: LLM client for generating code.
            validator: Code validator for safety checks.
            settings: Application settings.
            mutation_registry: Optional registry to persist mutations to Redis.
        """
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.validator = validator
        self.settings = settings
        self.mutation_registry = mutation_registry
        self.db_pool = db_pool
        self.mutation_counter = 0

    async def run(self) -> None:
        """Start listening to evolution plans.

        This is the main loop that processes plans and generates code.
        """
        logger.info("coder_agent_starting")

        async def handle_plan(event: EvolutionPlan) -> None:
            """Handle evolution plan event.

            Args:
                event: The evolution plan to implement.
            """
            cycle_id = event.cycle_id

            logger.info(
                "coder_received_plan",
                plan_id=event.plan_id,
                cycle_id=cycle_id,
                action_type=event.action_type,
            )

            # Send feed message about starting work
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="coder",
                    action="coding",
                    message=f"💻 Кодер: Пишу код для '{event.target_class}'...",
                    metadata={"cycle_id": cycle_id, "plan_id": event.plan_id},
                ),
            )

            # Generate code
            mutation = await self._generate_and_save_code(event)

            if mutation is None:
                logger.warning("coder_generation_failed", plan_id=event.plan_id)
                await self.event_bus.publish(
                    Channels.FEED,
                    FeedMessage(
                        agent="coder",
                        action="failed",
                        message="❌ Кодер: Не удалось сгенерировать код.",
                        metadata={"cycle_id": cycle_id, "plan_id": event.plan_id},
                    ),
                )
                return

            # Publish mutation ready event (carries cycle_id to Patcher)
            await self.event_bus.publish(Channels.MUTATION_READY, mutation)

            logger.info(
                "coder_mutation_ready",
                mutation_id=mutation.mutation_id,
                cycle_id=cycle_id,
                file_path=mutation.file_path,
            )

            # Read code snippet (first 20 lines) from the saved file
            snippet = _extract_snippet(mutation.file_path)

            # Publish detailed feed message per spec section 2.2
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="coder",
                    action="mutation_ready",
                    message=f"Сгенерирован код для мутации {mutation.trait_name} v{mutation.version}",
                    metadata={
                        "cycle_id": cycle_id,
                        "mutation": {
                            "mutation_id": mutation.mutation_id,
                            "trait_name": mutation.trait_name,
                            "version": mutation.version,
                            "file_path": mutation.file_path,
                        },
                        "code": {
                            "snippet": snippet,
                            "validation_errors": None,
                        },
                    },
                ),
            )

        # Subscribe to evolution plans
        await self.event_bus.subscribe(
            Channels.EVOLUTION_PLAN,
            handle_plan,
            EvolutionPlan,
        )

        logger.info("coder_subscribed", channel=Channels.EVOLUTION_PLAN)

        # Keep agent alive - handlers will be called by EventBus
        while True:
            await asyncio.sleep(60)  # Sleep to keep task alive

    async def _generate_and_save_code(
        self,
        plan: EvolutionPlan,
    ) -> MutationReady | None:
        """Generate code for the plan and save to file.

        Args:
            plan: The evolution plan to implement.

        Returns:
            MutationReady event if successful, None if generation/validation failed.
        """
        # Determine trait name
        trait_name = plan.target_class or "adaptive_behavior"

        # Generate code
        code = await self._generate_code(
            trait_name, plan.description, world_context=plan.world_context
        )

        if code is None:
            return None

        # Validate code
        validation_result = await self.validator.validate(code)

        if not validation_result.is_valid:
            logger.warning(
                "coder_validation_failed_retrying",
                plan_id=plan.plan_id,
                error=validation_result.error,
            )

            # Retry once with the validation error included in the prompt
            code = await self._generate_code(
                trait_name,
                plan.description,
                previous_error=validation_result.error,
                world_context=plan.world_context,
            )

            if code is None:
                logger.error("coder_retry_llm_failed", plan_id=plan.plan_id)
                return None

            validation_result = await self.validator.validate(code)

            if not validation_result.is_valid:
                validation_error = validation_result.error or "Validation failed"
                logger.error(
                    "coder_validation_failed_after_retry",
                    plan_id=plan.plan_id,
                    error=validation_error,
                )
                # Publish validation error to feed before returning
                await self.event_bus.publish(
                    Channels.FEED,
                    FeedMessage(
                        agent="coder",
                        action="validation_failed",
                        message=f"❌ Кодер: Код не прошёл валидацию для '{trait_name}'.",
                        metadata={
                            "cycle_id": plan.cycle_id,
                            "code": {
                                "validation_errors": validation_error,
                            },
                        },
                    ),
                )
                return None

        # Increment version
        self.mutation_counter += 1
        version = self.mutation_counter

        # Save to file
        filename = f"trait_{trait_name}_v{version}.py"
        file_path = os.path.join(self.settings.mutations_dir, filename)

        try:
            os.makedirs(self.settings.mutations_dir, exist_ok=True)

            with open(file_path, "w") as f:
                f.write(code)

            logger.info(
                "coder_file_saved",
                file_path=file_path,
                trait_name=trait_name,
                version=version,
            )

        except Exception as exc:
            logger.error(
                "coder_file_save_failed",
                file_path=file_path,
                error=str(exc),
            )
            return None

        # Create mutation ready event (carries cycle_id to Patcher)
        mutation = MutationReady(
            mutation_id=f"mut_{uuid.uuid4().hex[:8]}",
            plan_id=plan.plan_id,
            file_path=file_path,
            trait_name=validation_result.trait_class_name or trait_name,
            version=version,
            code_hash=validation_result.code_hash,
            cycle_id=plan.cycle_id,
        )

        # Persist to mutation registry if available
        if self.mutation_registry is not None:
            await self.mutation_registry.save(
                mutation_id=mutation.mutation_id,
                trait_name=mutation.trait_name,
                version=version,
                file_path=file_path,
                code_hash=mutation.code_hash,
                cycle_id=plan.cycle_id,
                source_code=code,
            )

        # Persist to PostgreSQL
        if self.db_pool is not None:
            try:
                from backend.db.repository import save_mutation
                await save_mutation(self.db_pool, {
                    "mutation_id": mutation.mutation_id,
                    "trait_name": mutation.trait_name,
                    "version": version,
                    "code_hash": mutation.code_hash,
                    "source_code": code,
                    "cycle_id": plan.cycle_id,
                    "trigger_type": plan.action_type,
                    "status": "pending",
                })
            except Exception as exc:
                logger.warning("coder_pg_save_failed", mutation_id=mutation.mutation_id, error=str(exc))

        return mutation

    async def _generate_code(
        self,
        trait_name: str,
        description: str,
        previous_error: str | None = None,
        world_context: dict | None = None,
    ) -> str | None:
        """Generate Python code for the trait.

        Args:
            trait_name: Name of the trait to generate.
            description: Description of what the trait should do.
            previous_error: Validation error from a previous attempt, if retrying.
            world_context: Current world state to guide code generation.

        Returns:
            Generated Python code or None if LLM fails.
        """
        # Create system prompt
        system_prompt = """You are an expert Python developer creating behavior code for digital creatures.
You must write clean, safe, efficient Python code that follows the BaseTrait protocol.

CRITICAL RULES:
1. Class MUST inherit from BaseTrait (not just any name)
2. Class MUST have async def execute(self, entity) method
3. Only use allowed imports: math, random, typing
4. If you use ANY module (e.g. math, random), you MUST add the import at the top of the file
5. NEVER use @dataclasses.dataclass decorator — use a plain class only
6. NO file I/O, NO network, NO eval/exec
7. Keep code simple and efficient (runs every tick)
8. Code must complete in under 5ms

""" + ENTITY_API_TEXT

        # Prefix the prompt with the previous error if this is a retry
        retry_prefix = ""
        if previous_error:
            if "Forbidden entity attribute" in previous_error:
                allowed = ", ".join(sorted(ALLOWED_ENTITY_ATTRS))
                retry_prefix = (
                    f"PREVIOUS ATTEMPT FAILED: {previous_error}\n"
                    f"You used an attribute that does NOT exist on the entity object. "
                    f"ONLY use these: {allowed}\n"
                    "Do NOT invent new attributes. If you need custom state, store it in entity.traits.\n\n"
                )
            elif "Forbidden import" in previous_error or "import" in previous_error.lower():
                retry_prefix = (
                    f"PREVIOUS ATTEMPT FAILED: {previous_error}\n"
                    "Only allowed imports: math, random, typing, dataclasses, enum, collections.\n\n"
                )
            elif "await entity." in previous_error or "synchronous" in previous_error:
                retry_prefix = (
                    f"PREVIOUS ATTEMPT FAILED: {previous_error}\n"
                    "Entity methods (move, eat_nearby, attack_nearby, is_alive, etc.) are SYNCHRONOUS. "
                    "Call them WITHOUT await: entity.eat_nearby(), entity.move(dx, dy)\n\n"
                )
            elif "Forbidden call" in previous_error:
                retry_prefix = (
                    f"PREVIOUS ATTEMPT FAILED: {previous_error}\n"
                    "Do NOT use eval, exec, open, print, globals, locals or any system calls.\n\n"
                )
            else:
                retry_prefix = (
                    f"PREVIOUS ATTEMPT FAILED: {previous_error}\n"
                    "Fix the issue and try again.\n\n"
                )

        # Prepend world context if available
        world_prefix = ""
        if world_context:
            wc = world_context
            world_prefix = (
                f"World context: {wc.get('entity_count')} entities alive, "
                f"avg_energy={wc.get('avg_energy')}, "
                f"resources={wc.get('resource_count')} available.\n"
                f"Design the trait to be effective under these conditions.\n\n"
            )

        # Create user prompt
        user_prompt = world_prefix + retry_prefix + f"""Create a Python trait class named '{trait_name}' that implements this behavior:

{description}

Requirements:
- Class name: {trait_name} (convert to PascalCase if needed)
- Must inherit from BaseTrait
- Must implement: async def execute(self, entity) -> None
- ONLY use: math, random (import them at the top if needed)
- NEVER use @dataclasses.dataclass — plain class only
- entity.state is a str ("alive"/"dead"), NOT a dict
- Do NOT use entity.world or create new entities
- Do NOT modify entity.energy to add energy — use eat_nearby() only

Example structure:
```python
from __future__ import annotations

import math
import random

class BaseTrait:
    \"\"\"Base trait protocol.\"\"\"
    pass

class {trait_name}(BaseTrait):
    \"\"\"Description of what this trait does.\"\"\"

    async def execute(self, entity) -> None:
        # entity has: id, x, y, energy, max_energy, age, traits, state (str)
        # To gain energy: entity.eat_nearby(radius=30.0) -> bool
        # To move: entity.move(dx, dy)
        pass
```

Write ONLY the Python code, no explanations."""

        # Call LLM
        response = await self.llm_client.generate(
            prompt=user_prompt,
            system=system_prompt,
        )

        if response is None:
            logger.error("coder_llm_failed", trait_name=trait_name)
            return None

        # Extract code from markdown
        code = extract_code_block(response, "python")

        if code is None:
            # If no code block found, try using raw response
            code = response.strip()

        logger.info(
            "coder_code_generated",
            trait_name=trait_name,
            code_length=len(code),
        )

        return code
