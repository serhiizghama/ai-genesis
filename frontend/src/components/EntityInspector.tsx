import { useEffect, useState } from 'react'
import { useWorldStore } from '../store/worldStore'

const API = '/api'

interface EntityDetail {
  numeric_id: number
  string_id: string
  generation: number
  age: number
  energy: number
  max_energy: number
  energy_pct: number
  state: string
  traits: string[]
  deactivated_traits: string[]
}

export function EntityInspector(): React.JSX.Element {
  const selectedEntityId = useWorldStore((s) => s.selectedEntityId)
  const selectEntity = useWorldStore((s) => s.selectEntity)
  const [detail, setDetail] = useState<EntityDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [killing, setKilling] = useState(false)

  useEffect(() => {
    if (selectedEntityId === null) {
      setDetail(null)
      return
    }

    setLoading(true)
    fetch(`${API}/entities/${selectedEntityId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setDetail(data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }, [selectedEntityId])

  async function handleKill() {
    if (!detail) return
    setKilling(true)
    try {
      await fetch(`${API}/entities/${selectedEntityId}/kill`, { method: 'POST' })
      selectEntity(null)
    } finally {
      setKilling(false)
    }
  }

  if (selectedEntityId === null) {
    return (
      <div className="entity-inspector">
        <div className="entity-inspector__empty">Click a Molbot to inspect</div>
      </div>
    )
  }

  return (
    <div className="entity-inspector">
      <div className="entity-inspector__panel">

        {/* Header */}
        <div className="entity-inspector__header-row">
          <span className="entity-inspector__title">Entity</span>
          <button
            className="entity-inspector__close"
            onClick={() => selectEntity(null)}
          >
            ×
          </button>
        </div>

        {loading && (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12 }}>Loading...</div>
        )}

        {!loading && !detail && (
          <div style={{ color: 'rgba(255,80,80,0.7)', fontSize: 12 }}>Entity not found</div>
        )}

        {!loading && detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

            <Row label="ID" value={`#${detail.numeric_id}`} />
            <Row label="Gen" value={`G${detail.generation}`} />
            <Row label="Age" value={`${detail.age} ticks`} />

            {/* Energy */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={labelStyle}>Energy</span>
                <span style={{ fontSize: 12, color: energyColor(detail.energy_pct) }}>
                  {detail.energy_pct.toFixed(0)}%
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.1)', overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${detail.energy_pct}%`,
                  background: energyColor(detail.energy_pct),
                  borderRadius: 3,
                  transition: 'width 0.3s',
                }} />
              </div>
            </div>

            {/* Traits */}
            <div>
              <span style={labelStyle}>Traits</span>
              <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                {detail.traits.length === 0 ? (
                  <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>none</span>
                ) : (
                  detail.traits.map((t) => (
                    <span key={t} style={{
                      fontSize: 11,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: detail.deactivated_traits.includes(t)
                        ? 'rgba(255,60,60,0.12)'
                        : 'rgba(77,255,145,0.1)',
                      color: detail.deactivated_traits.includes(t)
                        ? 'rgba(255,100,100,0.7)'
                        : 'rgba(77,255,145,0.85)',
                      textDecoration: detail.deactivated_traits.includes(t) ? 'line-through' : 'none',
                    }}>
                      {t}
                    </span>
                  ))
                )}
              </div>
            </div>

            {/* Kill button */}
            <button
              onClick={handleKill}
              disabled={killing}
              style={{
                marginTop: 6,
                background: 'rgba(255,60,60,0.12)',
                border: '1px solid rgba(255,60,60,0.3)',
                color: killing ? 'rgba(255,60,60,0.4)' : 'rgba(255,100,100,0.9)',
                fontFamily: 'monospace',
                fontSize: 12,
                padding: '6px 12px',
                borderRadius: 6,
                cursor: killing ? 'default' : 'pointer',
                width: '100%',
              }}
            >
              {killing ? 'Killing...' : '☠ Kill'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <span style={labelStyle}>{label}</span>
      <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.9)' }}>{value}</span>
    </div>
  )
}

function energyColor(pct: number): string {
  if (pct > 60) return '#4dff91'
  if (pct > 30) return '#ffd04d'
  return '#ff4d4d'
}

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'rgba(255,255,255,0.4)',
}
