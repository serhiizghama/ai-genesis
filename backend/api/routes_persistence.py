"""Persistence API routes — checkpoints and feed history.

Provides:
- GET /api/checkpoints       — list recent world checkpoints
- GET /api/feed/history      — feed message history from PostgreSQL
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

import structlog

logger = structlog.get_logger()

router = APIRouter()


@router.get("/checkpoints", summary="List recent world checkpoints")
async def get_checkpoints(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """Return the most recent world checkpoints from PostgreSQL.

    Args:
        limit: Maximum number of checkpoints to return (1-100).

    Returns:
        List of checkpoint summaries ordered newest-first.
    """
    db_pool = getattr(request.app.state.app_state, "db_pool", None)
    if db_pool is None:
        return []

    from backend.db.repository import get_checkpoints_list
    return await get_checkpoints_list(db_pool, limit=limit)


@router.get("/feed/history", summary="Feed message history")
async def get_feed_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """Return recent agent feed messages from PostgreSQL.

    Useful for populating the UI feed on browser refresh or system restart.

    Args:
        limit: Maximum number of messages to return (1-500).

    Returns:
        List of feed messages ordered oldest-first.
    """
    db_pool = getattr(request.app.state.app_state, "db_pool", None)
    if db_pool is None:
        return []

    from backend.db.repository import get_recent_feed
    return await get_recent_feed(db_pool, limit=limit)
