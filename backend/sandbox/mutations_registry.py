"""Mutation Registry — persists mutation metadata and source code to Redis.

Used by the Coder Agent to record each generated mutation so that
the REST API can serve GET /api/mutations and GET /api/mutations/{id}/source.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger()

# TTL for mutation records: 7 days
_MUTATION_TTL_SEC: int = 86400 * 7


class MutationRegistry:
    """Stores mutation metadata and source code in Redis.

    Redis key layout (matches existing API expectations):
        evo:mutation:{mutation_id}         — HASH with metadata fields
        evo:mutation:{mutation_id}:source  — STRING with full source code
    """

    def __init__(self, redis: Redis) -> None:
        """Initialise the registry.

        Args:
            redis: Async Redis connection.
        """
        self._redis = redis

    async def save(
        self,
        mutation_id: str,
        trait_name: str,
        version: int,
        file_path: str,
        code_hash: str,
        cycle_id: str,
        source_code: str,
        status: str = "pending",
    ) -> None:
        """Persist a mutation to Redis.

        Args:
            mutation_id: Unique mutation identifier (e.g. 'mut_01ab23cd').
            trait_name: Name of the generated trait class.
            version: Version number.
            file_path: Path to the saved .py file on disk.
            code_hash: SHA-256 hash of the source code.
            cycle_id: Evolution cycle ID shared across all agents.
            source_code: Full Python source code of the mutation.
            status: Initial status ('pending', 'applied', 'failed').
        """
        meta_key = f"evo:mutation:{mutation_id}"
        source_key = f"evo:mutation:{mutation_id}:source"

        await self._redis.hset(
            meta_key,
            mapping={
                "mutation_id": mutation_id,
                "trait_name": trait_name,
                "version": str(version),
                "status": status,
                "timestamp": str(time.time()),
                "file_path": file_path,
                "code_hash": code_hash,
                "cycle_id": cycle_id,
            },
        )
        await self._redis.expire(meta_key, _MUTATION_TTL_SEC)

        await self._redis.set(source_key, source_code, ex=_MUTATION_TTL_SEC)

        logger.info(
            "mutation_saved_to_registry",
            mutation_id=mutation_id,
            trait_name=trait_name,
            version=version,
            cycle_id=cycle_id,
        )
