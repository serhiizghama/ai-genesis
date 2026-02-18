"""WebSocket endpoint for external agent real-time telemetry.

Streams events from Redis Pub/Sub channels directly to connected agents,
eliminating the need for HTTP polling.

Subscribed channels:
  ch:telemetry       → WorldSnapshot events (compact)
  ch:mutation:applied → MutationActivated events
  ch:mutation:rollback → MutationRolledBack events
  ch:agent:tasks     → TaskPublished / TaskExpired events
"""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

logger = structlog.get_logger()

router = APIRouter()

_CHANNELS = [
    "ch:telemetry",
    "ch:mutation:applied",
    "ch:mutation:rollback",
    "ch:agent:tasks",
]

_CHANNEL_EVENT_MAP: dict[str, str] = {
    "ch:telemetry": "WorldSnapshot",
    "ch:mutation:applied": "MutationActivated",
    "ch:mutation:rollback": "MutationRolledBack",
    "ch:agent:tasks": "TaskPublished",  # task events carry their own sub-type
}


def _build_event(channel: str, data: dict[str, object]) -> dict[str, object]:
    """Attach event type label and return the outgoing message dict."""
    # Agent task channel carries sub-types (TaskPublished, TaskExpired)
    if channel == "ch:agent:tasks":
        event_type = str(data.get("event_type", "TaskPublished"))
    else:
        event_type = _CHANNEL_EVENT_MAP.get(channel, "Unknown")

    return {"event": event_type, **data}


@router.websocket("/agents/telemetry")
async def agent_telemetry_ws(websocket: WebSocket) -> None:
    """Stream world telemetry events to connected external agents.

    The client receives newline-delimited JSON frames. Each frame has an
    'event' field indicating the event type plus the relevant payload fields.

    Example frames:
        {"event": "WorldSnapshot", "tick": 45300, "entity_count": 138}
        {"event": "MutationActivated", "mutation_id": "mut_7f3a1c", "trait_name": "..."}
        {"event": "TaskPublished", "task_id": "task_b4e3cd", "problem_type": "..."}
    """
    # Access redis from app state — the WS endpoint doesn't get Request, only WebSocket
    app_state = websocket.app.state.app_state  # type: ignore[attr-defined]
    redis: Redis | None = app_state.redis

    await websocket.accept()
    logger.info("agent_telemetry_ws_connected")

    if redis is None:
        await websocket.send_json({"event": "Error", "detail": "Redis not available"})
        await websocket.close()
        return

    # Create an isolated pubsub subscriber for this WS connection
    pubsub = redis.pubsub()
    await pubsub.subscribe(*_CHANNELS)

    async def _read_redis() -> None:
        """Pull messages from Redis and forward to the WebSocket."""
        async for message in pubsub.listen():
            msg_type = message.get("type")
            if msg_type == "subscribe":
                continue

            channel_raw = message.get("channel", b"")
            channel = channel_raw.decode() if isinstance(channel_raw, bytes) else channel_raw

            payload_raw = message.get("data", b"")
            payload_str = (
                payload_raw.decode() if isinstance(payload_raw, bytes) else payload_raw
            )

            try:
                data: dict[str, object] = json.loads(payload_str)
            except (json.JSONDecodeError, TypeError):
                continue

            event = _build_event(channel, data)
            try:
                await websocket.send_json(event)
            except Exception:
                return  # Connection closed

    try:
        redis_task = asyncio.create_task(_read_redis())
        # Keep alive: wait for client disconnect or reader failure
        while True:
            try:
                # Use a short receive to detect disconnect (raises on close)
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send a keepalive ping
                try:
                    await websocket.send_json({"event": "Ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info("agent_telemetry_ws_disconnected")
    except Exception as exc:
        logger.error("agent_telemetry_ws_error", error=str(exc))
    finally:
        redis_task.cancel()
        try:
            await pubsub.unsubscribe(*_CHANNELS)
        except Exception:
            pass
        logger.info("agent_telemetry_ws_cleanup_done")
