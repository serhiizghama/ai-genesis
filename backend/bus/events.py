"""Event types for Redis Pub/Sub communication between system components.

All events are dataclasses that can be serialized to/from JSON.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TelemetryEvent:
    """Published by Core Engine every N ticks with world state snapshot.

    Attributes:
        tick: Current simulation tick number
        snapshot_key: Redis key containing the snapshot data (e.g., ws:snapshot:90300)
        timestamp: Unix timestamp when event was created
    """

    tick: int
    snapshot_key: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class EvolutionTrigger:
    """Published by Watcher Agent when anomaly is detected.

    Attributes:
        trigger_id: Unique identifier for this trigger
        problem_type: Type of problem detected
        severity: Severity level of the problem
        affected_entities: List of entity IDs affected by the problem
        suggested_area: Area where solution might be needed
        snapshot_key: Redis key for the snapshot that triggered this
    """

    trigger_id: str
    problem_type: str  # 'starvation' | 'overpopulation' | 'low_diversity'
    severity: str  # 'low' | 'medium' | 'high' | 'critical'
    affected_entities: list[str] = field(default_factory=list)
    suggested_area: str = ""  # 'traits' | 'physics' | 'environment'
    snapshot_key: str = ""


@dataclass
class EvolutionPlan:
    """Published by Architect Agent with evolution plan.

    Attributes:
        plan_id: Unique identifier for this plan
        trigger_id: ID of the trigger that caused this plan
        action_type: Type of action to take
        description: Natural language description of what to do
        target_class: Optional target class name to modify
        target_method: Optional target method name to modify
    """

    plan_id: str
    trigger_id: str
    action_type: str  # 'new_trait' | 'modify_trait' | 'adjust_params'
    description: str
    target_class: Optional[str] = None  # 'EntityLogic', 'WorldPhysics', etc.
    target_method: Optional[str] = None


@dataclass
class MutationReady:
    """Published by Coder Agent when code is generated and validated.

    Attributes:
        mutation_id: Unique identifier for this mutation
        plan_id: ID of the plan that caused this mutation
        file_path: Path to the generated Python file
        trait_name: Name of the trait
        version: Version number of the trait
        code_hash: SHA-256 hash of the source code
    """

    mutation_id: str
    plan_id: str
    file_path: str  # 'mutations/trait_heat_shield_v3.py'
    trait_name: str
    version: int
    code_hash: str


@dataclass
class MutationApplied:
    """Published by Runtime Patcher when mutation is successfully loaded.

    Attributes:
        mutation_id: ID of the applied mutation
        trait_name: Name of the trait that was applied
        version: Version number of the trait
        registry_version: New version of the DynamicRegistry
    """

    mutation_id: str
    trait_name: str
    version: int
    registry_version: int


@dataclass
class MutationFailed:
    """Published by Runtime Patcher when mutation fails to load.

    Attributes:
        mutation_id: ID of the failed mutation
        error: Error message
        stage: Stage where the failure occurred
        rollback_to: Optional path to previous version to rollback to
    """

    mutation_id: str
    error: str
    stage: str  # 'validation' | 'import' | 'execution'
    rollback_to: Optional[str] = None  # trait_name_v{N-1} or None


@dataclass
class FeedMessage:
    """Published by any agent for UI display in Evolution Feed.

    Attributes:
        agent: Name of the agent publishing the message
        action: Action type for categorization
        message: Human-readable message for display
        metadata: Additional metadata for the message
        timestamp: Unix timestamp when message was created
    """

    agent: str  # 'watcher' | 'architect' | 'coder' | 'patcher'
    action: str
    message: str
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
