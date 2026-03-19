import { useState, useEffect, useCallback } from 'react'

const API_BASE = 'http://localhost:8888'

interface SlateMatch {
  id: string
  label: string
  player_a: string
  player_b: string
  tournament: string
  round: string
  surface: string
  level: string
  event_type: string
  time: string
  baseline_prob_a: number
  baseline_prob_b: number
  adjusted_prob_a: number
  adjusted_prob_b: number
  delta: number
  baseline_confidence: string
  adjusted_confidence: string
  adjusted_action: string
  edge: number | null
  odds_a: number | null
  odds_b: number | null
  has_odds: boolean
  data_quality: number
  classification: string
  priority: number
  skip_escalated: boolean
  explanation: string
}

interface SlateData {
  date: string
  generated_at: string
  processed: number
  with_odds: number
  live_candidates: number
  paper_candidates: number
  prediction_only: number
  matches: SlateMatch[]
  status?: string
  message?: string
}

type FilterMode = 'ALL' | 'LIVE_CANDIDATE' | 'PAPER_CANDIDATE' | 'PREDICTION_ONLY' | 'BET'

function Badge({ level }: { level: string }) {
  return <span className={`badge badge-${level.toLowerCase()}`}>{level}</span>
}

function ClassBadge({ classification }: { classification: string }) {
  const config: Record<string, { icon: string; label: string; cls: string }> = {
    'LIVE_CANDIDATE': { icon: '🟢', label: 'LIVE', cls: 'slate-class-live' },
    'PAPER_CANDIDATE': { icon: '🟡', label: 'PAPER', cls: 'slate-class-paper' },
    'PREDICTION_ONLY': { icon: '⚪', label: 'PREDICT', cls: 'slate-class-predict' },
  }
  const c = config[classification] || { icon: '❓', label: classification, cls: '' }
  return <span className={`slate-class-badge ${c.cls}`}>{c.icon} {c.label}</span>
}

function QualityFlags({ match }: { match: SlateMatch }) {
  return (
    <div className="slate-quality-flags">
      <span className={match.has_odds ? 'flag-ok' : 'flag-missing'} title={match.has_odds ? 'Odds available' : 'No odds'}>
        {match.has_odds ? '✅' : '❌'} Odds
      </span>
      <span className={match.data_quality >= 0.4 ? 'flag-ok' : 'flag-missing'} title={`Data quality: ${(match.data_quality * 100).toFixed(0)}%`}>
        {match.data_quality >= 0.4 ? '✅' : '⚠️'} DQ {(match.data_quality * 100).toFixed(0)}%
      </span>
    </div>
  )
}

function SlateCard({ match, onSelect }: { match: SlateMatch; onSelect: (id: string) => void }) {
  const favoriteA = match.adjusted_prob_a >= 0.5
  const favName = favoriteA ? match.player_a : match.player_b
  const showAction = match.adjusted_action !== 'SKIP'

  return (
    <div className={`slate-card slate-card-${match.classification.toLowerCase()}`} onClick={() => onSelect(match.id)}>
      <div className="slate-card-header">
        <div className="slate-card-meta">
          <span className="slate-tournament">{match.tournament}</span>
          <span className="slate-round">{match.round} • {match.surface}</span>
          {match.time && <span className="slate-time">{match.time}</span>}
        </div>
        <ClassBadge classification={match.classification} />
      </div>

      <div className="slate-card-players">
        <div className={`slate-player ${favoriteA ? 'slate-favorite' : ''}`}>
          <span className="slate-player-name">{match.player_a}</span>
          <span className="slate-player-prob">{(match.adjusted_prob_a * 100).toFixed(1)}%</span>
        </div>
        <div className="slate-vs-divider">VS</div>
        <div className={`slate-player ${!favoriteA ? 'slate-favorite' : ''}`}>
          <span className="slate-player-name">{match.player_b}</span>
          <span className="slate-player-prob">{(match.adjusted_prob_b * 100).toFixed(1)}%</span>
        </div>
      </div>

      {/* Probability bar */}
      <div className="slate-prob-bar">
        <div className="slate-prob-a" style={{ width: `${match.adjusted_prob_a * 100}%` }} />
        <div className="slate-prob-b" style={{ width: `${match.adjusted_prob_b * 100}%` }} />
      </div>

      <div className="slate-card-footer">
        <div className="slate-card-stats">
          {/* Delta */}
          <span className={`slate-delta ${match.delta >= 0 ? 'positive' : 'negative'}`}>
            Δ {match.delta >= 0 ? '+' : ''}{(match.delta * 100).toFixed(2)}%
          </span>
          {/* Edge */}
          {match.edge !== null && (
            <span className={`slate-edge ${match.edge >= 0 ? 'positive' : 'negative'}`}>
              Edge: {match.edge >= 0 ? '+' : ''}{(match.edge * 100).toFixed(1)}%
            </span>
          )}
          {/* Odds */}
          {match.has_odds && match.odds_a && match.odds_b && (
            <span className="slate-odds">
              {match.odds_a.toFixed(2)} / {match.odds_b.toFixed(2)}
            </span>
          )}
        </div>
        <div className="slate-card-actions">
          <QualityFlags match={match} />
          <Badge level={match.adjusted_confidence} />
          {showAction && (
            <span className="slate-action-bet">
              🎯 {match.adjusted_action.replace('BET_', '')} {favName.split(' ').pop()}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

export default function TomorrowSlate({ onMatchSelect }: { onMatchSelect?: (id: string) => void }) {
  const [slate, setSlate] = useState<SlateData | null>(null)
  const [filter, setFilter] = useState<FilterMode>('ALL')
  const [loading, setLoading] = useState(true)

  const fetchSlate = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/slate`)
      if (res.ok) {
        const data = await res.json()
        setSlate(data)
      }
    } catch {
      // API not available
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSlate()
    const interval = setInterval(fetchSlate, 60000) // refresh every minute
    return () => clearInterval(interval)
  }, [fetchSlate])

  if (loading) {
    return <div className="slate-loading">Loading slate...</div>
  }

  if (!slate || !slate.matches || slate.matches.length === 0) {
    return (
      <div className="workspace-empty">
        <div className="empty-icon">🐠</div>
        <h3>No Slate Available</h3>
        <p>
          {slate?.message || 'Waiting for next slate cycle. The supervisor runs every 4 hours.'}
        </p>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
          Manual: <code>python3 terminal/intelligence/slate_runner.py --dry-run</code>
        </p>
      </div>
    )
  }

  const filtered = slate.matches.filter(m => {
    if (filter === 'ALL') return true
    if (filter === 'BET') return m.adjusted_action !== 'SKIP'
    return m.classification === filter
  })

  const genTime = slate.generated_at ? new Date(slate.generated_at).toLocaleTimeString() : ''

  return (
    <div className="tomorrow-slate">
      {/* Header */}
      <div className="slate-header">
        <div className="slate-header-left">
          <h3 className="slate-title">📅 Tomorrow's Slate</h3>
          <span className="slate-date">{slate.date}</span>
          <span className="slate-count">{slate.processed} matches</span>
        </div>
        <div className="slate-header-right">
          <span className="slate-kpi live">{slate.live_candidates} 🟢 Live</span>
          <span className="slate-kpi paper">{slate.paper_candidates} 🟡 Paper</span>
          <span className="slate-kpi predict">{slate.prediction_only} ⚪ Predict</span>
          <span className="slate-timestamp">Updated {genTime}</span>
        </div>
      </div>

      {/* Filter Chips */}
      <div className="slate-filter-chips">
        {([
          ['ALL', `All (${slate.matches.length})`],
          ['BET', `Actionable (${slate.matches.filter(m => m.adjusted_action !== 'SKIP').length})`],
          ['LIVE_CANDIDATE', `Live (${slate.live_candidates})`],
          ['PAPER_CANDIDATE', `Paper (${slate.paper_candidates})`],
          ['PREDICTION_ONLY', `Predict (${slate.prediction_only})`],
        ] as [FilterMode, string][]).map(([key, label]) => (
          <button
            key={key}
            className={`slate-chip ${filter === key ? 'active' : ''}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Match Cards */}
      <div className="slate-cards">
        {filtered.map(m => (
          <SlateCard
            key={m.id}
            match={m}
            onSelect={(id) => onMatchSelect?.(id)}
          />
        ))}
        {filtered.length === 0 && (
          <div className="slate-empty-filter">No matches in this category</div>
        )}
      </div>
    </div>
  )
}
