"""WebSocket handler for real-time world state streaming.

Provides:
- ConnectionManager for managing active WebSocket connections
- Binary protocol for efficient world state transmission
- WebSocket endpoint for streaming world updates
"""

from __future__ import annotations

import struct
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
import structlog

from backend.core.entity import BaseEntity

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


def build_world_frame(tick: int, entities: list[BaseEntity]) -> bytes:
    """Build a binary world state frame using struct.pack.

    Binary protocol format:
    - Header (6 bytes):
        - Tick: uint32 (4 bytes)
        - EntityCount: uint16 (2 bytes)
    - Body (20 bytes per entity):
        - ID: uint32 (4 bytes) - hash of string ID
        - X: float32 (4 bytes)
        - Y: float32 (4 bytes)
        - R: float32 (4 bytes) - radius
        - Color: uint32 (4 bytes) - hex color as integer

    Args:
        tick: Current simulation tick.
        entities: List of entities to include in the frame.

    Returns:
        Binary frame as bytes.

    Note:
        For 500 entities: ~6 + 500*20 = 10,006 bytes (~10KB)
        Compare to JSON: ~200KB for the same data.
    """
    entity_count = len(entities)

    # Pack header: tick (I = uint32), entity_count (H = uint16)
    # Using big-endian (>) for network byte order
    header = struct.pack(">IH", tick, entity_count)

    # Pack entities
    entity_data_parts: list[bytes] = []

    for entity in entities:
        # Hash string ID to uint32
        # Using Python's built-in hash and masking to 32 bits
        entity_id_hash = hash(entity.id) & 0xFFFFFFFF

        # Convert hex color string to integer
        # Color format: "#RRGGBB" -> 0xRRGGBB
        color_int = int(entity.color.lstrip("#"), 16)

        # Pack: ID (I), X (f), Y (f), R (f), Color (I)
        # Format: >I f f f I = 4 + 4 + 4 + 4 + 4 = 20 bytes
        entity_bytes = struct.pack(
            ">Ifffi",
            entity_id_hash,
            entity.x,
            entity.y,
            entity.radius,
            color_int,
        )
        entity_data_parts.append(entity_bytes)

    # Combine header and all entity data
    frame = header + b"".join(entity_data_parts)

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
