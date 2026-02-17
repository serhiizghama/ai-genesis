"""Async Event Bus implementation using Redis Pub/Sub.

The EventBus provides decoupled communication between Core Engine,
LLM Agents, Runtime Patcher, and other system components.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from typing import Callable, Any, TypeVar, Type, Optional

import structlog
import redis as sync_redis
from redis.asyncio import Redis

T = TypeVar('T')

logger = structlog.get_logger()


class EventBus:
    """Async event bus built on Redis Pub/Sub.

    Uses a synchronous Redis PubSub in a background thread for reliable
    message delivery, since async get_message() can hang under load.
    """

    def __init__(self, redis_client: Redis):
        self._redis = redis_client
        self._handlers: dict[str, list[tuple[Callable, Optional[Type[Any]]]]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Extract connection info for sync client
        kwargs = redis_client.connection_pool.connection_kwargs.copy()
        self._sync_redis = sync_redis.Redis(
            host=kwargs.get("host", "localhost"),
            port=kwargs.get("port", 6379),
            db=kwargs.get("db", 0),
            decode_responses=False,
        )
        self._sync_pubsub = self._sync_redis.pubsub()

    async def publish(self, channel: str, event: Any) -> None:
        payload = json.dumps(asdict(event), default=str)
        logger.info("event_bus_publishing", channel=channel, payload_length=len(payload))
        result = await self._redis.publish(channel, payload)
        logger.info("event_bus_published", channel=channel, subscribers=result)

    async def subscribe(self, channel: str, handler: Callable, event_type: Optional[Type[T]] = None) -> None:
        if channel not in self._handlers:
            self._sync_pubsub.subscribe(channel)
            logger.info("event_bus_subscribed_to_channel", channel=channel)
            self._handlers[channel] = []
        self._handlers[channel].append((handler, event_type))
        logger.info("event_bus_handler_registered", channel=channel, handler_count=len(self._handlers[channel]))

    async def listen(self) -> None:
        """Start listening for messages using a background thread.

        The sync Redis PubSub.listen() is run in a daemon thread.
        Messages are dispatched back to the asyncio event loop via
        loop.call_soon_threadsafe().
        """
        self._loop = asyncio.get_running_loop()
        logger.info("event_bus_listen_started", channels=list(self._handlers.keys()))

        # Start the sync listener in a background thread
        thread = threading.Thread(
            target=self._sync_listen_thread,
            daemon=True,
            name="event-bus-listener",
        )
        thread.start()
        logger.info("event_bus_listener_thread_started")

        # Keep this coroutine alive (it's a background task)
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("event_bus_listen_cancelled")
            raise

    def _sync_listen_thread(self) -> None:
        """Background thread that reads from sync Redis PubSub."""
        logger.info("event_bus_sync_listener_started")

        for message in self._sync_pubsub.listen():
            msg_type = message.get("type")
            if isinstance(msg_type, bytes):
                msg_type = msg_type.decode()

            if msg_type != "message":
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()

            payload = message["data"]
            if isinstance(payload, bytes):
                payload = payload.decode()

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue

            logger.info("event_bus_message_received", channel=channel)

            # Schedule dispatch on the asyncio event loop
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(
                    self._loop.create_task,
                    self._dispatch(channel, data),
                )

    async def _dispatch(self, channel: str, data: dict) -> None:
        """Dispatch a message to registered handlers."""
        logger.info("event_bus_received", channel=channel,
                     data_keys=list(data.keys()) if isinstance(data, dict) else "non-dict")

        handlers = self._handlers.get(channel, [])
        for handler, event_type in handlers:
            if event_type is not None:
                try:
                    event_obj = event_type(**data)
                    logger.info("event_bus_dispatching_typed", channel=channel, event_type=event_type.__name__)
                    asyncio.create_task(handler(event_obj))
                except Exception as exc:
                    logger.error("event_bus_handler_error", channel=channel, error=str(exc))
            else:
                logger.info("event_bus_dispatching_raw", channel=channel)
                asyncio.create_task(handler(data))

    async def close(self) -> None:
        self._sync_pubsub.close()
        self._sync_redis.close()
