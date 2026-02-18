"""FastAPI application factory with dependency injection.

This module provides the create_app() factory function that creates a
configured FastAPI application. The app receives CoreEngine, EventBus,
and Redis as dependencies from main.py rather than creating them itself.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from backend.core.engine import CoreEngine
from backend.api.ws_handler import ConnectionManager, FeedConnectionManager


class AppState:
    """Application state container for dependency injection.

    This class holds references to shared components that need to be
    accessed by API routes.
    """

    def __init__(
        self,
        engine: CoreEngine,
        redis: Optional[Redis],
        start_time: float,
        ws_manager: ConnectionManager,
        event_bus: Optional[Any] = None,
        feed_ws_manager: Optional[FeedConnectionManager] = None,
        db_pool: Optional[Any] = None,
    ) -> None:
        """Initialize app state.

        Args:
            engine: The running CoreEngine instance.
            redis: Redis connection for event bus.
            start_time: Server start timestamp for uptime calculation.
            ws_manager: WebSocket connection manager for real-time streaming.
            event_bus: Shared EventBus instance for publishing events.
            feed_ws_manager: WebSocket manager for Evolution Feed streaming.
            db_pool: asyncpg connection pool for PostgreSQL persistence.
        """
        self.engine = engine
        self.redis = redis
        self.start_time = start_time
        self.ws_manager = ws_manager
        self.event_bus = event_bus
        self.feed_ws_manager = feed_ws_manager or FeedConnectionManager()
        self.db_pool = db_pool


def create_app(
    engine: CoreEngine,
    redis: Optional[Redis] = None,
    ws_manager: Optional[ConnectionManager] = None,
    event_bus: Optional[Any] = None,
    feed_ws_manager: Optional[FeedConnectionManager] = None,
    db_pool: Optional[Any] = None,
) -> FastAPI:
    """Create and configure FastAPI application.

    Args:
        engine: Running CoreEngine instance (already initialized in main.py).
        redis: Optional Redis connection for event bus.
        ws_manager: WebSocket connection manager for real-time streaming.
        event_bus: Shared EventBus instance for publishing events.

    Returns:
        Configured FastAPI application.

    Note:
        This uses Dependency Injection pattern - the app receives components
        rather than creating them. The engine is already running in a
        background task managed by main.py.
    """
    # Create FastAPI app
    app = FastAPI(
        title="AI-Genesis",
        description="Autonomous evolutionary sandbox powered by LLM",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Setup CORS for development (allow all origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Create ConnectionManager if not provided
    if ws_manager is None:
        ws_manager = ConnectionManager()

    # Store shared state in app.state for access by routes
    app.state.app_state = AppState(
        engine=engine,
        redis=redis,
        start_time=time.time(),
        ws_manager=ws_manager,
        event_bus=event_bus,
        feed_ws_manager=feed_ws_manager,
        db_pool=db_pool,
    )

    # Import and register routers
    from backend.api.routes_world import router as world_router
    from backend.api.routes_evolution import router as evolution_router
    from backend.api.routes_persistence import router as persistence_router
    from backend.api.routes_agents import router as agents_router
    from backend.api.ws_agents import router as ws_agents_router

    app.include_router(world_router, prefix="/api", tags=["world"])
    app.include_router(evolution_router, prefix="/api", tags=["evolution"])
    app.include_router(persistence_router, prefix="/api", tags=["persistence"])
    app.include_router(agents_router, prefix="/api", tags=["agents"])
    app.include_router(ws_agents_router, prefix="/api", tags=["agents-ws"])

    # Health check endpoint
    @app.get("/", tags=["health"])
    async def root() -> dict[str, str]:
        """Root endpoint - basic health check."""
        return {
            "status": "ok",
            "service": "AI-Genesis API",
            "version": "0.2.0",
        }

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Health check endpoint for Docker and monitoring."""
        return {
            "status": "healthy",
            "engine_running": str(app.state.app_state.engine.running),
            "tick": str(app.state.app_state.engine.tick_counter),
        }

    return app
