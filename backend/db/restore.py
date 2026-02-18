"""Restore simulation state from the latest PostgreSQL checkpoint.

Called during startup before the tick loop begins.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import asyncpg
import structlog

from backend.db.repository import get_active_mutations, get_latest_checkpoint

if TYPE_CHECKING:
    from backend.core.dynamic_registry import DynamicRegistry
    from backend.core.engine import CoreEngine

logger = structlog.get_logger()


async def restore_from_checkpoint(
    pool: asyncpg.Pool,
    engine: CoreEngine,
    registry: DynamicRegistry,
) -> bool:
    """Restore engine tick and entity population from the latest checkpoint.

    Steps:
    1. Load latest world_checkpoint + entity_snapshots from PG.
    2. If none exists, return False (fresh start).
    3. Restore tick counter.
    4. Spawn entities from snapshot data.
    5. Re-write active mutation source files and register traits.

    Args:
        pool: asyncpg connection pool.
        engine: The CoreEngine to restore tick into.
        registry: DynamicRegistry to register restored trait classes.

    Returns:
        True if restored from checkpoint, False if starting fresh.
    """
    checkpoint = await get_latest_checkpoint(pool)

    if checkpoint is None:
        logger.info("restore_no_checkpoint_found", action="fresh_start")
        return False

    tick = checkpoint["tick"]
    entities_data = checkpoint["entities"]

    # Restore tick counter so simulation continues from where it left off
    engine.tick_counter = tick
    engine.last_snapshot_tick = tick

    # Restore entity population
    spawned = 0
    for edata in entities_data:
        if edata["state"] != "alive":
            continue
        entity = engine.entity_manager.spawn(
            x=edata["x"],
            y=edata["y"],
            traits=[],
            generation=0,
            tick=tick,
            initial_energy=edata["energy"],
        )
        entity._environment = engine.environment
        spawned += 1

    logger.info(
        "restore_entities_spawned",
        tick=tick,
        entity_count=spawned,
        checkpoint_id=checkpoint["id"],
    )

    # Restore active mutations: write source files and register traits
    mutations = await get_active_mutations(pool)
    restored_mutations = 0

    for mut in mutations:
        trait_name = mut["trait_name"]
        version = mut["version"]
        source_code = mut["source_code"]
        filename = f"trait_{trait_name}_v{version}.py"
        mutations_dir = engine.settings.mutations_dir
        file_path = os.path.join(mutations_dir, filename)

        # Write source file if missing (so watchdog / patcher can find it)
        if not os.path.exists(file_path):
            try:
                os.makedirs(mutations_dir, exist_ok=True)
                with open(file_path, "w") as fh:
                    fh.write(source_code)
            except OSError as exc:
                logger.warning(
                    "restore_mutation_write_failed",
                    trait_name=trait_name,
                    error=str(exc),
                )
                continue

        # Dynamically load and register the trait class
        try:
            import importlib.util
            import sys

            module_name = f"mutation_restored_{trait_name}_v{version}"
            if module_name in sys.modules:
                del sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if not spec or not spec.loader:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            trait_cls = getattr(module, trait_name, None)
            if trait_cls is None:
                logger.warning(
                    "restore_trait_class_not_found",
                    trait_name=trait_name,
                    file_path=file_path,
                )
                continue

            registry.register(trait_name, trait_cls)

            # Restore source in registry for API access
            registry.register_source(trait_name, source_code)

            restored_mutations += 1
            logger.info("restore_mutation_registered", trait_name=trait_name, version=version)

        except Exception as exc:
            logger.warning(
                "restore_mutation_load_failed",
                trait_name=trait_name,
                error=str(exc),
            )

    logger.info(
        "restore_complete",
        tick=tick,
        entities=spawned,
        mutations=restored_mutations,
    )
    return True
