import { useWorldStore } from './store/worldStore'
import { PixiApp } from './canvas/PixiApp'
import { WorldCanvas } from './canvas/WorldCanvas'
import { EvolutionFeed } from './components/EvolutionFeed'
import { PopulationGraph } from './components/PopulationGraph'
import { WorldControls } from './components/WorldControls'
import { EntityInspector } from './components/EntityInspector'
import { useFeedStream } from './hooks/useFeedStream'
import './App.css'

function Header(): React.JSX.Element {
  const tick = useWorldStore((s) => s.tick)
  const entityCount = useWorldStore((s) => s.entityCount)
  const isConnected = useWorldStore((s) => s.isConnected)

  return (
    <header className="header">
      <span className="header__title">AI-GENESIS</span>
      <div className="header__stats">
        <span>TICK: {tick.toLocaleString()}</span>
        <span>ENTITIES: {entityCount}</span>
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

function AppInner(): React.JSX.Element {
  useFeedStream()
  return (
    <div className="app-root">
      <Header />
      <div className="main-layout">
        <div className="canvas-area">
          <PixiApp>
            <WorldCanvas />
          </PixiApp>
        </div>
        <aside className="sidebar">
          <EvolutionFeed />
          <PopulationGraph />
          <EntityInspector />
          <WorldControls />
        </aside>
      </div>
    </div>
  )
}

function App(): React.JSX.Element {
  return <AppInner />
}

export default App
