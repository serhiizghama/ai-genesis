"""Redis Pub/Sub channel constants.

All channel names follow the convention: ch:<domain>:<event_type>

Reference: tech_stack.md Section 3.5
"""


class Channels:
    """Redis Pub/Sub channel name constants.

    These channels are used for asynchronous communication between Core Engine,
    LLM Agents, Runtime Patcher, and the API.
    """

    # Core Engine → Watcher Agent
    # Payload: {tick, snapshot_key}
    TELEMETRY = "ch:telemetry"

    # Watcher Agent → Architect Agent
    # Payload: {trigger_id, problem_type, severity}
    EVOLUTION_TRIGGER = "ch:evolution:trigger"

    # Architect Agent → Coder Agent
    # Payload: {plan_id, action_type, description}
    EVOLUTION_PLAN = "ch:evolution:plan"

    # Coder Agent → Runtime Patcher
    # Payload: {mutation_id, file_path}
    MUTATION_READY = "ch:mutation:ready"

    # Runtime Patcher → Core, Watcher, Feed
    # Payload: {mutation_id, trait_name, version}
    MUTATION_APPLIED = "ch:mutation:applied"

    # Runtime Patcher → Watcher, Feed
    # Payload: {mutation_id, error, rollback_to}
    MUTATION_FAILED = "ch:mutation:failed"

    # API (user) → Core Engine
    # Payload: {param_name, old_value, new_value}
    WORLD_PARAMS_CHANGED = "ch:world:params_changed"

    # API (user) → Watcher Agent
    # Payload: {reason: "manual_trigger"}
    EVOLUTION_FORCE = "ch:evolution:force"

    # Watcher Agent → Runtime Patcher
    # Payload: {mutation_id, trait_name, reason, fitness_delta}
    MUTATION_ROLLBACK = "ch:mutation:rollback"

    # All Agents → WebSocket Handler
    # Payload: {agent, message, timestamp}
    FEED = "ch:feed"
