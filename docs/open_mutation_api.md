# Open Mutation API — Спецификация и план реализации

**Статус:** Draft v0.2
**Дата:** 2026-02-18

---

## Суть идеи

Сейчас внутренняя LLM (Ollama/Llama 3) — единственный источник мутаций. Она особенная: имеет прямой доступ к внутренним агентам и шинам событий.

**Цель:** сделать локальную LLM просто одним из клиентов общего API мутаций. Внешние агенты (Claude, GPT-4, кастомные скрипты, curl) работают через тот же HTTP-интерфейс — и проходят через тот же sandbox-пайплайн. Локальную LLM можно полностью отключить.

```
Внешний агент (Claude, GPT-4, curl...)
         ↓
   HTTP Mutation API
         ↓
  Gatekeeper + Sandbox  ←←←  тот же, что и для локальной LLM
         ↓
   DynamicRegistry / Core
```

---

## Про импорт `Trait` в мутациях (важно)

**Проблема:** `from backend.core.traits import Trait` запрещён валидатором (`backend` не в `ALLOWED_IMPORTS`).

**Реальный паттерн** (используется в существующих мутациях в `mutations/`):

Мутация определяет свой stub `BaseTrait` прямо внутри файла. Patcher загружает модуль через `importlib`, берёт класс по имени и регистрирует в `DynamicRegistry`. Реальная типизация — duck typing через `Protocol`.

```python
from __future__ import annotations
import math
import random

class BaseTrait:
    """Base trait protocol stub — no import needed."""
    pass

class EnergyHoarderTrait(BaseTrait):
    async def execute(self, entity) -> None:
        if entity.energy < 25:
            entity.energy_consumption_rate *= 0.7
```

Это единственный корректный паттерн. В спецификации все примеры кода используют именно его.

---

## Блок 1 — Context API

Три GET-эндпоинта для того, чтобы агент понял ситуацию перед отправкой мутации.

### `GET /api/agents/context/metrics`

Агрегированный срез мира из последнего `WorldSnapshot` в Redis.

```json
{
  "tick": 45200,
  "entity_count": 134,
  "avg_energy": 42.7,
  "resource_count": 89,
  "death_stats": {
    "starvation": 12,
    "collision": 3
  },
  "trait_usage": {
    "heat_shield": 45,
    "resource_seeker": 78
  },
  "anomalies": ["starvation"]
}
```

Реализация: читаем последний ключ `ws:snapshot:*` из Redis.

---

### `GET /api/agents/context/tasks`

Очередь задач от Watcher/Architect. Задачи **не бессрочные** — каждая имеет TTL и исчезает по истечении.

```json
{
  "tasks": [
    {
      "task_id": "task_a3f2bc",
      "expires_at": 1708124056.7,
      "ttl_remaining_sec": 487,
      "source": "watcher",
      "problem_type": "starvation",
      "severity": "high",
      "description": "Средняя энергия упала до 20%. Нужен Trait, улучшающий сбор ресурсов.",
      "suggested_area": "traits",
      "world_context": {
        "entity_count": 134,
        "avg_energy": 20.1
      },
      "constraints": [
        "не использовать циклы > 100 итераций",
        "только: math, random, dataclasses, typing, enum, collections, functools, itertools",
        "определить BaseTrait stub в теле файла, не импортировать из backend.*"
      ]
    }
  ]
}
```

**Структура хранения:** Redis Sorted Set `agent:tasks:queue`, score = `expires_at` (unix timestamp). Задачи с `score < now()` считаются истёкшими и не возвращаются в ответе. Тело каждой задачи — в отдельном ключе `agent:task:{task_id}` с TTL.

**Время жизни задачи:**

| Тип проблемы | TTL задачи |
|---|---|
| `critical` (вымирание, критический голод) | 15 минут |
| `high` (голод, перенаселение) | 10 минут |
| `low` / `periodic_improvement` | 5 минут |

Задача удаляется из очереди при одном из условий:
- истёк TTL
- задача взята в work (`claim`) агентом и получила мутацию-ответ
- Watcher определил, что проблема разрешилась (новый снапшот без аномалии)

---

### `GET /api/agents/context/sandbox-api`

Правила для написания мутаций. Фиксированный JSON, не меняется в рантайме.

Содержит поле `sandbox_rules_version` — **инвариант совместимости**. Если правила меняются (новые запрещённые вызовы, новый timeout, новые атрибуты entity), версия увеличивается. Агент, кэширующий правила, должен сбрасывать кэш при изменении версии.

```json
{
  "api_version": "1",
  "sandbox_rules_version": "3",
  "trait_pattern": "define class BaseTrait stub inline, then inherit from it",
  "required_method": "async execute(self, entity) -> None",
  "allowed_imports": [
    "__future__", "math", "random", "dataclasses",
    "typing", "enum", "collections", "functools", "itertools"
  ],
  "forbidden_imports": ["os", "sys", "subprocess", "socket", "shutil", "backend"],
  "forbidden_calls": ["eval", "exec", "compile", "open", "__import__", "print", "globals"],
  "forbidden_attrs": ["__subclasses__", "__globals__", "__code__", "__builtins__", "__dict__"],
  "entity_allowed_attrs": ["x", "y", "energy", "speed", "state", "age", "traits", "..."],
  "timeout_ms": 5,
  "max_loop_iterations": 100,
  "no_module_level_code": true,
  "example": "class BaseTrait:\n    pass\n\nclass MyTrait(BaseTrait):\n    async def execute(self, entity) -> None:\n        if entity.energy < 30:\n            entity.energy_consumption_rate *= 0.8"
}
```

**Когда инкрементировать `sandbox_rules_version`:** при любом изменении `ALLOWED_IMPORTS`, `BANNED_CALLS`, `BANNED_ATTRS`, `ALLOWED_ENTITY_ATTRS`, `timeout_ms` или сигнатуры `execute`. Значение хранится в `backend/config.py` как константа `SANDBOX_RULES_VERSION`.

---

## Блок 2 — Propose API

### `POST /api/mutations/propose`

Отправить мутацию на валидацию.

**Request:**
```json
{
  "agent_id": "claude-external-1",
  "task_id": "task_a3f2bc",
  "trait_name": "energy_hoarder",
  "goal": "Накапливать энергию при низком уровне",
  "code": "from __future__ import annotations\nimport math\n\nclass BaseTrait:\n    pass\n\nclass EnergyHoarderTrait(BaseTrait):\n    async def execute(self, entity) -> None:\n        if entity.energy < 25:\n            entity.energy_consumption_rate *= 0.7"
}
```

**Поля:**
- `agent_id` — идентификатор агента (любая строка, для логов и лимитов)
- `task_id` — опционально, привязка к задаче из `/context/tasks`
- `trait_name` — snake_case (станет частью имени файла `trait_{name}_v{N}.py`)
- `goal` — описание цели (идёт в Evolution Feed)
- `code` — Python-код мутации

**Response 202:**
```json
{
  "mutation_id": "mut_7f3a1c",
  "status": "queued",
  "message": "Mutation accepted for validation"
}
```

**Response 429 (rate limit):**
```json
{
  "error": "RATE_LIMIT_EXCEEDED",
  "detail": "Too many active mutations for agent_id 'claude-external-1' (limit: 5)",
  "retry_after_sec": 120
}
```

---

### `GET /api/mutations/{mutation_id}/status`

```json
{
  "mutation_id": "mut_7f3a1c",
  "trait_name": "energy_hoarder",
  "agent_id": "claude-external-1",
  "status": "rejected",
  "failure_reason_code": "AST_IMPORT_FORBIDDEN",
  "created_at": 1708123456.7,
  "updated_at": 1708123461.3,
  "validation_log": [
    "AST parse: OK",
    "Import whitelist: FAILED — Forbidden import: backend.core.traits"
  ]
}
```

**Статусы:**
```
queued → validating → sandbox_ok → activated
                   ↘ rejected
activated → rolled_back
```

**Коды ошибок `failure_reason_code`:**

| Код | Что случилось | Как исправить |
|-----|--------------|---------------|
| `SYNTAX_ERROR` | Код не парсится | Исправить синтаксис |
| `AST_IMPORT_FORBIDDEN` | Запрещённый импорт | Убрать импорт из `backend.*`; stdlib-импорты только из whitelist |
| `AST_BANNED_CALL` | Вызов `eval`, `exec`, `open`, etc. | Убрать запрещённые вызовы |
| `AST_BANNED_ATTR` | Доступ к `__globals__`, `__code__`, etc. | Убрать доступ к dunder-атрибутам |
| `AST_NO_TRAIT_CLASS` | Нет класса, наследующего `BaseTrait`/`Trait` с `async execute` | Добавить корректный Trait-класс |
| `AST_ENTITY_ATTR_FORBIDDEN` | Обращение к `entity.X` где X не в whitelist | Использовать только разрешённые атрибуты entity |
| `AST_INIT_REQUIRED_ARGS` | `__init__` требует аргументы (Trait создаётся без args) | Убрать обязательные параметры из `__init__` |
| `AST_UNBOUND_VARIABLE` | Переменная используется до гарантированного присвоения | Исправить логику присвоения |
| `AST_AWAIT_ON_SYNC` | `await entity.method()` — методы entity синхронные | Убрать `await` перед вызовами entity |
| `DUPLICATE_CODE` | Код идентичен уже применённой мутации (по SHA-256) | Изменить логику |
| `SANDBOX_TIMEOUT` | Trait не уложился в 5ms | Упростить логику |
| `SANDBOX_EXCEPTION` | Исключение при тестовом выполнении | Исправить runtime-ошибку |
| `SANDBOX_FPS_DROP` | Падение FPS при тестировании | Снизить вычислительную нагрузку |
| `RATE_LIMIT_EXCEEDED` | Превышен лимит (не попадёт в статус, приходит в 429) | Подождать |

---

### `GET /api/mutations/{mutation_id}/effects`

Доступен после `status = activated`. Watcher наблюдает N тиков и пишет дельту.

```json
{
  "mutation_id": "mut_7f3a1c",
  "trait_name": "energy_hoarder",
  "status": "activated",
  "observation_window_ticks": 300,
  "observed": false,
  "effects": null
}
```

После наблюдения:
```json
{
  "mutation_id": "mut_7f3a1c",
  "trait_name": "energy_hoarder",
  "status": "activated",
  "observation_window_ticks": 300,
  "observed": true,
  "effects": {
    "entity_count_delta": 12,
    "avg_energy_delta": 8.3,
    "death_starvation_delta": -5
  },
  "fitness_verdict": "positive"
}
```

---

## Блок 3 — Telemetry WebSocket

### `WS /api/agents/telemetry`

Агент подключается к стриму и получает события без поллинга.

```json
{"event": "WorldSnapshot", "tick": 45300, "entity_count": 138, "avg_energy": 45.1}
{"event": "TaskPublished", "task_id": "task_b4e3cd", "problem_type": "overpopulation", "expires_at": 1708124500.0}
{"event": "TaskExpired", "task_id": "task_a3f2bc"}
{"event": "MutationActivated", "mutation_id": "mut_7f3a1c", "trait_name": "energy_hoarder"}
{"event": "MutationRolledBack", "mutation_id": "mut_7f3a1c", "reason": "population_decline", "fitness_delta": -0.31}
```

Реализация: WS handler, подписанный на Redis каналы `ch:telemetry`, `ch:mutation:applied`, `ch:mutation:rollback`, `ch:agent:tasks`.

---

## Rate Limiting

Авторизации нет. Только лимиты через Redis counters с TTL.

| Правило | Значение | Redis-ключ |
|---------|----------|-----------|
| Активных мутаций на `agent_id` | 5 | `ratelimit:active:{agent_id}` (счётчик) |
| `POST /propose` в минуту с одного IP | 10 | `ratelimit:ip:min:{ip}` (TTL 60s) |
| `POST /propose` в час с одного `agent_id` | 30 | `ratelimit:agent:hr:{agent_id}` (TTL 3600s) |
| Макс. размер `code` в теле | 32 KB | проверяется в FastAPI middleware |

```python
# Пример проверки в routes_agents.py
key = f"ratelimit:agent:hr:{agent_id}"
count = await redis.incr(key)
if count == 1:
    await redis.expire(key, 3600)
if count > 30:
    raise HTTPException(429, detail={"error": "RATE_LIMIT_EXCEEDED", "retry_after_sec": ...})
```

---

## Пайплайн валидации (не меняется)

Одинаков для локальной LLM и внешних агентов.

```
POST /api/mutations/propose
        ↓
1. Rate limit check → 429 если превышен
2. Schema validation → trait_name формат, code не пустой, размер ≤ 32KB
3. AST parse → SYNTAX_ERROR
4. Import whitelist → AST_IMPORT_FORBIDDEN
5. Banned calls/attrs → AST_BANNED_CALL / AST_BANNED_ATTR
6. Trait contract → AST_NO_TRAIT_CLASS
7. Entity attr whitelist → AST_ENTITY_ATTR_FORBIDDEN
8. Init signature → AST_INIT_REQUIRED_ARGS
9. Unbound vars → AST_UNBOUND_VARIABLE
10. Await-on-sync → AST_AWAIT_ON_SYNC
11. Deduplication (SHA-256) → DUPLICATE_CODE
12. Sandbox test (50 тиков) → SANDBOX_TIMEOUT / SANDBOX_EXCEPTION / SANDBOX_FPS_DROP
        ↓
Успех: файл в mutations/trait_{name}_v{N}.py
       → DynamicRegistry.register()
       → статус activated
Провал: статус rejected + failure_reason_code + validation_log
```

---

## Как задачи попадают к внешним агентам

Watcher при каждом `EvolutionTrigger` делает два действия параллельно:

1. Публикует в `ch:evolution:trigger` (как сейчас — для внутренней LLM)
2. Пишет задачу для внешних агентов:

```python
task_id = f"task_{uuid4().hex[:8]}"
ttl_sec = _task_ttl(trigger.severity)  # critical→900, high→600, low→300
expires_at = time.time() + ttl_sec

task_body = {
    "task_id": task_id,
    "expires_at": expires_at,
    "source": "watcher",
    "problem_type": trigger.problem_type,
    "severity": trigger.severity,
    "description": _format_description(trigger),
    "suggested_area": trigger.suggested_area,
    "world_context": trigger.world_context,
    "constraints": SANDBOX_CONSTRAINTS,
}

# Тело задачи с TTL
await redis.set(f"agent:task:{task_id}", json.dumps(task_body), ex=ttl_sec)

# Sorted set для очереди (score = expiry timestamp)
await redis.zadd("agent:tasks:queue", {task_id: expires_at})

# Публикуем в WS-канал (для подключённых агентов)
await bus.publish(Channels.AGENT_TASKS, {"task_id": task_id, "expires_at": expires_at, ...})
```

**Чтение очереди** (`GET /api/agents/context/tasks`):

```python
now = time.time()
# Удаляем просроченные (score < now)
await redis.zremrangebyscore("agent:tasks:queue", "-inf", now)
# Берём актуальные
task_ids = await redis.zrange("agent:tasks:queue", 0, -1)
tasks = [json.loads(await redis.get(f"agent:task:{tid}")) for tid in task_ids if ...]
```

---

## Изменения в коде

### Новые файлы

| Файл | Что делает |
|------|-----------|
| `backend/api/routes_agents.py` | Context API + Propose API |
| `backend/api/ws_agents.py` | WebSocket `/api/agents/telemetry` |
| `backend/agents/mutation_gatekeeper.py` | Async воркер: читает из очереди, запускает sandbox, пишет статус |

### Изменения существующих файлов

| Файл | Изменение |
|------|-----------|
| `backend/agents/watcher.py` | После `EvolutionTrigger` → пишет задачу в `agent:tasks:queue` |
| `backend/api/app.py` | Подключить `routes_agents` и `ws_agents` |
| `backend/bus/channels.py` | Добавить `AGENT_TASKS = "ch:agent:tasks"` |

### Что не меняется

- `backend/sandbox/` — пайплайн валидации не трогаем
- `backend/core/dynamic_registry.py` — регистрация трейтов не меняется
- `backend/agents/architect.py`, `coder.py` — работают как раньше

---

## Порядок реализации

### Шаг 1 — Context API (нет зависимостей, проверяется curl'ом)

Создать `routes_agents.py`:
- `GET /api/agents/context/metrics` — читаем из Redis `ws:snapshot:*`
- `GET /api/agents/context/tasks` — читаем из `agent:tasks:queue` (Sorted Set) + `agent:task:{id}`
- `GET /api/agents/context/sandbox-api` — статический JSON

Подключить в `app.py`.

### Шаг 2 — Task publishing в Watcher

В `watcher.py` после публикации `EvolutionTrigger`:
- писать тело задачи в `agent:task:{task_id}` с `ex=ttl_sec`
- добавлять `task_id` в `agent:tasks:queue` (sorted set, score=expires_at)
- публиковать `TaskPublished` событие в `ch:agent:tasks`

Проверить: после аномалии задача появляется в `/api/agents/context/tasks` и исчезает по TTL.

### Шаг 3 — Propose API

В `routes_agents.py`:
- `POST /api/mutations/propose` с rate limit check
- Записать метаданные в `evo:mutation:{id}` (hash), код в `evo:mutation:{id}:source`, статус `queued`
- Push `mutation_id` в Redis list `agent:mutation:queue`

Создать `backend/agents/mutation_gatekeeper.py`:
- `BRPOP agent:mutation:queue` в цикле (блокирующий pop)
- Запустить существующий `CodeValidator.validate()`
- При успехе: сохранить файл в `mutations/`, опубликовать `MutationReady` в bus → Patcher подхватит и зарегистрирует в DynamicRegistry
- При провале: записать `failure_reason_code` + `validation_log` → статус `rejected`

> Место выбрано сознательно: `agents/` — слой агентов (Watcher, Architect, Coder, теперь Gatekeeper). `core/` — protected zone, трогать нельзя. `sandbox/` — только валидация и патчинг, логика очереди туда не относится.

### Шаг 4 — Status + Effects

В `routes_agents.py`:
- `GET /api/mutations/{id}/status` — читаем из `evo:mutation:{id}`
- `GET /api/mutations/{id}/effects` — читаем из `evo:mutation:{id}:effects`

В `watcher.py` в `_check_fitness()`: при завершении наблюдения писать в `evo:mutation:{id}:effects`.

### Шаг 5 — WebSocket (опционально, если нужен real-time вместо поллинга)

`ws_agents.py`: подписка на Redis каналы, проброс событий в WS-соединение.

---

## Пример рабочего цикла внешнего агента

```bash
# 1. Смотрю задачи (есть TTL, протухают сами)
curl http://localhost:8000/api/agents/context/tasks

# 2. Читаю правила
curl http://localhost:8000/api/agents/context/sandbox-api

# 3. Отправляю мутацию
curl -X POST http://localhost:8000/api/mutations/propose \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "claude-external",
    "task_id": "task_a3f2bc",
    "trait_name": "energy_hoarder",
    "goal": "Накапливать энергию при низком уровне",
    "code": "from __future__ import annotations\n\nclass BaseTrait:\n    pass\n\nclass EnergyHoarderTrait(BaseTrait):\n    async def execute(self, entity) -> None:\n        if entity.energy < 25:\n            entity.energy_consumption_rate *= 0.7"
  }'
# → {"mutation_id": "mut_9a2b3c", "status": "queued"}

# 4. Жду (поллинг)
curl http://localhost:8000/api/mutations/mut_9a2b3c/status
# rejected → смотрю failure_reason_code, правлю код, снова propose
# activated → жду эффектов

# 5. Смотрю эффект
curl http://localhost:8000/api/mutations/mut_9a2b3c/effects
# → {"fitness_verdict": "positive", "avg_energy_delta": 6.2}
```

---

## Что за бортом (для v0.2)

- **Claim задачи** — атомарно "взять" задачу, чтобы два агента не дублировали работу
- **Batch propose** — несколько мутаций за раз
- **Webhook callbacks** — `notify_url` в propose-запросе вместо поллинга
- **Agent reputation** — история успешных мутаций по `agent_id`
- **Modify existing trait** — сейчас только новые трейты

---

*Следующий шаг: читаешь, даёшь фидбек → начинаем с Шага 1 (Context API).*
