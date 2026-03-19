import { useState, useEffect } from 'react'

const API_BASE = 'http://localhost:8888'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyRecord = Record<string, any>

export default function ReportView({ matchId }: { matchId: string }) {
  const [report, setReport] = useState<AnyRecord | null>(null)

  useEffect(() => {
    if (!matchId) return
    fetch(`${API_BASE}/api/match/${matchId}/report`)
      .then(r => r.json())
      .then(rp => setReport(rp))
      .catch(() => {})
  }, [matchId])

  if (!matchId || !report || report.error) {
    return <div className="workspace-empty"><div className="empty-icon">📝</div><h3>No report data</h3><p>Run scenario engine first</p></div>
  }

  const ds: AnyRecord = report.dossier_summary || {}
  const comp: AnyRecord = report.overlay_comparison || {}
  const adjustments: AnyRecord[] = report.adjustments || []

  return (
    <div className="report-page">
      {ds.player_a && (
        <div className="card">
          <div className="card-title">📋 Dossier Summary</div>
          <div className="report-grid">
            <div className="report-player">
              <div className="report-player-name">{ds.player_a.name}</div>
              <div className="report-player-stats">
                <span>Rank #{ds.player_a.ranking}</span>
                <span>Elo {ds.player_a.elo}</span>
              </div>
            </div>
            {ds.player_b && (
              <div className="report-player">
                <div className="report-player-name">{ds.player_b.name}</div>
                <div className="report-player-stats">
                  <span>Rank #{ds.player_b.ranking}</span>
                  <span>Elo {ds.player_b.elo}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {comp.baseline && (
        <div className="card">
          <div className="card-title">📊 Baseline vs Overlay</div>
          <table className="report-table">
            <thead><tr><th>Metric</th><th>Baseline</th><th>Adjusted</th><th>Delta</th></tr></thead>
            <tbody>
              <tr>
                <td>Prob A</td>
                <td className="mono">{(comp.baseline.prob_a * 100).toFixed(1)}%</td>
                <td className="mono">{(comp.adjusted.prob_a * 100).toFixed(1)}%</td>
                <td className={`mono ${comp.delta >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
                  {comp.delta >= 0 ? '+' : ''}{(comp.delta * 100).toFixed(2)}%
                </td>
              </tr>
              <tr>
                <td>Confidence</td>
                <td><span className={`badge badge-${comp.baseline.confidence?.toLowerCase()}`}>{comp.baseline.confidence}</span></td>
                <td><span className={`badge badge-${comp.adjusted.confidence?.toLowerCase()}`}>{comp.adjusted.confidence}</span></td>
                <td>{comp.baseline.confidence === comp.adjusted.confidence ? '—' : '↓'}</td>
              </tr>
              <tr>
                <td>Action</td>
                <td>{comp.baseline.action}</td>
                <td className="bold">{comp.adjusted.action}</td>
                <td>{comp.baseline.action !== comp.adjusted.action ? '⚠️ Changed' : '—'}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {adjustments.length > 0 && (
        <div className="card">
          <div className="card-title">🔍 What Mattered Most</div>
          <div className="report-adjustments">
            {adjustments.map((a, i) => (
              <div key={i} className="report-adj-item">
                <div className="report-adj-field">{a.source_signal || a.field}</div>
                <div className="report-adj-reason">{a.reason}</div>
                {a.delta !== undefined && (
                  <div className={`report-adj-delta ${a.delta >= 0 ? 'positive' : 'negative'}`}>
                    {a.delta >= 0 ? '+' : ''}{(a.delta * 100).toFixed(2)}%
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-title">ℹ️ Report Metadata</div>
        <div className="report-meta-grid">
          <span>Type: {String(report.report_type || '')}</span>
          <span>Generated: {String(report.generated_at || '')}</span>
          {report.match_label && <span>Match: {String(report.match_label)}</span>}
        </div>
      </div>
    </div>
  )
}
