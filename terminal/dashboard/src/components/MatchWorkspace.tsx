import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8888'

interface MatchOverview {
  match: { player_a: string; player_b: string; ranking_a: number; ranking_b: number; elo_a: number; elo_b: number; tournament: string; surface: string; round: string; level: string }
  market: { odds_a: number | null; odds_b: number | null }
  baseline: { prob_a: number; prob_b: number; confidence: string }
  overlay: { prob_a: number; prob_b: number; confidence: string; delta: number }
  decision: { action: string; skip_escalated: boolean }
  data_quality: number
  has_artifacts: boolean
}

interface ScenarioData {
  signals: Record<string, any>
  overlay: Record<string, any>
}

interface MatchListItem { id: string; label: string; timestamp: string }

function Badge({ level }: { level: string }) {
  return <span className={`badge badge-${level.toLowerCase()}`}>{level}</span>
}

function DataQualityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? 'var(--accent-green)' : pct >= 40 ? 'var(--accent-amber)' : 'var(--accent-red)'
  return (
    <div className="dq-bar">
      <div className="dq-label">Data Quality</div>
      <div className="dq-track">
        <div className="dq-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="dq-value" style={{ color }}>{pct}%</div>
    </div>
  )
}

function ProbBar({ label, probA, probB, nameA, nameB }: { label: string; probA: number; probB: number; nameA: string; nameB: string }) {
  return (
    <div className="prob-bar-container">
      <div className="prob-bar-label">{label}</div>
      <div className="prob-bar">
        <div className="prob-bar-a" style={{ width: `${probA * 100}%` }}>
          <span>{(probA * 100).toFixed(1)}%</span>
        </div>
        <div className="prob-bar-b" style={{ width: `${probB * 100}%` }}>
          <span>{(probB * 100).toFixed(1)}%</span>
        </div>
      </div>
      <div className="prob-bar-names">
        <span>{nameA}</span>
        <span>{nameB}</span>
      </div>
    </div>
  )
}

export default function MatchWorkspace({ externalMatchId }: { externalMatchId?: string }) {
  const [matches, setMatches] = useState<MatchListItem[]>([])
  const [selectedId, setSelectedId] = useState<string>('')
  const [overview, setOverview] = useState<MatchOverview | null>(null)
  const [scenario, setScenario] = useState<ScenarioData | null>(null)
  const [report, setReport] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)

  // Fetch match list (from slate first, then fallback to individual)
  useEffect(() => {
    const loadMatches = async () => {
      try {
        // Try slate first
        const slateRes = await fetch(`${API_BASE}/api/slate`)
        if (slateRes.ok) {
          const slateData = await slateRes.json()
          if (slateData.matches?.length > 0) {
            const items = slateData.matches.map((m: any) => ({
              id: m.id,
              label: m.label,
              timestamp: slateData.generated_at || '',
            }))
            setMatches(items)
            if (!selectedId && items.length > 0) setSelectedId(items[0].id)
            return
          }
        }
      } catch {}

      // Fallback to match list
      try {
        const res = await fetch(`${API_BASE}/api/match/list`)
        if (res.ok) {
          const data = await res.json()
          setMatches(data.matches || [])
          if (data.matches?.length > 0 && !selectedId) setSelectedId(data.matches[0].id)
        }
      } catch {}
    }
    loadMatches()
  }, [])

  // External match selection (from TomorrowSlate click)
  useEffect(() => {
    if (externalMatchId) setSelectedId(externalMatchId)
  }, [externalMatchId])

  // Fetch match data when selection changes
  useEffect(() => {
    if (!selectedId) return
    setLoading(true)
    Promise.all([
      fetch(`${API_BASE}/api/match/${selectedId}/overview`).then(r => r.json()),
      fetch(`${API_BASE}/api/match/${selectedId}/scenario`).then(r => r.json()),
      fetch(`${API_BASE}/api/match/${selectedId}/report`).then(r => r.json()),
    ]).then(([ov, sc, rp]) => {
      setOverview(ov)
      setScenario(sc)
      setReport(rp)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [selectedId])

  if (matches.length === 0) {
    return (
      <div className="workspace-empty">
        <div className="empty-icon">🎯</div>
        <h3>No Match Data</h3>
        <p>Run the scenario engine to generate match analysis:</p>
        <code>python3 terminal/intelligence/scenario_runner.py --player-a "..." --player-b "..." --surface Hard --tournament "..." --dry-run</code>
      </div>
    )
  }

  const m = overview?.match
  const signals = scenario?.signals || {}
  const overlayData = scenario?.overlay || {}
  const adjustments = overlayData.adjustments || []

  return (
    <div className="workspace">
      {/* Match Selector */}
      <div className="match-selector">
        <label>Select Match</label>
        <select value={selectedId} onChange={e => setSelectedId(e.target.value)}>
          {matches.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </div>

      {loading && <div className="workspace-loading">Loading match data...</div>}

      {overview && m && (
        <>
          {/* Match Header */}
          <div className="card ws-header">
            <div className="ws-header-main">
              <div className="ws-player ws-player-a">
                <div className="ws-player-name">{m.player_a}</div>
                <div className="ws-player-meta">#{m.ranking_a} • Elo {Math.round(m.elo_a)}</div>
              </div>
              <div className="ws-vs">
                <div className="ws-vs-text">VS</div>
                <div className="ws-tournament">{m.tournament}</div>
                <div className="ws-round">{m.round} • {m.surface}</div>
              </div>
              <div className="ws-player ws-player-b">
                <div className="ws-player-name">{m.player_b}</div>
                <div className="ws-player-meta">#{m.ranking_b} • Elo {Math.round(m.elo_b)}</div>
              </div>
            </div>
            <DataQualityBar score={overview.data_quality} />
          </div>

          {/* Prediction Stack */}
          <div className="ws-predictions">
            <ProbBar label="🐝 Swarm Baseline" probA={overview.baseline.prob_a} probB={overview.baseline.prob_b} nameA={m.player_a} nameB={m.player_b} />
            <div className="ws-overlay-delta">
              <span className="overlay-arrow">↓</span>
              <span className="overlay-label">NemoFish Overlay</span>
              <span className={`overlay-delta ${overview.overlay.delta >= 0 ? 'positive' : 'negative'}`}>
                {overview.overlay.delta >= 0 ? '+' : ''}{(overview.overlay.delta * 100).toFixed(2)}%
              </span>
            </div>
            <ProbBar label="🐠 Adjusted" probA={overview.overlay.prob_a} probB={overview.overlay.prob_b} nameA={m.player_a} nameB={m.player_b} />
          </div>

          {/* Decision Card */}
          <div className={`card ws-decision ${overview.decision.action === 'BET' ? 'decision-bet' : 'decision-skip'}`}>
            <div className="decision-verdict">
              <span className="decision-icon">{overview.decision.action === 'BET' ? '✅' : '⏸️'}</span>
              <span className="decision-action">{overview.decision.action === 'SKIP' ? 'SKIP' : `BET ${overview.decision.action.replace('BET_', '')}`}</span>
              <Badge level={overview.overlay.confidence} />
            </div>
            {overview.decision.skip_escalated && (
              <div className="decision-escalated">⚠️ Skip escalated by safety rules</div>
            )}
            {overlayData.explanation && (
              <div className="decision-explanation">{overlayData.explanation}</div>
            )}
          </div>

          {/* Scenario Signals */}
          {Object.keys(signals).length > 0 && (
            <div className="card ws-signals">
              <div className="card-title">🎯 Scenario Signals</div>
              <div className="signals-grid">
                {[
                  { key: 'pressure_edge_a', label: 'Pressure Edge', icon: '💪' },
                  { key: 'fatigue_risk_a', label: 'Fatigue Risk', icon: '🔋' },
                  { key: 'injury_risk_a', label: 'Injury Risk', icon: '🏥' },
                  { key: 'mental_resilience_a', label: 'Mental Resilience', icon: '🧠' },
                  { key: 'matchup_discomfort_a', label: 'Matchup Discomfort', icon: '⚔️' },
                  { key: 'volatility_score', label: 'Volatility', icon: '📊' },
                ].map(s => {
                  const val = signals[s.key]
                  if (val === undefined) return null
                  return (
                    <div key={s.key} className="signal-card">
                      <div className="signal-card-icon">{s.icon}</div>
                      <div className="signal-card-label">{s.label}</div>
                      <div className="signal-card-value">{typeof val === 'number' ? `${(val * 100).toFixed(0)}%` : String(val)}</div>
                    </div>
                  )
                })}
              </div>
              {signals.recommended_adjustments?.length > 0 && (
                <div className="signal-recommendations">
                  {signals.recommended_adjustments.map((a: string, i: number) => (
                    <div key={i} className="signal-rec">💡 {a}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Adjustments Audit */}
          {adjustments.length > 0 && (
            <div className="card ws-audit">
              <div className="card-title">📋 Adjustment Audit Trail</div>
              <div className="audit-list">
                {adjustments.map((a: any, i: number) => (
                  <div key={i} className="audit-item">
                    <span className="audit-field">[{a.source_signal || a.field}]</span>
                    <span className="audit-reason">{a.reason}</span>
                    {a.delta !== undefined && (
                      <span className={`audit-delta ${a.delta >= 0 ? 'positive' : 'negative'}`}>
                        {a.delta >= 0 ? '+' : ''}{(a.delta * 100).toFixed(2)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Report Summary */}
          {report && !report.error && (
            <div className="card ws-report">
              <div className="card-title">📝 Report Summary</div>
              <div className="report-meta">
                <span>Type: {report.report_type}</span>
                <span>Generated: {report.generated_at}</span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
