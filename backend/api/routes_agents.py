"""Open Mutation API — HTTP routes for external agent interaction.

Provides:
- Context API: world metrics, task queue, sandbox rules
- Propose API: submit mutations for validation
- Status/Effects API: poll mutation results

Architecture: routes are thin wrappers; business logic lives in agents/.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from redis.asyncio import Redis

from backend.agents.entity_api import ALLOWED_ENTITY_ATTRS
from backend.sandbox.validator import ALLOWED_IMPORTS, BANNED_ATTRS, BANNED_CALLS

logger = structlog.get_logger()

router = APIRouter()


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_redis(request: Request) -> Redis:
    redis: Optional[Redis] = request.app.state.app_state.redis
    if redis is None:
        raise HTTPException(503, detail="Redis not available")
    return redis


async def _check_rate_limits(
    redis: Redis,
    agent_id: str,
    client_ip: str,
) -> None:
    """Raise 429 if any rate limit exceeded."""
    # Per-IP per-minute
    key_ip = f"ratelimit:ip:min:{client_ip}"
    count_ip = await redis.incr(key_ip)
    if count_ip == 1:
        await redis.expire(key_ip, 60)
    if count_ip > 10:
        raise HTTPException(
            429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "detail": f"Too many requests from IP {client_ip} (limit: 10/min)",
                "retry_after_sec": 60,
            },
        )

    # Per-agent per-hour
    key_hr = f"ratelimit:agent:hr:{agent_id}"
    count_hr = await redis.incr(key_hr)
    if count_hr == 1:
        await redis.expire(key_hr, 3600)
    if count_hr > 60:
        raise HTTPException(
            429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "detail": f"Hourly limit exceeded for agent '{agent_id}' (limit: 60/hr)",
                "retry_after_sec": 3600,
            },
        )

    # Max active mutations per agent
    key_active = f"ratelimit:active:{agent_id}"
    raw_active = await redis.get(key_active)
    active = int(raw_active) if raw_active else 0
    if active >= 5:
        raise HTTPException(
            429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "detail": f"Too many active mutations for agent_id '{agent_id}' (limit: 5)",
                "retry_after_sec": 120,
            },
        )


# ─── Context API ─────────────────────────────────────────────────────────────


@router.get("/agents/context/metrics")
async def get_context_metrics(request: Request) -> dict[str, object]:
    """Return aggregated world metrics from the latest Redis snapshot."""
    redis = _get_redis(request)

    # Find the latest ws:snapshot:* key
    latest_key: Optional[str] = None
    latest_tick = -1
    async for key in redis.scan_iter("ws:snapshot:*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        try:
            tick = int(key_str.rsplit(":", 1)[-1])
            if tick > latest_tick:
                latest_tick = tick
                latest_key = key_str
        except ValueError:
            continue

    if latest_key is None:
        raise HTTPException(503, detail="No world snapshot available yet")

    raw = await redis.get(latest_key)
    if raw is None:
        raise HTTPException(503, detail="Snapshot expired")

    snap: dict[str, object] = json.loads(raw)

    # Detect anomalies inline (avoid importing watcher to respect arch boundaries)
    anomalies: list[str] = []
    avg_energy = float(snap.get("avg_energy", 100.0))
    entity_count = int(snap.get("entity_count", 0))
    if avg_energy < 20.0:
        anomalies.append("starvation")
    if entity_count < 30:  # min_population * 1.5 approximation
        anomalies.append("extinction")

    return {
        "tick": snap.get("tick", 0),
        "entity_count": entity_count,
        "avg_energy": round(avg_energy, 1),
        "resource_count": snap.get("resource_count", 0),
        "death_stats": snap.get("death_stats", {}),
        "trait_usage": snap.get("trait_usage", {}),
        "anomalies": anomalies,
    }


@router.get("/agents/context/tasks")
async def get_context_tasks(request: Request) -> dict[str, object]:
    """Return active (non-expired) tasks from the agent task queue."""
    redis = _get_redis(request)

    now = time.time()

    # Remove expired tasks (score < now)
    await redis.zremrangebyscore("agent:tasks:queue", "-inf", now)

    # Fetch remaining task IDs
    task_ids_raw: list = await redis.zrange("agent:tasks:queue", 0, -1, withscores=True)

    tasks: list[dict[str, object]] = []
    for item in task_ids_raw:
        task_id_bytes, expires_at = item
        task_id = task_id_bytes.decode() if isinstance(task_id_bytes, bytes) else task_id_bytes
        raw_body = await redis.get(f"agent:task:{task_id}")
        if raw_body is None:
            continue
        body: dict[str, object] = json.loads(raw_body)
        body["ttl_remaining_sec"] = max(0, int(float(expires_at) - now))
        tasks.append(body)

    return {"tasks": tasks}


@router.get("/agents/context/sandbox-api")
async def get_sandbox_api(request: Request) -> dict[str, object]:
    """Return sandbox rules for writing valid mutations. Versioned for caching."""
    app_state = request.app.state.app_state

    # Get sandbox_rules_version from settings if available via engine
    sandbox_rules_version = "3"
    try:
        engine = app_state.engine
        if hasattr(engine, "_settings"):
            sandbox_rules_version = engine._settings.sandbox_rules_version
    except Exception:
        pass

    return {
        "api_version": "1",
        "sandbox_rules_version": sandbox_rules_version,
        "trait_pattern": "define class BaseTrait stub inline, then inherit from it",
        "required_method": "async execute(self, entity) -> None",
        "allowed_imports": sorted(ALLOWED_IMPORTS),
        "forbidden_imports": ["os", "sys", "subprocess", "socket", "shutil", "backend"],
        "forbidden_calls": sorted(BANNED_CALLS),
        "forbidden_attrs": sorted(BANNED_ATTRS),
        "entity_allowed_attrs": sorted(ALLOWED_ENTITY_ATTRS),
        "timeout_ms": 5,
        "max_loop_iterations": 100,
        "no_module_level_code": True,
        "example": (
            "class BaseTrait:\n"
            "    pass\n\n"
            "class MyTrait(BaseTrait):\n"
            "    async def execute(self, entity) -> None:\n"
            "        if entity.energy < 30:\n"
            "            entity.energy_consumption_rate *= 0.8"
        ),
    }


# ─── Propose API ─────────────────────────────────────────────────────────────


class ProposeRequest(BaseModel):
    """Body for POST /api/mutations/propose."""

    agent_id: str
    task_id: Optional[str] = None
    trait_name: str
    goal: str
    code: str

    @field_validator("trait_name")
    @classmethod
    def trait_name_snake_case(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError("trait_name must be snake_case (a-z, 0-9, _)")
        return v

    @field_validator("code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be empty")
        if len(v.encode()) > 32 * 1024:
            raise ValueError("code exceeds 32 KB limit")
        return v


@router.post("/mutations/propose", status_code=202)
async def propose_mutation(
    body: ProposeRequest,
    request: Request,
) -> dict[str, object]:
    """Accept an external agent's mutation for validation.

    Returns mutation_id and 'queued' status. Poll GET /mutations/{id}/status.
    """
    redis = _get_redis(request)
    client_ip = request.client.host if request.client else "unknown"

    # Rate limiting
    await _check_rate_limits(redis, body.agent_id, client_ip)

    mutation_id = f"mut_{uuid.uuid4().hex[:6]}"
    now = time.time()

    # Persist metadata hash
    await redis.hset(
        f"evo:mutation:{mutation_id}",
        mapping={
            "mutation_id": mutation_id,
            "agent_id": body.agent_id,
            "task_id": body.task_id or "",
            "trait_name": body.trait_name,
            "goal": body.goal,
            "status": "queued",
            "failure_reason_code": "",
            "validation_log": json.dumps([]),
            "created_at": str(now),
            "updated_at": str(now),
        },
    )
    await redis.expire(f"evo:mutation:{mutation_id}", 86400 * 7)  # 7 days TTL

    # Persist source code
    await redis.set(f"evo:mutation:{mutation_id}:source", body.code, ex=86400 * 7)

    # Increment active counter
    key_active = f"ratelimit:active:{body.agent_id}"
    await redis.incr(key_active)

    # Enqueue for gatekeeper
    await redis.lpush("agent:mutation:queue", mutation_id)

    logger.info(
        "mutation_queued",
        mutation_id=mutation_id,
        agent_id=body.agent_id,
        trait_name=body.trait_name,
    )

    return {
        "mutation_id": mutation_id,
        "status": "queued",
        "message": "Mutation accepted for validation",
    }


# ─── Status & Effects ─────────────────────────────────────────────────────────


@router.get("/mutations/{mutation_id}/status")
async def get_mutation_status(
    mutation_id: str,
    request: Request,
) -> dict[str, object]:
    """Return current validation status for a mutation."""
    redis = _get_redis(request)

    raw = await redis.hgetall(f"evo:mutation:{mutation_id}")
    if not raw:
        raise HTTPException(404, detail=f"Mutation '{mutation_id}' not found")

    data: dict[str, object] = {
        k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
        for k, v in raw.items()
    }

    validation_log: list[str] = []
    try:
        validation_log = json.loads(str(data.get("validation_log", "[]")))
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "mutation_id": mutation_id,
        "trait_name": data.get("trait_name", ""),
        "agent_id": data.get("agent_id", ""),
        "status": data.get("status", "unknown"),
        "failure_reason_code": data.get("failure_reason_code") or None,
        "created_at": float(data["created_at"]) if "created_at" in data else None,
        "updated_at": float(data["updated_at"]) if "updated_at" in data else None,
        "validation_log": validation_log,
    }


@router.get("/mutations/{mutation_id}/effects")
async def get_mutation_effects(
    mutation_id: str,
    request: Request,
) -> dict[str, object]:
    """Return observed fitness effects after activation (populated by Watcher)."""
    redis = _get_redis(request)

    # Check mutation exists
    status_raw = await redis.hget(f"evo:mutation:{mutation_id}", "status")
    if status_raw is None:
        raise HTTPException(404, detail=f"Mutation '{mutation_id}' not found")

    status = status_raw.decode() if isinstance(status_raw, bytes) else status_raw
    trait_name_raw = await redis.hget(f"evo:mutation:{mutation_id}", "trait_name")
    trait_name = (
        trait_name_raw.decode() if isinstance(trait_name_raw, bytes) else (trait_name_raw or "")
    )

    # Read effects if available
    effects_raw = await redis.get(f"evo:mutation:{mutation_id}:effects")
    if effects_raw is None:
        return {
            "mutation_id": mutation_id,
            "trait_name": trait_name,
            "status": status,
            "observation_window_ticks": 300,
            "observed": False,
            "effects": None,
        }

    effects: dict[str, object] = json.loads(effects_raw)
    return {
        "mutation_id": mutation_id,
        "trait_name": trait_name,
        "status": status,
        "observation_window_ticks": 300,
        "observed": True,
        "effects": effects.get("delta"),
        "fitness_verdict": effects.get("verdict", "neutral"),
    }
