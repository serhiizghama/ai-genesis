import { useEffect, useState } from 'react'
import { useWorldStore } from '../store/worldStore'

const API = '/api'

interface EntityDetail {
  numeric_id: number
  string_id: string
  entity_type: string
  generation: number
  age: number
  energy: number
  max_energy: number
  energy_pct: number
  state: string
  traits: string[]
  deactivated_traits: string[]
  evolution_count: number
  infected: boolean
  infection_timer: number
  metabolism_rate: number
  parent_id: string | null
}

export function EntityInspector(): React.JSX.Element {
  const selectedEntityId = useWorldStore((s) => s.selectedEntityId)
  const selectEntity = useWorldStore((s) => s.selectEntity)
  const [detail, setDetail] = useState<EntityDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [killing, setKilling] = useState(false)
  const [sourceModal, setSourceModal] = useState<{ trait: string; code: string } | null>(null)

  useEffect(() => {
    if (selectedEntityId === null) {
      setDetail(null)
      return
    }

    let cancelled = false

    function fetchDetail() {
      if (cancelled) return
      fetch(`${API}/entities/${selectedEntityId}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (!cancelled) setDetail(data) })
        .catch(() => { if (!cancelled) setDetail(null) })
        .finally(() => { if (!cancelled) setLoading(false) })
    }

    setLoading(true)
    fetchDetail()

    const interval = setInterval(fetchDetail, 2000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
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

  async function handleShowSource(traitName: string) {
    try {
      const r = await fetch(`${API}/mutations/source/${traitName}`)
      if (r.ok) {
        const data = await r.json()
        setSourceModal({ trait: traitName, code: data.source })
      }
    } catch {
      // ignore
    }
  }

  if (selectedEntityId === null) {
    return (
      <div className="entity-inspector">
        <div className="entity-inspector__empty">Click an entity to inspect</div>
      </div>
    )
  }

  return (
    <>
      <div className="entity-inspector">
        <div className="entity-inspector__panel">

          <div className="entity-inspector__header-row">
            <span className="entity-inspector__title">Entity</span>
            <button className="entity-inspector__close" onClick={() => selectEntity(null)}>×</button>
          </div>

          {loading && (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12 }}>Loading...</div>
          )}

          {!loading && !detail && (
            <div style={{ color: 'rgba(255,80,80,0.7)', fontSize: 12 }}>Entity not found</div>
          )}

          {!loading && detail && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Type badge */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={labelStyle}>Type</span>
                <span style={{
                  fontSize: 11,
                  fontWeight: 'bold',
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: detail.entity_type === 'predator'
                    ? 'rgba(204,0,0,0.2)'
                    : 'rgba(77,255,145,0.12)',
                  color: detail.entity_type === 'predator'
                    ? '#ff6b6b'
                    : '#4dff91',
                  border: `1px solid ${detail.entity_type === 'predator' ? 'rgba(255,100,100,0.3)' : 'rgba(77,255,145,0.25)'}`,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  {detail.entity_type === 'predator' ? '⚔ Predator' : '◉ Molbot'}
                </span>
              </div>

              <Row label="ID" value={`#${detail.numeric_id}`} />
              <Row label="Gen" value={`G${detail.generation}`} />
              <Row label="Age" value={`${detail.age} ticks`} />

              {/* Evolution counter */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={labelStyle}>Evolution</span>
                <span style={{
                  fontSize: 13,
                  fontWeight: 'bold',
                  color: detail.evolution_count > 0 ? '#a78bfa' : 'rgba(255,255,255,0.3)',
                }}>
                  {detail.evolution_count > 0 ? `⚡ ×${detail.evolution_count}` : '—'}
                </span>
              </div>

              {/* Infection status */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={labelStyle}>Virus</span>
                {detail.infected ? (
                  <span style={{
                    fontSize: 11,
                    padding: '2px 8px',
                    borderRadius: 4,
                    background: 'rgba(153,50,204,0.2)',
                    color: '#c87eff',
                    border: '1px solid rgba(153,50,204,0.4)',
                  }}>
                    ☣ Infected ({detail.infection_timer} ticks)
                  </span>
                ) : (
                  <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.25)' }}>—</span>
                )}
              </div>

              {/* Metabolism */}
              <Row label="Metabolism" value={`${detail.metabolism_rate}×`} />

              {/* Parent */}
              {detail.parent_id && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={labelStyle}>Parent</span>
                  <span style={{
                    fontSize: 10,
                    color: 'rgba(255,255,255,0.35)',
                    fontFamily: 'monospace',
                    maxWidth: 140,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {detail.parent_id.slice(0, 8)}…
                  </span>
                </div>
              )}

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

              {/* Traits with source code button */}
              <div>
                <span style={labelStyle}>Traits</span>
                <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {detail.traits.length === 0 ? (
                    <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>none</span>
                  ) : (
                    detail.traits.map((t) => {
                      const isDeactivated = detail.deactivated_traits.includes(t)
                      return (
                        <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{
                            flex: 1,
                            fontSize: 11,
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: isDeactivated ? 'rgba(255,60,60,0.12)' : 'rgba(167,139,250,0.12)',
                            color: isDeactivated ? 'rgba(255,100,100,0.7)' : 'rgba(167,139,250,0.9)',
                            textDecoration: isDeactivated ? 'line-through' : 'none',
                          }}>
                            {t}
                          </span>
                          <button
                            title="View evolution code"
                            onClick={() => handleShowSource(t)}
                            style={{
                              background: 'rgba(167,139,250,0.1)',
                              border: '1px solid rgba(167,139,250,0.25)',
                              color: 'rgba(167,139,250,0.7)',
                              fontSize: 10,
                              padding: '1px 5px',
                              borderRadius: 3,
                              cursor: 'pointer',
                              fontFamily: 'monospace',
                            }}
                          >
                            {'</>'}
                          </button>
                        </div>
                      )
                    })
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

      {/* Source code modal */}
      {sourceModal && (
        <div
          onClick={() => setSourceModal(null)}
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#0d1117',
              border: '1px solid rgba(167,139,250,0.3)',
              borderRadius: 8,
              width: 560,
              maxHeight: '70vh',
              display: 'flex', flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '10px 16px',
              borderBottom: '1px solid rgba(167,139,250,0.15)',
            }}>
              <span style={{ fontSize: 12, color: 'rgba(167,139,250,0.9)', fontFamily: 'monospace' }}>
                ⚡ {sourceModal.trait}
              </span>
              <button
                onClick={() => setSourceModal(null)}
                style={{
                  background: 'none', border: 'none',
                  color: 'rgba(255,255,255,0.4)', fontSize: 16, cursor: 'pointer',
                }}
              >×</button>
            </div>
            <pre style={{
              margin: 0, padding: '12px 16px',
              fontSize: 11, lineHeight: 1.6,
              color: 'rgba(255,255,255,0.8)',
              overflowY: 'auto', fontFamily: 'monospace',
            }}>
              {sourceModal.code}
            </pre>
          </div>
        </div>
      )}
    </>
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
