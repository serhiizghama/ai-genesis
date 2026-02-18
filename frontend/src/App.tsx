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
        <Metric label="TICK" value={tick.toLocaleString()} tooltip="Total simulation steps executed since the world started" />
        <Metric label="ENTITIES" value={String(entityCount)} tooltip="Number of active molbots currently alive in the world" />
        <Metric label="AVG ENERGY" value={`${stats.avgEnergy.toFixed(0)}%`} color={energyColor} tooltip="Average energy level across all living entities. Below 30% signals critical stress" />
        <Metric label="RESOURCES" value={String(stats.resourceCount)} tooltip="Total resource units available in the world for entities to consume" />
        <Metric label="TPS" value={stats.tps.toFixed(0)} dim tooltip="Ticks per second — current simulation speed. Low values indicate server load" />
        <CycleIndicator stage={stats.cycleStage} problem={stats.cycleProblem} />
        <Metric label="🔴 KILLED" value={stats.predatorKills.toLocaleString()} color="#ff6b6b" tooltip="Molbots killed by predators (cumulative)" />
        <Metric label="🦠 VIRUS" value={stats.virusKills.toLocaleString()} color="#b44dff" tooltip="Molbots killed by virus (cumulative)" />
        <Metric label="☠ PRED ☠" value={stats.predatorDeaths.toLocaleString()} color="#4daaff" tooltip="Predators that died — from old age, starvation, or molbot attacks" />
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
  label, value, color, dim, tooltip,
}: {
  label: string
  value: string
  color?: string
  dim?: boolean
  tooltip?: string
}): React.JSX.Element {
  return (
    <div className="metric-wrapper">
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
      {tooltip && <span className="metric-tooltip">{tooltip}</span>}
    </div>
  )
}

const CYCLE_COLORS: Record<string, string> = {
  idle:     'rgba(255,255,255,0.2)',
  planning: '#ffd04d',
  coding:   '#4daaff',
  patching: '#b44dff',
  done:     '#4dff91',
  failed:   '#ff4d4d',
}

function CycleIndicator({ stage, problem }: { stage: string; problem: string }): React.JSX.Element {
  const color = CYCLE_COLORS[stage] ?? 'rgba(255,255,255,0.2)'
  const label = stage === 'idle'
    ? 'IDLE'
    : problem
      ? `${stage.toUpperCase()} · ${problem.replace('_', ' ')}`
      : stage.toUpperCase()

  const tooltip = ({
    idle:     'No active evolution cycle — waiting for anomaly',
    planning: 'Architect is designing an evolution plan (LLM call)',
    coding:   'Coder is writing trait code (LLM call)',
    patching: 'Patcher is hot-loading new code into the simulation',
    done:     'Evolution cycle completed successfully',
    failed:   'Evolution cycle failed — check feed for details',
  } as Record<string, string>)[stage] ?? ''

  return (
    <div className="metric-wrapper">
      <span style={{ fontSize: 9, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase' }}>
        EVO CYCLE
      </span>
      <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color, display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
                       boxShadow: stage !== 'idle' ? `0 0 6px ${color}` : 'none' }} />
        {label}
      </span>
      {tooltip && <span className="metric-tooltip">{tooltip}</span>}
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
