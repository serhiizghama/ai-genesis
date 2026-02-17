# AI-Genesis — Architecture & Tech Stack

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose                               │
│                                                                     │
│  ┌──────────────────────────────────┐   ┌────────────────────────┐  │
│  │         core-container           │   │   ollama-container     │  │
│  │                                  │   │                        │  │
│  │  ┌───────────┐  ┌────────────┐   │   │  ┌──────────────────┐  │  │
│  │  │   Core    │  │  Agents    │   │   │  │  Ollama Server   │  │  │
│  │  │  Engine   │  │  Pipeline  │   │   │  │  (Llama 3 8B)    │  │  │
│  │  │          ◄├──┤►           │   │   │  │                  │  │  │
│  │  └─────┬─────┘  └──────┬─────┘   │   │  └────────▲─────────┘  │  │
│  │        │               │         │   │           │            │  │
│  │  ┌─────▼─────┐  ┌──────▼─────┐   │   └───────────┼────────────┘  │
│  │  │  FastAPI  │  │  Runtime   │   │               │               │
│  │  │  + WS     │  │  Patcher   │   │         HTTP :11434           │
│  │  └─────┬─────┘  └────────────┘   │               │               │
│  │        │                         │   ┌───────────┼────────────┐  │
│  └────────┼─────────────────────────┘   │   redis-container      │  │
│           │                             │                        │  │
│     WS :8000                            │  ┌──────────────────┐  │  │
│           │                             │  │   Redis 7        │  │  │
│  ┌────────▼─────────────────────────┐   │  │   State + PubSub │  │  │
│  │         web-container            │   │  └──────────────────┘  │  │
│  │  React 19 + Vite + PixiJS 8     │   │                        │  │
│  │  Port :3000 (Nginx)              │   └────────────────────────┘  │
│  └──────────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 Container Map

| Container | Image | Ports | CPU Limit | RAM Limit | Volumes |
|-----------|-------|-------|-----------|-----------|---------|
| `core` | python:3.11-slim | 8000 | 2 cores | 4 GB | `./mutations:/app/mutations` |
| `ollama` | ollama/ollama | 11434 | 4 cores | 16 GB | `ollama_models:/root/.ollama` |
| `redis` | redis:7-alpine | 6379 | 1 core | 1 GB | `redis_data:/data` |
| `frontend` | nginx:alpine (built from node:22) | 3000 | 1 core | 512 MB | — |

---

## 2. Directory Structure (Final)

```text
ai-genesis/
├── backend/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── engine.py              # WorldLoop — async tick loop
│   │   ├── entity.py              # BaseEntity, DNA, lifecycle
│   │   ├── entity_manager.py      # CRUD для сущностей, spatial index
│   │   ├── traits.py              # BaseTrait, TraitExecutor
│   │   ├── world_physics.py       # Физика: gravity, friction, collisions
│   │   ├── environment.py         # Карта, ресурсы, погода
│   │   └── dynamic_registry.py    # Реестр Trait-классов (hot-swap)
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py          # Абстрактный агент
│   │   ├── watcher.py             # Наблюдатель — сбор телеметрии
│   │   ├── architect.py           # Архитектор — план эволюции
│   │   ├── coder.py               # Кодер — генерация Python-кода
│   │   └── llm_client.py          # Обёртка над Ollama HTTP API
│   │
│   ├── sandbox/
│   │   ├── __init__.py
│   │   ├── validator.py           # AST-валидация + whitelist
│   │   ├── patcher.py             # Runtime Patcher (importlib)
│   │   └── rollback.py            # Версионирование и откат мутаций
│   │
│   ├── bus/
│   │   ├── __init__.py
│   │   ├── event_bus.py           # Async event bus (Redis Pub/Sub)
│   │   ├── events.py              # Типы событий (dataclasses)
│   │   └── channels.py            # Константы каналов Redis
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                 # FastAPI application factory
│   │   ├── routes_world.py        # REST: /api/world/*
│   │   ├── routes_evolution.py    # REST: /api/evolution/*
│   │   └── ws_handler.py          # WebSocket: /ws/world-stream
│   │
│   ├── config.py                  # Pydantic Settings (env-driven)
│   ├── main.py                    # Точка входа: запуск всех подсистем
│   └── requirements.txt
│
├── mutations/                     # LLM-генерируемый код (volume mount)
│   ├── __init__.py
│   └── .gitkeep
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   ├── canvas/                # PixiJS-рендеринг Molbot'ов
│   │   ├── hooks/
│   │   └── types/
│   ├── package.json
│   └── vite.config.ts
│
├── docker-compose.yml
├── Dockerfile.core
├── Dockerfile.web
└── docs/
```

---

## 3. Data Layer: Redis

Redis — основное хранилище для всего, что требует скорости: world state, event bus, метрики.

### 3.1 Key Schema

```text
Prefix Legend:
  ws:    — world state (состояние мира)
  ent:   — entity (отдельная сущность)
  meta:  — метаданные системы
  evo:   — эволюция
  feed:  — evolution feed для UI
```

| Key Pattern | Type | TTL | Описание |
|-------------|------|-----|----------|
| `ws:tick` | String (int) | — | Текущий номер тика |
| `ws:params` | Hash | — | Глобальные параметры мира |
| `ws:snapshot:{tick}` | Hash | 5 min | Snapshot телеметрии для Watcher |
| `ent:{entity_id}` | Hash | — | Состояние одной сущности |
| `ent:index` | Set | — | Множество всех живых `entity_id` |
| `ent:spatial:{cell_x}:{cell_y}` | Set | — | Spatial hash: entity_id в ячейке |
| `meta:registry:traits` | Hash | — | `{trait_name: module_path}` — текущий реестр |
| `meta:registry:version` | String (int) | — | Версия реестра (инкремент при reload) |
| `evo:trigger:{id}` | Hash | 10 min | EvolutionTrigger от Watcher |
| `evo:plan:{id}` | Hash | 10 min | EvolutionPlan от Architect |
| `evo:mutation:{id}` | Hash | — | Мета мутации: `status`, `file_path`, `hash` |
| `evo:cycle:current` | String | — | ID текущего цикла эволюции (или `null`) |
| `feed:log` | Stream | 1 hour | Evolution Feed для UI (Redis Stream) |

### 3.2 World State Hash (`ws:params`)

```text
HSET ws:params
  world_width        2000
  world_height       2000
  gravity            0.98
  friction           0.85
  resource_spawn_rate 0.05
  temperature         20.0
  max_entities        500
  min_population      20
  tick_rate_ms        16
```

### 3.3 Entity Hash (`ent:{id}`)

```text
HSET ent:mol_00a3f1
  x               450.23
  y               312.77
  energy          78.5
  max_energy      100.0
  age             1842
  generation      3
  dna_hash        "a3f1c9"
  traits          "thermal_vision_v2,energy_absorb_v1"
  state           "alive"
  parent_id       "mol_009b12"
  born_at_tick    50200
  color           "#FF8C42"
  radius          6.2
```

### 3.4 Snapshot Hash (`ws:snapshot:{tick}`)

```text
HSET ws:snapshot:90300
  tick                90300
  timestamp           "2026-02-16T14:32:01Z"
  entity_count        237
  avg_energy          54.2
  births_last_period  12
  deaths_last_period  8
  death_starvation    5
  death_age           2
  death_collision     1
  resource_density    0.032
  trait_diversity     7
  dominant_trait      "energy_absorb_v1"
  temperature         20.0
```

### 3.5 Redis Pub/Sub Channels

Для асинхронного взаимодействия между подсистемами.

| Channel | Publisher | Subscriber(s) | Payload |
|---------|-----------|---------------|---------|
| `ch:telemetry` | Core Engine | Watcher Agent | `{tick, snapshot_key}` |
| `ch:evolution:trigger` | Watcher | Architect Agent | `{trigger_id, problem_type, severity}` |
| `ch:evolution:plan` | Architect | Coder Agent | `{plan_id, action_type, description}` |
| `ch:mutation:ready` | Coder | Runtime Patcher | `{mutation_id, file_path}` |
| `ch:mutation:applied` | Patcher | Core, Watcher, Feed | `{mutation_id, trait_name, version}` |
| `ch:mutation:failed` | Patcher | Watcher, Feed | `{mutation_id, error, rollback_to}` |
| `ch:world:params_changed` | API (user) | Core Engine | `{param_name, old_value, new_value}` |
| `ch:evolution:force` | API (user) | Watcher | `{reason: "manual_trigger"}` |
| `ch:feed` | All Agents | WebSocket Handler | `{agent, message, timestamp}` |

### 3.6 Redis Stream (`feed:log`)

Evolution Feed хранится как Redis Stream для ordered, persistent лога.

```text
XADD feed:log *
  agent      "architect"
  action     "plan_created"
  message    "Популяция голодает. Добавляю Trait: EnergyScavenger — поиск ресурсов в радиусе 50px."
  plan_id    "evo_plan_042"
  timestamp  "2026-02-16T14:32:15Z"
```

UI подписывается через `XREAD BLOCK 0 STREAMS feed:log $`, WebSocket handler транслирует в браузер.

---

## 4. Async Event Bus: Core ↔ LLM Interaction

> **MVP Architecture Note:** Redis is the only persistence layer. PostgreSQL is deferred to v0.2.
> All historical data (evolution cycles, mutation metadata) lives in Redis with TTLs.
> World snapshots persist in Redis `ws:snapshot:{tick}` (5 min TTL) only.

### 4.1 Architecture

Core и LLM-агенты **никогда не общаются напрямую**. Вся коммуникация идёт через асинхронную шину событий на базе Redis Pub/Sub.

```
┌─────────────┐          ┌─────────────────────────────────┐
│  Core       │          │         Redis Pub/Sub            │
│  Engine     │──publish──►  ch:telemetry                   │
│  (tick loop)│          │                                  │
└─────────────┘          │  ch:evolution:trigger            │
                         │  ch:evolution:plan               │
┌─────────────┐          │  ch:mutation:ready               │
│  Watcher    │◄─subscribe─  ch:mutation:applied            │
│  Agent      │──publish──►  ch:mutation:failed             │
└─────────────┘          │  ch:world:params_changed         │
                         │  ch:evolution:force              │
┌─────────────┐          │  ch:feed                         │
│  Architect  │◄─subscribe─                                 │
│  Agent      │──publish──►                                 │
└─────────────┘          └─────────────────────────────────┘
                                       ▲  ▲
┌─────────────┐                        │  │
│  Coder      │◄──subscribe────────────┘  │
│  Agent      │──publish──────────────────┘
└─────────────┘

┌─────────────┐
│  Runtime    │◄──subscribe── ch:mutation:ready
│  Patcher    │──publish────► ch:mutation:applied / ch:mutation:failed
└─────────────┘
```

### 4.2 Event Types (dataclasses)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class EventType(str, Enum):
    TELEMETRY           = "telemetry"
    EVOLUTION_TRIGGER   = "evolution_trigger"
    EVOLUTION_PLAN      = "evolution_plan"
    MUTATION_READY      = "mutation_ready"
    MUTATION_APPLIED    = "mutation_applied"
    MUTATION_FAILED     = "mutation_failed"
    PARAMS_CHANGED      = "params_changed"
    EVOLUTION_FORCE     = "evolution_force"
    FEED_MESSAGE        = "feed_message"


@dataclass
class TelemetryEvent:
    tick: int
    snapshot_key: str                         # Redis key: ws:snapshot:{tick}
    timestamp: float = field(default_factory=time.time)


@dataclass
class EvolutionTrigger:
    trigger_id: str
    problem_type: str                         # 'starvation' | 'overpopulation' | 'low_diversity'
    severity: str                             # 'low' | 'medium' | 'high' | 'critical'
    affected_entities: list[str] = field(default_factory=list)
    suggested_area: str = ""                  # 'traits' | 'physics' | 'environment'
    snapshot_key: str = ""


@dataclass
class EvolutionPlan:
    plan_id: str
    trigger_id: str
    action_type: str                          # 'new_trait' | 'modify_trait' | 'adjust_params'
    description: str                          # Естественный язык: что делать
    target_class: Optional[str] = None        # 'EntityLogic', 'WorldPhysics', etc.
    target_method: Optional[str] = None


@dataclass
class MutationReady:
    mutation_id: str
    plan_id: str
    file_path: str                            # 'mutations/trait_heat_shield_v3.py'
    trait_name: str
    version: int
    code_hash: str


@dataclass
class MutationApplied:
    mutation_id: str
    trait_name: str
    version: int
    registry_version: int                     # Новая версия DynamicRegistry


@dataclass
class MutationFailed:
    mutation_id: str
    error: str
    stage: str                                # 'validation' | 'import' | 'execution'
    rollback_to: Optional[str] = None         # trait_name_v{N-1} или None


@dataclass
class FeedMessage:
    agent: str                                # 'watcher' | 'architect' | 'coder' | 'patcher'
    action: str
    message: str                              # Человекочитаемое сообщение
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
```

### 4.3 Event Bus Implementation

```python
import asyncio
import json
from dataclasses import asdict
from redis.asyncio import Redis

class EventBus:
    """Async event bus built on Redis Pub/Sub."""

    def __init__(self, redis: Redis):
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._handlers: dict[str, list[callable]] = {}

    async def publish(self, channel: str, event) -> None:
        payload = json.dumps(asdict(event), default=str)
        await self._redis.publish(channel, payload)

    async def subscribe(self, channel: str, handler: callable) -> None:
        if channel not in self._handlers:
            self._handlers[channel] = []
            await self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)

    async def listen(self) -> None:
        """Main loop: dispatch incoming messages to handlers."""
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()
            data = json.loads(message["data"])
            for handler in self._handlers.get(channel, []):
                asyncio.create_task(handler(data))
```

### 4.4 Full Evolution Cycle (Sequence)

```
Time ──────────────────────────────────────────────────────────►

Core Engine           Watcher            Architect           Coder             Patcher
    │                    │                   │                  │                  │
    │  [every 300 ticks] │                   │                  │                  │
    ├──PUBLISH───────────►                   │                  │                  │
    │  ch:telemetry      │                   │                  │                  │
    │  {tick, snapshot}   │                   │                  │                  │
    │                    │                   │                  │                  │
    │                    ├─ compare with ─┐   │                  │                  │
    │                    │  last 5 snaps  │   │                  │                  │
    │                    ◄────────────────┘   │                  │                  │
    │                    │                   │                  │                  │
    │                    │ anomaly detected!  │                  │                  │
    │                    │                   │                  │                  │
    │                    ├──PUBLISH──────────►                  │                  │
    │                    │  ch:evo:trigger   │                  │                  │
    │                    │  {starvation,hi}  │                  │                  │
    │                    │                   │                  │                  │
    │                    │                   ├─ LLM call ──┐    │                  │
    │                    │                   │ (Ollama)    │    │                  │
    │                    │                   │ ~3-8 sec    │    │                  │
    │                    │                   ◄─────────────┘    │                  │
    │                    │                   │                  │                  │
    │                    │                   ├──PUBLISH─────────►                  │
    │                    │                   │  ch:evo:plan     │                  │
    │                    │                   │  {new_trait,     │                  │
    │                    │                   │   EnergyScav..}  │                  │
    │                    │                   │                  │                  │
    │                    │                   │                  ├─ LLM call ──┐    │
    │                    │                   │                  │ (Ollama)    │    │
    │                    │                   │                  │ ~3-8 sec    │    │
    │                    │                   │                  ◄─────────────┘    │
    │                    │                   │                  │                  │
    │                    │                   │                  ├─ ast.parse() ─┐  │
    │                    │                   │                  │               │  │
    │                    │                   │                  ◄───────────────┘  │
    │                    │                   │                  │                  │
    │                    │                   │                  ├─ save .py ────┐  │
    │                    │                   │                  │  mutations/   │  │
    │                    │                   │                  ◄───────────────┘  │
    │                    │                   │                  │                  │
    │                    │                   │                  ├──PUBLISH─────────►
    │                    │                   │                  │  ch:mutation:     │
    │                    │                   │                  │  ready            │
    │                    │                   │                  │                  │
    │                    │                   │                  │                  ├─ validate
    │                    │                   │                  │                  ├─ importlib
    │                    │                   │                  │                  ├─ register
    │                    │                   │                  │                  │
    ◄────────────────────┼───────────────────┼──────────────────┼──PUBLISH─────────┤
    │                    │                   │                  │  ch:mutation:     │
    │  DynamicRegistry   │                   │                  │  applied          │
    │  updated!          │                   │                  │                  │
    │                    │                   │                  │                  │
    ├─ next born Molbot  │                   │                  │                  │
    │  gets new Trait    │                   │                  │                  │
    ▼                    ▼                   ▼                  ▼                  ▼
```

### 4.5 Agent Concurrency Model

```python
async def main():
    redis = Redis(host="redis", port=6379, decode_responses=True)
    bus = EventBus(redis)

    engine   = CoreEngine(bus, redis)
    watcher  = WatcherAgent(bus, redis)
    architect = ArchitectAgent(bus, redis, ollama_url="http://ollama:11434")
    coder    = CoderAgent(bus, redis, ollama_url="http://ollama:11434")
    patcher  = RuntimePatcher(bus, redis, mutations_dir="./mutations")
    api      = create_fastapi_app(bus, redis)

    await asyncio.gather(
        engine.run(),               # Tick loop: never exits
        watcher.run(),              # Subscribe ch:telemetry → analyze
        architect.run(),            # Subscribe ch:evolution:trigger → plan
        coder.run(),                # Subscribe ch:evolution:plan → generate
        patcher.run(),              # Subscribe ch:mutation:ready → load
        bus.listen(),               # Dispatch all Pub/Sub messages
        run_uvicorn(api, port=8000) # FastAPI + WebSocket server
    )
```

Каждый агент — это **отдельная корутина**, а не отдельный процесс. Все работают в одном event loop. LLM-вызовы (`httpx.AsyncClient` → Ollama) неблокирующие. Core tick loop **никогда не ждёт** LLM — он подписывается на `ch:mutation:applied` и обновляет реестр, когда мутация готова.

---

## 5. Sandbox: Safe Code Execution

### 5.1 Threat Model

LLM может сгенерировать код, который:
- **Крашит процесс:** бесконечный цикл, деление на ноль, stack overflow.
- **Утекает из sandbox:** `os.system()`, `subprocess.Popen()`, запись в файлы вне `mutations/`.
- **Потребляет ресурсы:** бесконечная аллокация памяти, CPU-bound операции.
- **Нарушает контракт:** меняет сигнатуру `execute()`, возвращает неожиданный тип.

### 5.2 Validation Pipeline

```
LLM Output (raw string)
        │
        ▼
┌───────────────────────────┐
│  Step 1: SYNTAX CHECK     │
│  ast.parse(source_code)   │
│                           │
│  Reject: SyntaxError      │
└─────────┬─────────────────┘
          │ OK
          ▼
┌───────────────────────────┐
│  Step 2: AST INSPECTION   │
│  Walk AST tree:           │
│  - Check all Import nodes │
│  - Check all Call nodes   │
│  - Check for banned       │
│    constructs             │
│                           │
│  Reject: Forbidden import │
│  or dangerous call        │
└─────────┬─────────────────┘
          │ OK
          ▼
┌───────────────────────────┐
│  Step 3: CONTRACT CHECK   │
│  - Has class(Trait)?      │
│  - Has async execute()?   │
│  - Correct signature?     │
│                           │
│  Reject: Missing contract │
└─────────┬─────────────────┘
          │ OK
          ▼
┌───────────────────────────┐
│  Step 4: HASH + DEDUP     │
│  SHA-256(source_code)     │
│  Check vs mutations table │
│                           │
│  Reject: Duplicate code   │
└─────────┬─────────────────┘
          │ OK
          ▼
   Save to mutations/
   Status: "validated"
```

### 5.3 Validator Implementation

```python
import ast
from typing import NamedTuple


ALLOWED_IMPORTS = frozenset({
    "math", "random", "dataclasses", "typing",
    "enum", "collections", "functools", "itertools",
})

BANNED_CALLS = frozenset({
    "exec", "eval", "compile", "__import__",
    "open", "print",  # print мусорит в stdout
    "exit", "quit",
    "getattr", "setattr", "delattr",  # предотвращаем monkey-patching
})

BANNED_ATTRIBUTES = frozenset({
    "__subclasses__", "__bases__", "__globals__",
    "__code__", "__builtins__",
})


class ValidationResult(NamedTuple):
    is_valid: bool
    error: str | None = None
    trait_class_name: str | None = None


class CodeValidator:
    """AST-based validator for LLM-generated mutation code."""

    def validate(self, source_code: str) -> ValidationResult:
        # Step 1: Syntax
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return ValidationResult(False, f"SyntaxError: {e}")

        # Step 2: AST Inspection
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_module = alias.name.split(".")[0]
                    if root_module not in ALLOWED_IMPORTS:
                        return ValidationResult(
                            False, f"Forbidden import: {alias.name}"
                        )

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    root_module = node.module.split(".")[0]
                    if root_module not in ALLOWED_IMPORTS:
                        return ValidationResult(
                            False, f"Forbidden import: {node.module}"
                        )

            # Check dangerous function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in BANNED_CALLS:
                        return ValidationResult(
                            False, f"Banned call: {node.func.id}()"
                        )

            # Check dangerous attribute access
            if isinstance(node, ast.Attribute):
                if node.attr in BANNED_ATTRIBUTES:
                    return ValidationResult(
                        False, f"Banned attribute: .{node.attr}"
                    )

        # Step 2.5: Module-Level Execution Protection
        # Запретить любой исполняемый код на уровне модуля
        module_level_error = self._check_module_level_code(tree)
        if module_level_error:
            return ValidationResult(False, module_level_error)

        # Step 3: Contract — find Trait subclass with async execute
        trait_class = self._find_trait_class(tree)
        if trait_class is None:
            return ValidationResult(
                False, "No class inheriting from Trait found"
            )

        if not self._has_async_execute(trait_class):
            return ValidationResult(
                False, f"Class {trait_class.name} missing 'async def execute(self, entity)'"
            )

        return ValidationResult(True, None, trait_class.name)

    def _find_trait_class(self, tree: ast.Module) -> ast.ClassDef | None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name == "Trait":
                    return node
        return None

    def _has_async_execute(self, cls: ast.ClassDef) -> bool:
        for node in cls.body:
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "execute"
                and len(node.args.args) >= 2  # self, entity
            ):
                return True
        return False

    def _check_module_level_code(self, tree: ast.Module) -> str | None:
        """Запретить исполняемый код на уровне модуля (только class, def, import, constants)."""
        for node in tree.body:
            # Разрешены: ClassDef, FunctionDef, AsyncFunctionDef, Import, ImportFrom, Assign (константы), AnnAssign
            if isinstance(node, (
                ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign
            )):
                continue
            # Expr nodes (вызовы функций) запрещены
            if isinstance(node, ast.Expr):
                return "Module-level executable code is forbidden. Only class, def, import, and constants are allowed."
            # Все остальное (For, While, If, etc.) тоже запрещено
            return f"Module-level {node.__class__.__name__} is forbidden."
        return None
```

### 5.4 Runtime Patcher Implementation

```python
import importlib
import importlib.util
import hashlib
import asyncio
from pathlib import Path


class RuntimePatcher:
    """Loads validated mutation files into the running process."""

    def __init__(self, bus, redis, mutations_dir: str):
        self._bus = bus
        self._redis = redis
        self._mutations_dir = Path(mutations_dir)
        self._validator = CodeValidator()
        self._loaded_modules: dict[str, object] = {}

    async def run(self):
        await self._bus.subscribe("ch:mutation:ready", self._on_mutation_ready)

    async def _on_mutation_ready(self, data: dict):
        mutation_id = data["mutation_id"]
        file_path = Path(data["file_path"])
        trait_name = data["trait_name"]
        version = data["version"]

        try:
            # Re-validate (defense in depth)
            source = file_path.read_text(encoding="utf-8")
            result = self._validator.validate(source)
            if not result.is_valid:
                raise ValueError(f"Validation failed: {result.error}")

            # Dynamic import
            module_name = f"mutations.{file_path.stem}"
            spec = importlib.util.spec_from_file_location(
                module_name, str(file_path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the Trait class
            trait_cls = getattr(module, result.trait_class_name)

            # Register in DynamicRegistry
            registry_key = "meta:registry:traits"
            await self._redis.hset(registry_key, trait_name, str(file_path))
            new_version = await self._redis.incr("meta:registry:version")

            self._loaded_modules[trait_name] = trait_cls

            # Publish success
            await self._bus.publish("ch:mutation:applied", MutationApplied(
                mutation_id=mutation_id,
                trait_name=trait_name,
                version=version,
                registry_version=new_version,
            ))

            await self._bus.publish("ch:feed", FeedMessage(
                agent="patcher",
                action="mutation_applied",
                message=f"Trait '{trait_name}' v{version} loaded. "
                        f"Registry updated to v{new_version}.",
            ))

        except Exception as e:
            # Rollback to previous version
            prev = await self._get_previous_version(trait_name, version)

            await self._bus.publish("ch:mutation:failed", MutationFailed(
                mutation_id=mutation_id,
                error=str(e),
                stage="import",
                rollback_to=prev,
            ))

    async def _get_previous_version(
        self, trait_name: str, current_version: int
    ) -> str | None:
        if current_version <= 1:
            return None
        prev_file = f"trait_{trait_name}_v{current_version - 1}.py"
        prev_path = self._mutations_dir / prev_file
        if prev_path.exists():
            return str(prev_path)
        return None

    def get_trait_class(self, trait_name: str):
        return self._loaded_modules.get(trait_name)
```

### 5.5 Execution Safety (Trait Runtime)

Даже после валидации Trait может зависнуть или упасть в рантайме. Core защищается при вызове:

```python
import asyncio
import time


class TraitExecutor:
    """Safely executes Traits on entities with timeout and time budgeting."""

    TRAIT_TIMEOUT_SEC = 0.005  # 5ms per trait (hard limit)
    TICK_TIME_BUDGET_SEC = 0.014  # 14ms бюджет на весь тик (60 FPS = 16ms)

    async def execute_all_entities(self, entities: list) -> None:
        """Execute traits for all entities with global time budget."""
        tick_start = time.perf_counter()
        entities_processed = 0

        for entity in entities:
            # Check if we've exceeded tick time budget
            elapsed = time.perf_counter() - tick_start
            if elapsed >= self.TICK_TIME_BUDGET_SEC:
                # Skip remaining entities this tick, continue next tick
                break

            await self._execute_entity_traits(entity)
            entities_processed += 1

        # Log: if entities_processed < len(entities) → we're lagging

    async def _execute_entity_traits(self, entity) -> None:
        failed_traits = []

        for trait in entity.traits:
            try:
                await asyncio.wait_for(
                    trait.execute(entity),
                    timeout=self.TRAIT_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                failed_traits.append(trait)
                # Log: trait exceeded time budget
            except Exception:
                failed_traits.append(trait)
                # Log: trait runtime error

        # Deactivate failed traits (don't crash the entity)
        for trait in failed_traits:
            entity.traits.remove(trait)
            entity.deactivated_traits.append(trait.__class__.__name__)
```

### 5.6 Security Summary

| Layer | Mechanism | What It Catches |
|-------|-----------|----------------|
| **Syntax** | `ast.parse()` | Синтаксические ошибки, невалидный Python |
| **Static Analysis** | AST walk: import/call/attribute check | `os.system()`, `subprocess`, `eval`, monkey-patching |
| **Contract** | AST class/method inspection | Нарушение интерфейса `Trait.execute()` |
| **Deduplication** | SHA-256 hash | Повторный код, зацикливание LLM |
| **Import Isolation** | `importlib.util.spec_from_file_location` | Побочные эффекты при импорте |
| **Module-Level Protection** | AST check for Expr/For/While at module level | Блокировка Main Loop при импорте |
| **Runtime Timeout** | `asyncio.wait_for(5ms)` + Time Budgeting | Бесконечные циклы, CPU-bound код |
| **Runtime Error** | try/except per trait | Исключения не убивают Molbot'а |
| **Rollback** | Versioned files in `mutations/` | Откат к предыдущей рабочей версии |

---

## 6. API Contracts

### 6.1 REST Endpoints

| Method | Path | Body | Response | Description |
|--------|------|------|----------|-------------|
| GET | `/api/world/state` | — | `WorldState` JSON | Текущие параметры мира |
| POST | `/api/world/params` | `{param: value}` | `200 OK` | Изменить параметр среды |
| POST | `/api/evolution/trigger` | `{reason?: string}` | `{cycle_id}` | Форсировать цикл эволюции |
| GET | `/api/evolution/history` | `?limit=20` | `EvolutionCycle[]` | История циклов |
| GET | `/api/mutations` | `?status=applied` | `Mutation[]` | Список мутаций |
| GET | `/api/mutations/{id}/source` | — | `{source_code}` | Исходный код мутации |
| GET | `/api/stats` | — | `SystemStats` | Метрики: uptime, entity_count, etc. |

### 6.2 WebSocket Protocol

**Endpoint:** `ws://localhost:8000/ws/world-stream`

**Оптимизация:** Для популяций >200 Molbot'ов используется **Binary Array Protocol** вместо JSON для снижения трафика в 10x.

**Server → Client (30 FPS) — JSON Mode (<200 entities):**
```json
{
  "type": "world_frame",
  "tick": 90301,
  "entities": [
    {
      "id": "mol_00a3f1",
      "x": 450.23,
      "y": 312.77,
      "energy": 78.5,
      "radius": 6.2,
      "color": "#FF8C42",
      "state": "alive",
      "traits": ["thermal_vision_v2", "energy_absorb_v1"]
    }
  ],
  "resources": [
    {"x": 100, "y": 200, "amount": 50}
  ]
}
```

**Server → Client (30 FPS) — Binary Mode (>=200 entities):**
```
WebSocket Binary Frame:
  Header (8 bytes):
    - tick: uint32
    - entity_count: uint16
    - resource_count: uint16

  Entity Array (16 bytes per entity):
    - x: float32
    - y: float32
    - energy: float32
    - type: uint8 (encoded trait combination)
    - color: uint24 (RGB)

  Resource Array (12 bytes per resource):
    - x: float32
    - y: float32
    - amount: float32
```

Клиент автоматически переключается между режимами на основе `entity_count`.

**Server → Client (on event):**
```json
{
  "type": "feed_message",
  "agent": "architect",
  "message": "Популяция голодает. Проектирую Trait: EnergyScavenger.",
  "timestamp": "2026-02-16T14:32:15Z"
}
```

**Client → Server:**
```json
{
  "type": "set_param",
  "param": "temperature",
  "value": 35.0
}
```

---

## 7. Configuration (Pydantic Settings)

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    tick_rate_ms: int = 16
    max_entities: int = 500
    min_population: int = 20
    world_width: int = 2000
    world_height: int = 2000

    # Redis (only persistence layer for MVP)
    redis_url: str = "redis://redis:6379/0"

    # Ollama
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3:8b"
    llm_timeout_sec: int = 120

    # Sandbox
    mutations_dir: str = "./mutations"
    trait_timeout_sec: float = 0.005  # 5ms hard limit per trait
    tick_time_budget_sec: float = 0.014  # 14ms budget for entire tick
    max_active_traits: int = 30
    max_trait_versions_kept: int = 3  # Keep only last 3 versions for GC
    allowed_imports: str = "math,random,dataclasses,typing,enum,collections,functools,itertools"

    # Process Management
    soft_restart_interval_hours: int = 24  # Auto-restart для очистки памяти от классов-призраков
    soft_restart_mutation_threshold: int = 1000  # Или при достижении N мутаций

    # Watcher
    snapshot_interval_ticks: int = 300
    watcher_history_depth: int = 5
    anomaly_death_threshold: float = 0.30
    anomaly_overpop_threshold: float = 2.0

    # Evolution
    evolution_cooldown_sec: int = 60

    class Config:
        env_prefix = "GENESIS_"
        env_file = ".env"
```

---

## 8. Process Lifecycle & Memory Management

### 8.1 Garbage Collection Strategy

**Проблема:** При hot-reload через `importlib` старые версии классов остаются в памяти, если на них есть хоть одна ссылка (например, в `entity.traits`). Через неделю работы 24/7 это приведет к MemoryError.

**Решения:**

1. **Версионирование Trait'ов:**
   - Хранить только последние 3 версии каждого Trait'а в `mutations/`.
   - При создании v4 — удалять v1.

2. **Очистка ссылок:**
   - При замене Trait'а: обойти всех Molbot'ов и заменить старую версию на новую.
   - Вызвать `gc.collect()` после каждого цикла эволюции.

3. **Мониторинг:**
   - Отслеживать `sys.getsizeof(DynamicRegistry)` и `len(sys.modules)`.
   - Алерт при превышении порога.

### 8.2 Soft Restart (для MVP опционально, для Production критично)

**Механизм:**
- Раз в 24 часа (или при достижении 1000 мутаций) Core:
  1. Сохраняет полное состояние мира в Redis: `ws:restart_checkpoint`.
  2. Публикует событие `ch:system:shutdown`.
  3. Завершает процесс с кодом 0.
- Docker Compose с `restart: always` автоматически перезапускает контейнер.
- При старте Core проверяет наличие `ws:restart_checkpoint` и восстанавливает состояние.

**Преимущества:**
- Полная очистка памяти от классов-призраков.
- Обновление зависимостей (если образ пересобирался).
- Downtime < 2 секунды (незаметно для пользователя).

**Конфигурация:**
```yaml
# docker-compose.yml
services:
  core:
    restart: always
    environment:
      - GENESIS_SOFT_RESTART_INTERVAL_HOURS=24
      - GENESIS_SOFT_RESTART_MUTATION_THRESHOLD=1000
```

---

*Document Version: 1.1*
*References: PRD.md, architecture.md, technical.md, development_roadmap.md*
*Next Document: .cursorrules*
