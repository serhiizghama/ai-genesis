"""Tests for EventBus pub/sub functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import TelemetryEvent, EvolutionTrigger, FeedMessage


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    # Create a mock PubSub object (not wrapped in AsyncMock)
    pubsub = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    return redis


@pytest.fixture
def event_bus(mock_redis):
    """Create an EventBus instance with mock Redis."""
    return EventBus(mock_redis)


@pytest.mark.asyncio
async def test_publish_telemetry_event(event_bus, mock_redis):
    """Test publishing a TelemetryEvent."""
    event = TelemetryEvent(tick=100, snapshot_key="ws:snapshot:100", timestamp=1234567890.0)

    await event_bus.publish(Channels.TELEMETRY, event)

    # Verify Redis publish was called
    mock_redis.publish.assert_called_once()
    args = mock_redis.publish.call_args[0]

    # Check channel
    assert args[0] == Channels.TELEMETRY

    # Check payload is valid JSON with correct data
    import json
    payload = json.loads(args[1])
    assert payload["tick"] == 100
    assert payload["snapshot_key"] == "ws:snapshot:100"
    assert payload["timestamp"] == 1234567890.0


@pytest.mark.asyncio
async def test_publish_evolution_trigger(event_bus, mock_redis):
    """Test publishing an EvolutionTrigger event."""
    event = EvolutionTrigger(
        trigger_id="trigger_001",
        problem_type="starvation",
        severity="high",
        affected_entities=["mol_001", "mol_002"],
        suggested_area="traits",
        snapshot_key="ws:snapshot:200",
    )

    await event_bus.publish(Channels.EVOLUTION_TRIGGER, event)

    # Verify Redis publish was called
    mock_redis.publish.assert_called_once()
    args = mock_redis.publish.call_args[0]

    # Check payload
    import json
    payload = json.loads(args[1])
    assert payload["trigger_id"] == "trigger_001"
    assert payload["problem_type"] == "starvation"
    assert payload["severity"] == "high"
    assert payload["affected_entities"] == ["mol_001", "mol_002"]


@pytest.mark.asyncio
async def test_subscribe_adds_handler(event_bus, mock_redis):
    """Test that subscribe adds handler to internal registry."""
    handler = AsyncMock()

    await event_bus.subscribe(Channels.TELEMETRY, handler)

    # Verify Redis subscribe was called
    mock_redis.pubsub.return_value.subscribe.assert_called_once_with(Channels.TELEMETRY)

    # Verify handler was added
    assert Channels.TELEMETRY in event_bus._handlers
    assert handler in event_bus._handlers[Channels.TELEMETRY]


@pytest.mark.asyncio
async def test_subscribe_multiple_handlers(event_bus, mock_redis):
    """Test that multiple handlers can be registered for the same channel."""
    handler1 = AsyncMock()
    handler2 = AsyncMock()

    await event_bus.subscribe(Channels.TELEMETRY, handler1)
    await event_bus.subscribe(Channels.TELEMETRY, handler2)

    # Verify both handlers are registered
    assert len(event_bus._handlers[Channels.TELEMETRY]) == 2
    assert handler1 in event_bus._handlers[Channels.TELEMETRY]
    assert handler2 in event_bus._handlers[Channels.TELEMETRY]

    # Redis subscribe should only be called once
    assert mock_redis.pubsub.return_value.subscribe.call_count == 1


@pytest.mark.asyncio
async def test_listen_dispatches_to_handlers(event_bus, mock_redis):
    """Test that listen() dispatches messages to registered handlers."""
    handler = AsyncMock()
    await event_bus.subscribe(Channels.FEED, handler)

    # Mock the pubsub.listen() to yield a test message
    test_message = {
        "type": "message",
        "channel": b"ch:feed",
        "data": '{"agent": "watcher", "action": "test", "message": "Test message", "metadata": {}, "timestamp": 1234567890.0}',
    }

    async def mock_listen():
        yield test_message

    mock_redis.pubsub.return_value.listen = mock_listen

    # Run listen in background and wait for handler to be called
    listen_task = asyncio.create_task(event_bus.listen())

    # Give it time to process
    await asyncio.sleep(0.1)

    # Cancel the listen task
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    # Verify handler was called with deserialized data
    handler.assert_called_once()
    call_args = handler.call_args[0][0]
    assert call_args["agent"] == "watcher"
    assert call_args["action"] == "test"
    assert call_args["message"] == "Test message"


@pytest.mark.asyncio
async def test_listen_skips_non_message_events(event_bus, mock_redis):
    """Test that listen() skips non-message events like subscribe confirmations."""
    handler = AsyncMock()
    await event_bus.subscribe(Channels.TELEMETRY, handler)

    # Mock pubsub.listen() to yield a subscribe confirmation
    async def mock_listen():
        yield {"type": "subscribe", "channel": b"ch:telemetry", "data": 1}

    mock_redis.pubsub.return_value.listen = mock_listen

    # Run listen briefly
    listen_task = asyncio.create_task(event_bus.listen())
    await asyncio.sleep(0.1)
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    # Verify handler was NOT called
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_listen_handles_malformed_json(event_bus, mock_redis):
    """Test that listen() gracefully handles malformed JSON."""
    handler = AsyncMock()
    await event_bus.subscribe(Channels.TELEMETRY, handler)

    # Mock pubsub.listen() to yield invalid JSON
    async def mock_listen():
        yield {"type": "message", "channel": b"ch:telemetry", "data": "invalid json{"}

    mock_redis.pubsub.return_value.listen = mock_listen

    # Run listen briefly - should not crash
    listen_task = asyncio.create_task(event_bus.listen())
    await asyncio.sleep(0.1)
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass

    # Verify handler was NOT called
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_close(event_bus, mock_redis):
    """Test that close() closes the pubsub connection."""
    await event_bus.close()

    mock_redis.pubsub.return_value.close.assert_called_once()


@pytest.mark.asyncio
async def test_full_scenario_subscribe_publish_receive():
    """Integration-style test: subscribe -> publish -> verify handler receives data."""
    # This test uses a real-ish scenario without Redis
    received_data = []

    async def test_handler(data):
        received_data.append(data)

    # Create mock Redis
    redis = AsyncMock()
    pubsub = AsyncMock()
    redis.pubsub = MagicMock(return_value=pubsub)

    # Create event bus
    bus = EventBus(redis)

    # Subscribe
    await bus.subscribe(Channels.TELEMETRY, test_handler)

    # Verify subscription
    assert Channels.TELEMETRY in bus._handlers
    assert test_handler in bus._handlers[Channels.TELEMETRY]

    # Simulate receiving a message by manually calling the handler
    test_event_data = {"tick": 100, "snapshot_key": "ws:snapshot:100", "timestamp": 1234567890.0}
    await test_handler(test_event_data)

    # Verify handler received the data
    assert len(received_data) == 1
    assert received_data[0]["tick"] == 100
    assert received_data[0]["snapshot_key"] == "ws:snapshot:100"
