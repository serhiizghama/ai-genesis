"""Shared Entity API documentation for LLM agent prompts.

This module is the single source of truth for what LLM-generated traits
can access. Both the validator (sandbox/validator.py) and agent prompts
(architect.py, coder.py) import from here to stay in sync.
"""

# Single source of truth: attributes and methods LLM-generated traits may access.
# validator.py imports this set — do NOT define allowed attrs there separately.
ALLOWED_ENTITY_ATTRS = {
    # Read-only fields
    "id", "x", "y", "energy", "max_energy",
    "age", "max_age", "metabolism_rate",
    "traits", "state", "entity_type",
    # Methods safe for trait use
    "move", "eat_nearby", "attack_nearby",
    "is_alive", "deactivate_trait", "activate_trait",
}

ENTITY_API_TEXT = """Entity attributes:
- id: str — unique identifier
- x, y: float — position in world coordinates
- energy: float — current energy (decrease only; gain via eat_nearby())
- max_energy: float — energy capacity
- age: int — age in simulation ticks
- max_age: int — lifespan limit (0 = immortal)
- metabolism_rate: float — energy consumed per tick
- traits: list — active trait objects
- state: str — "alive", "dead", or "reproducing"
- entity_type: str — "molbot" or "predator"

Entity methods:
- move(dx, dy) — move by delta; max 20px/tick
- eat_nearby(radius=30.0) -> bool — consume nearest food; ONLY way to gain energy
- attack_nearby(radius=30.0, damage=20.0) -> bool — attack nearest predator within radius
- is_alive() -> bool — True if state == "alive"
- deactivate_trait(trait_name: str) / activate_trait(trait_name: str) — manage trait state by name

Constraints:
- entity has NO .world attribute — cannot access global world or create entities
- Do NOT increase entity.energy directly — use eat_nearby() only
- Allowed imports: math, random, typing"""
