"""PostgreSQL repository — all async CRUD operations for AI-Genesis.

All functions accept an asyncpg.Pool as the first argument so callers
don't have to manage individual connections.

JSON/JSONB columns receive Python dicts/lists directly — the asyncpg
pool is configured with a json codec in connection.init_db().
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg
import structlog

logger = structlog.get_logger()


async def save_checkpoint(
    pool: asyncpg.Pool,
    tick: int,
    params: dict,
    entities: list,
    avg_energy: float,
    resource_count: int,
) -> int:
    """Save a world checkpoint and entity snapshots.

    Args:
        pool: asyncpg connection pool.
        tick: Current simulation tick.
        params: World parameters (settings dict).
        entities: List of alive BaseEntity objects.
        avg_energy: Average energy across entities.
        resource_count: Number of resources in the environment.

    Returns:
        checkpoint_id (int) of the inserted row.
    """
    entity_count = len(entities)

    async with pool.acquire() as conn:
        async with conn.transaction():
            checkpoint_id: int = await conn.fetchval(
                """
                INSERT INTO world_checkpoints (tick, params, entity_count, avg_energy, resource_count)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                tick,
                params,  # dict → codec serialises to JSONB
                entity_count,
                avg_energy,
                resource_count,
            )

            # Batch-insert entity snapshots
            if entities:
                records = [
                    (
                        checkpoint_id,
                        e.id,
                        e.x,
                        e.y,
                        e.energy,
                        e.max_energy,
                        e.age,
                        [t.__class__.__name__ for t in e.traits],  # list → codec → JSONB
                        e.state,
                        e.parent_id,
                    )
                    for e in entities
                ]
                await conn.executemany(
                    """
                    INSERT INTO entity_snapshots
                        (checkpoint_id, entity_id, x, y, energy, max_energy, age, traits, state, parent_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    records,
                )

    logger.info(
        "checkpoint_saved",
        checkpoint_id=checkpoint_id,
        tick=tick,
        entity_count=entity_count,
    )
    return checkpoint_id


async def save_mutation(pool: asyncpg.Pool, mutation_data: dict) -> None:
    """Persist a new mutation record.

    Args:
        pool: asyncpg connection pool.
        mutation_data: Dict with keys: mutation_id, trait_name, version,
            code_hash, source_code, cycle_id, trigger_type, status.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mutations
                (mutation_id, trait_name, version, code_hash, source_code,
                 cycle_id, trigger_type, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (mutation_id) DO NOTHING
            """,
            mutation_data["mutation_id"],
            mutation_data["trait_name"],
            mutation_data["version"],
            mutation_data["code_hash"],
            mutation_data["source_code"],
            mutation_data.get("cycle_id"),
            mutation_data.get("trigger_type"),
            mutation_data.get("status", "pending"),
        )


async def update_mutation_status(
    pool: asyncpg.Pool,
    mutation_id: str,
    status: str,
    failed_reason: Optional[str] = None,
) -> None:
    """Update mutation status after apply or failure.

    Args:
        pool: asyncpg connection pool.
        mutation_id: The mutation to update.
        status: New status ('applied' or 'failed').
        failed_reason: Optional error message if status is 'failed'.
    """
    async with pool.acquire() as conn:
        if status == "applied":
            await conn.execute(
                """
                UPDATE mutations
                SET status = $1, is_active = TRUE, applied_at = NOW()
                WHERE mutation_id = $2
                """,
                status,
                mutation_id,
            )
        else:
            await conn.execute(
                """
                UPDATE mutations
                SET status = $1, is_active = FALSE, failed_reason = $2
                WHERE mutation_id = $3
                """,
                status,
                failed_reason,
                mutation_id,
            )


async def save_cycle(
    pool: asyncpg.Pool,
    cycle_id: str,
    problem_type: Optional[str],
    severity: Optional[str],
    stage: str,
) -> None:
    """Insert or update an evolution cycle record.

    Args:
        pool: asyncpg connection pool.
        cycle_id: Unique cycle identifier.
        problem_type: Type of problem that triggered the cycle.
        severity: Severity level ('low', 'medium', 'high').
        stage: Current stage name.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO evolution_cycles (cycle_id, problem_type, severity, stage)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (cycle_id) DO NOTHING
            """,
            cycle_id,
            problem_type,
            severity,
            stage,
        )


async def update_cycle_stage(
    pool: asyncpg.Pool,
    cycle_id: str,
    stage: str,
    mutation_id: Optional[str] = None,
    completed: bool = False,
) -> None:
    """Update the stage (and optionally complete) an evolution cycle.

    Args:
        pool: asyncpg connection pool.
        cycle_id: Cycle to update.
        stage: New stage name.
        mutation_id: Associated mutation ID (if any).
        completed: If True, sets completed_at to NOW().
    """
    async with pool.acquire() as conn:
        if completed:
            await conn.execute(
                """
                UPDATE evolution_cycles
                SET stage = $1, mutation_id = COALESCE($2, mutation_id), completed_at = NOW()
                WHERE cycle_id = $3
                """,
                stage,
                mutation_id,
                cycle_id,
            )
        else:
            await conn.execute(
                """
                UPDATE evolution_cycles
                SET stage = $1, mutation_id = COALESCE($2, mutation_id)
                WHERE cycle_id = $3
                """,
                stage,
                mutation_id,
                cycle_id,
            )


async def save_feed_message(
    pool: asyncpg.Pool,
    agent: str,
    action: str,
    message: str,
    metadata: Optional[dict],
    cycle_id: Optional[str],
) -> None:
    """Persist a feed message to the database.

    Args:
        pool: asyncpg connection pool.
        agent: Agent name (e.g. 'watcher', 'coder').
        action: Action type (e.g. 'mutation_ready').
        message: Human-readable message text.
        metadata: Optional dict of extra data.
        cycle_id: Optional evolution cycle ID.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO feed_messages (agent, action, message, metadata, cycle_id)
            VALUES ($1, $2, $3, $4, $5)
            """,
            agent,
            action,
            message,
            metadata,  # dict or None → codec → JSONB
            cycle_id,
        )


async def get_latest_checkpoint(pool: asyncpg.Pool) -> Optional[dict[str, Any]]:
    """Fetch the most recent world checkpoint with its entity snapshots.

    Args:
        pool: asyncpg connection pool.

    Returns:
        Dict with checkpoint data and 'entities' list, or None if no checkpoints.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, tick, params, entity_count, avg_energy, resource_count, created_at
            FROM world_checkpoints
            ORDER BY tick DESC
            LIMIT 1
            """
        )

        if not row:
            return None

        checkpoint = dict(row)
        # params is already a dict (decoded by the jsonb codec)

        entities = await conn.fetch(
            """
            SELECT entity_id, x, y, energy, max_energy, age, traits, state, parent_id
            FROM entity_snapshots
            WHERE checkpoint_id = $1
            """,
            checkpoint["id"],
        )

        checkpoint["entities"] = [
            {
                "entity_id": str(e["entity_id"]),
                "x": e["x"],
                "y": e["y"],
                "energy": e["energy"],
                "max_energy": e["max_energy"],
                "age": e["age"],
                "traits": e["traits"],  # already a list (decoded by codec)
                "state": e["state"],
                "parent_id": str(e["parent_id"]) if e["parent_id"] else None,
            }
            for e in entities
        ]

        return checkpoint


async def get_active_mutations(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """Fetch all active (applied) mutations for trait restoration.

    Args:
        pool: asyncpg connection pool.

    Returns:
        List of dicts with mutation fields.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT mutation_id, trait_name, version, code_hash, source_code, cycle_id
            FROM mutations
            WHERE is_active = TRUE AND status = 'applied'
            ORDER BY applied_at ASC
            """
        )
        return [dict(r) for r in rows]


async def get_recent_feed(pool: asyncpg.Pool, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch recent feed messages for UI on restart.

    Args:
        pool: asyncpg connection pool.
        limit: Max number of messages to return.

    Returns:
        List of feed message dicts ordered oldest-first.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT agent, action, message, metadata, cycle_id, created_at
            FROM feed_messages
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        result = []
        for r in rows:
            item = dict(r)
            # metadata is already a dict/None (decoded by codec)
            item["created_at"] = item["created_at"].isoformat()
            result.append(item)
        # Return oldest-first for chronological display
        result.reverse()
        return result


async def get_checkpoints_list(pool: asyncpg.Pool, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch recent checkpoint summaries for the API.

    Args:
        pool: asyncpg connection pool.
        limit: Max number of checkpoints to return.

    Returns:
        List of checkpoint summary dicts ordered newest-first.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, tick, entity_count, avg_energy, resource_count, created_at
            FROM world_checkpoints
            ORDER BY tick DESC
            LIMIT $1
            """,
            limit,
        )
        return [
            {
                "id": r["id"],
                "tick": r["tick"],
                "entity_count": r["entity_count"],
                "avg_energy": r["avg_energy"],
                "resource_count": r["resource_count"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
