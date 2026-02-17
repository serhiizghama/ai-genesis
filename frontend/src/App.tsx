import { PixiApp } from './canvas/PixiApp'
import { WorldCanvas } from './canvas/WorldCanvas'
import { EvolutionFeed } from './components/EvolutionFeed'
import { PopulationGraph } from './components/PopulationGraph'
import { WorldControls } from './components/WorldControls'
import { EntityInspector } from './components/EntityInspector'
import { useFeedStream } from './hooks/useFeedStream'
import './App.css'

function AppInner(): React.JSX.Element {
  useFeedStream()
  return (
    <>
      <PixiApp>
        <WorldCanvas />
      </PixiApp>
      <EvolutionFeed />
      <PopulationGraph />
      <WorldControls />
      <EntityInspector />
    </>
  )
}

function App(): React.JSX.Element {
  return (
    <div style={{ width: '100vw', height: '100vh', margin: 0, padding: 0, overflow: 'hidden' }}>
      <AppInner />
    </div>
  )
}

export default App
