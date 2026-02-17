"""Tests for AI agents with mocked LLM responses.

Tests the full chain: Trigger -> Architect -> Plan -> Coder -> MutationReady
without calling the real Ollama API.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.architect import ArchitectAgent
from backend.agents.coder import CoderAgent
from backend.agents.llm_client import LLMClient, extract_code_block, extract_json
from backend.bus.event_bus import EventBus
from backend.bus.events import EvolutionPlan, EvolutionTrigger, MutationReady
from backend.config import Settings
from backend.sandbox.validator import CodeValidator


class MockLLMClient:
    """Mock LLM client that returns predefined responses."""

    def __init__(self) -> None:
        """Initialize mock client with response queues."""
        self.json_responses: list[dict | None] = []
        self.text_responses: list[str | None] = []
        self.call_count = 0

    async def generate_json(
        self,
        prompt: str,
        schema: dict | None = None,
        model: str | None = None,
    ) -> dict | None:
        """Return next mocked JSON response."""
        self.call_count += 1
        if self.json_responses:
            return self.json_responses.pop(0)
        return None

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
    ) -> str | None:
        """Return next mocked text response."""
        self.call_count += 1
        if self.text_responses:
            return self.text_responses.pop(0)
        return None


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    """Create test settings with temp mutations directory."""
    settings = Settings()
    settings.mutations_dir = str(tmp_path / "mutations")
    return settings


@pytest.fixture
def mock_llm() -> MockLLMClient:
    """Create mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    """Create mock event bus."""
    bus = AsyncMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock()
    return bus


@pytest.fixture
def validator(settings: Settings) -> CodeValidator:
    """Create real code validator."""
    return CodeValidator(settings)


class TestExtractors:
    """Test utility functions for extracting JSON and code."""

    def test_extract_json_from_plain_text(self) -> None:
        """Test extracting JSON from plain text."""
        text = 'Some text before {"key": "value", "num": 42} some text after'
        result = extract_json(text)
        assert result == {"key": "value", "num": 42}

    def test_extract_json_from_markdown(self) -> None:
        """Test extracting JSON from markdown code block."""
        text = '```json\n{"trait_name": "test", "description": "desc"}\n```'
        result = extract_json(text)
        assert result == {"trait_name": "test", "description": "desc"}

    def test_extract_json_pure_json(self) -> None:
        """Test extracting pure JSON."""
        text = '{"key": "value"}'
        result = extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_no_json(self) -> None:
        """Test extracting JSON when none present."""
        text = "This is just plain text with no JSON"
        result = extract_json(text)
        assert result is None

    def test_extract_code_block_python(self) -> None:
        """Test extracting Python code block."""
        text = '```python\nprint("hello")\n```'
        result = extract_code_block(text, "python")
        assert result == 'print("hello")'

    def test_extract_code_block_generic(self) -> None:
        """Test extracting generic code block."""
        text = '```\nsome code\n```'
        result = extract_code_block(text)
        assert result == "some code"

    def test_extract_code_block_no_code(self) -> None:
        """Test extracting code when none present."""
        text = "This is just plain text"
        result = extract_code_block(text)
        assert result is None


class TestArchitectAgent:
    """Test Architect Agent with mocked LLM."""

    @pytest.mark.asyncio
    async def test_architect_creates_plan_from_trigger(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        settings: Settings,
    ) -> None:
        """Test that Architect processes trigger and creates plan."""
        # Setup mock response
        mock_llm.json_responses = [
            {
                "trait_name": "energy_saver",
                "description": "Reduces energy consumption during movement",
                "action_type": "new_trait",
            }
        ]

        # Create architect
        architect = ArchitectAgent(mock_event_bus, mock_llm, settings)  # type: ignore

        # Create trigger
        trigger = EvolutionTrigger(
            trigger_id="test_trigger",
            problem_type="starvation",
            severity="high",
        )

        # Manually call the plan creation
        plan = await architect._create_plan(trigger)

        # Verify plan was created
        assert plan is not None
        assert plan.trigger_id == "test_trigger"
        assert plan.action_type == "new_trait"
        assert plan.target_class == "energy_saver"
        assert "energy consumption" in plan.description

        # Verify LLM was called
        assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_architect_handles_llm_failure(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        settings: Settings,
    ) -> None:
        """Test that Architect handles LLM failure gracefully."""
        # Setup mock to return None (simulating LLM failure)
        mock_llm.json_responses = [None]

        # Create architect
        architect = ArchitectAgent(mock_event_bus, mock_llm, settings)  # type: ignore

        # Create trigger
        trigger = EvolutionTrigger(
            trigger_id="test_trigger",
            problem_type="extinction",
            severity="critical",
        )

        # Try to create plan
        plan = await architect._create_plan(trigger)

        # Verify plan is None (failure handled)
        assert plan is None


class TestCoderAgent:
    """Test Coder Agent with mocked LLM."""

    @pytest.mark.asyncio
    async def test_coder_generates_and_saves_code(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        validator: CodeValidator,
        settings: Settings,
    ) -> None:
        """Test that Coder generates code, validates, and saves file."""
        # Setup mock response with valid trait code
        mock_code = '''from __future__ import annotations

class BaseTrait:
    """Base trait protocol."""
    pass

class EnergySaver(BaseTrait):
    """Reduces energy consumption during movement."""

    async def execute(self, entity) -> None:
        # Reduce movement speed to save energy
        if entity.energy < 50:
            entity.state["movement_speed"] = 0.5
        else:
            entity.state["movement_speed"] = 1.0
'''

        mock_llm.text_responses = [f"```python\n{mock_code}\n```"]

        # Create coder
        coder = CoderAgent(mock_event_bus, mock_llm, validator, settings)  # type: ignore

        # Create plan
        plan = EvolutionPlan(
            plan_id="test_plan",
            trigger_id="test_trigger",
            action_type="new_trait",
            description="Reduce energy consumption",
            target_class="energy_saver",
        )

        # Generate and save code
        mutation = await coder._generate_and_save_code(plan)

        # Verify mutation was created
        assert mutation is not None
        assert mutation.plan_id == "test_plan"
        assert mutation.trait_name == "EnergySaver"
        assert mutation.version == 1
        assert os.path.exists(mutation.file_path)

        # Verify file was created with correct content
        with open(mutation.file_path) as f:
            content = f.read()
            assert "class EnergySaver" in content
            assert "async def execute" in content

        # Verify LLM was called
        assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_coder_handles_invalid_code(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        validator: CodeValidator,
        settings: Settings,
    ) -> None:
        """Test that Coder rejects invalid code."""
        # Setup mock response with invalid code (uses banned import)
        mock_code = '''import os

class BadTrait:
    async def execute(self, entity):
        os.system("rm -rf /")  # NEVER DO THIS
'''

        mock_llm.text_responses = [mock_code]

        # Create coder
        coder = CoderAgent(mock_event_bus, mock_llm, validator, settings)  # type: ignore

        # Create plan
        plan = EvolutionPlan(
            plan_id="test_plan",
            trigger_id="test_trigger",
            action_type="new_trait",
            description="Bad trait",
            target_class="bad_trait",
        )

        # Try to generate code
        mutation = await coder._generate_and_save_code(plan)

        # Verify mutation was rejected
        assert mutation is None

    @pytest.mark.asyncio
    async def test_coder_handles_llm_failure(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        validator: CodeValidator,
        settings: Settings,
    ) -> None:
        """Test that Coder handles LLM failure gracefully."""
        # Setup mock to return None
        mock_llm.text_responses = [None]

        # Create coder
        coder = CoderAgent(mock_event_bus, mock_llm, validator, settings)  # type: ignore

        # Create plan
        plan = EvolutionPlan(
            plan_id="test_plan",
            trigger_id="test_trigger",
            action_type="new_trait",
            description="Test",
            target_class="test_trait",
        )

        # Try to generate code
        mutation = await coder._generate_and_save_code(plan)

        # Verify mutation is None (failure handled)
        assert mutation is None

    @pytest.mark.asyncio
    async def test_coder_retries_on_validation_failure(
        self,
        mock_event_bus: AsyncMock,
        mock_llm: MockLLMClient,
        validator: CodeValidator,
        settings: Settings,
    ) -> None:
        """Test that Coder retries with error context when first attempt fails validation."""
        # First response: invalid code (forbidden import)
        invalid_code = "import os\n\nclass BadTrait:\n    async def execute(self, entity):\n        pass\n"

        # Second response: valid trait code
        valid_code = '''from __future__ import annotations

class BaseTrait:
    """Base trait protocol."""
    pass

class RetryTrait(BaseTrait):
    """Trait that succeeds on second attempt."""

    async def execute(self, entity) -> None:
        entity.state["retried"] = True
'''

        mock_llm.text_responses = [invalid_code, f"```python\n{valid_code}\n```"]

        # Create coder
        coder = CoderAgent(mock_event_bus, mock_llm, validator, settings)  # type: ignore

        # Create plan
        plan = EvolutionPlan(
            plan_id="retry_plan",
            trigger_id="retry_trigger",
            action_type="new_trait",
            description="Trait that requires a retry",
            target_class="retry_trait",
        )

        # Generate and save code
        mutation = await coder._generate_and_save_code(plan)

        # Verify second attempt succeeded
        assert mutation is not None
        assert mutation.plan_id == "retry_plan"
        assert mutation.trait_name == "RetryTrait"
        assert os.path.exists(mutation.file_path)

        # Verify LLM was called twice (initial attempt + one retry)
        assert mock_llm.call_count == 2


class TestFullChain:
    """Test the full chain from Trigger to MutationReady."""

    @pytest.mark.asyncio
    async def test_full_evolution_cycle(
        self,
        mock_event_bus: AsyncMock,
        settings: Settings,
        validator: CodeValidator,
    ) -> None:
        """Test complete chain: Trigger -> Architect -> Plan -> Coder -> MutationReady."""
        # Create mock LLM
        mock_llm = MockLLMClient()

        # Setup architect response
        mock_llm.json_responses = [
            {
                "trait_name": "food_seeker",
                "description": "Moves toward nearby food resources",
                "action_type": "new_trait",
            }
        ]

        # Setup coder response
        mock_code = '''from __future__ import annotations

class BaseTrait:
    """Base trait protocol."""
    pass

class FoodSeeker(BaseTrait):
    """Moves toward nearby food resources."""

    async def execute(self, entity) -> None:
        # Simple food seeking behavior
        if entity.energy < 80:
            entity.state["seeking_food"] = True
'''

        mock_llm.text_responses = [f"```python\n{mock_code}\n```"]

        # Create agents
        architect = ArchitectAgent(mock_event_bus, mock_llm, settings)  # type: ignore
        coder = CoderAgent(mock_event_bus, mock_llm, validator, settings)  # type: ignore

        # Step 1: Trigger -> Architect -> Plan
        trigger = EvolutionTrigger(
            trigger_id="chain_test",
            problem_type="starvation",
            severity="high",
        )

        plan = await architect._create_plan(trigger)
        assert plan is not None
        assert plan.target_class == "food_seeker"

        # Step 2: Plan -> Coder -> MutationReady
        mutation = await coder._generate_and_save_code(plan)
        assert mutation is not None
        assert mutation.trait_name == "FoodSeeker"
        assert os.path.exists(mutation.file_path)

        # Verify file content
        with open(mutation.file_path) as f:
            content = f.read()
            assert "class FoodSeeker" in content
            assert "seeking_food" in content

        # Verify both agents were called
        assert mock_llm.call_count == 2
