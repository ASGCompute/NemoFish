import { useState, useEffect, useCallback, useMemo } from 'react'
import './App.css'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line, Legend, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ReferenceLine
} from 'recharts'

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

// Real api-tennis.com live match shape
interface ApiLiveMatch {
  event_key: string
  playerA: string
  playerB: string
  score: string
  game_score: string
  status: 'live' | 'finished' | 'scheduled'
  set_status: string
  serve: string | null
  tournament: string
  round: string
  event_type: string
  time: string
  date: string
  oddsA: number | null
  oddsB: number | null
}

interface RankingEntry {
  rank: number
  points: number
  player_name: string
  player_id: string
  nationality: string
  movement: number
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

interface StrategyResult {
  name: string
  source: string
  bets: number
  wins: number
  winRate: number
  wagered: number
  pnl: number
  roi: number
  maxDrawdown: number
  sharpe: number
  avgPnlPerBet: number
  color: string
  pnlCurve: number[]
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

// === Strategy Demo Data (from backtest results) ===
const DEMO_STRATEGIES: StrategyResult[] = [
  { name: 'ATPConfidence(top5%)', source: 'ATPBetting', bets: 7, wins: 1, winRate: 14.3, wagered: 700, pnl: 354, roi: 50.6, maxDrawdown: 300, sharpe: 0.137, avgPnlPerBet: 50.6, color: '#ccff00',
    pnlCurve: [0, -100, -200, -300, -200, -100, 354] },
  { name: 'ValueConfirmation', source: 'NemoFish', bets: 108, wins: 81, winRate: 75.0, wagered: 10800, pnl: -129, roi: -1.2, maxDrawdown: 720, sharpe: -0.020, avgPnlPerBet: -1.2, color: '#0ea5e9',
    pnlCurve: Array.from({length: 20}, (_, i) => Math.sin(i * 0.5) * 300 + (i > 15 ? -200 : 100) - i * 6) },
  { name: 'ATPConfidence(top10%)', source: 'ATPBetting', bets: 15, wins: 2, winRate: 13.3, wagered: 1500, pnl: -66, roi: -4.4, maxDrawdown: 500, sharpe: -0.016, avgPnlPerBet: -4.4, color: '#22c55e',
    pnlCurve: Array.from({length: 15}, (_, i) => Math.sin(i * 0.7) * 200 - i * 4) },
  { name: 'SkempPredictWin+Value', source: 'skemp15', bets: 49, wins: 24, winRate: 49.0, wagered: 4900, pnl: -579, roi: -11.8, maxDrawdown: 1198, sharpe: -0.128, avgPnlPerBet: -11.8, color: '#06b6d4',
    pnlCurve: Array.from({length: 20}, (_, i) => Math.sin(i * 0.4) * 400 - i * 30) },
  { name: 'Edge(5%-20%)', source: 'NemoFish', bets: 23, wins: 10, winRate: 43.5, wagered: 2300, pnl: -410, roi: -17.8, maxDrawdown: 845, sharpe: -0.187, avgPnlPerBet: -17.8, color: '#d97706',
    pnlCurve: Array.from({length: 15}, (_, i) => -i * 28 + Math.sin(i) * 100) },
  { name: 'Edge(3%-30%)', source: 'NemoFish', bets: 35, wins: 15, winRate: 42.9, wagered: 3500, pnl: -691, roi: -19.7, maxDrawdown: 1022, sharpe: -0.208, avgPnlPerBet: -19.7, color: '#f59e0b',
    pnlCurve: Array.from({length: 18}, (_, i) => -i * 38 + Math.sin(i * 0.6) * 150) },
  { name: 'Kelly(¼)', source: 'NemoFish', bets: 36, wins: 15, winRate: 41.7, wagered: 6617, pnl: -1415, roi: -21.4, maxDrawdown: 1887, sharpe: -0.213, avgPnlPerBet: -39.3, color: '#c084fc',
    pnlCurve: Array.from({length: 18}, (_, i) => -i * 78 + Math.sin(i * 0.8) * 300) },
  { name: 'SkempInverse', source: 'skemp15', bets: 25, wins: 7, winRate: 28.0, wagered: 2500, pnl: -542, roi: -21.7, maxDrawdown: 743, sharpe: -0.169, avgPnlPerBet: -21.7, color: '#f97316',
    pnlCurve: Array.from({length: 15}, (_, i) => -i * 36 + Math.sin(i * 1.2) * 150) },
  { name: 'SkempValue', source: 'skemp15', bets: 128, wins: 39, winRate: 30.5, wagered: 12800, pnl: -3321, roi: -25.9, maxDrawdown: 3605, sharpe: -0.188, avgPnlPerBet: -25.9, color: '#ef4444',
    pnlCurve: Array.from({length: 25}, (_, i) => -i * 132 + Math.sin(i * 0.3) * 500) },
  { name: 'ATPConfidence(top15%)', source: 'ATPBetting', bets: 22, wins: 2, winRate: 9.1, wagered: 2200, pnl: -766, roi: -34.8, maxDrawdown: 920, sharpe: -0.152, avgPnlPerBet: -34.8, color: '#065f46',
    pnlCurve: Array.from({length: 15}, (_, i) => -i * 51 + Math.sin(i * 0.9) * 100) },
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
          <div className="heatmap-header heatmap-label-col">Match</div>
          {roles.map(r => <div key={r} className="heatmap-header">{r.slice(0, 4)}</div>)}
        </div>
        {bets.map(s => (
          <div key={s.id} className="heatmap-row">
            <div className="heatmap-label">{s.match}</div>
            {s.agents.map((a, i) => (
              <div key={i} className="heatmap-cell"
                style={{ background: getHeatColor(a.probA) }}
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

// --- LIVE EVENT FEED (REAL DATA from api-tennis.com) ---
function LiveEventFeed({ matches, source }: { matches: ApiLiveMatch[]; source: string }) {
  const statusIcon = (s: string) => ({ live: '🔴', finished: '✅', scheduled: '📅' }[s] || '❓')
  const statusColor = (s: string) => ({
    live: 'var(--accent-red)', finished: 'var(--accent-green)', scheduled: 'var(--text-muted)'
  }[s] || 'var(--text-muted)')

  const liveCount = matches.filter(m => m.status === 'live').length
  const scheduledCount = matches.filter(m => m.status === 'scheduled').length

  return (
    <div className="card live-feed">
      <div className="card-title">
        🔴 Live Event Feed
        <span className="live-count">
          {liveCount > 0 ? `${liveCount} LIVE` : `${scheduledCount} TODAY`}
        </span>
        {source && <span className="feed-source">{source}</span>}
      </div>
      <div className="feed-list">
        {matches.map(m => (
          <div key={m.event_key} className={`feed-item feed-${m.status}`}>
            <div className="feed-status">
              <span className="feed-icon">{statusIcon(m.status)}</span>
              <span className="feed-time" style={{ color: statusColor(m.status) }}>
                {m.status === 'live' ? 'LIVE' : m.status === 'finished' ? 'FT' : m.time || '—'}
              </span>
            </div>
            <div className="feed-match">
              <div className="feed-players">
                <span className={`feed-player ${m.serve === m.playerA ? 'serving' : ''}`}>
                  {m.serve === m.playerA && '🎾 '}{m.playerA}
                </span>
                <span className="feed-vs">vs</span>
                <span className={`feed-player ${m.serve === m.playerB ? 'serving' : ''}`}>
                  {m.serve === m.playerB && '🎾 '}{m.playerB}
                </span>
              </div>
              <div className="feed-meta">
                {m.round || ''} {m.round && '•'} {m.tournament}
                {m.event_type && <span className="feed-type"> • {m.event_type.replace('ATP Singles, ', '').replace('WTA Singles, ', '')}</span>}
              </div>
            </div>
            <div className="feed-score">
              {m.score && m.score !== '0-0' ? (
                <span className="score-text">{m.score}</span>
              ) : (
                <span className="score-scheduled">—</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- RANKINGS PANEL (REAL DATA from Sportradar) ---
function RankingsPanel({ rankings }: { rankings: Record<string, RankingEntry[]> }) {
  const [activeTour, setActiveTour] = useState<string>('atp')
  const tours = Object.keys(rankings)

  if (tours.length === 0) return null

  const entries = rankings[activeTour] || []

  return (
    <div className="card rankings-panel">
      <div className="card-title">
        🏆 World Rankings
        <span className="rankings-source">sportradar.com</span>
      </div>
      <div className="rankings-tabs">
        {tours.map(t => (
          <button
            key={t}
            className={`rankings-tab ${t === activeTour ? 'active' : ''}`}
            onClick={() => setActiveTour(t)}
          >
            {t.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="rankings-list">
        {entries.slice(0, 15).map(r => (
          <div key={r.player_id || r.rank} className="ranking-row">
            <span className="ranking-pos">#{r.rank}</span>
            <span className="ranking-name">{r.player_name}</span>
            <span className="ranking-pts">{r.points.toLocaleString()}</span>
            <span className={`ranking-move ${r.movement > 0 ? 'up' : r.movement < 0 ? 'down' : ''}`}>
              {r.movement > 0 ? `↑${r.movement}` : r.movement < 0 ? `↓${Math.abs(r.movement)}` : '—'}
            </span>
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

// === STRATEGY COMPARISON COMPONENT ===
function StrategyComparison() {
  const [activeStrategies, setActiveStrategies] = useState<Set<string>>(
    new Set(DEMO_STRATEGIES.map(s => s.name))
  )
  const [sortBy, setSortBy] = useState<'roi' | 'winRate' | 'sharpe' | 'bets'>('roi')

  const toggleStrategy = (name: string) => {
    setActiveStrategies(prev => {
      const n = new Set(prev)
      if (n.has(name)) n.delete(name); else n.add(name)
      return n
    })
  }

  const filtered = useMemo(() =>
    DEMO_STRATEGIES.filter(s => activeStrategies.has(s.name)),
    [activeStrategies]
  )

  const sorted = useMemo(() =>
    [...filtered].sort((a, b) => {
      if (sortBy === 'roi') return b.roi - a.roi
      if (sortBy === 'winRate') return b.winRate - a.winRate
      if (sortBy === 'sharpe') return b.sharpe - a.sharpe
      return b.bets - a.bets
    }),
    [filtered, sortBy]
  )

  // Build P&L curve data for the line chart
  const pnlLineData = useMemo(() => {
    const maxLen = Math.max(...filtered.map(s => s.pnlCurve.length))
    return Array.from({ length: maxLen }, (_, i) => {
      const point: Record<string, number> = { bet: i + 1 }
      filtered.forEach(s => {
        if (i < s.pnlCurve.length) point[s.name] = s.pnlCurve[i]
      })
      return point
    })
  }, [filtered])

  // ROI bar chart data
  const roiBarData = sorted.map(s => ({
    name: s.name.length > 18 ? s.name.slice(0, 18) + '…' : s.name,
    fullName: s.name,
    roi: s.roi,
    color: s.roi > 0 ? '#ccff00' : s.roi > -10 ? '#f59e0b' : '#ef4444'
  }))

  // Radar chart data
  const radarData = [
    { metric: 'ROI', ...Object.fromEntries(sorted.slice(0, 5).map(s => [s.name, Math.max(0, s.roi + 40)])) },
    { metric: 'Win Rate', ...Object.fromEntries(sorted.slice(0, 5).map(s => [s.name, s.winRate])) },
    { metric: 'Sharpe', ...Object.fromEntries(sorted.slice(0, 5).map(s => [s.name, (s.sharpe + 0.3) * 200])) },
    { metric: 'Volume', ...Object.fromEntries(sorted.slice(0, 5).map(s => [s.name, Math.min(100, s.bets)])) },
    { metric: 'Safety', ...Object.fromEntries(sorted.slice(0, 5).map(s => [s.name, Math.max(0, 100 - s.maxDrawdown / 40)])) },
  ]

  return (
    <div className="strategies-page">
      {/* Strategy Toggle Bar */}
      <div className="strategy-toggles">
        <div className="toggle-header">
          <span className="toggle-title">📊 Strategy Filter</span>
          <div className="toggle-actions">
            <button className="toggle-btn" onClick={() => setActiveStrategies(new Set(DEMO_STRATEGIES.map(s => s.name)))}>All</button>
            <button className="toggle-btn" onClick={() => setActiveStrategies(new Set(DEMO_STRATEGIES.filter(s => s.source === 'ATPBetting').map(s => s.name)))}>ATPBetting</button>
            <button className="toggle-btn" onClick={() => setActiveStrategies(new Set(DEMO_STRATEGIES.filter(s => s.source === 'skemp15').map(s => s.name)))}>skemp15</button>
            <button className="toggle-btn" onClick={() => setActiveStrategies(new Set(DEMO_STRATEGIES.filter(s => s.source === 'NemoFish').map(s => s.name)))}>NemoFish</button>
          </div>
        </div>
        <div className="toggle-chips">
          {DEMO_STRATEGIES.map(s => (
            <button
              key={s.name}
              className={`strategy-chip ${activeStrategies.has(s.name) ? 'active' : 'inactive'}`}
              style={activeStrategies.has(s.name) ? { borderColor: s.color, boxShadow: `0 0 12px ${s.color}33` } : {}}
              onClick={() => toggleStrategy(s.name)}
            >
              <span className="chip-dot" style={{ background: s.color }} />
              {s.name}
              <span className="chip-source">{s.source}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Hero KPIs */}
      <div className="strategy-hero-kpis">
        <div className="strat-kpi best">
          <div className="strat-kpi-label">🏆 Best Strategy</div>
          <div className="strat-kpi-value">{sorted[0]?.name || '—'}</div>
          <div className="strat-kpi-sub positive">+{sorted[0]?.roi?.toFixed(1)}% ROI</div>
        </div>
        <div className="strat-kpi">
          <div className="strat-kpi-label">Active Strategies</div>
          <div className="strat-kpi-value">{filtered.length}</div>
          <div className="strat-kpi-sub">of {DEMO_STRATEGIES.length} total</div>
        </div>
        <div className="strat-kpi">
          <div className="strat-kpi-label">Total Bets Tracked</div>
          <div className="strat-kpi-value">{filtered.reduce((a, s) => a + s.bets, 0)}</div>
          <div className="strat-kpi-sub">{filtered.reduce((a, s) => a + s.wins, 0)} wins</div>
        </div>
        <div className="strat-kpi">
          <div className="strat-kpi-label">Highest Win Rate</div>
          <div className="strat-kpi-value">{Math.max(...filtered.map(s => s.winRate)).toFixed(1)}%</div>
          <div className="strat-kpi-sub">{filtered.find(s => s.winRate === Math.max(...filtered.map(x => x.winRate)))?.name}</div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="strategy-charts-row">
        {/* ROI Bar Chart */}
        <div className="card strategy-chart">
          <div className="card-title">
            💰 ROI by Strategy
            <div className="sort-controls">
              {(['roi', 'winRate', 'sharpe', 'bets'] as const).map(s => (
                <button key={s} className={`sort-btn ${sortBy === s ? 'active' : ''}`} onClick={() => setSortBy(s)}>
                  {s === 'roi' ? 'ROI' : s === 'winRate' ? 'WR%' : s === 'sharpe' ? 'Sharpe' : 'Volume'}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={roiBarData} layout="vertical" margin={{ left: 10, right: 30, top: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="name" width={160} tick={{ fill: '#e2e8f0', fontSize: 11, fontFamily: 'JetBrains Mono' }} />
              <Tooltip
                contentStyle={{ background: 'rgba(10, 17, 32, 0.95)', border: '1px solid rgba(14,165,233,0.3)', borderRadius: 12, fontSize: 12, color: '#f8fafc' }}
                formatter={(v: unknown) => [`${Number(v).toFixed(1)}%`, 'ROI']}
              />
              <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" />
              <Bar dataKey="roi" radius={[0, 6, 6, 0]}>
                {roiBarData.map((entry, i) => (
                  <Cell key={i} fill={entry.color} fillOpacity={0.85} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cumulative P&L Line Chart */}
        <div className="card strategy-chart">
          <div className="card-title">📈 Cumulative P&L Curve</div>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={pnlLineData} margin={{ left: 10, right: 30, top: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="bet" tick={{ fill: '#94a3b8', fontSize: 11 }} label={{ value: 'Bet #', position: 'insideBottom', offset: -5, fill: '#64748b' }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ background: 'rgba(10, 17, 32, 0.95)', border: '1px solid rgba(14,165,233,0.3)', borderRadius: 12, fontSize: 12, color: '#f8fafc' }}
                formatter={(v: unknown, name: unknown) => [`$${Number(v).toFixed(0)}`, String(name)]}
              />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeDasharray="4 4" />
              {filtered.map(s => (
                <Line key={s.name} type="monotone" dataKey={s.name} stroke={s.color} strokeWidth={2} dot={false} />
              ))}
              <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Radar + Stats Table Row */}
      <div className="strategy-charts-row">
        {/* Radar Chart */}
        <div className="card strategy-chart radar-card">
          <div className="card-title">🎯 Strategy Profile (Top 5)</div>
          <ResponsiveContainer width="100%" height={340}>
            <RadarChart data={radarData} margin={{ top: 20, right: 30, bottom: 20, left: 30 }}>
              <PolarGrid stroke="rgba(255,255,255,0.1)" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <PolarRadiusAxis tick={false} axisLine={false} />
              {sorted.slice(0, 5).map(s => (
                <Radar key={s.name} name={s.name} dataKey={s.name} stroke={s.color} fill={s.color} fillOpacity={0.1} strokeWidth={2} />
              ))}
              <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {/* Strategy Stats Table */}
        <div className="card strategy-chart">
          <div className="card-title">📋 Detailed Metrics</div>
          <div className="strategy-table-scroll">
            <table className="strategy-table">
              <thead>
                <tr>
                  <th>Strategy</th><th>Source</th><th>Bets</th><th>WR%</th>
                  <th>P&L</th><th>ROI</th><th>Sharpe</th><th>MaxDD</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(s => (
                  <tr key={s.name} className={s.roi > 0 ? 'row-profit' : ''}>
                    <td>
                      <span className="table-dot" style={{ background: s.color }} />
                      {s.name}
                    </td>
                    <td><span className={`source-tag tag-${s.source.toLowerCase()}`}>{s.source}</span></td>
                    <td className="mono">{s.bets}</td>
                    <td className="mono">{s.winRate.toFixed(1)}%</td>
                    <td className={`mono ${s.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
                      {s.pnl >= 0 ? '+' : ''}${s.pnl.toLocaleString()}
                    </td>
                    <td className={`mono bold ${s.roi >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
                      {s.roi >= 0 ? '+' : ''}{s.roi.toFixed(1)}%
                    </td>
                    <td className="mono">{s.sharpe.toFixed(3)}</td>
                    <td className="mono" style={{ color: 'var(--accent-red)' }}>${s.maxDrawdown.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

// === MAIN APP ===
function App() {
  const [time, setTime] = useState(new Date())
  const [activeTab, setActiveTab] = useState<'dashboard' | 'strategies'>('dashboard')
  const [kpi, setKpi] = useState<KpiData>(DEMO_KPI)
  const [signals, setSignals] = useState<BetSignal[]>(DEMO_SIGNALS)
  const [trades, setTrades] = useState<Trade[]>(DEMO_TRADES)
  const [liveMatches, setLiveMatches] = useState<ApiLiveMatch[]>([])
  const [liveSource, setLiveSource] = useState<string>('')
  const [liveTotal, setLiveTotal] = useState<number>(0)
  const [rankings, setRankings] = useState<Record<string, RankingEntry[]>>({})
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

      const [kpiRes, liveRes, rankingsRes, newsRes, oddsRes] = await Promise.all([
        fetchAPI<KpiData>('/api/kpi'),
        fetchAPI<{ matches: ApiLiveMatch[]; source: string; total_count: number; live_count: number }>('/api/live'),
        fetchAPI<{ rankings: Record<string, RankingEntry[]> }>('/api/rankings'),
        fetchAPI<{ news: NewsItem[] }>('/api/news'),
        fetchAPI<{ movements: OddsMovement[] }>('/api/odds'),
      ])

      if (kpiRes) setKpi(kpiRes)
      if (liveRes?.matches) {
        setLiveMatches(liveRes.matches)
        setLiveSource(liveRes.source || '')
        setLiveTotal(liveRes.total_count || liveRes.matches.length)
      }
      if (rankingsRes?.rankings) setRankings(rankingsRes.rankings)
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
      {/* Dynamic Background Elements */}
      <div className="bg-orb orb-1"></div>
      <div className="bg-orb orb-2"></div>
      <div className="bg-orb orb-3"></div>

      <header className="header">
        <div className="header-left">
          <div className="logo-container">
            <div className="logo-icon">🐡🎾</div>
            <div>
              <div className="logo">NEMOFISH<span className="logo-highlight"> TENNIS</span></div>
              <div className="logo-sub">God View Terminal • Powered by MiroFish Swarm</div>
            </div>
          </div>
          <nav className="nav-tabs">
            <button className={`nav-tab ${activeTab === 'dashboard' ? 'active' : ''}`} onClick={() => setActiveTab('dashboard')}>
              📊 Dashboard
            </button>
            <button className={`nav-tab ${activeTab === 'strategies' ? 'active' : ''}`} onClick={() => setActiveTab('strategies')}>
              🧪 Strategies
            </button>
          </nav>
        </div>
        <div className="header-right">
          <span className={`api-status ${apiConnected ? 'connected' : 'offline'}`}>
            {apiConnected ? '🟢 API SYNCED' : '🔴 DEMO MODE'}
            {apiConnected && liveSource && ` (${liveSource})`}
          </span>
          {apiConnected && liveTotal > 0 && (
            <span className="match-count">{liveTotal} matches scanned</span>
          )}
          <span className="mode-badge paper">PAPER TRADING</span>
          <span className="clock">{time.toLocaleString('en-US', { hour12: false })}</span>
        </div>
      </header>

      <main className="dashboard">
        {activeTab === 'strategies' ? (
          <StrategyComparison />
        ) : (
          <>
            {/* Row 1: Player Profile / Swarm Insight & KPIs */}
            <div className="top-row">
              <div className="card profile-card">
                <div className="card-title">🔍 Swarm Active Profile Search</div>
                <div className="profile-content">
                  <img src="https://ui-avatars.com/api/?name=Jannik+Sinner&background=0D8ABC&color=fff&size=64" alt="Player" className="profile-img" />
                  <div className="profile-details">
                    <div className="profile-name">Jannik Sinner 🇮🇹</div>
                    <div className="profile-stats">
                      <span>#1 ATP</span>
                      <span> • </span>
                      <span>Win Rate: 79% (Hard)</span>
                    </div>
                    <div className="profile-tags">
                      <span className="tag green">Aggressive L-Baseline</span>
                      <span className="tag blue">Elite Returner</span>
                    </div>
                  </div>
                  <div className="profile-h2h">
                    <div className="h2h-title">H2H vs Alcaraz</div>
                    <div className="h2h-score">4 - 6</div>
                    <div className="h2h-sub">Sackmann DB Insight</div>
                  </div>
                </div>
              </div>

              <div className="kpi-grid">
                <KpiCard label="Bankroll Engine" value={kpi.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2 })} change={`${totalReturn}%`} color="green" prefix="$" />
                <KpiCard label="Daily Delta" value={Math.abs(kpi.dailyPnl).toFixed(2)} color={kpi.dailyPnl >= 0 ? 'green' : 'red'} prefix={kpi.dailyPnl >= 0 ? '+$' : '-$'} />
                <KpiCard label="Swarm Win Rate" value={kpi.winRate.toFixed(1)} color="blue" suffix="%" />
                <KpiCard label="Risk vs Reward (ROI)" value={kpi.roi.toFixed(1)} color="amber" prefix="+" suffix="%" />
              </div>
            </div>

            {/* Row 2: Heatmap + Signals */}
            <div className="middle-row">
              <AgentHeatmap signals={signals} />
              <SignalsList signals={signals} />
            </div>

            {/* Row 3: Live Feeds & Markets & Rankings */}
            <div className="bottom-row">
              <div className="col-1">
                 <LiveEventFeed matches={liveMatches} source={liveSource} />
                 <RankingsPanel rankings={rankings} />
              </div>
              <div className="col-2">
                 <MarketReaction movements={oddsMovements} />
                 <TradeJournal trades={trades} />
              </div>
              <div className="col-3">
                 <NewsFeed news={news} />
                 <div className="card sackmann-stats">
                   <div className="card-title">🎾 JeffSackmann Data Engine</div>
                   <div className="sackmann-data">
                     <div className="db-stat"><span className="db-icon">📚</span> 143,530 Matches Loaded</div>
                     <div className="db-stat"><span className="db-icon">👤</span> 132,494 Player Profiles</div>
                     <div className="db-stat"><span className="db-icon">📍</span> Shot-by-Shot Matrix Active</div>
                     <div className="db-stat"><span className="db-icon">🧮</span> Live Probability Alg Sync</div>
                   </div>
                 </div>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export default App
