# AI-Genesis — Task List

Атомарные задачи для пошаговой реализации проекта.
Каждая задача рассчитана на **15-30 минут** кодинга.
Задачи сгруппированы по фазам из `development_roadmap.md`.

**Обозначения:**
- `[x]` — выполнено
- `[ ]` — ожидает выполнения
- `Depends:` — зависимости (нельзя начать, пока не выполнены)
- `Verify:` — как проверить, что задача сделана
- `File:` — файл(ы), которые создаются или изменяются

---

## Phase 0: Environment & Infrastructure (10 tasks, ~3.5 hours)

Setup Docker, Redis, Ollama, project skeleton — ничего из бизнес-логики.

### 0.1 Project Scaffold

- [x] **T-001** Create directory structure and empty `__init__.py` files
  - File: all directories from `tech_stack.md` Section 2
  - Verify: `find backend -name __init__.py | wc -l` returns 6 (core, agents, sandbox, bus, api, backend)
  - Depends: —

- [x] **T-002** Create `backend/config.py` with Pydantic Settings
  - File: `backend/config.py`
  - Content: `Settings` class from `tech_stack.md` Section 8 (all env vars with defaults)
  - Verify: `python -c "from backend.config import Settings; s = Settings(); print(s.tick_rate_ms)"` prints `16`
  - Depends: T-001

- [x] **T-003** Create `backend/requirements.txt` with pinned dependencies
  - File: `backend/requirements.txt`
  - Content: fastapi, uvicorn, redis, httpx, pydantic, pydantic-settings, structlog, watchdog, pytest, pytest-asyncio, mypy
  - Verify: `pip install -r backend/requirements.txt` succeeds
  - Depends: T-001

- [x] **T-004** Create `.env.example` and `.gitignore`
  - File: `.env.example`, `.gitignore`
  - `.gitignore`: mutations/*.py (except __init__.py), .env, __pycache__, .mypy_cache, node_modules, dist
  - Verify: files exist, `git status` doesn't show .env
  - Depends: T-001

### 0.2 Docker & Ollama

- [x] **T-005** Create `Dockerfile.core` for Python backend
  - File: `Dockerfile.core`
  - Content: python:3.11-slim, WORKDIR /app, copy requirements, pip install, copy backend/, CMD uvicorn
  - Verify: `docker build -f Dockerfile.core -t genesis-core .` succeeds
  - Depends: T-003

- [x] **T-006** Create `docker-compose.yml` with 3 services: core, redis, ollama
  - File: `docker-compose.yml`
  - Services: core (port 8000), redis:7-alpine (port 6379), ollama/ollama (port 11434)
  - Volumes: `./mutations:/app/mutations`, `redis_data`, `ollama_models`
  - Resource limits per `tech_stack.md` Section 1.1
  - Verify: `docker compose config` validates without errors
  - Depends: T-005

- [x] **T-007** Add Ollama model pull script / healthcheck with startup wait
  - File: `scripts/setup_ollama.sh`, `docker-compose.yml` (extend healthcheck)
  - Content:
    - Script: `ollama pull llama3:8b` (WARNING: 4-5GB download, may take 10-20 min on slow internet)
    - Healthcheck: `curl -f http://localhost:11434/api/tags | grep llama3` (checks model is loaded, not just server running)
    - docker-compose: add `healthcheck` to ollama service with interval 10s, timeout 5s, retries 30 (allow 5 min for model download)
  - **CRITICAL:** Core service should have `depends_on: ollama: condition: service_healthy` to prevent startup crashes while Ollama is downloading model
  - Verify: script runs, `curl http://localhost:11434/api/tags` returns JSON with llama3, core waits for ollama to be healthy before starting
  - Depends: T-006

- [x] **T-008** Verify full Docker stack starts and services communicate
  - Action: `docker compose up -d`, verify redis-cli ping, curl ollama, curl core
  - Verify: all 3 containers healthy, `docker compose ps` shows all "Up"
  - Depends: T-006, T-007

### 0.3 Redis Connection

- [x] **T-009** Create Redis connection helper with async client
  - File: `backend/bus/__init__.py` (re-exports), internal helper in bus module
  - Content: `async def get_redis() -> Redis` factory, using `redis.asyncio.Redis.from_url(settings.redis_url)`
  - Verify: `pytest tests/bus/test_redis_connection.py` — connects, SET/GET works
  - Depends: T-002, T-003

- [x] **T-010** Create initial `mutations/` directory with `__init__.py` and `.gitkeep`
  - File: `mutations/__init__.py`, `mutations/.gitkeep`
  - Verify: directory exists, is importable as Python package
  - Depends: T-001

---

## Phase 1: "Dead World" — Core Engine (12 tasks, ~4.5 hours)

Ядро симуляции: entity model, world loop, physics — без AI, без фронтенда.

### 1.1 Data Models

- [x] **T-011** Create `BaseTrait` abstract class and `TraitExecutor`
  - File: `backend/core/traits.py`
  - Content: `class BaseTrait(Protocol)` with `async def execute(self, entity) -> None`, `TraitExecutor` with timeout wrapper (5ms hard limit, 2ms soft target), tick time budgeting (14ms total for all entities)
  - Verify: mypy passes, `TraitExecutor.execute_traits()` catches timeout, skips remaining entities if tick budget exceeded
  - Depends: T-001

- [x] **T-012** Create `BaseEntity` dataclass with fields and `update()` method
  - File: `backend/core/entity.py`
  - Fields: id, x, y, energy, max_energy, age, generation, dna_hash, traits, state, parent_id, born_at_tick, color, radius, metabolism_rate, deactivated_traits
  - Methods: `update()` calls TraitExecutor, `move(dx, dy)`, `consume_resource(r)`
  - Verify: `Entity` can be instantiated, `update()` iterates traits
  - Depends: T-011

- [x] **T-013** Create `DynamicRegistry` — in-memory Trait catalog with race condition protection
  - File: `backend/core/dynamic_registry.py`
  - Methods: `register(name, cls)`, `unregister(name)`, `get_all_traits()`, `get_trait(name)`, `get_snapshot() -> dict` (returns immutable copy for spawn), `unique_trait_count()`, `most_common_trait()`
  - Implementation: Use atomic dict replacement (create new dict, assign) instead of mutation. `get_snapshot()` returns `self._traits.copy()` to prevent race conditions during hot-reload.
  - Verify: register/get round-trip works, `get_snapshot()` returns independent copy, thread-safe via dict replacement
  - Depends: T-011

### 1.2 Entity Manager

- [x] **T-014** Create `EntityManager` — CRUD, spawn, remove
  - File: `backend/core/entity_manager.py`
  - Methods: `spawn(parent)`, `remove(entity)`, `alive()`, `count()`, `get(id)`
  - Internal: `dict[str, Entity]` for O(1) lookups
  - Verify: spawn 10 entities, remove 3, count() == 7
  - Depends: T-012

- [x] **T-015** Add spatial hash grid to `EntityManager` for collision detection
  - File: `backend/core/entity_manager.py` (extend)
  - Methods: `detect_collisions() -> list[tuple[Entity, Entity]]`, `nearby_entities(x, y, radius) -> list[Entity]`
  - Internal: grid cells of 50x50px, rebuild each tick
  - Verify: 2 entities at (10,10) and (15,15) collide; entity at (500,500) doesn't
  - Depends: T-014

### 1.3 World Physics & Environment

- [ ] **T-016** Create `WorldPhysics` — gravity, friction, collision resolution
  - File: `backend/core/world_physics.py`
  - Functions: `apply_friction(entity, friction)`, `resolve_collision(a, b)`, `apply_bounds(entity, width, height)`
  - Verify: entity at x=2001 wraps or bounces, friction reduces velocity
  - Depends: T-012

- [ ] **T-017** Create `Environment` — resource map, spawn, weather
  - File: `backend/core/environment.py`
  - Class: `Resource(x, y, amount)`, `Environment` with `respawn_resources(rate)`, `resource_density()`, `nearby_resources(x, y, radius)`
  - Verify: respawn adds resources, density calculated correctly
  - Depends: T-002

### 1.4 World Loop

- [ ] **T-018** Create `CoreEngine` with async tick loop (skeleton)
  - File: `backend/core/engine.py`
  - Content: `async def run()` — infinite loop with `asyncio.sleep(tick_rate)`, tick counter, calls entity updates
  - Verify: loop runs 60 ticks in 1 second (within 5% tolerance)
  - Depends: T-014, T-016, T-017

- [ ] **T-019** Add lifecycle logic to tick loop: death, respawn, energy drain
  - File: `backend/core/engine.py` (extend)
  - Content: check energy <= 0 → death, age > max_age → death, auto-respawn if count < MIN_POPULATION
  - **CRITICAL:** Use `registry.get_snapshot()` when assigning traits to new entities (in spawn function) to avoid race conditions during hot-reload when Patcher updates registry mid-spawn.
  - Verify: spawn 5 entities with energy=1, after 2 ticks they die, new ones respawn, spawning during registry update doesn't cause inconsistent trait assignment
  - Depends: T-018, T-013

- [ ] **T-020** Add `DeathRecord` logging and in-memory counters (birth_counter, death_counter)
  - File: `backend/core/engine.py` (extend)
  - Content: `DeathRecord` dataclass, counters with `flush()` method for snapshot
  - Verify: kill 3 entities, `death_counter.flush()` returns 3 then 0
  - Depends: T-019

- [ ] **T-021** Create `backend/main.py` entry point — launch engine standalone
  - File: `backend/main.py`
  - Content: `asyncio.run(main())`, creates Settings, Redis stub, EntityManager, Engine, starts loop
  - Verify: `python -m backend.main` starts, prints tick numbers, Ctrl+C stops gracefully
  - Depends: T-018, T-002

- [ ] **T-022** Write unit tests for Phase 1 (entity, manager, physics, engine)
  - File: `tests/core/test_entity.py`, `tests/core/test_entity_manager.py`, `tests/core/test_engine.py`
  - Verify: `pytest tests/core/ -v` — all green, mypy passes
  - Depends: T-021

---

## Phase 2: "Window to the World" — API & WebSocket (10 tasks, ~3.5 hours)

FastAPI, REST endpoints, WebSocket broadcast — Molbot'ы видны в браузере.

### 2.1 FastAPI Setup

- [ ] **T-023** Create FastAPI app factory with lifespan
  - File: `backend/api/app.py`
  - Content: `create_app()`, lifespan creates Redis connection, starts engine as background task
  - Verify: `uvicorn backend.api.app:create_app --factory` starts, `GET /docs` returns Swagger
  - Depends: T-021, T-009

- [ ] **T-024** Create `GET /api/world/state` endpoint
  - File: `backend/api/routes_world.py`
  - Response: `{tick, entity_count, avg_energy, world_params}`
  - Verify: `curl localhost:8000/api/world/state` returns JSON with live tick
  - Depends: T-023

- [ ] **T-025** Create `POST /api/world/params` endpoint
  - File: `backend/api/routes_world.py` (extend)
  - Body: `{param: string, value: number}`, updates world_params in-memory + Redis
  - Verify: POST temperature=35 → GET state shows temperature=35
  - Depends: T-024

- [ ] **T-026** Create `GET /api/stats` endpoint (uptime, entity_count, tick)
  - File: `backend/api/routes_world.py` (extend)
  - Verify: returns `{uptime_seconds, tick, entity_count, mutations_applied}`
  - Depends: T-024

### 2.2 WebSocket Stream

- [ ] **T-027** Create WebSocket handler `/ws/world-stream`
  - File: `backend/api/ws_handler.py`
  - Content: accept connection, add to `ConnectionManager`, handle disconnect
  - Verify: `wscat -c ws://localhost:8000/ws/world-stream` connects without error
  - Depends: T-023

- [ ] **T-028** Implement `build_world_frame()` — serialize entity state to Binary Array Protocol
  - File: `backend/api/ws_handler.py` (extend)
  - Content: Use `struct.pack()` to create binary frame: `[tick: u32, entity_count: u16, resource_count: u16, [x: f32, y: f32, energy: f32, type: u8, color: u24] * entity_count, ...]`
  - For <200 entities: fallback to JSON mode for debugging: `{tick, entities: [{id, x, y, energy, ...}]}`
  - Verify: Binary mode returns `bytes`, JSON mode returns dict, both contain entity data
  - Depends: T-027, T-014

- [ ] **T-029** Wire WebSocket broadcast into engine tick loop (every 2nd tick)
  - File: `backend/core/engine.py` (extend), `backend/api/ws_handler.py`
  - Content: engine calls `ws_manager.broadcast(frame)` every 2nd tick
  - Verify: connect via wscat, receive ~30 frames/sec with entity positions
  - Depends: T-028

### 2.3 Minimal Frontend

- [ ] **T-030** Scaffold React + Vite + TypeScript project in `frontend/`
  - File: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/src/App.tsx`
  - Config: strict TS, proxy `/api` and `/ws` to localhost:8000
  - Verify: `cd frontend && npm install && npm run dev` opens blank page at :5173
  - Depends: —

- [ ] **T-031** Create `useWorldStream` hook — WebSocket connection + binary parsing
  - File: `frontend/src/hooks/useWorldStream.ts`
  - Content: connect to `/ws/world-stream`, detect binary vs JSON mode (check `event.data instanceof ArrayBuffer`), parse binary using DataView (read u32, u16, f32 in sequence), fallback to JSON.parse for <200 entities, store in state, handle reconnect
  - Verify: hook returns `{entities, tick, connected}`, correctly parses both binary and JSON frames
  - Depends: T-030, T-029

- [ ] **T-032** Create debug canvas — render entities as colored circles (no PixiJS yet)
  - File: `frontend/src/components/DebugCanvas.tsx`
  - Content: HTML Canvas 2D, draw each entity as circle at (x,y) with radius and color
  - Verify: open browser, see dots moving on screen in real-time
  - Depends: T-031

---

## Phase 3: "The Observer" — Event Bus & Watcher (10 tasks, ~3.5 hours)

Redis Pub/Sub event bus, telemetry snapshots, Watcher Agent anomaly detection.

### 3.1 Event Bus

- [ ] **T-033** Create event dataclasses in `bus/events.py`
  - File: `backend/bus/events.py`
  - Content: all event types from `tech_stack.md` Section 5.2 (TelemetryEvent, EvolutionTrigger, EvolutionPlan, MutationReady, MutationApplied, MutationFailed, FeedMessage)
  - Verify: mypy passes, all fields typed, no `Any`
  - Depends: T-001

- [ ] **T-034** Create channel constants in `bus/channels.py`
  - File: `backend/bus/channels.py`
  - Content: `class Channels` with all channel names as class-level string constants
  - Verify: `Channels.TELEMETRY == "ch:telemetry"`
  - Depends: T-001

- [ ] **T-035** Implement `EventBus` class with publish/subscribe/listen
  - File: `backend/bus/event_bus.py`
  - Content: class from `tech_stack.md` Section 5.3 — Redis Pub/Sub wrapper
  - Verify: test pub/sub round-trip in pytest (publish event → handler receives it)
  - Depends: T-009, T-033, T-034

### 3.2 Telemetry Pipeline

- [ ] **T-036** Implement `WorldSnapshot` dataclass and `collect_snapshot()` function
  - File: `backend/core/engine.py` (extend)
  - Content: `WorldSnapshot` with all fields from `tech_stack.md` Section 3.4, pure function to aggregate from in-memory state
  - Verify: snapshot has correct entity_count, avg_energy, death breakdown
  - Depends: T-020, T-033

- [ ] **T-037** Wire snapshot collection into tick loop + Redis write + Pub/Sub publish
  - File: `backend/core/engine.py` (extend)
  - Content: every 300 ticks → pipeline HSET + EXPIRE + publish TelemetryEvent
  - Verify: `redis-cli HGETALL ws:snapshot:300` returns snapshot data after 300 ticks
  - Depends: T-036, T-035

### 3.3 Watcher Agent

- [ ] **T-038** Create `detect_anomaly()` pure function — 5 rules
  - File: `backend/agents/watcher.py`
  - Content: implement all 5 anomaly detection rules from `logic_flow.md` Section 2.3 (mass extinction, overpopulation, energy crisis, low diversity, stagnation)
  - Input: current `WorldSnapshot`, history `list[WorldSnapshot]`, thresholds from Settings
  - Output: `list[Anomaly]` or empty
  - Verify: unit tests — feed snapshot with 50% death rate → returns `starvation` anomaly
  - Depends: T-036

- [ ] **T-039** Create `WatcherAgent` class — subscribe to telemetry, run analysis loop with circuit breaker
  - File: `backend/agents/watcher.py` (extend)
  - Content: subscribe `ch:telemetry`, load snapshot from Redis, call `detect_anomaly()`, publish `EvolutionTrigger` if anomaly found, cooldown check
  - **Circuit Breaker:** If >5 triggers created in 60s window → activate `watcher:circuit_breaker` (TTL 300s), pause Watcher for 5 minutes to prevent Redis key bloat and Architect overload
  - Redis keys: `watcher:trigger_counter` (TTL 60s), `watcher:circuit_breaker` (TTL 300s)
  - Verify: manually write bad snapshot to Redis → Watcher publishes trigger, spam 6 triggers in 30s → circuit breaker activates, Watcher pauses
  - Depends: T-038, T-035

- [ ] **T-040** Add Evolution Feed messages from Watcher to Redis Stream
  - File: `backend/agents/watcher.py` (extend)
  - Content: on anomaly → publish `FeedMessage` to `ch:feed`, `XADD feed:log`
  - Verify: `redis-cli XRANGE feed:log - +` shows watcher messages
  - Depends: T-039

- [ ] **T-041** Wire Watcher into `main.py` as coroutine in `asyncio.gather()`
  - File: `backend/main.py` (extend)
  - Verify: start server, wait 30 seconds, see watcher log messages in stdout
  - Depends: T-039, T-037

- [ ] **T-042** Write unit tests for Watcher anomaly detection
  - File: `tests/agents/test_watcher.py`
  - Cases: no anomaly (stable world), starvation, overpopulation, energy crisis, stagnation, cooldown prevents duplicate triggers
  - Verify: `pytest tests/agents/test_watcher.py -v` — all green
  - Depends: T-039

---

## Phase 4: "Runtime Magic" — Sandbox & Hot-Reload (10 tasks, ~3.5 hours)

Code validation, importlib loading, DynamicRegistry update — без LLM (ручные мутации).

### 4.1 Validator

- [ ] **T-043** Implement `CodeValidator` with AST parsing and syntax check
  - File: `backend/sandbox/validator.py`
  - Content: `validate(source_code) -> ValidationResult`, Step 1: `ast.parse()`
  - Verify: valid code → is_valid=True, `def foo(` (broken syntax) → is_valid=False
  - Depends: T-001

- [ ] **T-044** Add import whitelist and banned calls/attributes checks to validator
  - File: `backend/sandbox/validator.py` (extend)
  - Content: AST walk — check Import/ImportFrom against whitelist, Call against banned, Attribute against banned
  - Verify: `import os` → rejected, `eval("x")` → rejected, `import math` → ok
  - Depends: T-043

- [ ] **T-045** Add contract check — Trait subclass with `async execute(self, entity)`
  - File: `backend/sandbox/validator.py` (extend)
  - Content: find ClassDef inheriting Trait, verify AsyncFunctionDef `execute` with 2+ args
  - Verify: class without Trait parent → rejected, missing execute → rejected, correct class → returns trait_class_name
  - Depends: T-044

- [ ] **T-046** Add SHA-256 deduplication check
  - File: `backend/sandbox/validator.py` (extend)
  - Content: hash source code, check against Redis set `evo:mutation:hashes`
  - Verify: validate same code twice → second time returns "duplicate"
  - Depends: T-045, T-009

### 4.2 Runtime Patcher

- [ ] **T-047** Implement `RuntimePatcher` — importlib load + register
  - File: `backend/sandbox/patcher.py`
  - Content: on `ch:mutation:ready` → re-validate → `importlib.util.spec_from_file_location` → `exec_module` → extract class → register in DynamicRegistry + Redis
  - Verify: place valid .py file in mutations/ → publish event → class appears in registry
  - Depends: T-045, T-013, T-035

- [ ] **T-048** Implement rollback logic — fallback to previous Trait version
  - File: `backend/sandbox/rollback.py`
  - Content: `get_previous_version(trait_name, version)`, on patcher failure → reload previous version, update registry
  - Verify: v2 fails to load → v1 is restored in registry
  - Depends: T-047

- [ ] **T-049** Wire Patcher into `main.py`, test manual mutation end-to-end
  - File: `backend/main.py` (extend)
  - Test: write a valid Trait file to `mutations/trait_test_v1.py` by hand → publish `MutationReady` → observe DynamicRegistry update → newborn Molbot gets the Trait
  - Verify: entity spawns with new Trait, trait's `execute()` runs each tick
  - Depends: T-047, T-041

- [ ] **T-050** Write adversarial tests for validator
  - File: `tests/sandbox/test_validator.py`
  - Cases: `os.system`, `subprocess.Popen`, `eval`, `__import__`, infinite loop (while True), missing execute, wrong signature, `__globals__` access, `open()`, duplicate code
  - Verify: `pytest tests/sandbox/ -v` — all adversarial codes rejected
  - Depends: T-046

- [ ] **T-051** Add `POST /api/evolution/trigger` (manual trigger) endpoint
  - File: `backend/api/routes_evolution.py`
  - Content: publish `EvolutionForce` event to `ch:evolution:force`, Watcher picks it up
  - Verify: `curl -X POST localhost:8000/api/evolution/trigger` → watcher logs "manual trigger"
  - Depends: T-039, T-023

- [ ] **T-052** Add `GET /api/mutations` and `GET /api/mutations/{id}/source` endpoints
  - File: `backend/api/routes_evolution.py` (extend)
  - Content: read from Redis `evo:mutation:*` keys, return list and source code
  - Verify: after manual mutation, GET /api/mutations returns it with status "applied"
  - Depends: T-051, T-047

---

## Phase 5: "Genesis" — LLM Integration (10 tasks, ~4 hours)

Connect Architect and Coder agents to Ollama. Full autonomous evolution cycle.

### 5.1 Ollama Client

- [ ] **T-053** Create `OllamaClient` — async HTTP wrapper for Ollama API
  - File: `backend/agents/llm_client.py`
  - Content: `async def generate(system_prompt, user_prompt, model, timeout) -> str`, uses httpx.AsyncClient, handles timeout/connection errors gracefully
  - Verify: call with simple prompt → returns text, call with wrong URL → returns None + logs error
  - Depends: T-003, T-007

- [ ] **T-054** Add `extract_json()` and `extract_code_block()` parser utilities
  - File: `backend/agents/llm_client.py` (extend)
  - Content: regex-based extraction of JSON from LLM prose, Python code from markdown fences
  - Verify: `extract_json('Some text {"key": "val"} more text')` → `{"key": "val"}`
  - Depends: T-053

### 5.2 Architect Agent

- [ ] **T-055** Create `ArchitectAgent` — subscribe to trigger, build context, call LLM
  - File: `backend/agents/architect.py`
  - Content: on `ch:evolution:trigger` → load WorldReport + Trait catalog from Redis → build system+user prompt (from `logic_flow.md` Section 3.3) → call Ollama → parse JSON → create EvolutionPlan
  - Verify: mock Ollama response → Architect publishes EvolutionPlan to `ch:evolution:plan`
  - Depends: T-053, T-054, T-035

- [ ] **T-056** Add graceful degradation — Architect handles LLM timeout/errors
  - File: `backend/agents/architect.py` (extend)
  - Content: on timeout → log + FeedMessage + return, on unparseable response → log + return
  - Verify: set Ollama URL to invalid → Architect logs error, Core keeps running
  - Depends: T-055

### 5.3 Coder Agent

- [ ] **T-057** Create `CoderAgent` — subscribe to plan, generate code, pre-validate
  - File: `backend/agents/coder.py`
  - Content: on `ch:evolution:plan` → build code-gen prompt (from `logic_flow.md` Section 3.4) → call Ollama → extract code → validate with CodeValidator → save to `mutations/` → publish MutationReady
  - Verify: mock Ollama returns valid Trait code → file appears in mutations/ → MutationReady published
  - Depends: T-053, T-054, T-043, T-035

- [ ] **T-058** Add retry-on-validation-failure logic to Coder
  - File: `backend/agents/coder.py` (extend)
  - Content: if first code fails validation → re-prompt with error message → retry once → if still fails → log + give up
  - Verify: mock Ollama returns `import os` first, then valid code → second attempt succeeds
  - Depends: T-057

- [ ] **T-059** Add SHA-256 dedup check before saving mutation file
  - File: `backend/agents/coder.py` (extend)
  - Content: hash generated code, check `evo:mutation:hashes` in Redis, skip if duplicate
  - Verify: generate same code twice → second time skipped with "duplicate" log
  - Depends: T-057, T-046

### 5.4 Full Cycle Integration

- [ ] **T-060** Wire Architect + Coder + Patcher into `main.py` as coroutines
  - File: `backend/main.py` (extend)
  - Content: `asyncio.gather(engine, watcher, architect, coder, patcher, bus.listen, uvicorn)`
  - Verify: start server with Ollama running → observe full cycle in logs: telemetry → trigger → plan → code → load
  - Depends: T-055, T-057, T-049

- [ ] **T-061** Create `EvolutionCycle` orchestration — track cycle state in Redis
  - File: `backend/agents/base_agent.py` (or new file)
  - Content: create `evolution_cycles` entry on trigger, update on plan/code/apply/fail
  - `evo:cycle:current` key to prevent overlapping cycles
  - Verify: `redis-cli HGETALL evo:cycle:current` shows running cycle, only 1 at a time
  - Depends: T-060

- [ ] **T-062** End-to-end test: let system run 10 minutes with Ollama
  - Action: `docker compose up`, wait 10 minutes, inspect logs and mutations/
  - Verify: at least 1 mutation file in mutations/, at least 1 new Trait in registry, no Core crashes, entity_count stable between MIN and MAX
  - Depends: T-061

---

## Phase 6: "The Window" — Frontend (14 tasks, ~5 hours)

React + PixiJS UI: World Canvas, Evolution Feed, Controls, Entity Inspector.

### 6.1 PixiJS Setup

- [ ] **T-063** Install PixiJS and @pixi/react, configure in Vite
  - File: `frontend/package.json`, `frontend/src/canvas/PixiApp.tsx`
  - Content: `npm install pixi.js @pixi/react zustand`, basic Stage component rendering empty canvas
  - Verify: blank PixiJS canvas renders at full width/height
  - Depends: T-030

- [ ] **T-064** Create `MolbotSprite` component — circle + ears shape
  - File: `frontend/src/canvas/MolbotSprite.tsx`
  - Content: PixiJS Graphics — draw circle (body) + 2 small circles (ears), color from props, radius from energy
  - Verify: single Molbot renders with correct color and ears visible
  - Depends: T-063

- [ ] **T-065** Create `ResourceDot` component — small resource indicators
  - File: `frontend/src/canvas/ResourceDot.tsx`
  - Content: small green/yellow circles for resources on the map
  - Verify: resources visible on canvas
  - Depends: T-063

- [ ] **T-066** Render all entities from WebSocket stream on PixiJS canvas
  - File: `frontend/src/canvas/WorldCanvas.tsx`
  - Content: consume `useWorldStream` hook, render `MolbotSprite` for each entity, `ResourceDot` for resources
  - Verify: open browser — see Molbots moving in real-time on canvas
  - Depends: T-064, T-065, T-031

### 6.2 State Management

- [ ] **T-067** Create Zustand store for world state
  - File: `frontend/src/store/worldStore.ts`
  - Content: `{entities, resources, tick, connected, feedMessages, selectedEntityId, worldParams}`
  - Verify: store updates from WebSocket, components re-render
  - Depends: T-031

- [ ] **T-068** Create `useFeedStream` hook — subscribe to feed messages via WebSocket
  - File: `frontend/src/hooks/useFeedStream.ts`
  - Content: parse `feed_message` type from WS, append to `feedMessages` array (max 50)
  - Verify: when Watcher detects anomaly, message appears in store
  - Depends: T-067

### 6.3 UI Components

- [ ] **T-069** Create `EvolutionFeed` component — scrollable log of AI decisions
  - File: `frontend/src/components/EvolutionFeed.tsx`
  - Content: consume feedMessages from store, render as scrollable list with timestamp + agent badge + message
  - Verify: feed shows colored entries (watcher=blue, architect=purple, coder=green, patcher=orange)
  - Depends: T-068

- [ ] **T-070** Create `PopulationGraph` component — line chart of entity count
  - File: `frontend/src/components/PopulationGraph.tsx`
  - Content: track entity_count over last 60 data points, render as SVG line chart or simple canvas chart
  - Verify: graph updates in real-time, shows trend line
  - Depends: T-067

- [ ] **T-071** Create `WorldControls` panel — temperature, resources, speed sliders
  - File: `frontend/src/components/WorldControls.tsx`
  - Content: sliders for temperature, resource_spawn_rate, tick_rate. On change → send `set_param` via WebSocket or POST /api/world/params
  - Verify: move temperature slider → world_params update, entities react
  - Depends: T-025, T-067

- [ ] **T-072** Create `EntityInspector` panel — click on Molbot shows details
  - File: `frontend/src/components/EntityInspector.tsx`
  - Content: on click MolbotSprite → set selectedEntityId in store → panel shows: id, energy bar, age, traits list, DNA hash, parent_id
  - Verify: click Molbot → panel appears with correct data
  - Depends: T-066, T-067

- [ ] **T-073** Create "Force Evolution" button wired to `POST /api/evolution/trigger`
  - File: `frontend/src/components/WorldControls.tsx` (extend)
  - Content: button sends POST request, shows spinner while cycle runs
  - Verify: click button → see Watcher/Architect/Coder messages in Feed
  - Depends: T-051, T-069

### 6.4 Layout & Polish

- [ ] **T-074** Create main layout: Canvas (left 70%) + Sidebar (right 30%)
  - File: `frontend/src/App.tsx`
  - Content: CSS Grid/Flex layout. Left: WorldCanvas. Right: stacked panels — EvolutionFeed, PopulationGraph, WorldControls, EntityInspector
  - Verify: responsive layout, all panels visible without overlap
  - Depends: T-066, T-069, T-070, T-071, T-072

- [ ] **T-075** Add dark theme, header with "AI-Genesis" title and connection status indicator
  - File: `frontend/src/App.tsx` (extend), `frontend/src/index.css`
  - Content: dark background (#0a0a0f), green dot when WS connected, red when disconnected
  - Verify: looks clean, connection indicator reflects actual WebSocket state
  - Depends: T-074

- [ ] **T-076** Create `Dockerfile.web` and add `web` service to docker-compose
  - File: `Dockerfile.web`, `docker-compose.yml` (extend)
  - Content: node:20-alpine, npm install, npm run build, serve with nginx or dev mode
  - Verify: `docker compose up` starts all 4 services, frontend accessible at :5173
  - Depends: T-075, T-006

---

## Phase 7: Final Integration & QA (6 tasks, ~2 hours)

Full system test, logging polish, documentation.

- [ ] **T-077** Add structured logging (structlog) throughout backend
  - File: all backend files
  - Content: replace `print()` with `structlog.get_logger()`, JSON format, include tick/agent/event context
  - Verify: logs are valid JSON, greppable by agent name
  - Depends: T-060

- [ ] **T-078** Add WebSocket feed bridge — forward `ch:feed` events to all WS clients
  - File: `backend/api/ws_handler.py` (extend)
  - Content: subscribe to `ch:feed` in EventBus → broadcast as `feed_message` type to all WebSocket connections
  - Verify: AI agent decisions appear in browser EvolutionFeed component in real-time
  - Depends: T-035, T-029, T-069

- [ ] **T-079** Add health endpoint `GET /api/health` and Ollama healthcheck
  - File: `backend/api/routes_world.py` (extend)
  - Content: check Redis ping, Ollama /api/tags, return status per service
  - Verify: `curl localhost:8000/api/health` → `{redis: "ok", ollama: "ok", core: "running"}`
  - Depends: T-023

- [ ] **T-080** Full system 30-minute soak test
  - Action: `docker compose up`, let run 30 minutes, no human interaction
  - Verify: Core didn't crash (uptime > 99%), >=3 mutations applied, no memory leak (RSS stable), feed messages flowing to UI
  - Depends: T-076, T-078

- [ ] **T-081** Run `mypy --strict` on entire backend, fix all errors
  - Action: `mypy --strict backend/`
  - Verify: 0 errors
  - Depends: T-080

- [ ] **T-082** Write `README.md` with setup instructions
  - File: `README.md`
  - Content: project description, prerequisites (Docker, 16GB RAM), setup steps (`docker compose up`), architecture diagram link, screenshots
  - Verify: fresh clone → follow README → system starts and works
  - Depends: T-080

---

## Summary

| Phase | Tasks | Est. Time | Cumulative |
|-------|-------|-----------|------------|
| 0 — Environment | 10 | 3.5 h | 3.5 h |
| 1 — Core Engine | 12 | 4.5 h | 8 h |
| 2 — API & WebSocket | 10 | 3.5 h | 11.5 h |
| 3 — Event Bus & Watcher | 10 | 3.5 h | 15 h |
| 4 — Sandbox & Hot-Reload | 10 | 3.5 h | 18.5 h |
| 5 — LLM Integration | 10 | 4 h | 22.5 h |
| 6 — Frontend | 14 | 5 h | 27.5 h |
| 7 — Final Integration | 6 | 2 h | **29.5 h** |
| **Total** | **82** | **~30 h** | |

---

## Dependency Graph (Critical Path)

```
T-001 ──► T-002 ──► T-005 ──► T-006 ──► T-008
  │         │                     │
  │         ▼                     ▼
  │       T-009 ─────────────► T-023 ──► T-024 ──► T-029 ──► T-032
  │                              │
  ▼                              ▼
T-011 ──► T-012 ──► T-014 ──► T-018 ──► T-021 ──► T-037
  │                   │                     │         │
  ▼                   ▼                     ▼         ▼
T-013              T-015               T-033 ──► T-035 ──► T-039 ──► T-041
                                                    │
                                                    ▼
T-043 ──► T-044 ──► T-045 ──► T-047 ──► T-049 ──► T-060 ──► T-062
                                                    │
                                                    ▼
                                   T-053 ──► T-055 ──► T-057
                                                         │
                                                         ▼
                         T-063 ──► T-064 ──► T-066 ──► T-074 ──► T-076 ──► T-080
                                               │
                                               ▼
                                    T-067 ──► T-069 ──► T-078
```

**Critical path:** T-001 → T-012 → T-018 → T-021 → T-037 → T-039 → T-060 → T-062 → T-080

This path determines minimum calendar time. Frontend (Phase 6) can start in parallel
after T-030 (no backend dependency for scaffold).

---

*Document Version: 1.0*
*References: development_roadmap.md, tech_stack.md, logic_flow.md, PRD.md*
*Next Document: frontend_blueprint.md*
