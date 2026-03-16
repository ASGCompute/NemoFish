import { useState, useEffect } from 'react'
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

// === Mock Data (would come from Python backend via API) ===
const DEMO_KPI: KpiData = {
  bankroll: 10198.88,
  totalPnl: 198.88,
  winRate: 66.7,
  totalBets: 3,
  activePositions: 0,
  maxDrawdown: 2.4,
  btcEquivalent: 0.142137,
  dailyPnl: 198.88,
  roi: 29.3,
  sharpe: 0.32,
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
  {
    id: 'NF-SKIP01', match: 'Sinner vs Medvedev', playerA: 'Jannik Sinner',
    playerB: 'Daniil Medvedev', pick: '-', odds: 1.35, edge: -0.013,
    betSize: 0, confidence: 'LOW', action: 'SKIP', surface: 'Hard', round: 'SF',
    modelProb: 0.726,
    agents: [
      { agentName: 'StatBot', role: 'Statistical', probA: 0.90, confidence: 0.9 },
      { agentName: 'PsychBot', role: 'Psychology', probA: 0.54, confidence: 0.6 },
      { agentName: 'MarketBot', role: 'Market', probA: 0.72, confidence: 0.8 },
      { agentName: 'ContrarianBot', role: 'Contrarian', probA: 0.50, confidence: 0.5 },
      { agentName: 'NewsBot', role: 'News', probA: 0.50, confidence: 0.5 },
    ],
  },
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

function ConfidenceBadge({ level }: { level: string }) {
  const cls = `badge badge-${level.toLowerCase()}`
  return <span className={cls}>{level}</span>
}

function getHeatColor(prob: number): string {
  if (prob >= 0.75) return 'rgba(34, 197, 94, 0.5)'
  if (prob >= 0.60) return 'rgba(34, 197, 94, 0.25)'
  if (prob >= 0.55) return 'rgba(59, 130, 246, 0.2)'
  if (prob >= 0.45) return 'rgba(100, 116, 139, 0.15)'
  if (prob >= 0.35) return 'rgba(239, 68, 68, 0.25)'
  return 'rgba(239, 68, 68, 0.4)'
}

function AgentHeatmap({ signals }: { signals: BetSignal[] }) {
  const agentRoles = ['Statistical', 'Psychology', 'Market', 'Contrarian', 'News']
  const betSignals = signals.filter(s => s.action === 'BET')

  return (
    <div className="card agent-heatmap">
      <div className="card-title">🤖 Agent Consensus Heatmap</div>
      <div className="heatmap-grid">
        <div className="heatmap-row">
          <div className="heatmap-header" style={{ textAlign: 'left' }}>Match</div>
          {agentRoles.map(r => (
            <div key={r} className="heatmap-header">{r.slice(0, 4)}</div>
          ))}
        </div>
        {betSignals.map(signal => (
          <div key={signal.id} className="heatmap-row">
            <div className="heatmap-label">{signal.match}</div>
            {signal.agents.map((agent, i) => (
              <div
                key={i}
                className="heatmap-cell"
                style={{ background: getHeatColor(agent.probA) }}
                title={`${agent.role}: ${signal.playerA} ${(agent.probA * 100).toFixed(0)}%`}
              >
                {(agent.probA * 100).toFixed(0)}%
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function SignalsList({ signals }: { signals: BetSignal[] }) {
  return (
    <div className="card signals">
      <div className="card-title">⚡ Bet Signals — Miami Open 2026</div>
      <div className="signal-list">
        {signals.map(signal => (
          <div key={signal.id} className={`signal-item ${signal.action === 'BET' ? 'bet' : 'skip'}`}>
            <div className="signal-pick">
              <div className="signal-match">
                {signal.action === 'BET' ? '🎾' : '⏸️'} {signal.match}
              </div>
              <div className="signal-detail">
                {signal.action === 'BET' ? `Pick: ${signal.pick} @ ${signal.odds.toFixed(2)}` : 'No edge'}
                {' • '}{signal.round} • {signal.surface}
                {' • '}<ConfidenceBadge level={signal.confidence} />
              </div>
            </div>
            <div className={`signal-edge ${signal.edge > 0 ? 'positive' : 'negative'}`}>
              {signal.edge > 0 ? '+' : ''}{(signal.edge * 100).toFixed(1)}%
            </div>
            {signal.betSize > 0 && (
              <div className="signal-bet">${signal.betSize.toFixed(0)}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function TradeJournal({ trades }: { trades: Trade[] }) {
  return (
    <div className="card journal">
      <div className="card-title">📋 Trade Journal</div>
      <table className="journal-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Time</th>
            <th>Match</th>
            <th>Pick</th>
            <th>Odds</th>
            <th>Edge</th>
            <th>Size</th>
            <th>Confidence</th>
            <th>Result</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map(trade => (
            <tr key={trade.id}>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
                {trade.id}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>{trade.timestamp}</td>
              <td>{trade.match}</td>
              <td style={{ fontWeight: 600 }}>{trade.pick}</td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>{trade.odds.toFixed(2)}</td>
              <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-green)' }}>
                +{(trade.edge * 100).toFixed(1)}%
              </td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>${trade.betSize.toFixed(0)}</td>
              <td><ConfidenceBadge level={trade.confidence} /></td>
              <td>
                {trade.won === null ? (
                  <span className="status-open">OPEN</span>
                ) : trade.won ? (
                  <span className="status-won">✅ WON</span>
                ) : (
                  <span className="status-lost">❌ LOST</span>
                )}
              </td>
              <td className={trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// === Main App ===
function App() {
  const [time, setTime] = useState(new Date())
  const [kpi] = useState<KpiData>(DEMO_KPI)
  const [signals] = useState<BetSignal[]>(DEMO_SIGNALS)
  const [trades] = useState<Trade[]>(DEMO_TRADES)

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  const totalReturn = ((kpi.bankroll / 10000 - 1) * 100).toFixed(1)

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <div>
            <div className="logo">🐡 NEMOFISH</div>
            <div className="logo-sub">God View Terminal</div>
          </div>
        </div>
        <div className="header-right">
          <span className="mode-badge paper">PAPER</span>
          <span className="clock">{time.toLocaleString('en-US', { hour12: false })}</span>
        </div>
      </header>

      {/* Dashboard Grid */}
      <main className="dashboard">
        {/* KPI Row */}
        <div className="kpi-row">
          <KpiCard
            label="Bankroll"
            value={kpi.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            change={`${totalReturn}%`}
            color="green"
            prefix="$"
          />
          <KpiCard
            label="BTC Equivalent"
            value={kpi.btcEquivalent.toFixed(6)}
            color="amber"
            prefix="₿"
          />
          <KpiCard
            label="Daily P&L"
            value={kpi.dailyPnl.toFixed(2)}
            color={kpi.dailyPnl >= 0 ? 'green' : 'red'}
            prefix={kpi.dailyPnl >= 0 ? '+$' : '-$'}
          />
          <KpiCard
            label="Win Rate"
            value={kpi.winRate.toFixed(1)}
            color="blue"
            suffix="%"
          />
          <KpiCard
            label="ROI"
            value={kpi.roi.toFixed(1)}
            color="purple"
            prefix="+"
            suffix="%"
          />
          <KpiCard
            label="Max Drawdown"
            value={kpi.maxDrawdown.toFixed(1)}
            color={kpi.maxDrawdown > 10 ? 'red' : 'green'}
            suffix="%"
          />
        </div>

        {/* Agent Heatmap + Signals */}
        <AgentHeatmap signals={signals} />
        <SignalsList signals={signals} />

        {/* Trade Journal */}
        <TradeJournal trades={trades} />
      </main>
    </div>
  )
}

export default App
