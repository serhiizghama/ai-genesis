import { useState } from 'react'

const API = 'http://localhost:8000/api'

async function postParam(param: string, value: number): Promise<void> {
  await fetch(`${API}/world/params`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ param, value }),
  })
}

async function triggerEvolution(): Promise<void> {
  await fetch(`${API}/evolution/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ problem: 'manual_test', severity: 0.5 }),
  })
}

export function WorldControls(): React.JSX.Element {
  const [timeScale, setTimeScale] = useState(1)
  const [spawnRate, setSpawnRate] = useState(0.5)
  const [evolving, setEvolving] = useState(false)

  function handleTimeScale(value: number) {
    setTimeScale(value)
    const tickRateMs = Math.round(1000 / value)
    postParam('tick_rate_ms', tickRateMs)
  }

  function handleSpawnRate(value: number) {
    setSpawnRate(value)
    postParam('spawn_rate', value)
  }

  async function handleForceEvolution() {
    setEvolving(true)
    try {
      await triggerEvolution()
    } finally {
      setTimeout(() => setEvolving(false), 2000)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      bottom: 0,
      left: 0,
      right: 0,
      height: 72,
      background: 'rgba(10,10,15,0.85)',
      backdropFilter: 'blur(8px)',
      borderTop: '1px solid rgba(255,255,255,0.08)',
      display: 'flex',
      alignItems: 'center',
      gap: 32,
      padding: '0 24px',
      zIndex: 100,
      fontFamily: 'monospace',
    }}>

      {/* Time Scale */}
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
        <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          Time Scale
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={timeScale}
            onChange={(e) => handleTimeScale(Number(e.target.value))}
            style={sliderStyle}
          />
          <span style={{ color: '#4dff91', fontSize: 13, minWidth: 32 }}>{timeScale}x</span>
        </div>
      </label>

      {/* Spawn Rate */}
      <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
        <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          Spawn Rate
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="range"
            min={0.0}
            max={5.0}
            step={0.1}
            value={spawnRate}
            onChange={(e) => handleSpawnRate(Number(e.target.value))}
            style={sliderStyle}
          />
          <span style={{ color: '#4dff91', fontSize: 13, minWidth: 32 }}>{spawnRate.toFixed(1)}x</span>
        </div>
      </label>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Force Evolution Button */}
      <button
        onClick={handleForceEvolution}
        disabled={evolving}
        style={{
          background: evolving ? 'rgba(74,222,128,0.15)' : 'rgba(74,222,128,0.1)',
          border: `1px solid ${evolving ? 'rgba(74,222,128,0.6)' : 'rgba(74,222,128,0.3)'}`,
          color: evolving ? 'rgba(74,222,128,0.6)' : '#4dff91',
          fontFamily: 'monospace',
          fontSize: 13,
          fontWeight: 600,
          letterSpacing: '0.05em',
          padding: '8px 20px',
          borderRadius: 6,
          cursor: evolving ? 'default' : 'pointer',
          transition: 'all 0.2s',
          whiteSpace: 'nowrap',
        }}
      >
        {evolving ? '⏳ Triggering...' : '🧬 Force Evolution'}
      </button>
    </div>
  )
}

const sliderStyle: React.CSSProperties = {
  appearance: 'none',
  WebkitAppearance: 'none',
  width: 120,
  height: 4,
  borderRadius: 2,
  background: 'rgba(255,255,255,0.15)',
  outline: 'none',
  cursor: 'pointer',
}
