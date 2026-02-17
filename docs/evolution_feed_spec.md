## Спецификация: улучшение Evolution Feed

### 1. Цели

- **Больше ясности**: пользователь должен понимать, что именно происходит в мире и в цикле эволюции.
- **Режим разработчика**: возможность увидеть технические детали — причину триггера, план Архитектора, код мутации.
- **Без изменения архитектуры**: использовать уже существующие события и API, расширяя `FeedMessage.metadata` и UI.

---

### 2. Данные и протокол

#### 2.1. Модель `FeedMessage` (backend)

Базовая структура (уже есть, фиксируем как контракт):

```python
@dataclass
class FeedMessage:
    agent: str              # 'watcher' | 'architect' | 'coder' | 'patcher' | 'system'
    action: str             # машинный тег: 'anomaly_detected', 'plan_created', ...
    message: str            # короткое человекочитаемое описание
    metadata: dict[str, object] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
```

#### 2.1.1. Форматы сообщения: wire vs store

Существует два разных представления одного и того же события — важно их не путать.

**Wire-формат (JSON по WebSocket, `ws://…/api/ws/feed`)**

Именно это приходит браузеру «как есть» из `feed_ws_manager.broadcast_json(...)`:

```json
{
  "agent": "coder",
  "action": "mutation_ready",
  "message": "Сгенерирован код для мутации energy_scavenger v2",
  "metadata": { "cycle_id": "evo_abc123", "mutation": { "mutation_id": "mut_01ab23cd", "trait_name": "energy_scavenger", "version": 2 } },
  "timestamp": 1718000000.123
}
```

Поля:
- `agent`, `action`, `message`, `metadata` — напрямую из `FeedMessage` на стороне Python.
- `timestamp` — Unix-время в секундах (`float`).
- Поля `type` нет — это просто JSON-объект.

**Нормализованный формат (Zustand store, `FeedMessage` в `types/feed.ts`)**

Браузер дополняет wire-пакет перед помещением в стор:

```ts
{
  id: 42,                      // авто-инкремент, генерируется хуком useFeedStream
  agent: "coder",
  action: "mutation_ready",
  message: "Сгенерирован код для мутации energy_scavenger v2",
  metadata: { ... },           // прокидывается без изменений
  timestamp: 1718000000.123    // number (секунды), не строка
}
```

Добавляется:
- `id: number` — уникальный порядковый номер в рамках сессии (для React-ключей и идентификации выбранного сообщения).

Убирается / отличается:
- Нет поля `type: "feed_message"` — оно не нужно, т.к. тип сообщения уже определён самим WebSocket-эндпоинтом.
- `timestamp` остаётся `number` (не конвертируется в `string`).

---

#### 2.2. Стандартизированное `metadata` по агентам

> **Примечание**: примеры ниже записаны в псевдо-JSON (JSONC-нотация).
> Конструкции вида `"field": "A" | "B"` обозначают допустимые значения (union type),
> а `// комментарий` — пояснения к полю. Это не валидный JSON и не предназначено
> для машинного разбора — только для документирования схемы.

**Общие поля (по возможности для всех):**

- `cycle_id: str` — идентификатор цикла эволюции, один и тот же для всех сообщений этого цикла.
- `metadata_schema_version: number` — версия схемы `metadata` (всегда `1` в текущей реализации). Добавляется опционально; позволит безболезненно мигрировать структуру в будущем без breaking change для старых клиентов.

**Watcher (`agent='watcher'`):**

```jsonc
{
  "cycle_id": "evo_cycle_042",
  "metadata_schema_version": 1,
  "trigger": {
    "problem_type": "starvation" | "overpopulation" | "low_diversity",
    "severity": "low" | "medium" | "high" | "critical"
  },
  "snapshot": {
    "tick": 90300,
    "entity_count": 142,
    "avg_energy": 22.1,
    "dominant_trait": "energy_absorb_v1"
  },
  "stats_diff": {
    "entity_count_before": 237,
    "entity_count_now": 142,
    "avg_energy_before": 54.2,
    "avg_energy_now": 22.1
  }
}
```

**Architect (`agent='architect'`):**

```jsonc
{
  "cycle_id": "evo_cycle_042",
  "metadata_schema_version": 1,
  "trigger": {
    "problem_type": "starvation",
    "severity": "high",
    "snapshot_tick": 90300
  },
  "plan": {
    "change_type": "new_trait" | "modify_trait" | "adjust_params",
    "target_class": "Trait" | "WorldPhysics" | "Environment" | "EntityLogic",
    "target_method": "execute" | "apply" | "calculate_movement" | null,
    "description": "Molbots should move toward nearest resource within 50px...",
    "expected_outcome": "Increase avg_energy and reduce starvation deaths",
    "constraints": [
      "No loops > 100 iterations",
      "Trait MUST be non-blocking (<5ms)"
    ]
  }
}
```

**Coder (`agent='coder'`):**

```jsonc
{
  "cycle_id": "evo_cycle_042",
  "metadata_schema_version": 1,
  "mutation": {
    "mutation_id": "mut_01ab23cd",
    "trait_name": "energy_scavenger",
    "version": 2,
    "file_path": "mutations/trait_energy_scavenger_v2.py"
  },
  "code": {
    "snippet": "class EnergyScavenger(Trait):\n    async def execute(self, entity):\n        ...",  // первые 15–20 строк
    "validation_errors": null  // или строка с сообщением, если не прошло
  }
}
```

**Patcher (`agent='patcher'`):**

```jsonc
{
  "cycle_id": "evo_cycle_042",
  "metadata_schema_version": 1,
  "mutation": {
    "mutation_id": "mut_01ab23cd",
    "trait_name": "energy_scavenger",
    "version": 2
  },
  "registry": {
    "registry_version": 14,
    "rollback_to": null  // или "mut_prev_id" при откате
  },
  "error": null  // строка при неуспехе
}
```

---

### 3. Требования к backend

- **WatcherAgent**
  - При публикации аномалии в `ch:feed` заполнять:
    - `metadata.cycle_id` (если цикл уже создан) или `null`.
    - `metadata.trigger`, `metadata.snapshot`, `metadata.stats_diff`.
- **ArchitectAgent**
  - Для каждого `EvolutionPlan` публиковать в `ch:feed` один подробный `FeedMessage` c `metadata.plan` и `metadata.trigger`.
- **CoderAgent**
  - При успешной генерации кода:
    - заполнять `metadata.mutation`, `metadata.code.snippet`.
  - При валидационной ошибке:
    - заполнять `metadata.code.validation_errors`.
- **RuntimePatcher**
  - При успехе:
    - `metadata.mutation`, `metadata.registry.registry_version`.
  - При неуспехе:
    - дополнительно `metadata.error`, `metadata.registry.rollback_to`.
- **Формат не ломать**:
  - Существующие клиенты, которые игнорируют `metadata`, продолжают работать.
  - Все новые поля добавляются только в `metadata`.

---

### 4. Требования к frontend

#### 4.1. Типы

В `types/feed.ts`:

- Обновить `FeedMessage.metadata` до структурированного типа:

```ts
export interface FeedTriggerMeta {
  problem_type: "starvation" | "overpopulation" | "low_diversity";
  severity: "low" | "medium" | "high" | "critical";
  snapshot_tick?: number;
  entity_count?: number;
  avg_energy?: number;
  dominant_trait?: string;
}

export interface FeedPlanMeta {
  change_type: "new_trait" | "modify_trait" | "adjust_params";
  target_class: string | null;
  target_method: string | null;
  description: string;
  expected_outcome?: string;
  constraints?: readonly string[];
}

export interface FeedMutationMeta {
  mutation_id: string;
  trait_name: string;
  version: number;
  file_path?: string;
}

export interface FeedCodeMeta {
  snippet?: string;
  validation_errors?: string | null;
}

export interface FeedRegistryMeta {
  registry_version?: number;
  rollback_to?: string | null;
}

export interface FeedMetadata {
  cycle_id?: string;
  metadata_schema_version?: number; // всегда 1 сейчас; нужен для будущих миграций
  trigger?: FeedTriggerMeta;
  plan?: FeedPlanMeta;
  mutation?: FeedMutationMeta;
  code?: FeedCodeMeta;
  registry?: FeedRegistryMeta;
  [key: string]: unknown; // для будущего расширения
}

// --- Форматы сообщений ---

// Wire-формат: то, что приходит по WebSocket напрямую из backend
export interface FeedMessageWire {
  readonly agent: AgentType;
  readonly action: string;
  readonly message: string;
  readonly timestamp: number; // Unix seconds (float)
  readonly metadata?: FeedMetadata;
  // Поля 'type' и 'id' отсутствуют в wire-формате
}

// Нормализованный формат: хранится в Zustand store
// Добавляется id (авто-инкремент) хуком useFeedStream
export interface FeedMessage {
  readonly id: number;         // генерируется на клиенте, не приходит с сервера
  readonly agent: AgentType | string;
  readonly action: string;
  readonly message: string;
  readonly timestamp: number;  // Unix seconds (number, не string)
  readonly metadata?: FeedMetadata;
}
```

#### 4.2. Компонент `FeedEntry`

Функциональные требования:

- Отображать в карточке:
  - время, агент, `message` (как сейчас);
  - если есть `metadata.trigger` — показывать чип с `problem_type` + `severity`;
  - если есть `metadata.mutation` — показывать `trait_name v{version}`.
- По клику по карточке:
  - открывать **панель подробностей** (см. 4.3).

#### 4.3. Компонент `DeveloperPanel` / `FeedDetailsDrawer`

- Тип: боковая панель (drawer) или модальное окно справа от Evolution Feed.
- Вход: `FeedMessage | null`.
- Содержимое:
  - **Summary**:
    - если есть `metadata.trigger` — список ключевых метрик (`entity_count`, `avg_energy`, severity).
    - если есть `metadata.plan` — форматированный блок:
      - заголовок: `change_type` + `target_class`/`target_method`;
      - описание + ожидания + список ограничений.
  - **Code** (если есть `metadata.code` или `metadata.mutation`):
    - показать `snippet` (если есть) в `pre` блоке;
    - кнопка **"View full code"**:
      - дергает `GET /api/mutations/{mutation_id}/source`;
      - отображает код в readonly viewer'е (подсветка, моно‑шрифт).
  - **Cycle timeline (опционально)**:
    - если у нескольких сообщений один `cycle_id`, можно отображать мини‑цепочку стадий WATCHER → ARCHITECT → CODER → PATCHER.

---

### 5. UI/UX‑требования

- **Основной Evolution Feed** остаётся лёгким:
  - короткие сообщения, цветовая кодировка по агентам как в `frontend_blueprint.md`.
- **Режим разработчика** явно отделён:
  - детали не перегружают основную ленту;
  - открывается по явному действию (клик/иконка "Details").
- **Код**:
  - отображается моно‑шрифтом;
  - максимум ~100–150 строк в viewer'е (остальное со скроллом).
- **Группировка по циклам**:
  - визуальный разделитель между различными `cycle_id` (тонкая линия с подписью `Cycle #42`).

---

### 6. Нефункциональные требования

- **Обратная совместимость**:
  - фронтенд обязан корректно работать, если `metadata` частично или полностью отсутствует.
  - при появлении `metadata_schema_version > 1` клиент должен gracefully игнорировать незнакомые поля (index signature `[key: string]: unknown` гарантирует это на уровне типов).
- **Производительность**:
  - размер `metadata` должен оставаться небольшим:
    - `code.snippet` ≤ 20 строк;
    - полный код запрашивается только по требованию (через REST).
- **Типобезопасность**:
  - ни в Python, ни в TypeScript не использовать `Any` / `any` (соответствие `.cursorrules`).
- **Локализация**:
  - текст в `message` остаётся на русском, поля в `metadata` — на английском (как контракт между сервисами).
