"""Mutation Gatekeeper — validates and dispatches external agent mutations.

Responsibilities:
  1. BRPOP from 'agent:mutation:queue' (blocking pop with timeout).
  2. Run CodeValidator against the submitted code.
  3. On failure: update status → 'rejected' with failure_reason_code.
  4. On success: write the trait file to mutations/, publish MutationReady
     (existing RuntimePatcher will load and register it).
  5. Subscribe to MUTATION_APPLIED / MUTATION_FAILED / MUTATION_ROLLBACK
     to track final status transitions.

Location rationale: agents/ layer — can import from bus/, sandbox/, config.
Must NOT import from core/ directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import structlog
from redis.asyncio import Redis

from backend.bus.channels import Channels
from backend.bus.event_bus import EventBus
from backend.bus.events import MutationReady
from backend.config import Settings
from backend.sandbox.validator import CodeValidator

logger = structlog.get_logger()


def _next_version(mutations_dir: str, trait_name: str) -> int:
    """Find next available version number for a trait file.

    Scans existing trait_{name}_v*.py files and returns max_version + 1.
    """
    path = Path(mutations_dir)
    pattern = re.compile(rf"^trait_{re.escape(trait_name)}_v(\d+)\.py$")
    max_v = 0
    try:
        for entry in path.iterdir():
            m = pattern.match(entry.name)
            if m:
                max_v = max(max_v, int(m.group(1)))
    except OSError:
        pass
    return max_v + 1


def _error_code(error_msg: str) -> str:
    """Map CodeValidator error message to spec failure_reason_code."""
    m = error_msg.lower()
    if "syntax error" in m:
        return "SYNTAX_ERROR"
    if "forbidden import" in m or "not imported" in m:
        return "AST_IMPORT_FORBIDDEN"
    if "forbidden function call" in m:
        return "AST_BANNED_CALL"
    if "forbidden attribute access" in m or "forbidden name" in m:
        return "AST_BANNED_ATTR"
    if "no valid trait class" in m:
        return "AST_NO_TRAIT_CLASS"
    if "forbidden entity attribute" in m:
        return "AST_ENTITY_ATTR_FORBIDDEN"
    if "traits instantiated without args" in m:
        return "AST_INIT_REQUIRED_ARGS"
    if "unbound" in m or "nameerror" in m:
        return "AST_UNBOUND_VARIABLE"
    if "await entity" in m:
        return "AST_AWAIT_ON_SYNC"
    if "duplicate code" in m:
        return "DUPLICATE_CODE"
    if "timeout" in m:
        return "SANDBOX_TIMEOUT"
    return "SANDBOX_EXCEPTION"


class MutationGatekeeper:
    """Async worker that validates and dispatches external agent mutations.

    Two concurrent loops:
    - _process_queue: BRPOP from Redis list, validate, write file, publish.
    - event bus subscriptions: update mutation status on MUTATION_APPLIED etc.
    """

    def __init__(
        self,
        redis: Redis,
        event_bus: EventBus,
        settings: Settings,
    ) -> None:
        self._redis = redis
        self._bus = event_bus
        self._settings = settings
        self._validator = CodeValidator(redis=redis)
        self._running = False
        # Set of mutation_ids we dispatched (for status update matching)
        self._pending: set[str] = set()

    async def run(self) -> None:
        """Start gatekeeper: BRPOP loop + event bus subscriptions."""
        self._running = True
        logger.info("mutation_gatekeeper_starting")

        # Subscribe to patcher outcome channels
        await self._bus.subscribe(Channels.MUTATION_APPLIED, self._handle_applied)
        await self._bus.subscribe(Channels.MUTATION_FAILED, self._handle_failed)
        await self._bus.subscribe(Channels.MUTATION_ROLLBACK, self._handle_rollback)

        logger.info("mutation_gatekeeper_subscribed")

        try:
            await self._process_queue()
        except Exception as exc:
            logger.error("mutation_gatekeeper_fatal", error=str(exc))
            raise

    def stop(self) -> None:
        """Signal the gatekeeper to stop."""
        self._running = False

    # ─── Queue processing ────────────────────────────────────────────────────

    async def _process_queue(self) -> None:
        """Blocking pop loop — waits for mutations in agent:mutation:queue."""
        while self._running:
            try:
                # BRPOP with 2s timeout so we can check _running
                result = await self._redis.brpop("agent:mutation:queue", timeout=2)
                if result is None:
                    continue  # Timeout, loop again

                _, mutation_id_raw = result
                mutation_id = (
                    mutation_id_raw.decode()
                    if isinstance(mutation_id_raw, bytes)
                    else mutation_id_raw
                )
                await self._handle_mutation(mutation_id)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("gatekeeper_queue_error", error=str(exc))
                await asyncio.sleep(1)

    async def _handle_mutation(self, mutation_id: str) -> None:
        """Process a single mutation from the queue."""
        logger.info("gatekeeper_processing", mutation_id=mutation_id)

        # Load metadata
        raw_meta = await self._redis.hgetall(f"evo:mutation:{mutation_id}")
        if not raw_meta:
            logger.warning("gatekeeper_no_metadata", mutation_id=mutation_id)
            return

        meta: dict[str, str] = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw_meta.items()
        }

        trait_name = meta.get("trait_name", "unknown")
        agent_id = meta.get("agent_id", "unknown")

        # Load source code
        code_raw = await self._redis.get(f"evo:mutation:{mutation_id}:source")
        if code_raw is None:
            logger.warning("gatekeeper_no_source", mutation_id=mutation_id)
            await self._reject(mutation_id, "SANDBOX_EXCEPTION", ["Source code not found"])
            return

        code = code_raw.decode() if isinstance(code_raw, bytes) else code_raw

        # Mark as validating
        await self._update_status(mutation_id, "validating")

        # Run validator
        validation_log: list[str] = []
        result = await self._validator.validate(code)

        if not result.is_valid:
            error_msg = result.error or "Unknown validation error"
            code_err = _error_code(error_msg)
            validation_log.append(f"Validation FAILED: {error_msg}")

            logger.info(
                "gatekeeper_validation_failed",
                mutation_id=mutation_id,
                error_code=code_err,
                error=error_msg,
            )
            await self._reject(mutation_id, code_err, validation_log)
            await self._decrement_active(agent_id)
            return

        validation_log.append("AST validation: OK")
        validation_log.append("Deduplication: OK")

        # Determine file version
        version = _next_version(self._settings.mutations_dir, trait_name)
        file_name = f"trait_{trait_name}_v{version}.py"
        file_path = os.path.join(self._settings.mutations_dir, file_name)

        # Write trait file
        try:
            os.makedirs(self._settings.mutations_dir, exist_ok=True)
            await asyncio.to_thread(_write_file, file_path, code)
        except Exception as exc:
            logger.error("gatekeeper_file_write_error", mutation_id=mutation_id, error=str(exc))
            await self._reject(mutation_id, "SANDBOX_EXCEPTION", [f"File write error: {exc}"])
            await self._decrement_active(agent_id)
            return

        validation_log.append(f"File written: {file_path}")

        # Update status to sandbox_ok and track as pending
        await self._update_status(mutation_id, "sandbox_ok", validation_log=validation_log)
        self._pending.add(mutation_id)

        # Publish MutationReady — RuntimePatcher will load and register
        event = MutationReady(
            mutation_id=mutation_id,
            plan_id="external",
            file_path=file_path,
            trait_name=trait_name,
            version=version,
            code_hash=result.code_hash or "",
            cycle_id=f"ext_{mutation_id}",
        )
        await self._bus.publish(Channels.MUTATION_READY, event)

        logger.info(
            "gatekeeper_mutation_dispatched",
            mutation_id=mutation_id,
            trait_name=trait_name,
            version=version,
            file_path=file_path,
        )

    # ─── Event bus handlers ──────────────────────────────────────────────────

    async def _handle_applied(self, data: dict[str, object]) -> None:
        """Update status to 'activated' when patcher confirms load."""
        mutation_id = str(data.get("mutation_id", ""))
        if mutation_id not in self._pending:
            return  # Not an external agent mutation

        self._pending.discard(mutation_id)
        await self._update_status(mutation_id, "activated")
        logger.info("gatekeeper_mutation_activated", mutation_id=mutation_id)

    async def _handle_failed(self, data: dict[str, object]) -> None:
        """Update status to 'rejected' when patcher fails to load."""
        mutation_id = str(data.get("mutation_id", ""))
        if mutation_id not in self._pending:
            return

        self._pending.discard(mutation_id)
        error = str(data.get("error", "Load failed"))
        code_err = _error_code(error)
        await self._reject(mutation_id, code_err, [f"Patcher error: {error}"])

        # Decrement active counter
        agent_id = await self._get_agent_id(mutation_id)
        if agent_id:
            await self._decrement_active(agent_id)

        logger.info("gatekeeper_mutation_load_failed", mutation_id=mutation_id, error=error)

    async def _handle_rollback(self, data: dict[str, object]) -> None:
        """Update status to 'rolled_back' on Watcher rollback."""
        mutation_id = str(data.get("mutation_id", ""))
        # May or may not be in _pending (already activated mutations can be rolled back)
        exists = await self._redis.hexists(f"evo:mutation:{mutation_id}", "mutation_id")
        if not exists:
            return

        await self._update_status(mutation_id, "rolled_back")

        # Decrement active counter
        agent_id = await self._get_agent_id(mutation_id)
        if agent_id:
            await self._decrement_active(agent_id)

        logger.info("gatekeeper_mutation_rolled_back", mutation_id=mutation_id)

    # ─── Redis helpers ───────────────────────────────────────────────────────

    async def _update_status(
        self,
        mutation_id: str,
        status: str,
        validation_log: Optional[list[str]] = None,
    ) -> None:
        mapping: dict[str, str] = {
            "status": status,
            "updated_at": str(time.time()),
        }
        if validation_log is not None:
            mapping["validation_log"] = json.dumps(validation_log)
        await self._redis.hset(f"evo:mutation:{mutation_id}", mapping=mapping)

    async def _reject(
        self,
        mutation_id: str,
        code: str,
        validation_log: list[str],
    ) -> None:
        await self._redis.hset(
            f"evo:mutation:{mutation_id}",
            mapping={
                "status": "rejected",
                "failure_reason_code": code,
                "validation_log": json.dumps(validation_log),
                "updated_at": str(time.time()),
            },
        )

    async def _decrement_active(self, agent_id: str) -> None:
        key = f"ratelimit:active:{agent_id}"
        new_val = await self._redis.decr(key)
        if new_val < 0:
            await self._redis.set(key, 0)

    async def _get_agent_id(self, mutation_id: str) -> Optional[str]:
        raw = await self._redis.hget(f"evo:mutation:{mutation_id}", "agent_id")
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw


def _write_file(file_path: str, code: str) -> None:
    """Write trait file synchronously (called via asyncio.to_thread)."""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)
