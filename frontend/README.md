# AI-Genesis Frontend

Real-time visualization of the AI-Genesis autonomous world simulation.

## Quick Start

### Prerequisites
- Node.js 20+
- Backend running at `http://localhost:8000`

### Install Dependencies
```bash
npm install
```

### Run Development Server
```bash
npm run dev
```

Open browser at `http://localhost:5173`

## What You'll See

When connected to the backend:
- **Dark canvas** with colored circles (entities/Molbots)
- **Status display** (top-left): Connection status, tick count, entity count
- **Real-time movement** as entities evolve in the simulation

## Architecture

### Technology Stack
- **React 19** - UI framework
- **TypeScript** (strict mode) - Type safety
- **Vite** - Build tool & dev server
- **Canvas 2D** - Rendering (PixiJS will be added in Phase 6)
- **WebSocket** - Real-time binary protocol streaming

### Key Files

- `src/hooks/useWorldStream.ts` - WebSocket connection & binary protocol parser
- `src/components/DebugCanvas.tsx` - Canvas rendering component
- `vite.config.ts` - Proxy configuration for `/api` and `/ws`

## Binary Protocol

The frontend parses binary frames from the backend:

**Header (6 bytes):**
- Tick: uint32 big-endian
- Count: uint16 big-endian

**Body (20 bytes per entity):**
- ID: uint32
- X: float32
- Y: float32
- Radius: float32
- Color: uint32 → hex string

## Development

### Type Checking
```bash
npx tsc --noEmit
```

### Linting
```bash
npm run lint
```

### Build for Production
```bash
npm run build
```

## Troubleshooting

**"DISCONNECTED" status:**
- Ensure backend is running: `docker-compose up` or `python -m backend.main`
- Check backend is accessible at `http://localhost:8000`
- Check WebSocket endpoint: `http://localhost:8000/ws/world-stream`

**No entities visible:**
- Backend simulation might be starting (wait 5-10 seconds)
- Check browser console for parsing errors
- Verify tick counter is incrementing

**Console errors about parsing:**
- Backend might not be sending binary frames yet
- Check backend logs for WebSocket connection messages

## Next Steps

See `docs/task_list.md` for upcoming features:
- T-066: PixiJS renderer with particle system
- T-067: Zustand state management
- T-068: Evolution feed (AI agent decisions)
- T-071: World control panel (sliders, force evolution)
- T-072: Entity inspector (click to see details)
