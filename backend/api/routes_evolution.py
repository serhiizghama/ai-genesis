"""Evolution and mutation API routes.

Provides endpoints for:
- Manually triggering evolution cycles
- Viewing applied mutations
- Inspecting mutation source code
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis

import structlog

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import EvolutionTrigger

logger = structlog.get_logger()

router = APIRouter()


# -------------------------------------------------------------------------
# Request Models
# -------------------------------------------------------------------------


class TriggerRequest(BaseModel):
    """Request model for manual evolution trigger."""

    problem: str = Field(
        default="manual_test",
        description="Type of problem to solve (e.g., 'starvation', 'overpopulation', 'manual_test')",
    )
    severity: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Severity level from 0.0 (low) to 1.0 (critical)",
    )


# -------------------------------------------------------------------------
# Response Models
# -------------------------------------------------------------------------


class TriggerResponse(BaseModel):
    """Response model for manual evolution trigger."""

    status: str = Field(..., description="Status of the trigger request")
    trigger_id: str = Field(..., description="Unique ID for this trigger")
    message: str = Field(..., description="Human-readable message")


class MutationInfo(BaseModel):
    """Information about a single mutation."""

    mutation_id: str = Field(..., description="Unique mutation identifier")
    trait_name: str = Field(..., description="Name of the trait")
    version: int = Field(..., description="Version number")
    status: str = Field(..., description="Status: applied, failed, pending")
    timestamp: float = Field(..., description="Unix timestamp when created")
    code_hash: str = Field(default="", description="SHA-256 hash of source code")


class MutationsListResponse(BaseModel):
    """Response model for mutations list endpoint."""

    count: int = Field(..., description="Total number of mutations")
    mutations: list[MutationInfo] = Field(..., description="List of mutations")


class MutationSourceResponse(BaseModel):
    """Response model for mutation source code endpoint."""

    mutation_id: str = Field(..., description="Mutation identifier")
    trait_name: str = Field(..., description="Trait name")
    source_code: str = Field(..., description="Python source code")
    status: str = Field(..., description="Status: applied, failed, pending")


# -------------------------------------------------------------------------
# T-058: POST /api/evolution/trigger
# -------------------------------------------------------------------------


@router.post("/evolution/trigger", response_model=TriggerResponse)
async def trigger_evolution(
    body: TriggerRequest,
    request: Request,
) -> TriggerResponse:
    """Manually trigger an evolution cycle.

    This endpoint publishes an EvolutionTrigger event to ch:evolution:trigger
    which will be picked up by the Architect agent to start an evolution cycle.

    Args:
        body: Request body with problem type and severity.

    Returns:
        TriggerResponse with status and unique trigger ID.

    Note:
        This allows manual triggering with custom problem types and severity levels.
        Use for testing or when you want to force specific adaptations.
    """
    app_state = request.app.state.app_state
    redis = app_state.redis
    event_bus = app_state.event_bus

    if not redis:
        raise HTTPException(
            status_code=503,
            detail="Redis not available. Cannot publish evolution event.",
        )

    if not event_bus:
        raise HTTPException(
            status_code=503,
            detail="EventBus not available. Cannot publish evolution event.",
        )

    # Generate unique trigger ID
    trigger_id = f"manual_{uuid.uuid4().hex[:8]}"

    # Map severity float (0.0-1.0) to severity level string
    if body.severity >= 0.8:
        severity_level = "critical"
    elif body.severity >= 0.6:
        severity_level = "high"
    elif body.severity >= 0.3:
        severity_level = "medium"
    else:
        severity_level = "low"

    try:
        evolution_event = EvolutionTrigger(
            trigger_id=trigger_id,
            problem_type=body.problem,
            severity=severity_level,
            affected_entities=[],
            suggested_area="traits",
            snapshot_key="",
        )

        await event_bus.publish(Channels.EVOLUTION_TRIGGER, evolution_event)

        logger.info(
            "manual_evolution_triggered",
            trigger_id=trigger_id,
            problem_type=body.problem,
            severity=severity_level,
            channel=Channels.EVOLUTION_TRIGGER,
        )

        return TriggerResponse(
            status="success",
            trigger_id=trigger_id,
            message=f"Evolution cycle triggered: {body.problem} (severity: {severity_level})",
        )

    except Exception as exc:
        logger.error(
            "evolution_trigger_failed",
            trigger_id=trigger_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger evolution: {exc}",
        )


# -------------------------------------------------------------------------
# T-052: GET /api/mutations
# -------------------------------------------------------------------------


@router.get("/mutations", response_model=MutationsListResponse)
async def get_mutations(request: Request) -> MutationsListResponse:
    """Get list of all mutations.

    Returns:
        List of mutations with their metadata (ID, trait name, status, etc.).

    Note:
        Reads from Redis keys: evo:mutation:*
        Each mutation has metadata stored in a hash with fields:
        - mutation_id
        - trait_name
        - version
        - status (applied/failed/pending)
        - timestamp
        - code_hash
    """
    app_state = request.app.state.app_state
    redis = app_state.redis

    if not redis:
        raise HTTPException(
            status_code=503,
            detail="Redis not available. Cannot fetch mutations.",
        )

    try:
        # Find all mutation keys
        # Pattern: evo:mutation:{mutation_id}
        mutation_keys = []
        async for key in redis.scan_iter(match="evo:mutation:*"):
            # Decode bytes to string if needed
            if isinstance(key, bytes):
                key = key.decode()
            mutation_keys.append(key)

        mutations: list[MutationInfo] = []

        # Fetch metadata for each mutation
        for key in mutation_keys:
            try:
                # Get mutation data from hash
                mutation_data = await redis.hgetall(key)  # type: ignore[misc]

                # Decode bytes to strings if needed
                if mutation_data:
                    decoded_data: dict[str, str] = {}
                    for k, v in mutation_data.items():
                        key_str = k.decode() if isinstance(k, bytes) else str(k)
                        val_str = v.decode() if isinstance(v, bytes) else str(v)
                        decoded_data[key_str] = val_str

                    # Extract mutation ID from key (evo:mutation:{id})
                    # Decode key if it's bytes
                    key_str = key.decode() if isinstance(key, bytes) else str(key)
                    mutation_id = key_str.split(":")[-1]

                    mutations.append(
                        MutationInfo(
                            mutation_id=decoded_data.get("mutation_id", mutation_id),
                            trait_name=decoded_data.get("trait_name", "unknown"),
                            version=int(decoded_data.get("version", 0)),
                            status=decoded_data.get("status", "unknown"),
                            timestamp=float(decoded_data.get("timestamp", 0)),
                            code_hash=decoded_data.get("code_hash", ""),
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "mutation_fetch_failed",
                    key=key,
                    error=str(exc),
                )
                continue

        # Sort by timestamp (newest first)
        mutations.sort(key=lambda m: m.timestamp, reverse=True)

        return MutationsListResponse(
            count=len(mutations),
            mutations=mutations,
        )

    except Exception as exc:
        logger.error(
            "mutations_list_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch mutations: {exc}",
        )


# -------------------------------------------------------------------------
# T-052: GET /api/mutations/{mutation_id}/source
# -------------------------------------------------------------------------


@router.get("/mutations/{mutation_id}/source", response_model=MutationSourceResponse)
async def get_mutation_source(
    mutation_id: str,
    request: Request,
) -> MutationSourceResponse:
    """Get source code for a specific mutation.

    Args:
        mutation_id: Unique identifier of the mutation.

    Returns:
        Mutation source code and metadata.

    Raises:
        HTTPException: If mutation not found or Redis unavailable.

    Note:
        Source code is stored in Redis key: evo:mutation:{mutation_id}:source
        Metadata is stored in Redis hash: evo:mutation:{mutation_id}
    """
    app_state = request.app.state.app_state
    redis = app_state.redis

    if not redis:
        raise HTTPException(
            status_code=503,
            detail="Redis not available. Cannot fetch mutation source.",
        )

    try:
        # Fetch metadata
        metadata_key = f"evo:mutation:{mutation_id}"
        mutation_data = await redis.hgetall(metadata_key)  # type: ignore[misc]

        if not mutation_data:
            raise HTTPException(
                status_code=404,
                detail=f"Mutation '{mutation_id}' not found",
            )

        # Decode metadata
        decoded_data: dict[str, str] = {}
        for k, v in mutation_data.items():
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            val_str = v.decode() if isinstance(v, bytes) else str(v)
            decoded_data[key_str] = val_str

        # Fetch source code
        source_key = f"evo:mutation:{mutation_id}:source"
        source_code = await redis.get(source_key)  # type: ignore[misc]

        if source_code is None:
            # Try alternative: file path in metadata
            file_path = decoded_data.get("file_path", "")
            if file_path:
                try:
                    from pathlib import Path

                    source_code = Path(file_path).read_text()
                except Exception as file_exc:
                    logger.warning(
                        "source_file_read_failed",
                        file_path=file_path,
                        error=str(file_exc),
                    )
                    source_code = "# Source code not available"
            else:
                source_code = "# Source code not available"
        elif isinstance(source_code, bytes):
            source_code = source_code.decode()

        return MutationSourceResponse(
            mutation_id=mutation_id,
            trait_name=decoded_data.get("trait_name", "unknown"),
            source_code=str(source_code),
            status=decoded_data.get("status", "unknown"),
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as exc:
        logger.error(
            "mutation_source_fetch_failed",
            mutation_id=mutation_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch mutation source: {exc}",
        )
