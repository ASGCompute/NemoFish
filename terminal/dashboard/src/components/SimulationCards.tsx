import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8888'

const SCENARIOS = [
  { key: 'pressure', icon: '💪', label: 'Pressure', fields: ['pressure_edge_a', 'pressure_edge_b'] },
  { key: 'fatigue', icon: '🔋', label: 'Fatigue / Injury', fields: ['fatigue_risk_a', 'fatigue_risk_b', 'injury_risk_a', 'injury_risk_b'] },
  { key: 'mental', icon: '🧠', label: 'Mental Resilience', fields: ['mental_resilience_a', 'mental_resilience_b'] },
  { key: 'matchup', icon: '⚔️', label: 'Matchup Discomfort', fields: ['matchup_discomfort_a', 'matchup_discomfort_b'] },
  { key: 'momentum', icon: '📈', label: 'Momentum Swing', fields: ['momentum_shift_probability'] },
  { key: 'volatility', icon: '📊', label: 'Volatility', fields: ['volatility_score'] },
]

function SignalMeter({ value, label, inverted = false }: { value: number; label: string; inverted?: boolean }) {
  const pct = Math.round(value * 100)
  const color = inverted
    ? (pct > 60 ? 'var(--accent-red)' : pct > 30 ? 'var(--accent-amber)' : 'var(--accent-green)')
    : (pct > 60 ? 'var(--accent-green)' : pct > 30 ? 'var(--accent-amber)' : 'var(--accent-red)')
  return (
    <div className="signal-meter">
      <div className="signal-meter-label">{label}</div>
      <div className="signal-meter-track">
        <div className="signal-meter-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="signal-meter-value" style={{ color }}>{pct}%</div>
    </div>
  )
}

export default function SimulationCards({ matchId }: { matchId: string }) {
  const [signals, setSignals] = useState<Record<string, any>>({})

  useEffect(() => {
    if (!matchId) return
    fetch(`${API_BASE}/api/match/${matchId}/scenario`)
      .then(r => r.json())
      .then(d => setSignals(d.signals || {}))
      .catch(() => {})
  }, [matchId])

  if (!matchId || Object.keys(signals).length === 0) {
    return <div className="workspace-empty"><div className="empty-icon">🧪</div><h3>No simulation data</h3><p>Run scenario engine first</p></div>
  }

  return (
    <div className="simulation-page">
      <div className="card">
        <div className="card-title">🧪 Scenario Simulation — {signals.simulation_confidence !== undefined ? `${(signals.simulation_confidence * 100).toFixed(0)}% confidence` : ''}</div>
      </div>
      <div className="sim-grid">
        {SCENARIOS.map(sc => {
          const hasData = sc.fields.some(f => signals[f] !== undefined)
          if (!hasData) return null
          return (
            <div key={sc.key} className="card sim-card">
              <div className="sim-card-header">
                <span className="sim-card-icon">{sc.icon}</span>
                <span className="sim-card-title">{sc.label}</span>
              </div>
              <div className="sim-card-body">
                {sc.fields.map(f => {
                  const val = signals[f]
                  if (val === undefined) return null
                  const nice = f.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                  const inverted = f.includes('risk') || f.includes('discomfort') || f.includes('fatigue')
                  return <SignalMeter key={f} value={val} label={nice} inverted={inverted} />
                })}
              </div>
            </div>
          )
        })}
      </div>
      {signals.recommended_adjustments?.length > 0 && (
        <div className="card sim-recs">
          <div className="card-title">💡 Recommendations</div>
          {signals.recommended_adjustments.map((a: string, i: number) => (
            <div key={i} className="sim-rec-item">• {a}</div>
          ))}
        </div>
      )}
    </div>
  )
}
