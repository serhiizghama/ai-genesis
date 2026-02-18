"""WebSocket handler for real-time world state streaming.

Provides:
- ConnectionManager for managing active WebSocket connections
- FeedConnectionManager for Evolution Feed streaming
- Binary protocol for efficient world state transmission
- WebSocket endpoint for streaming world updates
"""

from __future__ import annotations

import json
import struct
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
import structlog

from backend.core.entity import BaseEntity
from backend.core.environment import Resource

logger = structlog.get_logger()


class ConnectionManager:
    """Manages active WebSocket connections.

    Handles connection lifecycle and broadcasting messages to all
    connected clients.
    """

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept.
        """
        # Accept WebSocket connection (no origin check for development)
        # In production, add origin validation here
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "ws_client_connected",
            total_connections=len(self.active_connections),
            origin=websocket.headers.get("origin", "unknown"),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                "ws_client_disconnected",
                total_connections=len(self.active_connections),
            )

    async def broadcast_bytes(self, data: bytes) -> None:
        """Broadcast binary data to all connected clients.

        Args:
            data: Binary data to send to all clients.

        Note:
            Removes disconnected clients automatically.
        """
        disconnected: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_bytes(data)
            except Exception as exc:
                logger.warning(
                    "ws_broadcast_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_text(self, message: str) -> None:
        """Broadcast text message to all connected clients.

        Args:
            message: Text message to send to all clients.

        Note:
            Used for control messages and events.
            Removes disconnected clients automatically.
        """
        disconnected: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as exc:
                logger.warning(
                    "ws_broadcast_error",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


class FeedConnectionManager:
    """Manages WebSocket connections for Evolution Feed streaming.

    Broadcasts JSON feed messages from agents to all connected clients.
    """

    def __init__(self) -> None:
        """Initialize the feed connection manager."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new feed WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            "feed_ws_client_connected",
            total_connections=len(self.active_connections),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a feed WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                "feed_ws_client_disconnected",
                total_connections=len(self.active_connections),
            )

    async def broadcast_json(self, data: dict[str, str | float]) -> None:
        """Broadcast a JSON message to all connected feed clients.

        Args:
            data: Dict with agent, message, timestamp fields.
        """
        disconnected: list[WebSocket] = []
        text = json.dumps(data)

        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except Exception as exc:
                logger.warning("feed_ws_broadcast_error", error=str(exc))
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


def build_world_frame(
    tick: int,
    entities: list[BaseEntity],
    resources: list[Resource] | None = None,
) -> bytes:
    """Build a binary world state frame using struct.pack.

    Binary protocol format:
    - Header (8 bytes):
        - Tick: uint32 (4 bytes)
        - EntityCount: uint16 (2 bytes)
        - ResourceCount: uint16 (2 bytes)
    - Body (21 bytes per entity):
        - ID: uint32 (4 bytes) - hash of string ID
        - X: float32 (4 bytes)
        - Y: float32 (4 bytes)
        - R: float32 (4 bytes) - radius
        - Color: uint32 (4 bytes) - hex color as integer
        - Flags: uint8 (1 byte) - 0x01=isPredator, 0x02=isInfected
    - Resources (8 bytes each):
        - X: float32 (4 bytes)
        - Y: float32 (4 bytes)

    Args:
        tick: Current simulation tick.
        entities: List of entities to include in the frame.
        resources: List of food resources to include in the frame.

    Returns:
        Binary frame as bytes.

    Note:
        For 2000 entities + 100 resources:
        ~8 + 2000*21 + 100*8 = 43,008 bytes (~42KB)
        Compare to JSON: ~800KB for the same data.
    """
    if resources is None:
        resources = []

    entity_count = len(entities)
    resource_count = len(resources)

    # Pack header: tick (I = uint32), entity_count (H = uint16), resource_count (H = uint16)
    # Using big-endian (>) for network byte order
    header = struct.pack(">IHH", tick, entity_count, resource_count)

    # Pack entities
    entity_data_parts: list[bytes] = []

    for entity in entities:
        # Hash string ID to uint32
        # Using Python's built-in hash and masking to 32 bits
        entity_id_hash = hash(entity.id) & 0xFFFFFFFF

        # Convert hex color string to integer
        # Color format: "#RRGGBB" -> 0xRRGGBB
        color_int = int(entity.color.lstrip("#"), 16)

        # Build flags byte: 0x01=isPredator, 0x02=isInfected
        flags = 0
        if getattr(entity, "entity_type", "molbot") == "predator":
            flags |= 0x01
        if getattr(entity, "infected", False):
            flags |= 0x02

        # Pack: ID (I), X (f), Y (f), R (f), Color (I), Flags (B)
        # Format: >I f f f I B = 4 + 4 + 4 + 4 + 4 + 1 = 21 bytes
        entity_bytes = struct.pack(
            ">IfffIB",
            entity_id_hash,
            entity.x,
            entity.y,
            entity.radius,
            color_int,
            flags,
        )
        entity_data_parts.append(entity_bytes)

    # Pack resources (x, y only — 8 bytes each)
    resource_data_parts: list[bytes] = []
    for resource in resources:
        resource_bytes = struct.pack(">ff", resource.x, resource.y)
        resource_data_parts.append(resource_bytes)

    # Combine header, entity data, and resource data
    frame = header + b"".join(entity_data_parts) + b"".join(resource_data_parts)

    return frame


async def websocket_endpoint(
    websocket: WebSocket,
    manager: ConnectionManager,
) -> None:
    """WebSocket endpoint for world state streaming.

    Args:
        websocket: The WebSocket connection.
        manager: The connection manager instance.

    Note:
        Clients will receive binary frames pushed from the engine.
        They don't need to send anything - this is a one-way stream.
    """
    await manager.connect(websocket)

    try:
        # Keep connection alive - clients just receive data
        # They can send messages (e.g., ping) to keep connection active
        while True:
            # Wait for any message from client (or disconnect)
            # We don't process the message, just use it to detect disconnection
            data = await websocket.receive_text()

            # Optional: log client messages for debugging
            if data and data != "ping":
                logger.debug("ws_client_message", message=data)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("ws_client_disconnected_gracefully")
    except Exception as exc:
        logger.error(
            "ws_endpoint_error",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        manager.disconnect(websocket)
