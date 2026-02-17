import { useState } from 'react'
import { useWorldStore } from './store/worldStore'
import { PixiApp } from './canvas/PixiApp'
import { WorldCanvas } from './canvas/WorldCanvas'
import { EvolutionFeed } from './components/EvolutionFeed'
import { PopulationGraph } from './components/PopulationGraph'
import { WorldControls } from './components/WorldControls'
import { EntityInspector } from './components/EntityInspector'
import { DeveloperPanel } from './components/DeveloperPanel'
import { useFeedStream } from './hooks/useFeedStream'
import { useStatsPoller } from './hooks/useStatsPoller'
import type { FeedMessage } from './types/feed'
import './App.css'

function Header(): React.JSX.Element {
  const tick = useWorldStore((s) => s.tick)
  const entityCount = useWorldStore((s) => s.entityCount)
  const isConnected = useWorldStore((s) => s.isConnected)
  const stats = useWorldStore((s) => s.stats)

  const energyColor = stats.avgEnergy > 60 ? '#4dff91' : stats.avgEnergy > 30 ? '#ffd04d' : '#ff4d4d'

  return (
    <header className="header">
      <span className="header__title">AI-GENESIS</span>
      <div className="header__stats">
        <Metric label="TICK" value={tick.toLocaleString()} />
        <Metric label="ENTITIES" value={String(entityCount)} />
        <Metric label="AVG ENERGY" value={`${stats.avgEnergy.toFixed(0)}%`} color={energyColor} />
        <Metric label="RESOURCES" value={String(stats.resourceCount)} />
        <Metric label="TPS" value={stats.tps.toFixed(0)} dim />
      </div>
      <div
        className={`header__connection ${
          isConnected ? 'header__connection--connected' : 'header__connection--disconnected'
        }`}
        title={isConnected ? 'Connected' : 'Disconnected'}
      />
    </header>
  )
}

function Metric({
  label, value, color, dim,
}: {
  label: string
  value: string
  color?: string
  dim?: boolean
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
      <span style={{
        fontSize: 9,
        letterSpacing: '0.08em',
        color: 'rgba(255,255,255,0.3)',
        textTransform: 'uppercase',
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 13,
        fontFamily: 'var(--font-mono)',
        color: color ?? (dim ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.9)'),
      }}>
        {value}
      </span>
    </div>
  )
}

function AppInner(): React.JSX.Element {
  useFeedStream()
  useStatsPoller()
  const [selectedMsg, setSelectedMsg] = useState<FeedMessage | null>(null)

  return (
    <div className="app-root">
      <Header />
      <div className={`main-layout${selectedMsg ? ' main-layout--with-panel' : ''}`}>
        <div className="canvas-area">
          <PixiApp>
            <WorldCanvas />
          </PixiApp>
        </div>
        <aside className="sidebar">
          <EvolutionFeed
            selectedId={selectedMsg?.id ?? null}
            onSelect={setSelectedMsg}
          />
          <PopulationGraph />
          <EntityInspector />
          <WorldControls />
        </aside>
        {selectedMsg && (
          <DeveloperPanel
            msg={selectedMsg}
            onClose={() => setSelectedMsg(null)}
          />
        )}
      </div>
    </div>
  )
}

function App(): React.JSX.Element {
  return <AppInner />
}

export default App
