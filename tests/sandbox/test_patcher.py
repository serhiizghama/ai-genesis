"""Tests for RuntimePatcher hot-reload functionality."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import MutationApplied, MutationFailed
from backend.core.dynamic_registry import DynamicRegistry
from backend.sandbox.patcher import RuntimePatcher
from backend.sandbox.validator import CodeValidator, ValidationResult


@pytest.fixture
def mock_redis():
    """Create a mock Redis connection."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def event_bus(mock_redis):
    """Create an EventBus with mock Redis."""
    return EventBus(mock_redis)


@pytest.fixture
def registry():
    """Create a DynamicRegistry."""
    return DynamicRegistry()


@pytest.fixture
def validator(mock_redis):
    """Create a CodeValidator with mock Redis."""
    return CodeValidator(redis=mock_redis)


@pytest.fixture
def patcher(event_bus, registry, validator):
    """Create a RuntimePatcher instance."""
    return RuntimePatcher(
        event_bus=event_bus,
        registry=registry,
        validator=validator,
    )


@pytest.mark.asyncio
async def test_patcher_initialization(patcher):
    """Test that patcher initializes correctly."""
    assert patcher._registry_version == 0
    assert patcher._event_bus is not None
    assert patcher._registry is not None
    assert patcher._validator is not None


@pytest.mark.asyncio
async def test_patcher_subscribes_to_channel(patcher, event_bus):
    """Test that patcher subscribes to mutation channel."""
    with patch.object(event_bus, 'subscribe', new=AsyncMock()) as mock_subscribe:
        await patcher.run()
        mock_subscribe.assert_called_once_with(Channels.MUTATION_READY, patcher._handle_mutation_ready)


@pytest.mark.asyncio
async def test_handle_mutation_ready_file_not_found(patcher):
    """Test handling of mutation when file doesn't exist."""
    event_data = {
        "mutation_id": "test_123",
        "file_path": "/nonexistent/path.py",
        "trait_name": "TestTrait",
        "version": 1,
    }

    # Mock the publish method to capture the failure event
    with patch.object(patcher._event_bus, 'publish', new=AsyncMock()) as mock_publish:
        await patcher._handle_mutation_ready(event_data)

        # Should publish MutationFailed
        assert mock_publish.called
        call_args = mock_publish.call_args[0]
        assert call_args[0] == Channels.MUTATION_FAILED
        assert isinstance(call_args[1], MutationFailed)
        assert call_args[1].stage == "validation"


@pytest.mark.asyncio
async def test_validate_mutation_success(patcher, tmp_path):
    """Test successful mutation validation."""
    # Create a valid trait file
    trait_code = '''"""Test trait."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

class TestTrait:
    async def execute(self, entity: BaseEntity) -> None:
        pass
'''
    trait_file = tmp_path / "test_trait.py"
    trait_file.write_text(trait_code)

    # Mock validator to return valid result
    valid_result = ValidationResult(
        is_valid=True,
        trait_class_name="TestTrait",
        code_hash="abc123",
    )

    with patch.object(patcher._validator, 'validate', return_value=valid_result):
        result = await patcher._validate_mutation(str(trait_file))

        assert result is not None
        assert result.is_valid
        assert result.trait_class_name == "TestTrait"


@pytest.mark.asyncio
async def test_validate_mutation_invalid_code(patcher, tmp_path):
    """Test validation failure for invalid code."""
    # Create an invalid trait file
    trait_code = "invalid python code {"
    trait_file = tmp_path / "invalid_trait.py"
    trait_file.write_text(trait_code)

    with patch.object(patcher._event_bus, 'publish', new=AsyncMock()):
        result = await patcher._validate_mutation(str(trait_file))

        assert result is None


@pytest.mark.asyncio
async def test_load_module_success(patcher, tmp_path):
    """Test successful module loading."""
    # Create a valid trait file
    trait_code = '''"""Test trait."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

class LoadTestTrait:
    async def execute(self, entity: BaseEntity) -> None:
        entity.energy += 10
'''
    trait_file = tmp_path / "load_test_trait.py"
    trait_file.write_text(trait_code)

    trait_class = patcher._load_module(str(trait_file), "LoadTestTrait")

    assert trait_class is not None
    assert trait_class.__name__ == "LoadTestTrait"
    assert hasattr(trait_class, "execute")


@pytest.mark.asyncio
async def test_load_module_import_error(patcher, tmp_path):
    """Test module loading with import error."""
    # Create a trait file that will fail on import
    trait_code = '''"""Test trait with error."""
import nonexistent_module

class ErrorTrait:
    async def execute(self, entity) -> None:
        pass
'''
    trait_file = tmp_path / "error_trait.py"
    trait_file.write_text(trait_code)

    trait_class = patcher._load_module(str(trait_file), "ErrorTrait")

    # Should return None on import error
    assert trait_class is None


@pytest.mark.asyncio
async def test_full_mutation_flow_success(patcher, registry, tmp_path):
    """Test complete successful mutation application flow."""
    # Create a valid trait file
    trait_code = '''"""Test trait."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

class FullFlowTrait:
    async def execute(self, entity: BaseEntity) -> None:
        pass
'''
    trait_file = tmp_path / "full_flow_trait.py"
    trait_file.write_text(trait_code)

    # Mock validator to return valid result
    valid_result = ValidationResult(
        is_valid=True,
        trait_class_name="FullFlowTrait",
        code_hash="def456",
    )

    event_data = {
        "mutation_id": "test_full_flow",
        "file_path": str(trait_file),
        "trait_name": "FullFlowTrait",
        "version": 1,
    }

    published_events = []

    async def mock_publish(channel, event):
        published_events.append((channel, event))

    with patch.object(patcher._validator, 'validate', return_value=valid_result):
        with patch.object(patcher._validator, 'mark_as_used', new=AsyncMock()):
            with patch.object(patcher._event_bus, 'publish', new=mock_publish):
                await patcher._handle_mutation_ready(event_data)

    # Verify trait was registered
    assert registry.get_trait("FullFlowTrait") is not None

    # Verify success event was published
    assert len(published_events) == 1
    channel, event = published_events[0]
    assert channel == Channels.MUTATION_APPLIED
    assert isinstance(event, MutationApplied)
    assert event.mutation_id == "test_full_flow"
    assert event.trait_name == "FullFlowTrait"


@pytest.mark.asyncio
async def test_registry_version_increments(patcher, registry, tmp_path):
    """Test that registry version increments after successful mutation."""
    trait_code = '''"""Test trait."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

class VersionTrait:
    async def execute(self, entity: BaseEntity) -> None:
        pass
'''
    trait_file = tmp_path / "version_trait.py"
    trait_file.write_text(trait_code)

    valid_result = ValidationResult(
        is_valid=True,
        trait_class_name="VersionTrait",
        code_hash="ver123",
    )

    event_data = {
        "mutation_id": "test_version",
        "file_path": str(trait_file),
        "trait_name": "VersionTrait",
        "version": 1,
    }

    initial_version = patcher._registry_version

    with patch.object(patcher._validator, 'validate', return_value=valid_result):
        with patch.object(patcher._validator, 'mark_as_used', new=AsyncMock()):
            with patch.object(patcher._event_bus, 'publish', new=AsyncMock()):
                await patcher._handle_mutation_ready(event_data)

    assert patcher._registry_version == initial_version + 1


@pytest.mark.asyncio
async def test_rollback_on_registration_error(patcher, registry, tmp_path):
    """Test that registry is not modified if registration fails."""
    trait_code = '''"""Test trait."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.entity import BaseEntity

class RollbackTrait:
    async def execute(self, entity: BaseEntity) -> None:
        pass
'''
    trait_file = tmp_path / "rollback_trait.py"
    trait_file.write_text(trait_code)

    valid_result = ValidationResult(
        is_valid=True,
        trait_class_name="RollbackTrait",
        code_hash="roll123",
    )

    event_data = {
        "mutation_id": "test_rollback",
        "file_path": str(trait_file),
        "trait_name": "RollbackTrait",
        "version": 1,
    }

    # Mock registry.register to raise an exception
    with patch.object(patcher._validator, 'validate', return_value=valid_result):
        with patch.object(registry, 'register', side_effect=Exception("Registration failed")):
            with patch.object(patcher._event_bus, 'publish', new=AsyncMock()) as mock_publish:
                await patcher._handle_mutation_ready(event_data)

                # Should publish MutationFailed
                call_args = mock_publish.call_args[0]
                assert isinstance(call_args[1], MutationFailed)
                assert call_args[1].stage == "execution"

    # Verify trait was NOT registered
    assert registry.get_trait("RollbackTrait") is None
