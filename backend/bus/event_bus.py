"""Async Event Bus implementation using Redis Pub/Sub.

The EventBus provides decoupled communication between Core Engine,
LLM Agents, Runtime Patcher, and other system components.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Callable, Any

from redis.asyncio import Redis


class EventBus:
    """Async event bus built on Redis Pub/Sub.

    Usage:
        bus = EventBus(redis)
        await bus.subscribe("ch:telemetry", handler_func)
        await bus.publish("ch:telemetry", TelemetryEvent(tick=100, snapshot_key="ws:snapshot:100"))
        await bus.listen()  # Run in background task
    """

    def __init__(self, redis: Redis):
        """Initialize EventBus with Redis connection.

        Args:
            redis: Async Redis client instance
        """
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._handlers: dict[str, list[Callable]] = {}

    async def publish(self, channel: str, event: Any) -> None:
        """Publish an event to a channel.

        Args:
            channel: Redis channel name (e.g., "ch:telemetry")
            event: Event dataclass instance to publish

        Note:
            The event is serialized to JSON using dataclasses.asdict().
            datetime objects are converted to strings using default=str.
        """
        payload = json.dumps(asdict(event), default=str)
        await self._redis.publish(channel, payload)

    async def subscribe(self, channel: str, handler: Callable) -> None:
        """Subscribe to a channel with a handler function.

        Args:
            channel: Redis channel name to subscribe to
            handler: Async function to call when message arrives.
                     Handler receives deserialized dict as argument.

        Note:
            Multiple handlers can be registered for the same channel.
            Handlers are called concurrently via asyncio.create_task().
        """
        if channel not in self._handlers:
            self._handlers[channel] = []
            await self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)

    async def listen(self) -> None:
        """Main event loop: dispatch incoming messages to handlers.

        This method runs indefinitely and should be started as a background task.
        It listens for messages on all subscribed channels and dispatches them
        to registered handlers.

        Each handler is executed in a separate task to avoid blocking the event loop.
        """
        async for message in self._pubsub.listen():
            # Skip non-message events (subscribe confirmations, etc.)
            if message["type"] != "message":
                continue

            # Decode channel name if it's bytes
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()

            # Deserialize JSON payload
            try:
                data = json.loads(message["data"])
            except json.JSONDecodeError:
                # Skip malformed messages
                continue

            # Dispatch to all handlers for this channel
            for handler in self._handlers.get(channel, []):
                asyncio.create_task(handler(data))

    async def close(self) -> None:
        """Close the PubSub connection.

        Should be called during application shutdown.
        """
        await self._pubsub.close()
