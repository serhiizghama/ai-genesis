# AI-Genesis — Logic Flow

Пошаговое описание трёх ключевых процессов системы.
Каждый процесс разбит на шаги, с указанием: кто выполняет, какие данные на входе/выходе,
какие Redis-ключи и Pub/Sub каналы задействованы, и как обрабатываются ошибки.

---

## 1. Telemetry Collection Cycle

### 1.1 Overview

Телеметрия — единственный источник правды о состоянии мира для всех AI-агентов.
Core Engine собирает метрики каждые `SNAPSHOT_INTERVAL_TICKS` (300 тиков, ~10 секунд)
и публикует их в Redis. Watcher Agent подписывается на уведомления и строит аналитику.

World Loop при этом **никогда не останавливается** ради телеметрии — сбор выполняется
внутри тика и укладывается в бюджет 16ms.

### 1.2 Step-by-Step

```
World Loop (engine.py)
│
│  tick_counter += 1
│
├─── Step 1: UPDATE ENTITIES ──────────────────────────────────────────
│    for entity in entity_manager.alive():
│        await trait_executor.execute_traits(entity)   # Trait'ы двигают Molbot'ов
│        entity.age += 1
│        entity.energy -= entity.metabolism_rate
│
├─── Step 2: RESOLVE INTERACTIONS ─────────────────────────────────────
│    collisions = entity_manager.detect_collisions()   # Spatial hash lookup
│    for (a, b) in collisions:
│        await resolve_collision(a, b)                 # Обмен энергией, урон
│
├─── Step 3: LIFECYCLE ────────────────────────────────────────────────
│    dead = [e for e in entities if e.energy <= 0 or e.age > e.max_age]
│    for e in dead:
│        death_log.append(DeathRecord(id=e.id, cause=..., tick=tick))
│        entity_manager.remove(e)
│
│    if entity_manager.count() < MIN_POPULATION:
│        spawn_batch(count=MIN_POPULATION - entity_manager.count())
│
│    if entity_manager.count() < MAX_ENTITIES and random() < spawn_chance:
│        entity_manager.spawn(parent=random_entity)
│
├─── Step 4: RESOURCE RESPAWN ─────────────────────────────────────────
│    environment.respawn_resources(rate=world_params.resource_spawn_rate)
│
├─── Step 5: TELEMETRY SNAPSHOT (conditional) ─────────────────────────
│    if tick_counter % SNAPSHOT_INTERVAL_TICKS == 0:
│        │
│        │   ┌─────────────────────────────────────────────────┐
│        └──►│  collect_and_publish_snapshot(tick_counter)      │
│            └─────────────────────────────────────────────────┘
│
├─── Step 6: BROADCAST TO WEBSOCKET (every 2nd tick) ──────────────────
│    if tick_counter % 2 == 0:
│        frame = build_world_frame(entity_manager, environment)
│        await ws_manager.broadcast(frame)
│
└─── await asyncio.sleep(tick_rate_sec - elapsed)  # Maintain 60 FPS
```

### 1.3 Snapshot Collection Detail

```
collect_and_publish_snapshot(tick)
│
├─── Step 5a: AGGREGATE METRICS ───────────────────────────────────────
│
│    Читаем из in-memory structures (НЕ из Redis — экономим round-trip):
│
│    snapshot = WorldSnapshot(
│        tick            = tick,
│        timestamp       = utc_now(),
│        entity_count    = entity_manager.count(),
│        avg_energy      = mean(e.energy for e in entities),
│        births_last_period = birth_counter.flush(),     # Счётчик с прошлого snapshot'а
│        deaths_last_period = death_counter.flush(),
│        death_starvation   = death_log.count_by("starvation"),
│        death_age          = death_log.count_by("age"),
│        death_collision    = death_log.count_by("collision"),
│        resource_density   = environment.resource_density(),
│        trait_diversity    = dynamic_registry.unique_trait_count(),
│        dominant_trait     = dynamic_registry.most_common_trait(),
│        temperature        = world_params.temperature,
│    )
│
├─── Step 5b: WRITE TO REDIS ──────────────────────────────────────────
│
│    Используем pipeline для атомарности и скорости (1 round-trip):
│
│    async with redis.pipeline() as pipe:
│        snapshot_key = f"ws:snapshot:{tick}"
│        pipe.hset(snapshot_key, mapping=snapshot.to_dict())
│        pipe.expire(snapshot_key, ttl=300)              # 5 min TTL
│        pipe.set("ws:tick", tick)
│        await pipe.execute()
│
├─── Step 5c: PUBLISH EVENT ───────────────────────────────────────────
│
│    await bus.publish(Channels.TELEMETRY, TelemetryEvent(
│        tick=tick,
│        snapshot_key=snapshot_key,
│    ))
│
│    Watcher Agent получит это сообщение через Redis Pub/Sub.
│    Core Engine НЕ ЖДЁТ ответа. Он уже перешёл к следующему тику.
│
├─── Step 5d: PERSIST TO POSTGRES (every 30th snapshot = ~5 min) ──────
│
│    if tick % (SNAPSHOT_INTERVAL_TICKS * 30) == 0:
│        await pg_pool.execute(INSERT_WORLD_SNAPSHOT, snapshot.to_row())
│
└─── return
```

### 1.4 Data Produced

| Artifact | Storage | Key/Table | TTL | Consumer |
|----------|---------|-----------|-----|----------|
| `WorldSnapshot` hash | Redis | `ws:snapshot:{tick}` | 5 min | Watcher Agent |
| Current tick | Redis | `ws:tick` | — | API, WebSocket |
| `TelemetryEvent` | Redis Pub/Sub | `ch:telemetry` | — | Watcher Agent |
| Historical snapshot | PostgreSQL | `world_snapshots` | 7 days | Dashboard, analytics |

### 1.5 Performance Budget

| Operation | Target | Notes |
|-----------|--------|-------|
| Metric aggregation | < 1ms | In-memory counters, no Redis reads |
| Redis pipeline write | < 2ms | 3 commands in 1 round-trip |
| Pub/Sub publish | < 0.5ms | Fire-and-forget |
| Postgres write | < 5ms | Async, happens once per ~5 min, non-blocking |
| **Total snapshot overhead** | **< 4ms** | Fits within 16ms tick budget |

---

## 2. Watcher Agent: Context Analysis

### 2.1 Overview

Watcher Agent — аналитик экосистемы. Он не пишет код, не вызывает LLM.
Он читает snapshot'ы, сравнивает тренды, определяет аномалии и генерирует
`EvolutionTrigger`, если экосистема в опасности.

Watcher работает как подписчик `ch:telemetry`. Каждый раз, когда Core
публикует новый snapshot, Watcher получает сообщение и запускает анализ.

### 2.2 State Machine

```
                      ┌──────────────┐
                      │              │
              ┌───────►   IDLE       │
              │       │  (waiting)   │
              │       └──────┬───────┘
              │              │
              │      ch:telemetry received
              │      OR ch:evolution:force
              │              │
              │       ┌──────▼───────┐
              │       │              │
              │       │  COLLECTING  │
              │       │  (read snap- │
              │       │   shots)     │
              │       └──────┬───────┘
              │              │
              │       ┌──────▼───────┐
              │       │              │
              │       │  ANALYZING   │
              │       │  (compare    │
              │       │   trends)    │
              │       └──────┬───────┘
              │              │
              │        ┌─────┴──────┐
              │        │            │
              │    no anomaly    anomaly!
              │        │            │
              │        │     ┌──────▼───────┐
              │        │     │              │
              │        │     │  TRIGGERING  │
              │        │     │  (cooldown   │
              └────────┘     │   check)     │
              │              └──────┬───────┘
              │                     │
              │               ┌─────┴──────┐
              │               │            │
              │           cooldown       cooldown
              │           active         expired
              │               │            │
              │               │     ┌──────▼───────┐
              │               │     │  PUBLISHING   │
              │               │     │  (emit        │
              └───────────────┘     │   trigger)    │
                                    └──────┬───────┘
                                           │
                                    back to IDLE
```

### 2.3 Step-by-Step

```
Watcher Agent (watcher.py)
│
├─── INIT ─────────────────────────────────────────────────────────────
│    Subscribe to: ch:telemetry, ch:evolution:force, ch:mutation:applied,
│                  ch:mutation:failed
│    history_buffer: deque(maxlen=WATCHER_HISTORY_DEPTH)  # last 5 snapshots
│    last_trigger_at: float = 0.0
│
│    Redis keys used:
│      - watcher:trigger_counter (TTL: 60s) — for circuit breaker
│      - watcher:circuit_breaker (TTL: 300s) — pause flag
│
│
╔══ ON EVENT: ch:telemetry ════════════════════════════════════════════╗
║                                                                      ║
║  Step 1: LOAD SNAPSHOT FROM REDIS ───────────────────────────────    ║
║                                                                      ║
║    snapshot_key = event["snapshot_key"]       # "ws:snapshot:90300"   ║
║    raw = await redis.hgetall(snapshot_key)                           ║
║    snapshot = WorldSnapshot.from_dict(raw)                           ║
║    history_buffer.append(snapshot)                                   ║
║                                                                      ║
║    if len(history_buffer) < 2:                                       ║
║        return  # Need at least 2 snapshots to detect trends          ║
║                                                                      ║
║  Step 2: COMPUTE DELTAS ─────────────────────────────────────────    ║
║                                                                      ║
║    prev = history_buffer[-2]                                         ║
║    curr = history_buffer[-1]                                         ║
║                                                                      ║
║    deltas = TelemetryDeltas(                                         ║
║        population_change = (curr.entity_count - prev.entity_count)   ║
║                            / max(prev.entity_count, 1),              ║
║        energy_trend      = curr.avg_energy - prev.avg_energy,        ║
║        death_rate        = curr.deaths_last_period                   ║
║                            / max(curr.entity_count, 1),              ║
║        birth_rate        = curr.births_last_period                   ║
║                            / max(curr.entity_count, 1),              ║
║        resource_trend    = curr.resource_density                     ║
║                            - prev.resource_density,                  ║
║        trait_diversity    = curr.trait_diversity,                     ║
║    )                                                                 ║
║                                                                      ║
║  Step 3: DETECT ANOMALIES ───────────────────────────────────────    ║
║                                                                      ║
║    anomalies: list[Anomaly] = []                                     ║
║                                                                      ║
║    ┌──────────────────────────────────────────────────────────────┐   ║
║    │  Rule 1: MASS EXTINCTION                                     │   ║
║    │  IF death_rate > ANOMALY_DEATH_THRESHOLD (0.30)              │   ║
║    │  AND population_change < -0.10                               │   ║
║    │  THEN anomalies.append(Anomaly(                              │   ║
║    │      type="starvation" | "overcrowding" | "environmental",   │   ║
║    │      severity="high" | "critical",                           │   ║
║    │      area="traits",                                          │   ║
║    │  ))                                                          │   ║
║    └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║    ┌──────────────────────────────────────────────────────────────┐   ║
║    │  Rule 2: OVERPOPULATION                                      │   ║
║    │  IF entity_count > MAX_ENTITIES * ANOMALY_OVERPOP (2.0)      │   ║
║    │  AND birth_rate > death_rate * 2                             │   ║
║    │  THEN anomalies.append(Anomaly(                              │   ║
║    │      type="overpopulation",                                  │   ║
║    │      severity="medium",                                      │   ║
║    │      area="physics",  # adjust spawn rate or carrying cap    │   ║
║    │  ))                                                          │   ║
║    └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║    ┌──────────────────────────────────────────────────────────────┐   ║
║    │  Rule 3: ENERGY CRISIS                                       │   ║
║    │  IF avg_energy < 20.0  (below 20% of max 100)               │   ║
║    │  AND energy_trend < -5.0 (falling fast)                      │   ║
║    │  THEN anomalies.append(Anomaly(                              │   ║
║    │      type="energy_crisis",                                   │   ║
║    │      severity="high",                                        │   ║
║    │      area="traits",  # need energy-gathering Trait           │   ║
║    │  ))                                                          │   ║
║    └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║    ┌──────────────────────────────────────────────────────────────┐   ║
║    │  Rule 4: LOW DIVERSITY                                       │   ║
║    │  IF trait_diversity < 3                                      │   ║
║    │  AND entity_count > 50                                       │   ║
║    │  THEN anomalies.append(Anomaly(                              │   ║
║    │      type="low_diversity",                                   │   ║
║    │      severity="medium",                                      │   ║
║    │      area="traits",                                          │   ║
║    │  ))                                                          │   ║
║    └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║    ┌──────────────────────────────────────────────────────────────┐   ║
║    │  Rule 5: STAGNATION                                          │   ║
║    │  IF last 5 snapshots have < 2% change in all metrics         │   ║
║    │  AND no new mutations applied in last 10 minutes             │   ║
║    │  THEN anomalies.append(Anomaly(                              │   ║
║    │      type="stagnation",                                      │   ║
║    │      severity="low",                                         │   ║
║    │      area="environment",                                     │   ║
║    │  ))                                                          │   ║
║    └──────────────────────────────────────────────────────────────┘   ║
║                                                                      ║
║                                                                      ║
║  Step 4: DECISION ───────────────────────────────────────────────    ║
║                                                                      ║
║    if not anomalies:                                                 ║
║        log("World is stable. No action needed.")                     ║
║        return                                                        ║
║                                                                      ║
║    # Pick the most severe anomaly                                    ║
║    worst = max(anomalies, key=lambda a: SEVERITY_ORDER[a.severity])  ║
║                                                                      ║
║                                                                      ║
║  Step 5: COOLDOWN CHECK + CIRCUIT BREAKER ──────────────────────    ║
║                                                                      ║
║    elapsed = time.time() - last_trigger_at                           ║
║    if elapsed < EVOLUTION_COOLDOWN_SEC:                               ║
║        log(f"Cooldown active ({elapsed:.0f}s / {COOLDOWN}s). Skip.") ║
║        return                                                        ║
║                                                                      ║
║    # CIRCUIT BREAKER: Prevent Redis key bloat from trigger spam      ║
║    # If Watcher creates >5 triggers in 60 seconds, pause for 5 min   ║
║    trigger_count = await redis.incr("watcher:trigger_counter")       ║
║    await redis.expire("watcher:trigger_counter", 60)  # 1 min window ║
║                                                                      ║
║    if trigger_count > 5:                                             ║
║        log("Circuit breaker activated: >5 triggers/min. Pausing.")   ║
║        await redis.setex("watcher:circuit_breaker", 300, "1")  # 5min║
║        await bus.publish(Channels.FEED, FeedMessage(                 ║
║            agent="watcher", action="circuit_breaker_activated",      ║
║            message="Too many triggers. Watcher paused for 5 minutes."║
║        ))                                                            ║
║        return                                                        ║
║                                                                      ║
║    # Check if circuit breaker is active from previous triggers       ║
║    if await redis.exists("watcher:circuit_breaker"):                 ║
║        return  # Silently skip this cycle                            ║
║                                                                      ║
║                                                                      ║
║  Step 6: BUILD WORLD REPORT ─────────────────────────────────────    ║
║                                                                      ║
║    report = WorldReport(                                             ║
║        trigger_id     = generate_uuid(),                             ║
║        tick           = curr.tick,                                   ║
║        anomaly        = worst,                                       ║
║        snapshot        = curr,                                       ║
║        history_summary = summarize(history_buffer),                  ║
║        active_traits  = await redis.hgetall("meta:registry:traits"), ║
║        death_breakdown = curr.death_causes,                          ║
║    )                                                                 ║
║                                                                      ║
║                                                                      ║
║  Step 7: PUBLISH TRIGGER ────────────────────────────────────────    ║
║                                                                      ║
║    await bus.publish(Channels.EVOLUTION_TRIGGER, EvolutionTrigger(    ║
║        trigger_id       = report.trigger_id,                         ║
║        problem_type     = worst.type,                                ║
║        severity         = worst.severity,                            ║
║        affected_entities = find_most_affected(entities, worst),      ║
║        suggested_area   = worst.area,                                ║
║        snapshot_key     = snapshot_key,                               ║
║    ))                                                                ║
║                                                                      ║
║    # Persist trigger to Redis (for Architect to read full context)   ║
║    await redis.hset(                                                 ║
║        f"evo:trigger:{report.trigger_id}",                           ║
║        mapping=report.to_dict(),                                     ║
║    )                                                                 ║
║    await redis.expire(f"evo:trigger:{report.trigger_id}", 600)       ║
║                                                                      ║
║    # Log to Evolution Feed                                           ║
║    await bus.publish(Channels.FEED, FeedMessage(                     ║
║        agent="watcher",                                              ║
║        action="anomaly_detected",                                    ║
║        message=f"Anomaly: {worst.type} (severity: {worst.severity})" ║
║                f" | population: {curr.entity_count}"                 ║
║                f" | avg energy: {curr.avg_energy:.1f}"               ║
║                f" | Triggering evolution cycle.",                     ║
║    ))                                                                ║
║                                                                      ║
║    last_trigger_at = time.time()                                     ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 2.4 Anomaly Severity Scale

| Severity | Condition Example | Cooldown Override | Evolution Speed |
|----------|-------------------|-------------------|-----------------|
| `low` | Stagnation, minor diversity drop | No | Normal (wait cooldown) |
| `medium` | Overpopulation, low diversity | No | Normal |
| `high` | 30%+ death rate, energy crisis | No | Normal |
| `critical` | 50%+ death rate, near-extinction | **Yes** (skip cooldown) | Immediate |

### 2.5 Context Passed to Architect

Architect Agent подписан на `ch:evolution:trigger`. Когда он получает событие,
он загружает полный контекст из Redis:

```
Architect receives EvolutionTrigger via Pub/Sub
│
├─── Read evo:trigger:{trigger_id} from Redis   ← WorldReport (full context)
├─── Read meta:registry:traits from Redis        ← Current Trait catalog
├─── Read ws:snapshot:{tick} from Redis          ← Latest numbers
│
└─── Now Architect has everything to make a decision
```

**Контекст, доступный Architect'у:**

| Data | Source | Contains |
|------|--------|----------|
| `WorldReport` | `evo:trigger:{id}` | Anomaly type, severity, affected entities, death breakdown |
| `Trait Catalog` | `meta:registry:traits` | Names and paths of all loaded Traits |
| `WorldSnapshot` | `ws:snapshot:{tick}` | All numeric metrics at time of trigger |
| `EvolutionTrigger` | Pub/Sub payload | `trigger_id`, `problem_type`, `suggested_area` |

---

## 3. Patch Generation & Hot-Reload

### 3.1 Overview

Это самый длинный процесс: от решения Architect'а до применения нового Trait'а
в ядре. Он включает два LLM-вызова (Architect + Coder), валидацию,
запись файла и динамическую загрузку — и всё это **без остановки World Loop**.

### 3.2 Full Pipeline Flowchart

```
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║    ch:evolution:trigger                                              ║
║         │                                                            ║
║         ▼                                                            ║
║  ┌──────────────┐                                                    ║
║  │  ARCHITECT   │  Step A: Read context from Redis                   ║
║  │  AGENT       │  Step B: Build LLM prompt                          ║
║  │              │  Step C: Call Ollama (3-8 sec)                      ║
║  │              │  Step D: Parse response → EvolutionPlan             ║
║  └──────┬───────┘                                                    ║
║         │                                                            ║
║    ch:evolution:plan                                                 ║
║         │                                                            ║
║         ▼                                                            ║
║  ┌──────────────┐                                                    ║
║  │  CODER       │  Step E: Read plan + Sandbox API                   ║
║  │  AGENT       │  Step F: Build code-gen prompt                     ║
║  │              │  Step G: Call Ollama (3-8 sec)                      ║
║  │              │  Step H: Extract Python code from LLM response     ║
║  │              │  Step I: Pre-validate (ast.parse + whitelist)       ║
║  │              │  Step J: Save to mutations/                         ║
║  └──────┬───────┘                                                    ║
║         │                                                            ║
║    ch:mutation:ready                                                 ║
║         │                                                            ║
║         ▼                                                            ║
║  ┌──────────────┐                                                    ║
║  │  RUNTIME     │  Step K: Re-validate (defense in depth)            ║
║  │  PATCHER     │  Step L: importlib load                            ║
║  │              │  Step M: Register in DynamicRegistry               ║
║  │              │  Step N: Persist metadata to PostgreSQL             ║
║  └──────┬───────┘                                                    ║
║         │                                                            ║
║    ch:mutation:applied                                               ║
║         │                                                            ║
║         ▼                                                            ║
║  ┌──────────────┐                                                    ║
║  │  CORE        │  Step O: Update in-memory registry                 ║
║  │  ENGINE      │  Step P: Next-born Molbots get new Trait           ║
║  │  (tick loop  │                                                    ║
║  │   continues) │  World Loop NEVER paused during this process.      ║
║  └──────────────┘                                                    ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 3.3 Step A-D: Architect Agent

```
on_evolution_trigger(event: EvolutionTrigger)
│
├─── Step A: READ CONTEXT ─────────────────────────────────────────────
│
│    trigger_data = await redis.hgetall(f"evo:trigger:{event.trigger_id}")
│    trait_catalog = await redis.hgetall("meta:registry:traits")
│    snapshot = await redis.hgetall(f"ws:snapshot:{event.tick}")
│
│    # Build context object
│    context = ArchitectContext(
│        problem      = trigger_data["anomaly"],
│        metrics      = snapshot,
│        traits       = list(trait_catalog.keys()),
│        sandbox_api  = SANDBOX_API_SCHEMA,     # What can be modified
│    )
│
├─── Step B: BUILD LLM PROMPT ─────────────────────────────────────────
│
│    system_prompt = """
│    You are the Architect of AI-Genesis, a self-evolving digital world.
│    Your role: analyze world problems and design solutions.
│    You do NOT write code. You describe WHAT to build and WHY.
│
│    Rules:
│    - Solutions must be a single Trait (Python class with async execute).
│    - Suggest trait name in snake_case.
│    - action_type: "new_trait" | "modify_trait" | "adjust_params"
│    - Respond ONLY in JSON format.
│    """
│
│    user_prompt = f"""
│    WORLD STATE:
│    - Population: {context.metrics.entity_count}
│    - Avg energy: {context.metrics.avg_energy}
│    - Deaths last period: {context.metrics.deaths_last_period}
│    - Death causes: {context.metrics.death_causes}
│    - Active traits: {context.traits}
│    - Resource density: {context.metrics.resource_density}
│
│    PROBLEM: {context.problem.type} (severity: {context.problem.severity})
│
│    Design a solution. JSON format:
│    {{
│      "action_type": "new_trait",
│      "trait_name": "snake_case_name",
│      "description": "What this trait does and why it solves the problem",
│      "target_behavior": "Detailed behavior description for the Coder"
│    }}
│    """
│
├─── Step C: CALL OLLAMA ──────────────────────────────────────────────
│
│    try:
│        response = await httpx_client.post(
│            f"{OLLAMA_URL}/api/generate",
│            json={
│                "model": OLLAMA_MODEL,
│                "prompt": user_prompt,
│                "system": system_prompt,
│                "stream": False,
│                "options": {"temperature": 0.7, "num_predict": 512},
│            },
│            timeout=LLM_TIMEOUT_SEC,           # 30 seconds
│        )
│    except (httpx.TimeoutException, httpx.ConnectError) as e:
│        await bus.publish(Channels.FEED, FeedMessage(
│            agent="architect", action="llm_error",
│            message=f"Ollama unavailable: {e}. Skipping this cycle.",
│        ))
│        return  # ← Graceful degradation: Core keeps running
│
├─── Step D: PARSE RESPONSE ───────────────────────────────────────────
│
│    raw_text = response.json()["response"]
│    plan_data = extract_json(raw_text)         # Regex/parse JSON from response
│
│    if plan_data is None:
│        log("Architect returned unparseable response. Skipping.")
│        return
│
│    plan = EvolutionPlan(
│        plan_id       = generate_uuid(),
│        trigger_id    = event.trigger_id,
│        action_type   = plan_data["action_type"],
│        description   = plan_data["description"],
│        target_class  = plan_data.get("trait_name"),
│        target_method = plan_data.get("target_behavior"),
│    )
│
│    # Persist plan
│    await redis.hset(f"evo:plan:{plan.plan_id}", mapping=asdict(plan))
│    await redis.expire(f"evo:plan:{plan.plan_id}", 600)
│
│    # Publish to Coder
│    await bus.publish(Channels.EVOLUTION_PLAN, plan)
│
│    await bus.publish(Channels.FEED, FeedMessage(
│        agent="architect", action="plan_created",
│        message=f"Plan: {plan.action_type} — {plan.description}",
│    ))
│
└─── return
```

### 3.4 Step E-J: Coder Agent

```
on_evolution_plan(event: EvolutionPlan)
│
├─── Step E: READ PLAN + SANDBOX API ──────────────────────────────────
│
│    plan = await redis.hgetall(f"evo:plan:{event.plan_id}")
│    existing_code = load_existing_trait(event.target_class)  # if modify_trait
│
├─── Step F: BUILD CODE-GEN PROMPT ────────────────────────────────────
│
│    system_prompt = """
│    You are a Python developer in the AI-Genesis system.
│    Write a class that inherits from Trait.
│    The class MUST have: async def execute(self, entity) -> None
│
│    Available on entity:
│      entity.x: float, entity.y: float       — position
│      entity.energy: float                    — current energy (0 = death)
│      entity.max_energy: float                — max energy
│      entity.age: int                         — ticks alive
│      entity.traits: list[Trait]              — active traits
│      entity.nearby_entities: list[Entity]    — neighbors (radius 50)
│      entity.nearby_resources: list[Resource] — resources in range
│      entity.move(dx, dy) -> None             — move by delta
│      entity.consume_resource(r) -> float     — eat resource, returns energy gained
│
│    Allowed imports: math, random, dataclasses, typing, enum,
│                     collections, functools, itertools.
│    FORBIDDEN: os, sys, subprocess, socket, eval, exec, open, print.
│    Output ONLY the Python code. No explanations.
│    """
│
│    user_prompt = f"""
│    Task: {event.description}
│    Trait name: {event.target_class}
│    Behavior: {event.target_method}
│
│    Write the complete Python class.
│    """
│
├─── Step G: CALL OLLAMA ──────────────────────────────────────────────
│
│    response = await ollama_generate(system_prompt, user_prompt)
│    raw_code = response  # Raw LLM output
│
│    if not raw_code:
│        log("Coder returned empty response. Aborting.")
│        return
│
├─── Step H: EXTRACT PYTHON CODE ──────────────────────────────────────
│
│    # LLM might wrap code in ```python ... ``` blocks
│    source_code = extract_code_block(raw_code)
│
│    # Prepend required import if missing
│    if "from core.traits import Trait" not in source_code:
│        source_code = "from core.traits import Trait\n\n" + source_code
│
├─── Step I: PRE-VALIDATE ─────────────────────────────────────────────
│
│    result = code_validator.validate(source_code)
│
│    if not result.is_valid:
│        log(f"Validation failed: {result.error}")
│        await bus.publish(Channels.FEED, FeedMessage(
│            agent="coder", action="validation_failed",
│            message=f"Generated code rejected: {result.error}",
│        ))
│
│        # RETRY ONCE with error feedback
│        retry_prompt = f"""
│        Previous code was rejected: {result.error}
│        Fix the issue and regenerate. Rules remain the same.
│        """
│        response = await ollama_generate(system_prompt, retry_prompt)
│        source_code = extract_code_block(response)
│        result = code_validator.validate(source_code)
│
│        if not result.is_valid:
│            log(f"Retry also failed: {result.error}. Giving up.")
│            await persist_failed_mutation(event, source_code, result.error)
│            return
│
├─── Step J: SAVE TO MUTATIONS/ ───────────────────────────────────────
│
│    trait_name = to_snake_case(result.trait_class_name)
│    version = await get_next_version(trait_name)     # Check existing files
│    file_name = f"trait_{trait_name}_v{version}.py"
│    file_path = MUTATIONS_DIR / file_name
│
│    code_hash = hashlib.sha256(source_code.encode()).hexdigest()
│
│    # Deduplication check
│    existing_hash = await redis.hget(f"evo:mutation:hashes", code_hash)
│    if existing_hash:
│        log(f"Duplicate code detected (hash: {code_hash[:8]}). Skipping.")
│        return
│
│    # Write file (async to_thread because filesystem I/O)
│    await asyncio.to_thread(file_path.write_text, source_code, "utf-8")
│
│    # Record mutation metadata
│    mutation_id = generate_uuid()
│    await redis.hset(f"evo:mutation:{mutation_id}", mapping={
│        "status": "validated",
│        "file_path": str(file_path),
│        "trait_name": trait_name,
│        "version": version,
│        "code_hash": code_hash,
│        "plan_id": event.plan_id,
│    })
│    await redis.hset("evo:mutation:hashes", code_hash, mutation_id)
│
│    # Signal Patcher
│    await bus.publish(Channels.MUTATION_READY, MutationReady(
│        mutation_id = mutation_id,
│        plan_id     = event.plan_id,
│        file_path   = str(file_path),
│        trait_name  = trait_name,
│        version     = version,
│        code_hash   = code_hash,
│    ))
│
│    await bus.publish(Channels.FEED, FeedMessage(
│        agent="coder", action="code_generated",
│        message=f"Trait '{trait_name}' v{version} written to {file_name}. "
│                f"Sending to Patcher for loading.",
│    ))
│
└─── return
```

### 3.5 Step K-N: Runtime Patcher (Hot-Reload)

```
on_mutation_ready(event: MutationReady)
│
├─── Step K: RE-VALIDATE (defense in depth) ───────────────────────────
│
│    source = await asyncio.to_thread(
│        Path(event.file_path).read_text, "utf-8"
│    )
│    result = code_validator.validate(source)
│
│    if not result.is_valid:
│        await publish_failure(event, result.error, stage="validation")
│        return
│
├─── Step L: IMPORTLIB LOAD ───────────────────────────────────────────
│
│    ┌──────────────────────────────────────────────────────────────┐
│    │  This is the ONLY place in the codebase where dynamic       │
│    │  module loading happens. It executes LLM-generated code.    │
│    │                                                              │
│    │  Safety net:                                                 │
│    │  - Code already passed AST validation (twice)               │
│    │  - No forbidden imports or calls                            │
│    │  - Trait timeout (50ms) catches runtime issues later        │
│    └──────────────────────────────────────────────────────────────┘
│
│    module_name = f"mutations.{Path(event.file_path).stem}"
│
│    try:
│        spec = importlib.util.spec_from_file_location(
│            module_name, event.file_path
│        )
│        if spec is None or spec.loader is None:
│            raise ImportError(f"Cannot create spec for {event.file_path}")
│
│        module = importlib.util.module_from_spec(spec)
│
│        # exec_module runs the module code — this is where
│        # LLM-generated code actually executes for the first time
│        spec.loader.exec_module(module)
│
│    except Exception as e:
│        await publish_failure(event, str(e), stage="import")
│        return
│
│    # Extract Trait class from loaded module
│    trait_class = getattr(module, result.trait_class_name, None)
│    if trait_class is None:
│        await publish_failure(
│            event, f"Class {result.trait_class_name} not found", stage="import"
│        )
│        return
│
├─── Step M: REGISTER IN DYNAMIC REGISTRY ─────────────────────────────
│
│    ┌──────────────────────────────────────────────────────────────┐
│    │  This operation is ATOMIC from Core's perspective.           │
│    │  Core reads registry only at entity birth time.             │
│    │  Existing entities keep their current Traits.               │
│    │  Only newly born Molbots will receive the new Trait.        │
│    └──────────────────────────────────────────────────────────────┘
│
│    # Update in-memory registry (thread-safe dict replacement)
│    loaded_modules[event.trait_name] = trait_class
│
│    # Update Redis registry (source of truth for persistence)
│    async with redis.pipeline() as pipe:
│        pipe.hset("meta:registry:traits", event.trait_name, event.file_path)
│        pipe.incr("meta:registry:version")
│        new_version = await pipe.execute()
│
│    registry_version = new_version[-1]  # Result of INCR
│
├─── Step N: PERSIST TO POSTGRESQL ────────────────────────────────────
│
│    await pg_pool.execute("""
│        INSERT INTO mutations (id, cycle_id, trait_name, version,
│                               file_path, source_code, code_hash, status,
│                               applied_at)
│        VALUES ($1, $2, $3, $4, $5, $6, $7, 'applied', now())
│    """, event.mutation_id, plan.cycle_id, event.trait_name,
│       event.version, event.file_path, source, event.code_hash)
│
├─── Step PUBLISH SUCCESS ─────────────────────────────────────────────
│
│    await bus.publish(Channels.MUTATION_APPLIED, MutationApplied(
│        mutation_id      = event.mutation_id,
│        trait_name       = event.trait_name,
│        version          = event.version,
│        registry_version = registry_version,
│    ))
│
│    await bus.publish(Channels.FEED, FeedMessage(
│        agent="patcher", action="mutation_applied",
│        message=f"Trait '{event.trait_name}' v{event.version} is LIVE. "
│                f"Registry v{registry_version}. "
│                f"New Molbots will inherit this Trait.",
│    ))
│
└─── return
```

### 3.6 Step O-P: Core Engine Applies Trait

```
Core Engine (engine.py) — runs independently, never paused
│
│  Subscribed to: ch:mutation:applied
│
╔══ ON EVENT: ch:mutation:applied ═════════════════════════════════════╗
║                                                                      ║
║  Step O: UPDATE IN-MEMORY REGISTRY ──────────────────────────────    ║
║                                                                      ║
║    This handler runs as an asyncio.Task inside the event loop,       ║
║    scheduled by the EventBus. It does NOT interrupt the tick loop.   ║
║                                                                      ║
║    trait_name = event["trait_name"]                                   ║
║    trait_class = patcher.get_trait_class(trait_name)                  ║
║                                                                      ║
║    dynamic_registry.register(trait_name, trait_class)                 ║
║    log(f"Registry updated: {trait_name} now available for new births")║
║                                                                      ║
║                                                                      ║
║  Step P: NEW MOLBOTS GET THE TRAIT ──────────────────────────────    ║
║                                                                      ║
║    This happens organically during the tick loop, NOT in this        ║
║    handler. When a new Molbot is born:                               ║
║                                                                      ║
║    def spawn(parent: Entity | None) -> Entity:                       ║
║        baby = Entity(dna=mutate_dna(parent.dna) if parent else ...)  ║
║                                                                      ║
║        # RACE CONDITION PROTECTION:                                  ║
║        # Use snapshot to avoid inconsistent registry state           ║
║        # if Patcher updates registry mid-spawn.                      ║
║        available = dynamic_registry.get_snapshot()  # Atomic copy    ║
║                                                                      ║
║        baby.traits = select_traits(                                  ║
║            available = available,                                    ║
║            dna       = baby.dna,      # DNA determines probability   ║
║            max_traits = 5,            # Max traits per entity        ║
║        )                                                             ║
║                                                                      ║
║        return baby                                                   ║
║                                                                      ║
║    Existing Molbots are NOT retroactively changed.                   ║
║    Evolution spreads through new births, just like biology.          ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

### 3.7 Failure & Rollback Flow

```
Any step fails
│
├─ IF failure in Step C or G (LLM unavailable):
│   └─ Log error → Feed message → return
│      World continues with existing Traits. No rollback needed.
│
├─ IF failure in Step D or H (LLM response unparseable):
│   └─ Log error → Feed message → return
│      No code was generated. No rollback needed.
│
├─ IF failure in Step I (pre-validation):
│   └─ Retry ONCE with error feedback → if retry fails → return
│      Bad code never reaches mutations/. No rollback needed.
│
├─ IF failure in Step K (re-validation):
│   └─ Publish MutationFailed → delete file from mutations/ → return
│      File existed briefly but was never loaded.
│
├─ IF failure in Step L (importlib):
│   ├─ Publish MutationFailed with error details
│   ├─ Attempt rollback:
│   │   ├─ Find previous version: trait_{name}_v{N-1}.py
│   │   ├─ If exists: reload previous version, update registry
│   │   └─ If not: remove trait from registry entirely
│   └─ Feed message: "Mutation failed, rolled back to v{N-1}"
│
└─ IF failure in Step M (Redis write):
    └─ In-memory state may be ahead of Redis.
       On next startup, Core rebuilds registry from mutations/ dir.
       Feed message: "Registry sync issue, will self-heal."
```

### 3.8 Timing Summary

| Phase | Agent | Duration | Blocking? |
|-------|-------|----------|-----------|
| A-D | Architect | 4-10 sec (mostly LLM latency) | No — async HTTP |
| E-J | Coder | 4-10 sec (mostly LLM latency) | No — async HTTP |
| K | Patcher validate | < 5ms | No — `to_thread` |
| L | Patcher import | < 10ms | Brief GIL lock, but < 1 tick |
| M | Registry update | < 2ms | Redis pipeline |
| N | Postgres write | < 5ms | Async |
| O-P | Core applies | 0ms (next birth picks it up) | No |
| **Total** | **All** | **~10-25 sec** | **Core never blocked** |

The World Loop processes ~600-1500 ticks while one evolution cycle runs in the background.

---

## 4. Concurrency Guarantees

### 4.1 Why Core Never Blocks

```
asyncio.gather(
    engine.run(),          ← Tick loop: sleeps between ticks, yields to event loop
    watcher.run(),         ← Waits for Pub/Sub messages (non-blocking)
    architect.run(),       ← Waits for Pub/Sub, then async HTTP to Ollama
    coder.run(),           ← Waits for Pub/Sub, then async HTTP to Ollama
    patcher.run(),         ← Waits for Pub/Sub, then importlib (< 10ms)
    bus.listen(),          ← Async iterator over Redis Pub/Sub
    run_uvicorn(api),      ← FastAPI on its own async handlers
)
```

All components use `await` at their I/O boundaries. The `asyncio` event loop
multiplexes them on a single thread. During the ~8 seconds while Ollama "thinks",
the engine runs ~500 ticks. They never compete for the same lock.

### 4.2 The Only Shared Mutable State

| State | Written by | Read by | Protection |
|-------|-----------|---------|------------|
| `DynamicRegistry` (in-memory dict) | Patcher | Core (at birth) | `get_snapshot()` method returns atomic copy |
| `entity_manager` entities | Core tick loop | WebSocket handler (read-only snapshot) | Copy-on-read for WS frames |
| Redis keys | Multiple writers | Multiple readers | Redis is single-threaded, atomic per command |

**Race Condition Protection:**

DynamicRegistry implements `get_snapshot()` to avoid inconsistent reads during updates:

```python
class DynamicRegistry:
    def __init__(self):
        self._traits: dict[str, type[Trait]] = {}

    def register(self, name: str, trait_class: type[Trait]) -> None:
        # Thread-safe: create new dict instead of mutating
        new_traits = self._traits.copy()
        new_traits[name] = trait_class
        self._traits = new_traits  # Atomic replacement (GIL)

    def get_snapshot(self) -> dict[str, type[Trait]]:
        # Return immutable copy to prevent mid-spawn registry changes
        return self._traits.copy()
```

This ensures `spawn()` works with a consistent view even if Patcher updates registry mid-execution.

No explicit locks are needed in MVP because:
- DynamicRegistry uses atomic dict replacement + snapshot pattern.
- Redis serializes all commands.
- Entity list is only mutated by the tick loop coroutine.

---

*Document Version: 1.0*
*References: tech_stack.md (sections 5, 6), PRD.md (user stories US-1 through US-6)*
*Next Document: task_list.md*
