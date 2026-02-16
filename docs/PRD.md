# AI-Genesis — Product Requirements Document (PRD)

## 1. Overview

**Product Name:** AI-Genesis
**Version:** 0.1.0 (MVP)
**Author:** Human + AI Collaborative Design
**Status:** Pre-Development

### 1.1 One-Liner

Автономная серверная песочница, в которой цифровые сущности (Molbots) эволюционируют через самомодификацию кода под управлением локальной LLM — без участия человека.

### 1.2 Problem Statement

Существующие симуляции жизни (Conway's Game of Life, Tierra, Lenia) ограничены жёстко заданными правилами. Они не могут:
- Порождать **качественно новое** поведение (только комбинации заданного).
- Модифицировать собственную логику для адаптации к возникающим условиям.
- Использовать языковые модели как «двигатель эволюции», способный генерировать программный код.

AI-Genesis решает эту проблему: мир **переписывает собственный исходный код** в рантайме через цепочку LLM-агентов, порождая поведение, которое не было заложено разработчиком.

### 1.3 Vision

Цифровой аквариум, работающий 24/7, где «природой» управляет LLM. Код — это ДНК мира. Мутации кода — это эволюция. Пользователь наблюдает через браузер, как кругленькие Molbot'ы рождаются, объединяются в группы, вырабатывают новые способности и вымирают — а LLM-агент в реальном времени комментирует свои решения в Evolution Feed.

---

## 2. Goals & Success Metrics

### 2.1 Project Goals

| # | Цель | Приоритет |
|---|------|-----------|
| G1 | Создать стабильное ядро симуляции, работающее непрерывно без сбоев | Critical |
| G2 | Реализовать полный цикл самомодификации: наблюдение → анализ → генерация кода → hot-reload | Critical |
| G3 | Обеспечить безопасное исполнение LLM-генерируемого кода (sandbox) | Critical |
| G4 | Визуализировать мир в реальном времени через WebSocket-стрим | High |
| G5 | Достичь полной автономности: система работает 24/7 без вмешательства человека | High |
| G6 | Предоставить пользователю «окно» для наблюдения и ограниченного вмешательства | Medium |

### 2.2 Success Metrics (MVP)

| Метрика | Целевое значение | Как измеряем |
|---------|------------------|--------------|
| **Uptime ядра** | >99% за 24 часа непрерывной работы | Heartbeat-логи, отсутствие crash-рестартов |
| **Успешных мутаций** | >=70% сгенерированного кода проходит валидацию и загружается | Счётчик в Watcher: `mutations_applied / mutations_generated` |
| **Время цикла эволюции** | < 5 минут от обнаружения проблемы до внедрения патча | Таймстемпы в event log |
| **Разнообразие Trait'ов** | >=10 уникальных Trait-классов, сгенерированных LLM за 24 часа | Кол-во файлов в `mutations/` |
| **Latency WebSocket** | < 100ms от тика сервера до кадра на фронтенде | Замер round-trip через ping-pong |
| **Популяция** | Стабильная популяция 50-500 Molbot'ов без вымирания или бесконтрольного роста | Метрика `entity_count` в Redis |

---

## 3. User Stories (System ↔ AI-Agent)

В AI-Genesis основной «пользователь» — это не человек, а связка внутренних AI-агентов. User Stories описывают взаимодействие между подсистемами.

### 3.1 Core ↔ Watcher Agent

> **US-1:** Как **Simulation Core**, я генерирую телеметрию (рождения, смерти, столкновения, уровни энергии) каждые N тиков, чтобы **Watcher Agent** мог обнаружить аномалии и дисбалансы в экосистеме.
>
> **Acceptance Criteria:**
> - Core пишет snapshot состояния мира в Redis каждые 300 тиков (~10 секунд).
> - Snapshot содержит: `entity_count`, `avg_energy`, `death_causes{}`, `resource_density`, `trait_usage_stats{}`.
> - Watcher читает snapshot и формирует `WorldReport` в формате JSON.

> **US-2:** Как **Watcher Agent**, я анализирую накопленную статистику и формирую краткий диагностический отчёт, чтобы **Architect Agent** получил контекст для принятия эволюционных решений.
>
> **Acceptance Criteria:**
> - Watcher сравнивает текущий snapshot с предыдущими 5-ю.
> - Если обнаружена аномалия (вымирание >30%, перенаселение >200% от нормы), Watcher генерирует `EvolutionTrigger`.
> - **Watcher оценивает успешность конкретных Trait'ов**: выживаемость Molbot'ов с данным Trait'ом vs без него, корреляция Trait'а с причинами смерти.
> - Отчёт содержит: `problem_type`, `severity`, `affected_entities[]`, `suggested_area`, `trait_performance{trait_name: {survival_rate, avg_lifespan}}`.

### 3.2 Watcher ↔ Architect Agent

> **US-3:** Как **Architect Agent**, я получаю `WorldReport` от Watcher и проектирую высокоуровневое решение (без кода), чтобы **Coder Agent** мог реализовать конкретный патч.
>
> **Acceptance Criteria:**
> - Architect получает report + текущую схему доступных классов (Sandbox API).
> - Architect возвращает `EvolutionPlan` в структурированном формате JSON:
>   ```json
>   {
>     "change_type": "new_trait" | "modify_trait" | "adjust_params",
>     "target": "TraitClassName или EntityLogic.method_name",
>     "description": "Описание логики на естественном языке",
>     "expected_outcome": "Ожидаемое изменение поведения",
>     "constraints": ["не использовать циклы >100 итераций", ...]
>   }
>   ```
> - Architect **не генерирует код** — только спецификацию.

### 3.3 Architect ↔ Coder Agent

> **US-4:** Как **Coder Agent**, я получаю `EvolutionPlan` от Architect и генерирую валидный Python-модуль, чтобы **Runtime Patcher** мог загрузить его в ядро без остановки симуляции.
>
> **Acceptance Criteria:**
> - Coder генерирует `.py` файл, содержащий класс-наследник `Trait` с методом `async execute(self, entity)`.
> - Код проходит `ast.parse()` без ошибок.
> - Код не использует запрещённые модули (`os`, `sys`, `subprocess`, `socket`, `shutil`).
> - Файл сохраняется в `mutations/` с версионным именем: `trait_{name}_v{N}.py`.

### 3.4 Coder ↔ Runtime Patcher

> **US-5:** Как **Runtime Patcher**, я обнаруживаю новый файл в `mutations/`, валидирую его и регистрирую в Dynamic Registry ядра, чтобы **новые сущности** при рождении могли получить этот Trait.
>
> **Acceptance Criteria:**
> - Patcher использует `watchdog` или polling для обнаружения новых файлов.
> - Перед загрузкой: проверка через `ast.parse()` + whitelist импортов.
> - Загрузка через `importlib.import_module()` → регистрация класса в `DynamicRegistry`.
> - При ошибке загрузки: откат, логирование, уведомление Watcher'а.
> - Старые версии Trait'ов сохраняются для возможности rollback.

### 3.5 Core ↔ Entities (Molbots)

> **US-6:** Как **Molbot (BaseEntity)**, я на каждом тике вызываю все свои Trait'ы из списка `self.traits`, чтобы моё поведение определялось динамически загруженным кодом, а не хардкодом.
>
> **Acceptance Criteria:**
> - Метод `update()` итерирует `self.traits` и вызывает `trait.execute(self)`.
> - Если Trait выбрасывает исключение — оно перехватывается, Trait деактивируется, Molbot продолжает жить.
> - Новорождённые Molbot'ы получают Trait'ы из текущего состояния `DynamicRegistry`.

### 3.6 System ↔ Human Observer

> **US-7:** Как **наблюдатель (человек)**, я открываю браузер и вижу живую карту мира с Molbot'ами, график популяции и Evolution Feed — лог решений AI-агентов, чтобы понимать, как и почему мир меняется.
>
> **Acceptance Criteria:**
> - WebSocket-стрим передаёт позиции, состояния и типы всех сущностей.
> - Evolution Feed отображает последние 50 записей в формате: `[timestamp] Agent: "решение"`.
> - UI обновляется с частотой >= 30 FPS при популяции до 500 сущностей.

> **US-8:** Как **наблюдатель**, я могу вмешаться: изменить параметры среды (температура, количество ресурсов) или принудительно вызвать цикл эволюции, чтобы ускорить или направить развитие мира.
>
> **Acceptance Criteria:**
> - REST API endpoint `POST /api/world/params` принимает JSON с параметрами среды.
> - Кнопка "Force Evolution" отправляет `POST /api/evolution/trigger`.
> - Изменения применяются в течение следующего тика (< 16ms задержки).

---

## 4. Key Features

### 4.1 Autonomy 24/7

Система спроектирована для непрерывной работы без оператора.

**Механизмы обеспечения:**
- **Async Event Loop** (`asyncio`) — ядро никогда не блокируется ожиданием LLM. Агенты работают в отдельных корутинах/процессах.
- **Graceful Degradation** — если Ollama недоступен, ядро продолжает работу с текущим набором Trait'ов. Эволюция ставится на паузу, симуляция — нет.
- **Auto-Recovery** — при crash мутации не теряются (персистенция в файловой системе + Redis). После рестарта Core подхватывает последнее состояние.
- **Resource Limits** — Docker-контейнеры с лимитами CPU/RAM. LLM изолирован от Core.

### 4.2 Self-Modifying Code

Центральная фича проекта — код приложения изменяется в рантайме.

**Пайплайн самомодификации:**

```
Telemetry → Watcher (анализ) → Architect (план) → Coder (код) → Validator (проверка) → Runtime Patcher (загрузка) → Core (применение)
```

**Зоны модификации (Sandbox API):**

| Зона | Что можно менять | Что нельзя менять |
|------|-----------------|-------------------|
| `Trait` классы | Логика `execute()`, новые Trait'ы | Сигнатуру `execute(self, entity)` |
| `EntityLogic` | `calculate_movement()`, `on_collision()`, `consume_energy()` | Сигнатуры функций, имена параметров |
| `WorldPhysics` | Числовые параметры: `gravity`, `friction`, `resource_spawn_rate` | Структуру World Loop |
| `Environment` | `generate_map()`, `apply_weather_effects()` | Формат возвращаемых данных |

**Безопасность:**
- **AST-валидация:** `ast.parse()` перед загрузкой.
- **Import Whitelist:** Разрешены только `math`, `random`, `dataclasses`, `typing`, `enum`, `collections`.
- **Timeout:** Выполнение Trait'а ограничено 50ms на тик через `asyncio.wait_for()`. При превышении — принудительная деактивация.
- **Loop Protection:** Coder Agent получает constraint: «избегать циклов >100 итераций». Статический анализ AST на наличие `while True` без `break`.
- **Rollback:** Каждая версия Trait'а хранится в `mutations/`. Хранятся только последние 3 версии для экономии памяти. При ошибке — откат к предыдущей версии.

### 4.3 Molbot Visualization

Сущности визуализируются как Molbot'ы — кругленькие существа с ушками, вдохновлённые стилем Molbot.

**Визуальные характеристики:**
- **Базовая форма:** Круглое тело + два «ушка» сверху.
- **Цвет тела:** Определяется набором Trait'ов (теплозащита — оранжевый, хищник — красный, симбионт — зелёный).
- **Размер:** Пропорционален `energy` сущности.
- **Анимация:** Плавное перемещение, пульсация при потреблении энергии, мерцание при мутации.
- **Связи:** Линии между Molbot'ами в одной группе/колонии.

**UI-компоненты:**
- **World Canvas** — основная область отрисовки (PixiJS), вид сверху на мир.
- **Population Graph** — линейный график популяции за последний час.
- **Evolution Feed** — текстовый лог решений AI-агентов в реальном времени.
- **World Controls** — панель параметров среды (температура, ресурсы, скорость).
- **Entity Inspector** — клик по Molbot'у показывает его DNA, Trait'ы, энергию, возраст.

**WebSocket-оптимизация:**
- Для популяций >200 Molbot'ов используется **Binary Array Protocol**: `[x1, y1, type1, energy1, x2, y2, type2, energy2, ...]` вместо JSON.
- При меньших популяциях — стандартный JSON для читаемости при отладке.
- Переключение автоматическое на основе `entity_count`.

---

## 5. Scope & Boundaries

### 5.1 In Scope (MVP)

- Ядро симуляции с async world loop.
- 3 роли AI-агентов: Watcher, Architect, Coder.
- Hot-reload через `importlib` + `mutations/` директорию.
- Базовый жизненный цикл Molbot'ов: рождение, движение, потребление энергии, смерть.
- WebSocket-стрим состояния мира.
- React + PixiJS фронтенд с World Canvas и Evolution Feed.
- Локальная LLM через Ollama (Llama 3 8B).
- Redis для state management.

### 5.2 Out of Scope (MVP)

- Многопользовательский режим.
- Облачный деплой и масштабирование.
- Сложные социальные структуры (корпорации, государства) — перенесено на v0.2.
- 3D-визуализация (Three.js) — перенесено на v0.2.
- PostgreSQL для истории эволюции — перенесено на v0.2.
- Пользовательская авторизация.
- Мобильный интерфейс.

---

## 6. Technical Constraints

| Ограничение | Описание |
|-------------|----------|
| **LLM Latency** | Ollama + Llama 3 8B: ~2-10 секунд на генерацию Trait'а. Эволюция — не real-time, а batch (раз в 1-5 минут). |
| **Hardware** | Минимум: 16GB RAM, 8GB VRAM. Рекомендуется: 32GB RAM, 12GB+ VRAM. |
| **Sandbox Security** | LLM-генерируемый код исполняется в том же процессе (через `importlib`). Критически важна AST-валидация и whitelist. Полная изоляция (subprocess) — в v0.2. |
| **Entity Scale** | MVP поддерживает до 500 сущностей. Оптимизация (spatial hashing, ECS) — в v0.2. |
| **Single Instance** | Один экземпляр Core, один экземпляр LLM. Без горизонтального масштабирования. |

---

## 7. Tech Stack (Locked for MVP)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Language** | Python 3.11+ | Динамическая природа, `importlib`, `ast`, async/await |
| **Web Framework** | FastAPI | Async-native, WebSocket support, автодокументация API |
| **AI Runtime** | Ollama (Llama 3 8B) | Локальный, бесплатный, достаточный для генерации коротких скриптов |
| **State Store** | Redis | In-memory скорость для world state, pub/sub для event bus |
| **Frontend** | React 18 + Vite | Быстрая сборка, component-based UI |
| **Rendering** | PixiJS 7 | GPU-ускоренная 2D-отрисовка тысяч спрайтов |
| **Hot-Reload** | `importlib` + `watchdog` | Нативный Python, без внешних зависимостей для перезагрузки |
| **Containerization** | Docker + docker-compose | Изоляция Core и Ollama, лимиты ресурсов |

---

## 8. Risks & Mitigations

| Риск | Вероятность | Импакт | Митигация |
|------|------------|--------|-----------|
| **Memory leaks при Hot-Reload** | Высокая | Critical | **Garbage Collection Strategy**: принудительная очистка ссылок на старые классы при замене Trait'а. Хранить только последние 3 версии каждого Trait'а. Периодический `gc.collect()` после каждого цикла эволюции. Мониторинг `sys.getsizeof(DynamicRegistry)`. |
| **Infinite loops в сгенерированном коде** | Средняя | High | Timeout на `trait.execute()` — 50ms через `asyncio.wait_for()`. При превышении — принудительная деактивация Trait'а. Coder Agent получает constraint: «избегать циклов >100 итераций». Fallback: если Trait зависает 3 раза подряд — удаление из Registry. |
| **Конфликт версий схем данных в Redis** | Средняя | High | Хранить в Redis только чистый JSON (data-only), без привязки к Python-классам. При загрузке данных «натягивать» их на текущие версии классов через фабрику. Версионирование схемы: `entity_schema_v1`, миграции при несовпадении. |
| LLM генерирует невалидный/опасный код | Высокая | Critical | AST-валидация, import whitelist, timeout, rollback |
| LLM «зацикливается» и генерирует одинаковые Trait'ы | Средняя | Medium | Дедупликация по хешу кода, diversity-промпт для Architect |
| Популяция вымирает полностью | Средняя | High | Auto-respawn при `entity_count < MIN_POPULATION`, Watcher-триггер |
| Популяция растёт бесконтрольно | Средняя | High | Hard cap на `MAX_ENTITIES`, естественная конкуренция за ресурсы |
| Ollama падает / зависает | Низкая | Medium | Health-check, graceful degradation (Core работает без эволюции) |

---

## 9. Glossary

| Термин | Определение |
|--------|------------|
| **Molbot** | Цифровая сущность в мире AI-Genesis. Визуально — кругленькое существо с ушками. |
| **Trait** | Динамически загружаемый Python-класс, определяющий одну способность Molbot'а. |
| **Mutation** | Файл с кодом нового Trait'а, сгенерированный Coder Agent'ом. |
| **Tick** | Один шаг симуляции (~16ms при 60 FPS). |
| **Evolution Cycle** | Полный цикл: Watcher → Architect → Coder → Patcher → Core. Занимает 1-5 минут. |
| **Dynamic Registry** | Реестр доступных Trait-классов, из которого Molbot'ы получают способности при рождении. |
| **Hot-Reload** | Загрузка нового Python-модуля в работающий процесс через `importlib`. |
| **Sandbox API** | Набор правил, определяющих, какие части кода LLM имеет право модифицировать. |
| **Evolution Feed** | UI-компонент: лог решений AI-агентов в реальном времени. |
| **World Report** | JSON-документ с телеметрией мира, генерируемый Watcher'ом для Architect'а. |

---

*Document Version: 1.0*
*Next Document: Architecture & Stack (architecture_and_stack.md)*
