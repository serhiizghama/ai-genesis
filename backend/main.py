"""AI-Genesis entry point — simulation runner with FastAPI server.

This module initializes all core components and starts both:
- The simulation loop (CoreEngine)
- The FastAPI REST API server (uvicorn)

Can be run directly via `python -m backend.main` or through Docker.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Optional

import structlog
import uvicorn

from backend.agents.architect import ArchitectAgent
from backend.agents.coder import CoderAgent
from backend.agents.cycle_manager import EvolutionCycleManager
from backend.agents.llm_client import LLMClient
from backend.agents.watcher import WatcherAgent
from backend.bus.channels import Channels
from backend.bus.events import FeedMessage as FeedEvent
from backend.api.app import create_app
from backend.api.ws_handler import ConnectionManager, FeedConnectionManager
from backend.bus import get_redis
from backend.bus.event_bus import EventBus
from backend.config import Settings
from backend.core.dynamic_registry import DynamicRegistry
from backend.core.engine import CoreEngine
from backend.core.entity_manager import EntityManager
from backend.core.environment import Environment
from backend.core.world_physics import WorldPhysics
from backend.sandbox import CodeValidator, RuntimePatcher
from backend.sandbox.mutations_registry import MutationRegistry

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(min_level="info"),  # INFO level
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


class SimulationRunner:
    """Manages simulation lifecycle and graceful shutdown."""

    def __init__(self) -> None:
        """Initialize the runner."""
        self.engine: Optional[CoreEngine] = None
        self.watcher: Optional[WatcherAgent] = None
        self.architect: Optional[ArchitectAgent] = None
        self.coder: Optional[CoderAgent] = None
        self.patcher: Optional[RuntimePatcher] = None
        self.uvicorn_server: Optional[uvicorn.Server] = None
        self.shutdown_event = asyncio.Event()

    async def run(self) -> None:
        """Initialize and run the simulation with FastAPI server.

        Sets up all components:
        - Settings
        - Redis connection
        - EntityManager
        - Environment
        - WorldPhysics
        - DynamicRegistry
        - CoreEngine
        - FastAPI application

        Then starts both the simulation loop and the API server.
        """
        logger.info("ai_genesis_starting", version="0.2.0")

        # T-021: Initialize all components
        settings = Settings()
        logger.info("settings_loaded", tick_rate_ms=settings.tick_rate_ms)

        # Initialize Redis connection
        try:
            redis = await get_redis(settings)
            await redis.ping()
            logger.info("redis_connected", url=settings.redis_url)
        except Exception as exc:
            logger.warning(
                "redis_connection_failed",
                url=settings.redis_url,
                error=str(exc),
                fallback="continuing_without_redis",
            )
            # For MVP, we can run without Redis
            # Event bus will be needed in Phase 2
            redis = None  # type: ignore

        # Initialize EventBus (T-039)
        event_bus = EventBus(redis)  # type: ignore
        logger.info("event_bus_initialized")

        # Initialize core components
        entity_manager = EntityManager(
            world_width=settings.world_width,
            world_height=settings.world_height,
        )
        logger.info("entity_manager_initialized")

        environment = Environment(
            world_width=settings.world_width,
            world_height=settings.world_height,
            initial_resources=100,
            resource_energy=50.0,
        )
        logger.info("environment_initialized", initial_resources=100)

        physics = WorldPhysics(
            world_width=settings.world_width,
            world_height=settings.world_height,
            friction_coefficient=0.98,
            boundary_mode="bounce",
        )
        logger.info("physics_initialized")

        registry = DynamicRegistry()
        logger.info("dynamic_registry_initialized")

        # Create WebSocket connection manager (T-027)
        ws_manager = ConnectionManager()
        logger.info("ws_manager_initialized")

        # Create Feed WebSocket connection manager (T-068)
        feed_ws_manager = FeedConnectionManager()
        logger.info("feed_ws_manager_initialized")

        # Create the core engine
        self.engine = CoreEngine(
            entity_manager=entity_manager,
            environment=environment,
            physics=physics,
            registry=registry,
            redis=redis,  # type: ignore
            settings=settings,
            ws_manager=ws_manager,
        )
        logger.info("core_engine_initialized")

        # Create Watcher Agent (T-041)
        self.watcher = WatcherAgent(
            redis=redis,  # type: ignore
            event_bus=event_bus,
            settings=settings,
        )
        logger.info("watcher_agent_initialized")

        # Create LLM Client (T-057)
        llm_client = LLMClient(settings=settings)
        logger.info("llm_client_initialized", ollama_url=settings.ollama_url)

        # Create CodeValidator (T-047)
        validator = CodeValidator(redis=redis)  # type: ignore
        logger.info("code_validator_initialized")

        # Create EvolutionCycleManager (T-061)
        cycle_manager = EvolutionCycleManager(redis=redis, settings=settings)  # type: ignore
        logger.info("cycle_manager_initialized")

        # Create Architect Agent (T-057)
        self.architect = ArchitectAgent(
            event_bus=event_bus,
            llm_client=llm_client,
            settings=settings,
            cycle_manager=cycle_manager,
        )
        logger.info("architect_agent_initialized")

        # Create MutationRegistry for persisting generated mutations to Redis
        mutation_registry = MutationRegistry(redis=redis) if redis is not None else None  # type: ignore

        # Create Coder Agent (T-057)
        self.coder = CoderAgent(
            event_bus=event_bus,
            llm_client=llm_client,
            validator=validator,
            settings=settings,
            mutation_registry=mutation_registry,
        )
        logger.info("coder_agent_initialized")

        # Subscribe feed_ws_manager to ch:feed events (T-068)
        async def _on_feed_event(event: FeedEvent) -> None:
            await feed_ws_manager.broadcast_json({
                "agent": event.agent,
                "action": event.action,
                "message": event.message,
                "metadata": event.metadata,
                "timestamp": event.timestamp,
            })

        await event_bus.subscribe(Channels.FEED, _on_feed_event, FeedEvent)
        logger.info("feed_channel_subscribed")

        # Create RuntimePatcher (T-047)

        self.patcher = RuntimePatcher(
            event_bus=event_bus,
            registry=registry,
            validator=validator,
        )
        logger.info("runtime_patcher_initialized")

        # Create FastAPI app (T-023 integration)
        app = create_app(
            engine=self.engine,
            redis=redis,  # type: ignore
            ws_manager=ws_manager,
            event_bus=event_bus,
            feed_ws_manager=feed_ws_manager,
        )
        logger.info("fastapi_app_created")

        # Configure uvicorn server
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=False,  # Reduce noise
        )
        self.uvicorn_server = uvicorn.Server(config)
        logger.info("uvicorn_configured", host="0.0.0.0", port=8000)

        # Register signal handlers for graceful shutdown
        def handle_shutdown(sig: int) -> None:
            logger.info("shutdown_signal_received", signal=sig)
            self.shutdown_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))

        # Start all services: engine, watcher, architect, coder, patcher, event bus, and API server
        logger.info("starting_all_services")

        # Run all agents in parallel (T-057)
        engine_task = asyncio.create_task(self.engine.run())
        watcher_task = asyncio.create_task(self.watcher.run())
        architect_task = asyncio.create_task(self.architect.run())
        coder_task = asyncio.create_task(self.coder.run())
        patcher_task = asyncio.create_task(self.patcher.run())

        # Give agents a moment to subscribe before starting event bus listener
        await asyncio.sleep(1)  # Wait for all subscriptions to complete

        event_bus_task = asyncio.create_task(event_bus.listen())
        server_task = asyncio.create_task(self.uvicorn_server.serve())

        logger.info(
            "services_running",
            simulation="running",
            watcher="running",
            architect="running",
            coder="running",
            patcher="running",
            api_server="http://0.0.0.0:8000",
            docs="http://0.0.0.0:8000/docs",
        )

        # Wait for shutdown signal
        await self.shutdown_event.wait()

        # Graceful shutdown
        logger.info("initiating_graceful_shutdown")

        # Stop the engine
        if self.engine:
            self.engine.stop()

        # Stop the watcher agent
        if self.watcher:
            self.watcher.stop()

        # Stop the uvicorn server
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True

        # Close event bus
        await event_bus.close()

        # Wait for all tasks to finish (give them 5 seconds)
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    engine_task,
                    watcher_task,
                    architect_task,
                    coder_task,
                    patcher_task,
                    event_bus_task,
                    server_task,
                    return_exceptions=True,
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("shutdown_timeout")
            engine_task.cancel()
            watcher_task.cancel()
            architect_task.cancel()
            coder_task.cancel()
            patcher_task.cancel()
            event_bus_task.cancel()
            server_task.cancel()

        logger.info("all_services_stopped")


async def main() -> None:
    """Main entry point."""
    runner = SimulationRunner()
    try:
        await runner.run()
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt_received")
    except Exception as exc:
        logger.error("fatal_error", error=str(exc), error_type=type(exc).__name__)
        raise


if __name__ == "__main__":
    # Run the simulation
    asyncio.run(main())
