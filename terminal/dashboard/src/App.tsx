import { useState, useEffect, useCallback } from 'react'
import './App.css'

// === Types ===
interface KpiData {
  bankroll: number
  totalPnl: number
  winRate: number
  totalBets: number
  activePositions: number
  maxDrawdown: number
  btcEquivalent: number
  dailyPnl: number
  roi: number
  sharpe: number
}

interface AgentVote {
  agentName: string
  role: string
  probA: number
  confidence: number
}

interface BetSignal {
  id: string
  match: string
  playerA: string
  playerB: string
  pick: string
  odds: number
  edge: number
  betSize: number
  confidence: 'ELITE' | 'HIGH' | 'MEDIUM' | 'LOW'
  action: 'BET' | 'SKIP'
  surface: string
  round: string
  agents: AgentVote[]
  modelProb: number
}

interface Trade {
  id: string
  timestamp: string
  match: string
  pick: string
  odds: number
  edge: number
  betSize: number
  won: boolean | null
  pnl: number
  confidence: string
  sport: string
}

interface LiveMatch {
  match_id: string
  player_a: string
  player_b: string
  score: string
  status: 'live' | 'finished' | 'scheduled'
  tournament: string
  round_name: string
  surface: string
  start_time: string
  odds_a: number | null
  odds_b: number | null
  set_scores: string[]
  server: string
}

interface NewsItem {
  title: string
  source: string
  url: string
  published: string
  category: string
  sentiment: string
  players: string[]
}

interface OddsMovement {
  match_id: string
  player_a: string
  player_b: string
  odds_a_open: number
  odds_b_open: number
  odds_a_current: number
  odds_b_current: number
  movement_a: number
  movement_b: number
}

// === API ===
const API_BASE = 'http://localhost:8888'

async function fetchAPI<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

// === Demo Data (fallback when API is not running) ===
const DEMO_KPI: KpiData = {
  bankroll: 10198.88, totalPnl: 198.88, winRate: 66.7, totalBets: 3,
  activePositions: 0, maxDrawdown: 2.4, btcEquivalent: 0.142137,
  dailyPnl: 198.88, roi: 29.3, sharpe: 0.32,
}

const DEMO_SIGNALS: BetSignal[] = [
  {
    id: 'NF-A3CC6A25', match: 'Djokovic vs Alcaraz', playerA: 'Novak Djokovic',
    playerB: 'Carlos Alcaraz', pick: 'Novak Djokovic', odds: 2.40, edge: 0.138,
    betSize: 250, confidence: 'LOW', action: 'BET', surface: 'Hard', round: 'QF',
    modelProb: 0.552,
    agents: [
      { agentName: 'StatBot', role: 'Statistical', probA: 0.68, confidence: 0.9 },
      { agentName: 'PsychBot', role: 'Psychology', probA: 0.48, confidence: 0.6 },
      { agentName: 'MarketBot', role: 'Market', probA: 0.40, confidence: 0.8 },
      { agentName: 'ContrarianBot', role: 'Contrarian', probA: 0.50, confidence: 0.5 },
      { agentName: 'NewsBot', role: 'News', probA: 0.50, confidence: 0.5 },
    ],
  },
  {
    id: 'NF-3513D00B', match: 'Medvedev vs de Minaur', playerA: 'Daniil Medvedev',
    playerB: 'Alex de Minaur', pick: 'Daniil Medvedev', odds: 1.80, edge: 0.120,
    betSize: 250, confidence: 'LOW', action: 'BET', surface: 'Hard', round: 'R16',
    modelProb: 0.675,
    agents: [
      { agentName: 'StatBot', role: 'Statistical', probA: 0.93, confidence: 0.9 },
      { agentName: 'PsychBot', role: 'Psychology', probA: 0.52, confidence: 0.6 },
      { agentName: 'MarketBot', role: 'Market', probA: 0.54, confidence: 0.8 },
      { agentName: 'ContrarianBot', role: 'Contrarian', probA: 0.49, confidence: 0.5 },
      { agentName: 'NewsBot', role: 'News', probA: 0.50, confidence: 0.5 },
    ],
  },
  {
    id: 'NF-36A012DD', match: 'Sinner vs Alcaraz', playerA: 'Jannik Sinner',
    playerB: 'Carlos Alcaraz', pick: 'Jannik Sinner', odds: 1.55, edge: 0.051,
    betSize: 179.79, confidence: 'HIGH', action: 'BET', surface: 'Hard', round: 'F',
    modelProb: 0.693,
    agents: [
      { agentName: 'StatBot', role: 'Statistical', probA: 0.87, confidence: 0.9 },
      { agentName: 'PsychBot', role: 'Psychology', probA: 0.55, confidence: 0.6 },
      { agentName: 'MarketBot', role: 'Market', probA: 0.62, confidence: 0.8 },
      { agentName: 'ContrarianBot', role: 'Contrarian', probA: 0.50, confidence: 0.5 },
      { agentName: 'NewsBot', role: 'News', probA: 0.50, confidence: 0.5 },
    ],
  },
]

const DEMO_LIVE: LiveMatch[] = [
  { match_id: 'd1', player_a: 'Jannik Sinner', player_b: 'Ben Shelton', score: '6-4 3-2',
    status: 'live', tournament: 'Miami Open 2026', round_name: 'R32', surface: 'Hard',
    start_time: '15:00', odds_a: 1.18, odds_b: 5.50, set_scores: ['6-4', '3-2'], server: 'Sinner' },
  { match_id: 'd2', player_a: 'Carlos Alcaraz', player_b: 'Hubert Hurkacz', score: '4-6 6-3 2-1',
    status: 'live', tournament: 'Miami Open 2026', round_name: 'R32', surface: 'Hard',
    start_time: '17:00', odds_a: 1.35, odds_b: 3.40, set_scores: ['4-6', '6-3', '2-1'], server: 'Alcaraz' },
  { match_id: 'd3', player_a: 'Alexander Zverev', player_b: 'Lorenzo Musetti', score: '7-5 6-4',
    status: 'finished', tournament: 'Miami Open 2026', round_name: 'R32', surface: 'Hard',
    start_time: '12:00', odds_a: 1.28, odds_b: 4.00, set_scores: ['7-5', '6-4'], server: '' },
  { match_id: 'd4', player_a: 'Daniil Medvedev', player_b: 'Tommy Paul', score: '',
    status: 'scheduled', tournament: 'Miami Open 2026', round_name: 'R16', surface: 'Hard',
    start_time: '14:00', odds_a: 1.65, odds_b: 2.30, set_scores: [], server: '' },
  { match_id: 'd5', player_a: 'Novak Djokovic', player_b: 'Frances Tiafoe', score: '6-3 5-4',
    status: 'live', tournament: 'Miami Open 2026', round_name: 'R32', surface: 'Hard',
    start_time: '19:00', odds_a: 1.12, odds_b: 7.00, set_scores: ['6-3', '5-4'], server: 'Djokovic' },
]

const DEMO_NEWS: NewsItem[] = [
  { title: 'Sinner enters Miami Open as top seed, targeting back-to-back titles', source: 'ATP Tour',
    url: '', published: '2026-03-16T10:00Z', category: 'preview', sentiment: 'positive', players: ['Sinner'] },
  { title: 'Djokovic hints at reduced schedule, Miami appearance uncertain', source: 'Tennis365',
    url: '', published: '2026-03-16T08:00Z', category: 'injury', sentiment: 'negative', players: ['Djokovic'] },
  { title: 'Alcaraz adjusting to new racquet setup ahead of hard court swing', source: 'ESPN',
    url: '', published: '2026-03-15T22:00Z', category: 'preview', sentiment: 'neutral', players: ['Alcaraz'] },
  { title: "Medvedev: 'Hard courts are my territory, I'm ready to fight'", source: 'Reuters',
    url: '', published: '2026-03-15T18:00Z', category: 'preview', sentiment: 'positive', players: ['Medvedev'] },
  { title: 'Fritz withdraws from doubles to focus on singles campaign', source: 'Tennis Channel',
    url: '', published: '2026-03-15T15:00Z', category: 'news', sentiment: 'neutral', players: ['Fritz'] },
  { title: "BREAKING: De Minaur nursing wrist discomfort, training limited", source: 'Tennis AU',
    url: '', published: '2026-03-15T09:00Z', category: 'injury', sentiment: 'negative', players: ['de Minaur'] },
]

const DEMO_ODDS: OddsMovement[] = [
  { match_id: 'd1', player_a: 'Sinner', player_b: 'Shelton', odds_a_open: 1.22, odds_b_open: 4.80,
    odds_a_current: 1.18, odds_b_current: 5.50, movement_a: -0.04, movement_b: 0.70 },
  { match_id: 'd2', player_a: 'Alcaraz', player_b: 'Hurkacz', odds_a_open: 1.40, odds_b_open: 3.10,
    odds_a_current: 1.35, odds_b_current: 3.40, movement_a: -0.05, movement_b: 0.30 },
  { match_id: 'd5', player_a: 'Djokovic', player_b: 'Tiafoe', odds_a_open: 1.15, odds_b_open: 6.50,
    odds_a_current: 1.12, odds_b_current: 7.00, movement_a: -0.03, movement_b: 0.50 },
  { match_id: 'd4', player_a: 'Medvedev', player_b: 'Paul', odds_a_open: 1.70, odds_b_open: 2.20,
    odds_a_current: 1.65, odds_b_current: 2.30, movement_a: -0.05, movement_b: 0.10 },
]

const DEMO_TRADES: Trade[] = [
  { id: 'NF-A3CC6A25', timestamp: '2026-03-16 00:43', match: 'Djokovic vs Alcaraz', pick: 'Novak Djokovic', odds: 2.40, edge: 0.138, betSize: 250, won: true, pnl: 350, confidence: 'LOW', sport: 'tennis' },
  { id: 'NF-36A012DD', timestamp: '2026-03-16 00:43', match: 'Sinner vs Alcaraz', pick: 'Jannik Sinner', odds: 1.55, edge: 0.051, betSize: 179.79, won: true, pnl: 98.88, confidence: 'HIGH', sport: 'tennis' },
  { id: 'NF-3513D00B', timestamp: '2026-03-16 00:43', match: 'Medvedev vs de Minaur', pick: 'Daniil Medvedev', odds: 1.80, edge: 0.120, betSize: 250, won: false, pnl: -250, confidence: 'LOW', sport: 'tennis' },
]

// === Components ===

function KpiCard({ label, value, change, color, prefix = '', suffix = '' }: {
  label: string; value: string; change?: string; color?: string; prefix?: string; suffix?: string
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${color || ''}`}>{prefix}{value}{suffix}</div>
      {change && (
        <div className={`kpi-change ${parseFloat(change) >= 0 ? 'positive' : 'negative'}`}>
          {parseFloat(change) >= 0 ? '↑' : '↓'} {change}
        </div>
      )}
    </div>
  )
}

function Badge({ level }: { level: string }) {
  return <span className={`badge badge-${level.toLowerCase()}`}>{level}</span>
}

function getHeatColor(prob: number): string {
  if (prob >= 0.75) return 'rgba(34, 197, 94, 0.5)'
  if (prob >= 0.60) return 'rgba(34, 197, 94, 0.25)'
  if (prob >= 0.55) return 'rgba(59, 130, 246, 0.2)'
  if (prob >= 0.45) return 'rgba(100, 116, 139, 0.15)'
  if (prob >= 0.35) return 'rgba(239, 68, 68, 0.25)'
  return 'rgba(239, 68, 68, 0.4)'
}

// --- Agent Heatmap ---
function AgentHeatmap({ signals }: { signals: BetSignal[] }) {
  const roles = ['Statistical', 'Psychology', 'Market', 'Contrarian', 'News']
  const bets = signals.filter(s => s.action === 'BET')
  return (
    <div className="card agent-heatmap">
      <div className="card-title">🤖 Agent Consensus Heatmap</div>
      <div className="heatmap-grid">
        <div className="heatmap-row">
          <div className="heatmap-header" style={{ textAlign: 'left' }}>Match</div>
          {roles.map(r => <div key={r} className="heatmap-header">{r.slice(0, 4)}</div>)}
        </div>
        {bets.map(s => (
          <div key={s.id} className="heatmap-row">
            <div className="heatmap-label">{s.match}</div>
            {s.agents.map((a, i) => (
              <div key={i} className="heatmap-cell" style={{ background: getHeatColor(a.probA) }}
                title={`${a.role}: ${s.playerA} ${(a.probA * 100).toFixed(0)}%`}>
                {(a.probA * 100).toFixed(0)}%
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Bet Signals ---
function SignalsList({ signals }: { signals: BetSignal[] }) {
  return (
    <div className="card signals">
      <div className="card-title">⚡ Bet Signals — Miami Open 2026</div>
      <div className="signal-list">
        {signals.map(s => (
          <div key={s.id} className={`signal-item ${s.action === 'BET' ? 'bet' : 'skip'}`}>
            <div className="signal-pick">
              <div className="signal-match">
                {s.action === 'BET' ? '🎾' : '⏸️'} {s.match}
              </div>
              <div className="signal-detail">
                {s.action === 'BET' ? `Pick: ${s.pick} @ ${s.odds.toFixed(2)}` : 'No edge'}
                {' • '}{s.round} • {s.surface} • <Badge level={s.confidence} />
              </div>
            </div>
            <div className={`signal-edge ${s.edge > 0 ? 'positive' : 'negative'}`}>
              {s.edge > 0 ? '+' : ''}{(s.edge * 100).toFixed(1)}%
            </div>
            {s.betSize > 0 && <div className="signal-bet">${s.betSize.toFixed(0)}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

// --- LIVE EVENT FEED ---
function LiveEventFeed({ matches }: { matches: LiveMatch[] }) {
  const statusIcon = (s: string) => ({ live: '🔴', finished: '✅', scheduled: '📅' }[s] || '❓')
  const statusColor = (s: string) => ({
    live: 'var(--accent-red)', finished: 'var(--accent-green)', scheduled: 'var(--text-muted)'
  }[s] || 'var(--text-muted)')

  return (
    <div className="card live-feed">
      <div className="card-title">
        🔴 Live Event Feed
        <span className="live-count">{matches.filter(m => m.status === 'live').length} LIVE</span>
      </div>
      <div className="feed-list">
        {matches.map(m => (
          <div key={m.match_id} className={`feed-item feed-${m.status}`}>
            <div className="feed-status">
              <span className="feed-icon">{statusIcon(m.status)}</span>
              <span className="feed-time" style={{ color: statusColor(m.status) }}>
                {m.status === 'live' ? 'LIVE' : m.status === 'finished' ? 'FT' : m.start_time.slice(-5)}
              </span>
            </div>
            <div className="feed-match">
              <div className="feed-players">
                <span className={`feed-player ${m.server === m.player_a ? 'serving' : ''}`}>
                  {m.server === m.player_a && '🎾 '}{m.player_a}
                </span>
                <span className="feed-vs">vs</span>
                <span className={`feed-player ${m.server === m.player_b ? 'serving' : ''}`}>
                  {m.server === m.player_b && '🎾 '}{m.player_b}
                </span>
              </div>
              <div className="feed-meta">
                {m.round_name} • {m.tournament}
              </div>
            </div>
            <div className="feed-score">
              {m.score ? (
                <span className="score-text">{m.score}</span>
              ) : (
                <span className="score-scheduled">—</span>
              )}
            </div>
            {m.odds_a && (
              <div className="feed-odds">
                <span className="odds-val">{m.odds_a.toFixed(2)}</span>
                <span className="odds-sep">|</span>
                <span className="odds-val">{m.odds_b?.toFixed(2)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// --- MARKET REACTION / ODDS MOVEMENTS ---
function MarketReaction({ movements }: { movements: OddsMovement[] }) {
  return (
    <div className="card market-reaction">
      <div className="card-title">📊 Market Reaction — Odds Movement</div>
      <div className="market-list">
        {movements.map(o => {
          const dirA = o.movement_a < 0 ? 'shortening' : 'drifting'
          const dirB = o.movement_b > 0 ? 'drifting' : 'shortening'
          return (
            <div key={o.match_id} className="market-item">
              <div className="market-players">
                <span className="market-player">{o.player_a}</span>
                <span className="market-vs">vs</span>
                <span className="market-player">{o.player_b}</span>
              </div>
              <div className="market-odds-row">
                <div className={`market-odds-cell ${dirA}`}>
                  <span className="market-odds-label">{o.player_a}</span>
                  <span className="market-odds-current">{o.odds_a_current.toFixed(2)}</span>
                  <span className={`market-movement ${o.movement_a < 0 ? 'down' : 'up'}`}>
                    {o.movement_a < 0 ? '↓' : '↑'} {Math.abs(o.movement_a).toFixed(3)}
                  </span>
                  <div className="market-bar-track">
                    <div className="market-bar"
                      style={{
                        width: `${Math.min(100, Math.abs(o.movement_a) * 500)}%`,
                        background: o.movement_a < 0 ? 'var(--accent-green)' : 'var(--accent-red)'
                      }} />
                  </div>
                </div>
                <div className={`market-odds-cell ${dirB}`}>
                  <span className="market-odds-label">{o.player_b}</span>
                  <span className="market-odds-current">{o.odds_b_current.toFixed(2)}</span>
                  <span className={`market-movement ${o.movement_b > 0 ? 'up' : 'down'}`}>
                    {o.movement_b > 0 ? '↑' : '↓'} {Math.abs(o.movement_b).toFixed(3)}
                  </span>
                  <div className="market-bar-track">
                    <div className="market-bar"
                      style={{
                        width: `${Math.min(100, Math.abs(o.movement_b) * 200)}%`,
                        background: o.movement_b > 0 ? 'var(--accent-red)' : 'var(--accent-green)'
                      }} />
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// --- NEWS FEED ---
function NewsFeed({ news }: { news: NewsItem[] }) {
  const catIcon = (c: string) => ({ injury: '🏥', preview: '📋', news: '📰', result: '🏆' }[c] || '📰')
  const sentColor = (s: string) => ({
    positive: 'var(--accent-green)', negative: 'var(--accent-red)', neutral: 'var(--text-secondary)'
  }[s] || 'var(--text-secondary)')

  return (
    <div className="card news-feed">
      <div className="card-title">📰 Tennis News Feed</div>
      <div className="news-list">
        {news.map((n, i) => (
          <div key={i} className={`news-item news-${n.sentiment}`}>
            <span className="news-icon">{catIcon(n.category)}</span>
            <div className="news-content">
              <div className="news-title">{n.title}</div>
              <div className="news-meta">
                <span className="news-source">{n.source}</span>
                <span className="news-dot">•</span>
                <span className="news-time">{n.published.slice(0, 10)}</span>
                {n.sentiment !== 'neutral' && (
                  <span className="news-sentiment" style={{ color: sentColor(n.sentiment) }}>
                    {n.sentiment === 'positive' ? '📈' : '📉'} {n.sentiment}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Trade Journal ---
function TradeJournal({ trades }: { trades: Trade[] }) {
  return (
    <div className="card journal">
      <div className="card-title">📋 Trade Journal</div>
      <table className="journal-table">
        <thead>
          <tr>
            <th>ID</th><th>Time</th><th>Match</th><th>Pick</th>
            <th>Odds</th><th>Edge</th><th>Size</th><th>Conf</th>
            <th>Result</th><th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map(t => (
            <tr key={t.id}>
              <td className="mono muted">{t.id}</td>
              <td className="mono small">{t.timestamp}</td>
              <td>{t.match}</td>
              <td className="bold">{t.pick}</td>
              <td className="mono">{t.odds.toFixed(2)}</td>
              <td className="mono green">+{(t.edge * 100).toFixed(1)}%</td>
              <td className="mono">${t.betSize.toFixed(0)}</td>
              <td><Badge level={t.confidence} /></td>
              <td>{t.won === null ? <span className="status-open">OPEN</span> :
                   t.won ? <span className="status-won">✅ WON</span> :
                   <span className="status-lost">❌ LOST</span>}</td>
              <td className={t.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// === MAIN APP ===
function App() {
  const [time, setTime] = useState(new Date())
  const [kpi, setKpi] = useState<KpiData>(DEMO_KPI)
  const [signals, setSignals] = useState<BetSignal[]>(DEMO_SIGNALS)
  const [trades, setTrades] = useState<Trade[]>(DEMO_TRADES)
  const [liveMatches, setLiveMatches] = useState<LiveMatch[]>(DEMO_LIVE)
  const [news, setNews] = useState<NewsItem[]>(DEMO_NEWS)
  const [oddsMovements, setOddsMovements] = useState<OddsMovement[]>(DEMO_ODDS)
  const [apiConnected, setApiConnected] = useState(false)

  // Clock
  useEffect(() => {
    const i = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(i)
  }, [])

  // API polling
  const pollAPI = useCallback(async () => {
    const health = await fetchAPI<{ status: string }>('/api/health')
    if (health?.status === 'ok') {
      setApiConnected(true)
      const [kpiRes, liveRes, newsRes, oddsRes] = await Promise.all([
        fetchAPI<KpiData>('/api/kpi'),
        fetchAPI<{ matches: LiveMatch[] }>('/api/live'),
        fetchAPI<{ news: NewsItem[] }>('/api/news'),
        fetchAPI<{ movements: OddsMovement[] }>('/api/odds'),
      ])
      if (kpiRes) setKpi(kpiRes)
      if (liveRes?.matches) setLiveMatches(liveRes.matches)
      if (newsRes?.news) setNews(newsRes.news)
      if (oddsRes?.movements) setOddsMovements(oddsRes.movements)
    } else {
      setApiConnected(false)
    }
  }, [])

  useEffect(() => {
    pollAPI()
    const i = setInterval(pollAPI, 30000) // Poll every 30s
    return () => clearInterval(i)
  }, [pollAPI])

  const totalReturn = ((kpi.bankroll / 10000 - 1) * 100).toFixed(1)

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <div>
            <div className="logo">🐡 NEMOFISH</div>
            <div className="logo-sub">God View Terminal</div>
          </div>
        </div>
        <div className="header-right">
          <span className={`api-status ${apiConnected ? 'connected' : 'offline'}`}>
            {apiConnected ? '🟢 API' : '🔴 DEMO'}
          </span>
          <span className="mode-badge paper">PAPER</span>
          <span className="clock">{time.toLocaleString('en-US', { hour12: false })}</span>
        </div>
      </header>

      <main className="dashboard">
        {/* KPIs */}
        <div className="kpi-row">
          <KpiCard label="Bankroll"
            value={kpi.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            change={`${totalReturn}%`} color="green" prefix="$" />
          <KpiCard label="BTC Equivalent" value={kpi.btcEquivalent.toFixed(6)} color="amber" prefix="₿" />
          <KpiCard label="Daily P&L"
            value={Math.abs(kpi.dailyPnl).toFixed(2)}
            color={kpi.dailyPnl >= 0 ? 'green' : 'red'}
            prefix={kpi.dailyPnl >= 0 ? '+$' : '-$'} />
          <KpiCard label="Win Rate" value={kpi.winRate.toFixed(1)} color="blue" suffix="%" />
          <KpiCard label="ROI" value={kpi.roi.toFixed(1)} color="purple" prefix="+" suffix="%" />
          <KpiCard label="Max Drawdown" value={kpi.maxDrawdown.toFixed(1)}
            color={kpi.maxDrawdown > 10 ? 'red' : 'green'} suffix="%" />
        </div>

        {/* Row 2: Heatmap + Signals */}
        <AgentHeatmap signals={signals} />
        <SignalsList signals={signals} />

        {/* Row 3: LIVE FEED + MARKET REACTION */}
        <LiveEventFeed matches={liveMatches} />
        <MarketReaction movements={oddsMovements} />

        {/* Row 4: NEWS + JOURNAL */}
        <NewsFeed news={news} />
        <TradeJournal trades={trades} />
      </main>
    </div>
  )
}

export default App
