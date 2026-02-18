"""World state and control API routes.

Provides endpoints for:
- Getting current world state
- Updating world parameters
- Retrieving simulation statistics
- Health check with Redis and Ollama probes
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket
from starlette.websockets import WebSocketDisconnect
from pydantic import BaseModel, Field

import structlog

from backend.api.ws_handler import FeedConnectionManager, websocket_endpoint

logger = structlog.get_logger()

router = APIRouter()


# -------------------------------------------------------------------------
# Request/Response Models
# -------------------------------------------------------------------------


class WorldStateResponse(BaseModel):
    """Response model for world state endpoint."""

    tick: int = Field(..., description="Current simulation tick")
    entity_count: int = Field(..., description="Number of living entities")
    total_entities: int = Field(..., description="Total entities (including dead)")
    resource_count: int = Field(..., description="Number of resources in world")
    world_params: dict[str, Any] = Field(
        ..., description="World parameters (width, height, etc.)"
    )


class WorldParamsUpdate(BaseModel):
    """Request model for updating world parameters."""

    param: str = Field(..., description="Parameter name to update")
    value: Any = Field(..., description="New value for the parameter")


class StatsResponse(BaseModel):
    """Response model for simulation statistics."""

    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    tick: int = Field(..., description="Current simulation tick")
    entity_count: int = Field(..., description="Current living entity count")
    total_entities_spawned: int = Field(
        ..., description="Total entities spawned since start"
    )
    avg_energy: float = Field(..., description="Average entity energy")
    resource_count: int = Field(..., description="Current resource count")
    mutations_applied: int = Field(
        default=0, description="Number of mutations applied (Phase 5)"
    )
    tps: float = Field(..., description="Ticks per second (actual vs target)")
    predator_kills: int = Field(default=0, description="Molbots killed by predators (cumulative)")
    virus_kills: int = Field(default=0, description="Molbots killed by virus (cumulative)")
    predator_deaths: int = Field(default=0, description="Predators that died (cumulative)")
    cycle_stage: str = Field(default="idle", description="Current evolution cycle stage")
    cycle_problem: str = Field(default="", description="Problem type triggering the cycle")
    cycle_severity: str = Field(default="", description="Severity of the detected problem")


# -------------------------------------------------------------------------
# T-024: GET /api/world/state
# -------------------------------------------------------------------------


@router.get("/world/state", response_model=WorldStateResponse)
async def get_world_state(request: Request) -> WorldStateResponse:
    """Get current world state.

    Returns:
        Current tick, entity count, and world parameters.

    Note:
        World parameters are read from the engine's settings.
    """
    app_state = request.app.state.app_state
    engine = app_state.engine

    # Get entity counts
    entity_count = engine.entity_manager.count_alive()
    total_entities = engine.entity_manager.count()

    # Get resource count
    resource_count = engine.environment.count()

    # Build world params from settings
    world_params = {
        "width": engine.settings.world_width,
        "height": engine.settings.world_height,
        "tick_rate_ms": engine.settings.tick_rate_ms,
        "min_population": engine.settings.min_population,
        "max_entities": engine.settings.max_entities,
        "friction": engine.physics.friction_coefficient,
        "boundary_mode": engine.physics.boundary_mode,
    }

    return WorldStateResponse(
        tick=engine.tick_counter,
        entity_count=entity_count,
        total_entities=total_entities,
        resource_count=resource_count,
        world_params=world_params,
    )


# -------------------------------------------------------------------------
# T-025: POST /api/world/params
# -------------------------------------------------------------------------


@router.post("/world/params")
async def update_world_params(
    params: WorldParamsUpdate,
    request: Request,
) -> dict[str, str]:
    """Update world parameters dynamically.

    Args:
        params: Parameter name and new value.

    Returns:
        Success message with updated parameter info.

    Raises:
        HTTPException: If parameter is invalid or update fails.

    Note:
        Updates are applied to the running engine's settings.
        In Phase 3, this will also publish ch:world:params_changed event.
    """
    app_state = request.app.state.app_state
    engine = app_state.engine
    redis = app_state.redis

    param_name = params.param
    param_value = params.value

    # Map of allowed parameters and their types
    allowed_params = {
        "min_population": int,
        "max_entities": int,
        "tick_rate_ms": int,
        "friction": float,
        "spawn_rate": float,
    }

    # Validate parameter name
    if param_name not in allowed_params:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid parameter '{param_name}'. Allowed: {list(allowed_params.keys())}",
        )

    # Validate and convert type
    expected_type = allowed_params[param_name]
    try:
        typed_value = expected_type(param_value)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid value type for '{param_name}'. Expected {expected_type.__name__}: {e}",
        )

    # Apply update based on parameter
    try:
        if param_name == "min_population":
            engine.settings.min_population = typed_value
        elif param_name == "max_entities":
            engine.settings.max_entities = typed_value
        elif param_name == "tick_rate_ms":
            engine.settings.tick_rate_ms = typed_value
        elif param_name == "friction":
            engine.physics.friction_coefficient = typed_value
        elif param_name == "spawn_rate":
            engine.settings.spawn_rate = typed_value

        logger.info(
            "world_param_updated",
            param=param_name,
            value=typed_value,
            tick=engine.tick_counter,
        )

        # TODO Phase 3: Publish event to Redis
        # if redis:
        #     await redis.publish(
        #         "ch:world:params_changed",
        #         json.dumps({"param": param_name, "value": typed_value})
        #     )

        return {
            "status": "success",
            "message": f"Updated {param_name} to {typed_value}",
            "param": param_name,
            "value": str(typed_value),
        }

    except Exception as e:
        logger.error(
            "world_param_update_failed",
            param=param_name,
            value=typed_value,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update parameter: {e}",
        )


# -------------------------------------------------------------------------
# T-026: GET /api/stats
# -------------------------------------------------------------------------


@router.get("/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    """Get extended simulation statistics.

    Returns:
        Detailed statistics including uptime, entity counts, energy,
        resources, and performance metrics.

    Note:
        mutations_applied will be populated in Phase 5 when LLM integration is added.
    """
    app_state = request.app.state.app_state
    engine = app_state.engine

    # Calculate uptime
    uptime = time.time() - app_state.start_time

    # Get entity stats
    entities = engine.entity_manager.alive()
    entity_count = len(entities)

    # Calculate average energy
    avg_energy = 0.0
    if entity_count > 0:
        total_energy = sum(e.energy for e in entities)
        avg_energy = total_energy / entity_count

    # Calculate actual TPS (ticks per second)
    # If tick_counter > 0 and uptime > 0, calculate actual rate
    tps = 0.0
    if uptime > 0 and engine.tick_counter > 0:
        tps = engine.tick_counter / uptime

    # Get resource count
    resource_count = engine.environment.count()

    # Total entities spawned (approximate - would need counter in engine)
    # For now, use current count as placeholder
    total_spawned = engine.entity_manager.count()

    # Read current evolution cycle state from Redis
    cycle_stage = "idle"
    cycle_problem = ""
    cycle_severity = ""
    redis = getattr(app_state, "redis", None)
    if redis:
        try:
            lock_exists = await redis.exists("evo:cycle:lock")
            if lock_exists:
                raw = await redis.hgetall("evo:cycle:current")
                if raw:
                    decoded = {k.decode() if isinstance(k, bytes) else k:
                               v.decode() if isinstance(v, bytes) else v
                               for k, v in raw.items()}
                    cycle_stage = decoded.get("stage", "idle")
                    cycle_problem = decoded.get("problem_type", "")
                    cycle_severity = decoded.get("severity", "")
        except Exception:
            pass  # Redis unavailable — stay idle

    return StatsResponse(
        uptime_seconds=round(uptime, 2),
        tick=engine.tick_counter,
        entity_count=entity_count,
        total_entities_spawned=total_spawned,
        avg_energy=round(avg_energy, 2),
        resource_count=resource_count,
        mutations_applied=0,  # TODO: Track in Phase 5
        tps=round(tps, 2),
        predator_kills=engine._predator_kill_count,
        virus_kills=engine._virus_kill_count,
        predator_deaths=engine._predator_death_count,
        cycle_stage=cycle_stage,
        cycle_problem=cycle_problem,
        cycle_severity=cycle_severity,
    )


# -------------------------------------------------------------------------
# T-027: WebSocket /ws/world-stream
# -------------------------------------------------------------------------


# -------------------------------------------------------------------------
# T-079: GET /api/health
# -------------------------------------------------------------------------


class HealthServicesStatus(BaseModel):
    """Status of individual backing services."""

    redis: bool
    ollama: bool
    core: bool


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""

    status: str = Field(..., description='"ok" or "degraded"')
    services: HealthServicesStatus


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Check health of Redis, Ollama, and the simulation core.

    Returns 200 with status="ok" when all services are reachable.
    Returns 503 with status="degraded" and per-service detail when any
    service is unavailable.
    """
    app_state = request.app.state.app_state
    engine = app_state.engine
    redis = app_state.redis

    # --- Redis ping ---
    redis_ok = False
    if redis is not None:
        try:
            await redis.ping()
            redis_ok = True
        except Exception:
            pass

    # --- Ollama reachability ---
    ollama_ok = False
    ollama_url: str = engine.settings.ollama_url
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        pass

    # --- Core engine ---
    core_ok: bool = engine.running

    services = HealthServicesStatus(
        redis=redis_ok,
        ollama=ollama_ok,
        core=core_ok,
    )

    all_ok = redis_ok and ollama_ok and core_ok
    status_str = "ok" if all_ok else "degraded"

    if not all_ok:
        raise HTTPException(
            status_code=503,
            detail=HealthResponse(status=status_str, services=services).model_dump(),
        )

    return HealthResponse(status=status_str, services=services)


# -------------------------------------------------------------------------
# T-072: GET /api/entities/{entity_id} — entity inspector
# -------------------------------------------------------------------------


class EntityDetailResponse(BaseModel):
    """Response model for entity detail endpoint."""

    numeric_id: int = Field(..., description="Numeric ID (hash) as seen in stream")
    string_id: str = Field(..., description="Internal UUID")
    entity_type: str = Field(..., description="Entity type: 'molbot' or 'predator'")
    generation: int
    age: int
    energy: float
    max_energy: float
    energy_pct: float
    state: str
    traits: list[str] = Field(..., description="Active trait class names")
    deactivated_traits: list[str]
    evolution_count: int = Field(..., description="Number of mutations applied to this entity")
    infected: bool = Field(default=False, description="Whether entity is currently infected by virus")
    infection_timer: int = Field(default=0, description="Ticks remaining until virus recovery")
    metabolism_rate: float = Field(..., description="Energy consumed per tick")
    parent_id: str | None = Field(default=None, description="Parent entity UUID (null for seed entities)")


@router.get("/entities/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(entity_id: int, request: Request) -> EntityDetailResponse:
    """Get details for a specific entity by its stream numeric ID."""
    engine = request.app.state.app_state.engine
    entities = engine.entity_manager.alive()

    entity = next(
        (e for e in entities if (hash(e.id) & 0xFFFFFFFF) == entity_id),
        None,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    trait_names = [t.__class__.__name__ for t in entity.traits]
    return EntityDetailResponse(
        numeric_id=entity_id,
        string_id=entity.id,
        entity_type=entity.entity_type,
        generation=entity.generation,
        age=entity.age,
        energy=round(entity.energy, 1),
        max_energy=entity.max_energy,
        energy_pct=round(max(0.0, min(100.0, (entity.energy / entity.max_energy) * 100)), 1),
        state=entity.state,
        traits=trait_names,
        deactivated_traits=list(entity.deactivated_traits),
        evolution_count=len(entity.traits),
        infected=entity.infected,
        infection_timer=entity.infection_timer,
        metabolism_rate=round(entity.metabolism_rate, 2),
        parent_id=entity.parent_id,
    )


@router.get("/mutations/source/{trait_name}")
async def get_trait_source(trait_name: str, request: Request) -> dict[str, str]:
    """Get the LLM-generated source code for a registered trait by name."""
    engine = request.app.state.app_state.engine
    source = engine.registry.get_source(trait_name)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source not found for trait '{trait_name}'")
    return {"trait_name": trait_name, "source": source}


@router.post("/entities/{entity_id}/kill")
async def kill_entity(entity_id: int, request: Request) -> dict[str, str]:
    """Kill a specific entity (debug)."""
    engine = request.app.state.app_state.engine
    entities = engine.entity_manager.alive()

    entity = next(
        (e for e in entities if (hash(e.id) & 0xFFFFFFFF) == entity_id),
        None,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity.energy = 0.0
    entity.state = "dead"
    logger.info("entity_killed_debug", entity_id=entity.id, numeric_id=entity_id)
    return {"status": "killed", "entity_id": entity.id}


# -------------------------------------------------------------------------

@router.websocket("/ws/feed")
async def feed_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for Evolution Feed streaming.

    Clients connect to receive JSON feed messages from agents:
    {agent, message, timestamp}

    Agent values: 'watcher' | 'architect' | 'coder' | 'patcher'
    """
    app_state = websocket.app.state.app_state
    feed_manager: FeedConnectionManager = app_state.feed_ws_manager
    await feed_manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data and data != "ping":
                logger.debug("feed_ws_client_message", message=data)
    except WebSocketDisconnect:
        feed_manager.disconnect(websocket)
    except Exception as exc:
        logger.error("feed_ws_error", error=str(exc), error_type=type(exc).__name__)
        feed_manager.disconnect(websocket)


@router.websocket("/ws/world-stream")
async def world_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time world state streaming.

    Clients connect to this endpoint to receive binary world state frames
    pushed from the simulation engine at 30 FPS (every 2 ticks).

    Protocol:
        - Server → Client: Binary frames (struct.pack format)
        - Client → Server: Optional ping messages to keep connection alive

    Note:
        This is a one-way stream. Clients don't need to send anything,
        but can send "ping" to prevent timeout.
    """
    # Access app state through websocket.app
    app_state = websocket.app.state.app_state
    ws_manager = app_state.ws_manager

    await websocket_endpoint(websocket, ws_manager)
