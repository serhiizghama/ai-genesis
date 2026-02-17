"""Architect Agent — designs biological adaptations in response to anomalies.

Listens to evolution triggers, analyzes the problem, and creates evolution plans.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Optional

import structlog

from backend.agents.llm_client import LLMClient
from backend.bus.channels import Channels
from backend.bus.events import EvolutionPlan, EvolutionTrigger, FeedMessage

if TYPE_CHECKING:
    from backend.agents.cycle_manager import EvolutionCycleManager
    from backend.bus.event_bus import EventBus
    from backend.config import Settings

logger = structlog.get_logger()


class ArchitectAgent:
    """Agent that designs evolutionary solutions to detected problems.

    Listens to evolution triggers from the Watcher, uses LLM to design
    biological adaptations (traits), and publishes evolution plans.
    """

    def __init__(
        self,
        event_bus: EventBus,
        llm_client: LLMClient,
        settings: Settings,
        cycle_manager: Optional[EvolutionCycleManager] = None,
    ) -> None:
        """Initialize the Architect Agent.

        Args:
            event_bus: Event bus for pub/sub communication.
            llm_client: LLM client for generating solutions.
            settings: Application settings.
            cycle_manager: Optional cycle manager for mutex-based serialisation.
        """
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.settings = settings
        self.cycle_manager = cycle_manager

    async def run(self) -> None:
        """Start listening to evolution triggers.

        This is the main loop that processes triggers and creates plans.
        """
        logger.info("architect_agent_starting")

        async def handle_trigger(event: EvolutionTrigger) -> None:
            """Handle evolution trigger event.

            Args:
                event: The evolution trigger to process.
            """
            logger.info(
                "architect_received_trigger",
                trigger_id=event.trigger_id,
                problem_type=event.problem_type,
                severity=event.severity,
            )

            # Acquire cycle lock — reject if another cycle is running
            if self.cycle_manager is not None:
                acquired = await self.cycle_manager.start_cycle(event)
                if not acquired:
                    logger.warning(
                        "architect_trigger_rejected_cycle_locked",
                        trigger_id=event.trigger_id,
                    )
                    await self.event_bus.publish(
                        Channels.FEED,
                        FeedMessage(
                            agent="architect",
                            action="skipped",
                            message="⏳ Архитектор: Цикл эволюции уже запущен, пропускаю триггер.",
                            metadata={"trigger_id": event.trigger_id},
                        ),
                    )
                    return

            # Send feed message about starting work
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="architect",
                    action="analyzing",
                    message=f"🧠 Архитектор: Анализирую проблему '{event.problem_type}'...",
                    metadata={"trigger_id": event.trigger_id},
                ),
            )

            # Generate evolution plan
            plan = await self._create_plan(event)

            if plan is None:
                logger.warning(
                    "architect_plan_failed",
                    trigger_id=event.trigger_id,
                )
                await self.event_bus.publish(
                    Channels.FEED,
                    FeedMessage(
                        agent="architect",
                        action="failed",
                        message="❌ Архитектор: Не удалось создать план эволюции.",
                        metadata={"trigger_id": event.trigger_id},
                    ),
                )
                if self.cycle_manager is not None:
                    await self.cycle_manager.fail_cycle("LLM plan generation failed")
                return

            # Publish the plan
            await self.event_bus.publish(Channels.EVOLUTION_PLAN, plan)

            logger.info(
                "architect_plan_created",
                plan_id=plan.plan_id,
                action_type=plan.action_type,
            )

            # Advance cycle stage to "coding" (Coder picks it up next)
            if self.cycle_manager is not None:
                await self.cycle_manager.update_stage("coding")

            # Send success feed message
            await self.event_bus.publish(
                Channels.FEED,
                FeedMessage(
                    agent="architect",
                    action="plan_created",
                    message=f"✅ Архитектор: Создан план — {plan.description}",
                    metadata={
                        "plan_id": plan.plan_id,
                        "action_type": plan.action_type,
                    },
                ),
            )

        # Subscribe to evolution triggers
        await self.event_bus.subscribe(
            Channels.EVOLUTION_TRIGGER,
            handle_trigger,
            EvolutionTrigger,
        )

        logger.info("architect_subscribed", channel=Channels.EVOLUTION_TRIGGER)

        # Keep agent alive - handlers will be called by EventBus
        while True:
            await asyncio.sleep(60)  # Sleep to keep task alive

    async def _create_plan(self, trigger: EvolutionTrigger) -> EvolutionPlan | None:
        """Create an evolution plan for the given trigger.

        Args:
            trigger: The evolution trigger containing problem details.

        Returns:
            EvolutionPlan if successful, None if LLM fails.
        """
        # Build context about the problem
        problem_context = self._build_problem_context(trigger)

        # Create system prompt
        system_prompt = """You are an AI architect designing biological adaptations for digital creatures.
Your task is to design new traits that help creatures survive in their environment.

Traits are Python classes that modify entity behavior. They can:
- Change movement patterns
- Optimize energy usage
- Improve resource gathering
- Enable cooperation or competition

Design creative, simple solutions that address the specific problem."""

        # Create user prompt
        user_prompt = f"""Problem detected:
- Type: {trigger.problem_type}
- Severity: {trigger.severity}
- Affected entities: {len(trigger.affected_entities)}

{problem_context}

Design a new biological trait to solve this problem.

Respond with JSON in this format:
{{
    "trait_name": "descriptive_name_in_snake_case",
    "description": "brief description of what the trait does and how it solves the problem",
    "action_type": "new_trait"
}}

Keep trait names simple and descriptive (e.g., "heat_resistance", "food_seeker", "energy_saver")."""

        # Call LLM
        result = await self.llm_client.generate_json(
            prompt=user_prompt,
            schema={
                "trait_name": "string",
                "description": "string",
                "action_type": "string",
            },
        )

        if result is None:
            logger.error("architect_llm_failed", trigger_id=trigger.trigger_id)
            return None

        # Validate response has required fields
        if not all(key in result for key in ["trait_name", "description"]):
            logger.error(
                "architect_invalid_response",
                trigger_id=trigger.trigger_id,
                response=result,
            )
            return None

        # Create evolution plan
        plan = EvolutionPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            action_type=result.get("action_type", "new_trait"),
            description=result["description"],
            target_class=result.get("trait_name"),
        )

        return plan

    def _build_problem_context(self, trigger: EvolutionTrigger) -> str:
        """Build context string about the problem.

        Args:
            trigger: The evolution trigger.

        Returns:
            Formatted context string.
        """
        context_parts = []

        if trigger.problem_type == "starvation":
            context_parts.append(
                "Entities are running low on energy. They need better strategies "
                "for finding and consuming resources, or reducing energy consumption."
            )
        elif trigger.problem_type == "extinction":
            context_parts.append(
                "Population is critically low. Entities need survival traits "
                "to avoid death and reproduce more efficiently."
            )
        elif trigger.problem_type == "overpopulation":
            context_parts.append(
                "Too many entities competing for resources. Need traits that "
                "improve resource efficiency or territorial behavior."
            )
        elif trigger.problem_type == "manual_trigger":
            context_parts.append(
                "Manual evolution trigger activated. Design an innovative trait "
                "to improve overall fitness and adaptability."
            )

        if trigger.suggested_area:
            context_parts.append(f"Suggested focus area: {trigger.suggested_area}")

        return "\n".join(context_parts)
