# AI-Genesis — Frontend Blueprint

React 18 + Vite + PixiJS 7 + Zustand. TypeScript strict mode.
Ни одного `any`. Все пропсы — через `interface`.

---

## 1. Component Tree

```
<App>
├── <Header />                          ─ лого, тик, connection indicator
│
├── <MainLayout>                        ─ CSS Grid: canvas 70% | sidebar 30%
│   │
│   ├── <WorldCanvas />                 ─ PixiJS Stage (левая колонка)
│   │   ├── <PixiStage>                 ─ @pixi/react обёртка
│   │   │   ├── <ConnectionLines />     ─ Graphics: связи (FIRST — under entities)
│   │   │   ├── <ResourceLayer />       ─ ParticleContainer для ресурсов
│   │   │   ├── <MolbotLayer />         ─ ParticleContainer для 500+ спрайтов
│   │   │   └── <SelectionRing />       ─ Кольцо вокруг выбранного Molbot'а
│   │   │
│   │   └── <CanvasOverlay />           ─ HTML поверх Canvas (tooltip, minimap)
│   │       ├── <HoverTooltip />        ─ Имя + энергия при наведении
│   │       └── <Minimap />             ─ Уменьшенная карта мира (200x200)
│   │
│   └── <Sidebar>                       ─ правая колонка, вертикальный стек
│       ├── <EvolutionFeed />           ─ Лог решений AI-агентов
│       ├── <PopulationGraph />         ─ Линейный график популяции
│       ├── <WorldControls />           ─ Слайдеры параметров + Force Evolution
│       └── <EntityInspector />         ─ Детали выбранного Molbot'а
│
└── <ConnectionStatus />                ─ toast/banner при потере WebSocket
```

---

## 2. Directory Structure

```text
frontend/
├── src/
│   ├── App.tsx                         # Root layout
│   ├── main.tsx                        # Entry point
│   ├── index.css                       # Global styles, dark theme
│   │
│   ├── types/
│   │   ├── world.ts                    # EntityState, WorldFrame, Resource
│   │   ├── feed.ts                     # FeedMessage, AgentType
│   │   └── api.ts                      # WorldParams, SystemStats
│   │
│   ├── store/
│   │   ├── worldStore.ts              # Zustand: entities, tick, resources
│   │   ├── feedStore.ts               # Zustand: feed messages
│   │   └── uiStore.ts                 # Zustand: selectedEntityId, panelState
│   │
│   ├── hooks/
│   │   ├── useWorldStream.ts          # WebSocket → worldStore
│   │   ├── useFeedStream.ts           # WebSocket feed events → feedStore
│   │   ├── useEntitySelection.ts      # Click entity → uiStore
│   │   └── useWorldApi.ts             # REST calls: set params, trigger evolution
│   │
│   ├── canvas/
│   │   ├── WorldCanvas.tsx            # PixiJS Stage wrapper
│   │   ├── MolbotLayer.tsx            # ParticleContainer + sprite pool
│   │   ├── MolbotSprite.tsx           # Single Molbot shape (body + ears)
│   │   ├── ResourceLayer.tsx          # Resource dots
│   │   ├── ConnectionLines.tsx        # Group bonds
│   │   ├── SelectionRing.tsx          # Highlight selected entity
│   │   └── textures.ts               # Pre-generated textures atlas
│   │
│   ├── components/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   ├── EvolutionFeed.tsx
│   │   ├── FeedEntry.tsx              # Single feed message row
│   │   ├── PopulationGraph.tsx
│   │   ├── WorldControls.tsx
│   │   ├── EntityInspector.tsx
│   │   ├── EnergyBar.tsx              # Reusable energy bar
│   │   ├── TraitBadge.tsx             # Colored pill for trait name
│   │   ├── ConnectionStatus.tsx
│   │   ├── HoverTooltip.tsx
│   │   └── Minimap.tsx
│   │
│   └── utils/
│       ├── colors.ts                  # Trait → color mapping
│       ├── interpolation.ts           # Lerp for smooth entity movement
│       └── formatters.ts              # Time, numbers, truncate
│
├── public/
│   └── favicon.svg
│
├── package.json
├── tsconfig.json                      # strict: true
└── vite.config.ts                     # proxy /api and /ws to :8000
```

---

## 3. TypeScript Types

```typescript
// types/world.ts

export interface EntityState {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly energy: number;
  readonly radius: number;
  readonly color: string;          // hex: "#FF8C42"
  readonly state: "alive" | "dead";
  readonly traits: readonly string[];
}

export interface ResourceState {
  readonly x: number;
  readonly y: number;
  readonly amount: number;
}

// Binary WebSocket Frame (>=200 entities)
export interface BinaryWorldFrame {
  readonly type: "world_frame_binary";
  readonly tick: number;
  readonly entityCount: number;
  readonly resourceCount: number;
  readonly buffer: ArrayBuffer;    // Packed binary data
}

// JSON WebSocket Frame (<200 entities, debugging)
export interface WorldFrame {
  readonly type: "world_frame";
  readonly tick: number;
  readonly entities: readonly EntityState[];
  readonly resources: readonly ResourceState[];
}

export interface WorldParams {
  readonly world_width: number;
  readonly world_height: number;
  readonly gravity: number;
  readonly friction: number;
  readonly resource_spawn_rate: number;
  readonly temperature: number;
  readonly max_entities: number;
  readonly tick_rate_ms: number;
}
```

```typescript
// types/feed.ts

export const AGENT_TYPES = ["watcher", "architect", "coder", "patcher", "system"] as const;
export type AgentType = typeof AGENT_TYPES[number];

export interface FeedMessage {
  readonly type: "feed_message";
  readonly agent: AgentType;
  readonly action: string;
  readonly message: string;
  readonly timestamp: string;       // ISO 8601
  readonly metadata?: {
    readonly plan_id?: string;
    readonly mutation_id?: string;
    readonly trait_name?: string;
    readonly code_snippet?: string; // First 5 lines for Coder messages
  };
}

export type WSMessage = WorldFrame | BinaryWorldFrame | FeedMessage;
```

```typescript
// types/api.ts

export interface SystemStats {
  readonly uptime_seconds: number;
  readonly tick: number;
  readonly entity_count: number;
  readonly mutations_applied: number;
  readonly mutations_failed: number;
  readonly ollama_status: "ok" | "unavailable";
  readonly redis_status: "ok" | "unavailable";
}

export interface MutationInfo {
  readonly id: string;
  readonly trait_name: string;
  readonly version: number;
  readonly status: "pending" | "validated" | "applied" | "failed" | "rolled_back";
  readonly created_at: string;
  readonly code_hash: string;
}
```

---

## 4. State Management (Zustand)

Три изолированных store. Нет единого God-store — каждый компонент подписывается
только на нужный срез.

**КРИТИЧНО:** Разделение "горячих" (Canvas) и "холодных" (UI) данных для производительности.

```typescript
// store/worldStore.ts

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type { EntityState, ResourceState } from "../types/world";

interface WorldState {
  // ===== TRANSIENT DATA (PixiJS only, не триггерит React re-render) =====
  // Stored in WeakMap/external refs, не в Zustand state

  // ===== SLOW UI DATA (React components) =====
  readonly tick: number;
  readonly connected: boolean;
  readonly entityCount: number;

  // History for PopulationGraph (last 120 data points = ~2 min at 1/sec)
  readonly populationHistory: readonly number[];

  // Actions
  updateFrame: (tick: number, entities: EntityState[], resources: ResourceState[]) => void;
  setConnected: (connected: boolean) => void;

  // FAST CANVAS ACCESS (no React render)
  _transient: {
    entities: EntityState[];
    resources: ResourceState[];
    prevEntities: Map<string, { x: number; y: number }>;
  };
}

export const useWorldStore = create<WorldState>()(
  subscribeWithSelector((set, get) => ({
    tick: 0,
    connected: false,
    entityCount: 0,
    populationHistory: [],

    _transient: {
      entities: [],
      resources: [],
      prevEntities: new Map(),
    },

    updateFrame: (tick, entities, resources) => {
      const state = get();
      const prev = state._transient.entities;
      const prevMap = new Map(prev.map((e) => [e.id, { x: e.x, y: e.y }]));
      const history = [...state.populationHistory, entities.length].slice(-120);

      // Update transient data (Canvas reads this directly via subscribe)
      state._transient.entities = entities;
      state._transient.resources = resources;
      state._transient.prevEntities = prevMap;

      // Update UI-only data (triggers React re-render ONLY for these fields)
      set({
        tick,
        entityCount: entities.length,
        populationHistory: history,
      });
    },

    setConnected: (connected) => set({ connected }),
  }))
);

// ===== CANVAS-ONLY SUBSCRIPTIONS (No React) =====
// PixiJS components use this to avoid React render loop
export function subscribeToEntities(
  callback: (entities: EntityState[], resources: ResourceState[], prevEntities: Map<string, { x: number; y: number }>) => void
): () => void {
  return useWorldStore.subscribe(
    (state) => state._transient,
    (transient) => {
      callback(transient.entities, transient.resources, transient.prevEntities);
    }
  );
}
```

```typescript
// store/feedStore.ts

import { create } from "zustand";
import type { FeedMessage } from "../types/feed";

const MAX_FEED_MESSAGES = 200;

interface FeedState {
  readonly messages: readonly FeedMessage[];
  readonly unreadCount: number;

  addMessage: (msg: FeedMessage) => void;
  markAllRead: () => void;
}

export const useFeedStore = create<FeedState>((set, get) => ({
  messages: [],
  unreadCount: 0,

  addMessage: (msg) => {
    const updated = [msg, ...get().messages].slice(0, MAX_FEED_MESSAGES);
    set({ messages: updated, unreadCount: get().unreadCount + 1 });
  },

  markAllRead: () => set({ unreadCount: 0 }),
}));
```

```typescript
// store/uiStore.ts

import { create } from "zustand";

interface UIState {
  readonly selectedEntityId: string | null;
  readonly hoveredEntityId: string | null;
  readonly sidebarPanel: "feed" | "controls" | "inspector";
  readonly canvasScale: number;
  readonly canvasOffset: { x: number; y: number };

  selectEntity: (id: string | null) => void;
  hoverEntity: (id: string | null) => void;
  setSidebarPanel: (panel: UIState["sidebarPanel"]) => void;
  setCanvasView: (scale: number, offset: { x: number; y: number }) => void;
}

export const useUIStore = create<UIState>((set) => ({
  selectedEntityId: null,
  hoveredEntityId: null,
  sidebarPanel: "feed",
  canvasScale: 1,
  canvasOffset: { x: 0, y: 0 },

  selectEntity: (id) => set({ selectedEntityId: id, sidebarPanel: id ? "inspector" : "feed" }),
  hoverEntity: (id) => set({ hoveredEntityId: id }),
  setSidebarPanel: (panel) => set({ sidebarPanel: panel }),
  setCanvasView: (scale, offset) => set({ canvasScale: scale, canvasOffset: offset }),
}));
```

---

## 5. WebSocket Data Pipeline

### 5.1 Connection Hook (Binary Protocol)

**🔴 КРИТИЧНО:** WebSocket должен использовать Binary ArrayBuffer для entity positions (>=200 entities).

```typescript
// hooks/useWorldStream.ts

import { useEffect, useRef } from "react";
import { useWorldStore } from "../store/worldStore";
import { useFeedStore } from "../store/feedStore";
import type { WSMessage, WorldFrame, BinaryWorldFrame, EntityState, ResourceState } from "../types/world";
import type { FeedMessage } from "../types/feed";

const WS_URL = `ws://${window.location.host}/ws/world-stream`;
const RECONNECT_DELAY_MS = 2000;

// Binary frame format (from tech_stack.md):
// Header (8 bytes): tick (u32), entity_count (u16), resource_count (u16)
// Entities (16 bytes each): x (f32), y (f32), energy (f32), type (u8), color (u24)
// Resources (12 bytes each): x (f32), y (f32), amount (f32)

function parseBinaryFrame(buffer: ArrayBuffer): { tick: number; entities: EntityState[]; resources: ResourceState[] } {
  const view = new DataView(buffer);
  let offset = 0;

  // Read header
  const tick = view.getUint32(offset, true); offset += 4;
  const entityCount = view.getUint16(offset, true); offset += 2;
  const resourceCount = view.getUint16(offset, true); offset += 2;

  // Read entities
  const entities: EntityState[] = [];
  for (let i = 0; i < entityCount; i++) {
    const x = view.getFloat32(offset, true); offset += 4;
    const y = view.getFloat32(offset, true); offset += 4;
    const energy = view.getFloat32(offset, true); offset += 4;
    const type = view.getUint8(offset); offset += 1;
    const colorRaw = view.getUint32(offset, true) & 0xFFFFFF; offset += 3; // u24

    entities.push({
      id: `ent_${i}`,  // Binary mode doesn't include full IDs
      x,
      y,
      energy,
      radius: 6 + energy / 20,  // Approximate from energy
      color: `#${colorRaw.toString(16).padStart(6, '0')}`,
      state: "alive",
      traits: [],  // Binary mode omits trait names for bandwidth
    });
  }

  // Read resources
  const resources: ResourceState[] = [];
  for (let i = 0; i < resourceCount; i++) {
    const x = view.getFloat32(offset, true); offset += 4;
    const y = view.getFloat32(offset, true); offset += 4;
    const amount = view.getFloat32(offset, true); offset += 4;

    resources.push({ x, y, amount });
  }

  return { tick, entities, resources };
}

export function useWorldStream(): void {
  const wsRef = useRef<WebSocket | null>(null);
  const updateFrame = useWorldStore((s) => s.updateFrame);
  const setConnected = useWorldStore((s) => s.setConnected);
  const addMessage = useFeedStore((s) => s.addMessage);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let alive = true;

    function connect(): void {
      if (!alive) return;

      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";  // 🔴 CRITICAL: Enable binary mode
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event: MessageEvent) => {
        // Binary frame (ArrayBuffer)
        if (event.data instanceof ArrayBuffer) {
          const { tick, entities, resources } = parseBinaryFrame(event.data);
          updateFrame(tick, entities, resources);
          return;
        }

        // JSON frame (fallback for <200 entities or feed messages)
        const data: WSMessage = JSON.parse(event.data as string);

        if (data.type === "world_frame") {
          const frame = data as WorldFrame;
          updateFrame(frame.tick, [...frame.entities], [...frame.resources]);
        } else if (data.type === "feed_message") {
          addMessage(data as FeedMessage);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (alive) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [updateFrame, setConnected, addMessage]);
}
```

### 5.2 Data Flow (Optimized for Performance)

```
WebSocket (30 FPS)
    │
    ├── Binary ArrayBuffer (>=200 entities)
    │   └─ parseBinaryFrame() → {entities, resources, tick}
    │
    └── JSON (text) (<200 entities or feed)
        └─ JSON.parse() → WorldFrame | FeedMessage
    │
    ▼
useWorldStream() hook
    │
    ├── type === "world_frame" | ArrayBuffer
    │       │
    │       ▼
    │   worldStore.updateFrame()
    │       │
    │       ├── _transient.entities ← new entities (NO React render)
    │       ├── _transient.prevEntities ← old entities (for lerp)
    │       ├── tick, entityCount, populationHistory ← UI data (React render)
    │       │
    │       ├─── WorldCanvas.subscribeToEntities() → PixiJS sprites update (30 FPS, NO React)
    │       ├─── PopulationGraph reads history      → React re-render (1 FPS)
    │       ├─── Header reads entityCount + tick    → React re-render (30 FPS)
    │       └─── EntityInspector reads selected     → React re-render (on click only)
    │
    └── type === "feed_message"
            │
            ▼
        feedStore.addMessage()
            │
            └─── EvolutionFeed reads messages      → prepend new entry (event-driven)
```

**Performance optimization:**
- PixiJS reads `_transient` directly via `subscribeToEntities()` → bypasses React render loop
- React components read UI-only data (`tick`, `entityCount`, `populationHistory`) → minimal re-renders
- Binary protocol reduces parse time from ~15ms (JSON.parse 200KB) to ~2ms (DataView)

### 5.3 Frame Throttling (Client-Side)

Если browser рендерит медленнее, чем сервер шлёт (30 FPS), мы пропускаем кадры:

```typescript
// Inside useWorldStream, replace direct updateFrame with:

let frameBuffer: WorldFrame | null = null;
let rafId = 0;

function processFrame(): void {
  if (frameBuffer) {
    updateFrame(frameBuffer.tick, [...frameBuffer.entities], [...frameBuffer.resources]);
    frameBuffer = null;
  }
  rafId = requestAnimationFrame(processFrame);
}

ws.onmessage = (event: MessageEvent) => {
  const data: WSMessage = JSON.parse(event.data as string);
  if (data.type === "world_frame") {
    frameBuffer = data as WorldFrame;   // Only latest frame kept
  } else if (data.type === "feed_message") {
    addMessage(data as FeedMessage);    // Feed messages never dropped
  }
};

rafId = requestAnimationFrame(processFrame);

// cleanup:
cancelAnimationFrame(rafId);
```

Результат: если WS шлёт 30 FPS, а монитор 60 Hz — рисуем каждый кадр.
Если монитор 30 Hz — пропускаем ровно половину. Если лаг — рисуем только
последний полученный кадр, без очереди.

---

## 6. PixiJS Rendering Architecture

### 6.1 Why PixiJS + ParticleContainer

| Подход | 100 entities | 500 entities | 2000 entities |
|--------|-------------|-------------|---------------|
| DOM (`<div>`) | 60 FPS | 15 FPS | < 5 FPS |
| Canvas 2D | 60 FPS | 45 FPS | 20 FPS |
| PixiJS Container | 60 FPS | 60 FPS | 40 FPS |
| PixiJS **ParticleContainer** | 60 FPS | 60 FPS | **60 FPS** |

`ParticleContainer` uses a single draw call for all sprites of the same texture,
leveraging WebGL batching. It's the only viable option for 500+ entities at 60 FPS.

### 6.2 Texture Atlas — Pre-Generated Shapes

Molbot'ы рисуются не через `Graphics` каждый кадр (дорого), а через предгенерированные
текстуры, которые создаются один раз при старте и затем используются как спрайты.

```typescript
// canvas/textures.ts

import { Application, Graphics, RenderTexture } from "pixi.js";

export interface MolbotTextures {
  readonly body: RenderTexture;     // Круглое тело
  readonly ears: RenderTexture;     // Два ушка
  readonly glow: RenderTexture;     // Свечение при мутации
  readonly selection: RenderTexture; // Кольцо выделения
}

const BASE_RADIUS = 10;

export function generateMolbotTextures(app: Application): MolbotTextures {
  // Body: filled circle (white — tint will color it)
  const bodyGfx = new Graphics();
  bodyGfx.beginFill(0xffffff);
  bodyGfx.drawCircle(BASE_RADIUS, BASE_RADIUS, BASE_RADIUS);
  bodyGfx.endFill();

  const body = app.renderer.generateTexture(bodyGfx, {
    resolution: 2,    // Retina
    region: bodyGfx.getBounds(),
  });

  // Ears: two small circles above body
  const earsGfx = new Graphics();
  earsGfx.beginFill(0xffffff);
  earsGfx.drawCircle(BASE_RADIUS - 5, 2, 4);   // Left ear
  earsGfx.drawCircle(BASE_RADIUS + 5, 2, 4);   // Right ear
  earsGfx.endFill();

  const ears = app.renderer.generateTexture(earsGfx, {
    resolution: 2,
    region: earsGfx.getBounds(),
  });

  // Glow: larger semi-transparent circle
  const glowGfx = new Graphics();
  glowGfx.beginFill(0xffffff, 0.3);
  glowGfx.drawCircle(BASE_RADIUS, BASE_RADIUS, BASE_RADIUS * 2);
  glowGfx.endFill();

  const glow = app.renderer.generateTexture(glowGfx, {
    resolution: 2,
    region: glowGfx.getBounds(),
  });

  // Selection ring
  const selGfx = new Graphics();
  selGfx.lineStyle(2, 0xffffff, 0.8);
  selGfx.drawCircle(BASE_RADIUS, BASE_RADIUS, BASE_RADIUS + 4);

  const selection = app.renderer.generateTexture(selGfx, {
    resolution: 2,
    region: selGfx.getBounds(),
  });

  return { body, ears, glow, selection };
}
```

### 6.3 Sprite Pool (Object Recycling)

Чтобы не создавать/удалять `Sprite` каждый кадр (GC pressure), используем пул.

```typescript
// canvas/MolbotLayer.tsx (rendering logic)

import { useEffect, useRef } from "react";
import { Sprite, ParticleContainer } from "pixi.js";
import { subscribeToEntities } from "../store/worldStore";

const MAX_POOL_SIZE = 600;

interface SpritePool {
  active: Map<string, Sprite>;     // entity_id → sprite (on screen)
  dormant: Sprite[];               // off-screen sprites for reuse
}

// Example: MolbotLayer component uses subscribe (NO React re-render)
export function MolbotLayer({ container, textures }: Props): null {
  const poolRef = useRef<SpritePool>({ active: new Map(), dormant: [] });

  useEffect(() => {
    // Subscribe to entities WITHOUT triggering React render
    const unsubscribe = subscribeToEntities((entities, resources, prevEntities) => {
      updateSprites(poolRef.current, entities, prevEntities, 0.5, container, textures);
    });

    return unsubscribe;
  }, [container, textures]);

  return null;  // No React render, pure PixiJS side-effects
}

function updateSprites(
  pool: SpritePool,
  entities: readonly EntityState[],
  prevEntities: ReadonlyMap<string, { x: number; y: number }>,
  lerpAlpha: number,
  container: ParticleContainer,
  textures: MolbotTextures,
): void {
  const currentIds = new Set(entities.map((e) => e.id));

  // Return despawned sprites to dormant pool
  for (const [id, sprite] of pool.active) {
    if (!currentIds.has(id)) {
      sprite.visible = false;
      pool.dormant.push(sprite);
      pool.active.delete(id);
    }
  }

  // Update or create sprites for living entities
  for (const entity of entities) {
    let sprite = pool.active.get(entity.id);

    if (!sprite) {
      // Recycle from dormant pool or create new
      sprite = pool.dormant.pop() ?? new Sprite(textures.body);
      sprite.anchor.set(0.5);
      container.addChild(sprite);
      pool.active.set(entity.id, sprite);
    }

    // Interpolate position for smooth movement
    const prev = prevEntities.get(entity.id);
    if (prev) {
      sprite.x = lerp(prev.x, entity.x, lerpAlpha);
      sprite.y = lerp(prev.y, entity.y, lerpAlpha);
    } else {
      sprite.x = entity.x;
      sprite.y = entity.y;
    }

    // Visual properties
    sprite.tint = parseInt(entity.color.slice(1), 16);
    sprite.scale.set(entity.radius / 10);    // BASE_RADIUS = 10
    sprite.alpha = entity.energy / 100;       // Fade as energy drops
    sprite.visible = true;
  }
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
```

### 6.4 Smooth Movement (Interpolation)

Сервер шлёт 30 FPS, монитор рисует 60 FPS. Без интерполяции Molbot'ы «телепортируются»
каждые 33ms. С интерполяцией — плавное скольжение.

```
Server frames (30 FPS):     ─────F1──────────────F2──────────────F3──────
Browser frames (60 FPS):    ─F1──lerp(0.5)──F2──lerp(0.5)──F3──lerp(0.5)──

lerp alpha = время_с_последнего_серверного_кадра / интервал_серверных_кадров
```

```typescript
// Inside PixiJS ticker callback:

const SERVER_FRAME_INTERVAL = 1000 / 30;  // ~33ms
let lastServerFrameTime = performance.now();

app.ticker.add(() => {
  const now = performance.now();
  const elapsed = now - lastServerFrameTime;
  const alpha = Math.min(elapsed / SERVER_FRAME_INTERVAL, 1.0);

  updateSprites(pool, entities, prevEntities, alpha, container, textures);
});

// When new WorldFrame arrives from WebSocket:
lastServerFrameTime = performance.now();
```

### 6.5 Camera / Viewport

Мир 2000x2000px, экран ~1400x900px. Нужны pan & zoom.

```typescript
// WorldCanvas.tsx — viewport controls

interface ViewportState {
  scale: number;    // 0.2 (zoomed out) .. 3.0 (zoomed in)
  offsetX: number;  // world-space offset
  offsetY: number;
}

// Mouse wheel → zoom
function onWheel(e: WheelEvent, viewport: ViewportState): ViewportState {
  const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
  const newScale = clamp(viewport.scale * zoomFactor, 0.2, 3.0);
  return { ...viewport, scale: newScale };
}

// Mouse drag → pan
function onDrag(dx: number, dy: number, viewport: ViewportState): ViewportState {
  return {
    ...viewport,
    offsetX: viewport.offsetX - dx / viewport.scale,
    offsetY: viewport.offsetY - dy / viewport.scale,
  };
}

// Apply to PixiJS stage:
stage.scale.set(viewport.scale);
stage.position.set(
  -viewport.offsetX * viewport.scale + screenWidth / 2,
  -viewport.offsetY * viewport.scale + screenHeight / 2,
);
```

---

## 7. Evolution Feed — AI Thought Process Interface

### 7.1 Concept

Evolution Feed — это «окно в сознание» AI-агентов. Пользователь наблюдает
в реальном времени, как Watcher обнаруживает проблему, Architect формулирует
решение, Coder пишет код, а Patcher загружает его. Каждый агент имеет свой
визуальный стиль, чтобы лента читалась как диалог между специалистами.

### 7.2 Visual Design

```
┌─────────────────────────────────────────────────────┐
│  EVOLUTION FEED                          3 unread ↑  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ● 14:32:45  PATCHER                               │
│  │  ✅ Trait 'energy_scavenger' v2 is LIVE.         │
│  │  Registry v14. New Molbots will inherit.         │
│  │                                                  │
│  ● 14:32:38  CODER                                  │
│  │  📝 Generated 'energy_scavenger' v2 (23 lines).  │
│  │  ┌──────────────────────────────────┐            │
│  │  │ class EnergyScavenger(Trait):    │ ← expand   │
│  │  │   async def execute(self, ent):  │            │
│  │  │     nearest = min(ent.nearby_... │            │
│  │  │     ...                          │            │
│  │  └──────────────────────────────────┘            │
│  │                                                  │
│  ● 14:32:31  ARCHITECT                              │
│  │  🧠 Plan: NEW TRAIT — EnergyScavenger            │
│  │  "Molbots starve because they wander randomly.   │
│  │   New trait: move toward nearest resource         │
│  │   within 50px radius. If none found, continue    │
│  │   random walk."                                  │
│  │                                                  │
│  ● 14:32:15  WATCHER                                │
│  │  ⚠️  Anomaly: STARVATION (severity: high)        │
│  │  Population: 237 → 142 (-40%)                    │
│  │  Avg energy: 22.1 (critical threshold: 20)       │
│  │  Triggering evolution cycle.                     │
│  │                                                  │
│  ● 14:31:02  PATCHER                               │
│  │  ❌ Trait 'heat_shield' v1 FAILED to load.       │
│  │  Error: "Class HeatShield has no execute()"      │
│  │  Rolled back. No previous version available.     │
│  │                                                  │
│  ┆  (scroll for older messages)                     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 7.3 Agent Styling

| Agent | Color | Icon | Background |
|-------|-------|------|------------|
| `watcher` | `#3B82F6` (blue) | `⚠️` warning / `📊` stats | `rgba(59,130,246,0.08)` |
| `architect` | `#8B5CF6` (purple) | `🧠` brain | `rgba(139,92,246,0.08)` |
| `coder` | `#10B981` (green) | `📝` code | `rgba(16,185,129,0.08)` |
| `patcher` | `#F59E0B` (amber) | `✅` success / `❌` fail | `rgba(245,158,11,0.08)` |
| `system` | `#6B7280` (gray) | `ℹ️` info | `rgba(107,114,128,0.08)` |

### 7.4 FeedEntry Component

```typescript
// components/FeedEntry.tsx

interface FeedEntryProps {
  readonly message: FeedMessage;
  readonly isNew: boolean;        // Animate entrance
}

const AGENT_CONFIG = {
  watcher:   { color: "#3B82F6", icon: "⚠️",  label: "WATCHER" },
  architect: { color: "#8B5CF6", icon: "🧠", label: "ARCHITECT" },
  coder:     { color: "#10B981", icon: "📝", label: "CODER" },
  patcher:   { color: "#F59E0B", icon: "✅", label: "PATCHER" },
  system:    { color: "#6B7280", icon: "ℹ️",  label: "SYSTEM" },
} as const;

export function FeedEntry({ message, isNew }: FeedEntryProps): JSX.Element {
  const config = AGENT_CONFIG[message.agent];
  const [expanded, setExpanded] = useState(false);
  const time = new Date(message.timestamp).toLocaleTimeString("en-GB");

  return (
    <div
      className={`feed-entry ${isNew ? "feed-entry--new" : ""}`}
      style={{ borderLeftColor: config.color }}
    >
      <div className="feed-entry__header">
        <span className="feed-entry__dot" style={{ background: config.color }} />
        <span className="feed-entry__time">{time}</span>
        <span
          className="feed-entry__agent"
          style={{ color: config.color }}
        >
          {config.label}
        </span>
      </div>

      <div className="feed-entry__body">
        <span className="feed-entry__icon">{config.icon}</span>
        <p className="feed-entry__message">{message.message}</p>
      </div>

      {/* Code snippet for Coder messages */}
      {message.metadata?.code_snippet && (
        <button
          className="feed-entry__code-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Hide code ▲" : "Show code ▼"}
        </button>
      )}
      {expanded && message.metadata?.code_snippet && (
        <pre className="feed-entry__code">
          {message.metadata.code_snippet}
        </pre>
      )}
    </div>
  );
}
```

### 7.5 EvolutionFeed Container

```typescript
// components/EvolutionFeed.tsx

import { useRef, useEffect } from "react";
import { useFeedStore } from "../store/feedStore";
import { FeedEntry } from "./FeedEntry";

export function EvolutionFeed(): JSX.Element {
  const messages = useFeedStore((s) => s.messages);
  const unreadCount = useFeedStore((s) => s.unreadCount);
  const markAllRead = useFeedStore((s) => s.markAllRead);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to top (newest first) when new message arrives
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [messages.length, autoScroll]);

  // Mark as read when panel is visible
  useEffect(() => {
    if (unreadCount > 0) {
      const timer = setTimeout(markAllRead, 1000);
      return () => clearTimeout(timer);
    }
  }, [unreadCount, markAllRead]);

  return (
    <div className="evolution-feed">
      <div className="evolution-feed__header">
        <h3>Evolution Feed</h3>
        {unreadCount > 0 && (
          <span className="evolution-feed__badge">{unreadCount} new</span>
        )}
      </div>

      <div
        className="evolution-feed__scroll"
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          setAutoScroll(el.scrollTop < 10);
        }}
      >
        {messages.map((msg, i) => (
          <FeedEntry
            key={`${msg.timestamp}-${msg.agent}-${i}`}
            message={msg}
            isNew={i < unreadCount}
          />
        ))}

        {messages.length === 0 && (
          <div className="evolution-feed__empty">
            Waiting for first evolution cycle...
          </div>
        )}
      </div>
    </div>
  );
}
```

### 7.6 Feed CSS

```css
/* Evolution Feed Styles */

.evolution-feed {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f0f14;
  border-radius: 8px;
  overflow: hidden;
}

.evolution-feed__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #1e1e2e;
}

.evolution-feed__header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #e0e0e0;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.evolution-feed__badge {
  background: #3B82F6;
  color: white;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}

.evolution-feed__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.feed-entry {
  border-left: 3px solid;
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 0 6px 6px 0;
  background: rgba(255, 255, 255, 0.02);
  transition: background 0.3s ease;
}

.feed-entry--new {
  animation: feedSlideIn 0.3s ease-out;
  background: rgba(255, 255, 255, 0.05);
}

@keyframes feedSlideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.feed-entry__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.feed-entry__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.feed-entry__time {
  font-size: 11px;
  color: #6b7280;
  font-family: "JetBrains Mono", monospace;
}

.feed-entry__agent {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.feed-entry__body {
  display: flex;
  gap: 6px;
}

.feed-entry__icon {
  flex-shrink: 0;
  font-size: 14px;
}

.feed-entry__message {
  margin: 0;
  font-size: 13px;
  color: #d1d5db;
  line-height: 1.5;
}

.feed-entry__code-toggle {
  background: none;
  border: none;
  color: #6b7280;
  font-size: 11px;
  cursor: pointer;
  padding: 4px 0;
}

.feed-entry__code-toggle:hover {
  color: #10B981;
}

.feed-entry__code {
  background: #0a0a0f;
  border: 1px solid #1e1e2e;
  border-radius: 4px;
  padding: 8px;
  font-size: 11px;
  color: #10B981;
  font-family: "JetBrains Mono", monospace;
  overflow-x: auto;
  margin-top: 4px;
}
```

---

## 8. Main Layout

### 8.1 Grid Structure

```
┌────────────────────────────────────────────────────────────────┐
│  <Header>  AI-Genesis  │  tick: 90301  │  ● 237 entities  │ 🟢│
├──────────────────────────────────┬─────────────────────────────┤
│                                  │  ┌───────────────────────┐  │
│                                  │  │   EvolutionFeed       │  │
│                                  │  │   (40% sidebar height)│  │
│                                  │  │                       │  │
│        WorldCanvas               │  ├───────────────────────┤  │
│        (PixiJS)                  │  │   PopulationGraph     │  │
│                                  │  │   (20% sidebar height)│  │
│        70% width                 │  ├───────────────────────┤  │
│                                  │  │   WorldControls       │  │
│                                  │  │   (20% sidebar height)│  │
│                                  │  ├───────────────────────┤  │
│                                  │  │   EntityInspector     │  │
│                                  │  │   (20% sidebar height)│  │
│                                  │  └───────────────────────┘  │
└──────────────────────────────────┴─────────────────────────────┘
```

### 8.2 CSS

```css
/* index.css */

:root {
  --bg-primary: #0a0a0f;
  --bg-secondary: #0f0f14;
  --bg-panel: #141420;
  --border: #1e1e2e;
  --text-primary: #e0e0e0;
  --text-secondary: #6b7280;
  --accent-blue: #3B82F6;
  --accent-green: #10B981;
  --accent-purple: #8B5CF6;
  --accent-amber: #F59E0B;
  --accent-red: #EF4444;
  --font-mono: "JetBrains Mono", "Fira Code", monospace;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: "Inter", -apple-system, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
  height: 100vh;
}

#root {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.header__title {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1px;
  background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header__stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.header__connection {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  transition: background 0.3s;
}

.header__connection--connected { background: var(--accent-green); }
.header__connection--disconnected { background: var(--accent-red); animation: pulse 1s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.main-layout {
  display: grid;
  grid-template-columns: 1fr 380px;
  flex: 1;
  overflow: hidden;
}

.canvas-area {
  position: relative;
  overflow: hidden;
  background: var(--bg-primary);
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--border);
  border-left: 1px solid var(--border);
  overflow: hidden;
}

.sidebar > * {
  background: var(--bg-secondary);
}

.sidebar .evolution-feed  { flex: 4; min-height: 0; }
.sidebar .population-graph { flex: 2; min-height: 120px; }
.sidebar .world-controls   { flex: 2; min-height: 0; }
.sidebar .entity-inspector { flex: 2; min-height: 0; }
```

---

## 9. Key Components Detail

### 9.1 PopulationGraph

SVG-based line chart, no external library needed.

```typescript
// components/PopulationGraph.tsx

import { useWorldStore } from "../store/worldStore";

const GRAPH_WIDTH = 360;
const GRAPH_HEIGHT = 100;
const PADDING = 20;

export function PopulationGraph(): JSX.Element {
  const history = useWorldStore((s) => s.populationHistory);

  if (history.length < 2) {
    return <div className="population-graph">Collecting data...</div>;
  }

  const maxVal = Math.max(...history, 1);
  const minVal = Math.min(...history, 0);
  const range = maxVal - minVal || 1;

  const points = history.map((val, i) => {
    const x = PADDING + (i / (history.length - 1)) * (GRAPH_WIDTH - 2 * PADDING);
    const y = PADDING + (1 - (val - minVal) / range) * (GRAPH_HEIGHT - 2 * PADDING);
    return `${x},${y}`;
  }).join(" ");

  const current = history[history.length - 1];

  return (
    <div className="population-graph">
      <div className="population-graph__header">
        <h4>Population</h4>
        <span className="population-graph__value">{current}</span>
      </div>
      <svg viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} preserveAspectRatio="none">
        <polyline
          fill="none"
          stroke="#3B82F6"
          strokeWidth="2"
          points={points}
        />
        <polyline
          fill="url(#gradient)"
          stroke="none"
          points={`${PADDING},${GRAPH_HEIGHT - PADDING} ${points} ${GRAPH_WIDTH - PADDING},${GRAPH_HEIGHT - PADDING}`}
        />
        <defs>
          <linearGradient id="gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#3B82F6" stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}
```

### 9.2 EntityInspector

```typescript
// components/EntityInspector.tsx

import { useUIStore } from "../store/uiStore";
import { useWorldStore } from "../store/worldStore";
import { EnergyBar } from "./EnergyBar";
import { TraitBadge } from "./TraitBadge";

export function EntityInspector(): JSX.Element {
  const selectedId = useUIStore((s) => s.selectedEntityId);
  const entities = useWorldStore((s) => s.entities);
  const entity = entities.find((e) => e.id === selectedId);

  if (!entity) {
    return (
      <div className="entity-inspector">
        <p className="entity-inspector__empty">Click a Molbot to inspect</p>
      </div>
    );
  }

  return (
    <div className="entity-inspector">
      <div className="entity-inspector__header">
        <div
          className="entity-inspector__avatar"
          style={{ background: entity.color }}
        />
        <div>
          <h4>{entity.id}</h4>
          <span className="entity-inspector__state">{entity.state}</span>
        </div>
      </div>

      <EnergyBar current={entity.energy} max={100} />

      <div className="entity-inspector__grid">
        <div className="entity-inspector__stat">
          <span className="label">Position</span>
          <span className="value">{entity.x.toFixed(0)}, {entity.y.toFixed(0)}</span>
        </div>
        <div className="entity-inspector__stat">
          <span className="label">Radius</span>
          <span className="value">{entity.radius.toFixed(1)}</span>
        </div>
      </div>

      <div className="entity-inspector__traits">
        <h5>Active Traits</h5>
        <div className="entity-inspector__trait-list">
          {entity.traits.map((t) => (
            <TraitBadge key={t} name={t} />
          ))}
          {entity.traits.length === 0 && (
            <span className="entity-inspector__no-traits">No traits</span>
          )}
        </div>
      </div>
    </div>
  );
}
```

### 9.3 WorldControls

```typescript
// components/WorldControls.tsx

interface SliderConfig {
  readonly param: string;
  readonly label: string;
  readonly min: number;
  readonly max: number;
  readonly step: number;
  readonly unit: string;
}

const SLIDERS: readonly SliderConfig[] = [
  { param: "temperature",          label: "Temperature",    min: -20, max: 60,  step: 1,    unit: "°C" },
  { param: "resource_spawn_rate",  label: "Resource Rate",  min: 0,   max: 0.2, step: 0.01, unit: ""   },
  { param: "gravity",              label: "Gravity",        min: 0,   max: 2,   step: 0.05, unit: ""   },
  { param: "friction",             label: "Friction",       min: 0,   max: 1,   step: 0.05, unit: ""   },
] as const;
```

---

## 10. Performance Checklist

| Area | Requirement | Implementation |
|------|------------|----------------|
| Entity rendering | 60 FPS at 500 entities | PixiJS `ParticleContainer` + sprite pool |
| Position updates | No jitter at 30 FPS server rate | Lerp interpolation between frames |
| WebSocket parsing | **< 2ms per binary frame** (was 15ms JSON) | **Binary ArrayBuffer + DataView** (>=200 entities), JSON fallback |
| Store updates | **No React re-renders for Canvas** | **Zustand `_transient` + `subscribeToEntities()`** — PixiJS reads directly, bypasses React |
| Feed messages | Never dropped | Separate from frame buffer, immediate store update |
| Memory | Stable RSS | Sprite pool (no GC churn), feed capped at 200 messages, binary protocol reduces GC pressure |
| Canvas resize | Responsive | `ResizeObserver` on canvas container, PixiJS `renderer.resize()` |
| Click detection | Accurate on zoomed/panned canvas | Convert screen coords → world coords via viewport transform |

---

*Document Version: 1.0*
*References: PRD.md (Section 4.3), tech_stack.md (Section 7.2), task_list.md (Phase 6)*
