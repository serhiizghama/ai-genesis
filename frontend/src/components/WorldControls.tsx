import { useState } from 'react'

const API = '/api'

async function postParam(param: string, value: number): Promise<void> {
  await fetch(`${API}/world/params`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ param, value }),
  })
}

export function WorldControls(): React.JSX.Element {
  const [timeScale, setTimeScale] = useState(1)
  const [spawnRate, setSpawnRate] = useState(0.5)

  function handleTimeScale(value: number) {
    setTimeScale(value)
    const tickRateMs = Math.round(1000 / value)
    postParam('tick_rate_ms', tickRateMs)
  }

  function handleSpawnRate(value: number) {
    setSpawnRate(value)
    postParam('spawn_rate', value)
  }

  return (
    <div className="world-controls">
      <div className="world-controls__title">Controls</div>

      {/* Time Scale */}
      <div className="world-controls__row">
        <span className="world-controls__row-label">Time Scale</span>
        <div className="world-controls__row-inner">
          <input
            type="range"
            min={1}
            max={30}
            step={1}
            value={timeScale}
            onChange={(e) => handleTimeScale(Number(e.target.value))}
            className="world-controls__slider"
          />
          <span className="world-controls__value">{timeScale}x</span>
        </div>
      </div>

      {/* Spawn Rate */}
      <div className="world-controls__row">
        <span className="world-controls__row-label">Spawn Rate</span>
        <div className="world-controls__row-inner">
          <input
            type="range"
            min={0.0}
            max={30}
            step={0.5}
            value={spawnRate}
            onChange={(e) => handleSpawnRate(Number(e.target.value))}
            className="world-controls__slider"
          />
          <span className="world-controls__value">{spawnRate.toFixed(1)}x</span>
        </div>
      </div>
    </div>
  )
}
