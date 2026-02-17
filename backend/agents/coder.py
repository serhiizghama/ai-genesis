"""Coder Agent — generates Python code for new traits.

Listens to evolution plans, generates trait code using LLM, validates,
and saves to mutations directory.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING

import structlog

from backend.agents.llm_client import LLMClient, extract_code_block
from backend.bus.channels import Channels
from backend.bus.events import EvolutionPlan, FeedMessage, MutationReady

if TYPE_CHECKING:
    from backend.bus.event_bus import EventBus
    from backend.config import Settings
    from backend.sandbox.validator import CodeValidator

logger = structlog.get_logger()


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
    ) -> None:
        """Initialize the Coder Agent.

        Args:
            event_bus: Event bus for pub/sub communication.
            llm_client: LLM client for generating code.
            validator: Code validator for safety checks.
            settings: Application settings.
        """
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.validator = validator
        self.settings = settings
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
            logger.info(
                "coder_received_plan",
                plan_id=event.plan_id,
                action_type=event.action_type,
            )

            # Send feed message about starting work
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="coder",
                    action="coding",
                    message=f"💻 Кодер: Пишу код для '{event.target_class}'...",
                    metadata={"plan_id": event.plan_id},
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
                        metadata={"plan_id": event.plan_id},
                    ),
                )
                return

            # Publish mutation ready event
            await self.event_bus.publish(Channels.MUTATION_READY, mutation)

            logger.info(
                "coder_mutation_ready",
                mutation_id=mutation.mutation_id,
                file_path=mutation.file_path,
            )

            # Send success feed message
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="coder",
                    action="mutation_ready",
                    message=f"✅ Кодер: Код готов, отправляю на проверку...",
                    metadata={
                        "mutation_id": mutation.mutation_id,
                        "trait_name": mutation.trait_name,
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
        code = await self._generate_code(trait_name, plan.description)

        if code is None:
            return None

        # Validate code
        validation_result = await self.validator.validate(code)

        if not validation_result.is_valid:
            logger.error(
                "coder_validation_failed",
                plan_id=plan.plan_id,
                error=validation_result.error,
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

        # Create mutation ready event
        mutation = MutationReady(
            mutation_id=f"mut_{uuid.uuid4().hex[:8]}",
            plan_id=plan.plan_id,
            file_path=file_path,
            trait_name=validation_result.trait_class_name or trait_name,
            version=version,
            code_hash=validation_result.code_hash,
        )

        return mutation

    async def _generate_code(self, trait_name: str, description: str) -> str | None:
        """Generate Python code for the trait.

        Args:
            trait_name: Name of the trait to generate.
            description: Description of what the trait should do.

        Returns:
            Generated Python code or None if LLM fails.
        """
        # Create system prompt
        system_prompt = """You are an expert Python developer creating behavior code for digital creatures.
You must write clean, safe, efficient Python code that follows the BaseTrait protocol.

CRITICAL RULES:
1. Class MUST inherit from BaseTrait (not just any name)
2. Class MUST have async def execute(self, entity) method
3. Only use allowed imports: math, random, dataclasses, typing, enum, collections, functools, itertools
4. NO file I/O, NO network, NO eval/exec
5. Keep code simple and efficient (runs every tick)
6. Code must complete in under 5ms

The entity parameter has these attributes:
- id: str
- x, y: float (position)
- energy: float (current energy)
- max_energy: float
- age: int (in ticks)
- traits: list (other traits)
- state: dict (for storing data)

Entity methods:
- move(dx, dy): move entity
- consume_resource(resource): eat resource, gain energy"""

        # Create user prompt
        user_prompt = f"""Create a Python trait class named '{trait_name}' that implements this behavior:

{description}

Requirements:
- Class name: {trait_name} (convert to PascalCase if needed)
- Must inherit from BaseTrait
- Must implement: async def execute(self, entity) -> None
- Use only allowed imports from: math, random, typing
- Keep it simple and efficient

Example structure:
```python
from __future__ import annotations

import math

class BaseTrait:
    \"\"\"Base trait protocol.\"\"\"
    pass

class {trait_name}(BaseTrait):
    \"\"\"Description of what this trait does.\"\"\"

    async def execute(self, entity) -> None:
        # Your implementation here
        # entity has: id, x, y, energy, max_energy, age, traits, state
        # entity methods: move(dx, dy), consume_resource(resource)
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
