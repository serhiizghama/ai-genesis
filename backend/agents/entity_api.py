"""Shared Entity API documentation for LLM agent prompts."""

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
- move(dx, dy) — move by delta; max 50px/tick
- eat_nearby(radius=50.0) -> bool — consume nearest food; ONLY way to gain energy
- attack_nearby(radius=30.0, damage=20.0) -> bool — attack nearest predator within radius
- is_alive() -> bool — True if state == "alive"
- deactivate_trait(trait_name: str) / activate_trait(trait_name: str) — manage trait state by name

Constraints:
- entity has NO .world attribute — cannot access global world or create entities
- Do NOT increase entity.energy directly — use eat_nearby() only
- Allowed imports: math, random, typing"""
