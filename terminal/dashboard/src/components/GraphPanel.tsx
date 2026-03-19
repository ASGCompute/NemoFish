import { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8888'

interface GraphNode { id: string; label: string; type: string; group: string; data?: Record<string, any> }
interface GraphEdge { source: string; target: string; label: string }

const GROUP_COLORS: Record<string, string> = {
  player: '#ccff00', context: '#0ea5e9', match: '#c084fc',
  data: '#22c55e', market: '#f59e0b', risk: '#ef4444',
}

export default function GraphPanel({ matchId }: { matchId: string }) {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})

  useEffect(() => {
    if (!matchId) return
    fetch(`${API_BASE}/api/match/${matchId}/graph`)
      .then(r => r.json())
      .then(d => {
        setNodes(d.nodes || [])
        setEdges(d.edges || [])
        // Compute circular layout
        const pos: Record<string, { x: number; y: number }> = {}
        const cx = 400, cy = 300, r = 220
        ;(d.nodes || []).forEach((n: GraphNode, i: number) => {
          const angle = (2 * Math.PI * i) / (d.nodes || []).length - Math.PI / 2
          pos[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
        })
        setPositions(pos)
      })
      .catch(() => {})
  }, [matchId])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || nodes.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = 800 * dpr
    canvas.height = 600 * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, 800, 600)

    // Draw edges
    edges.forEach(e => {
      const s = positions[e.source], t = positions[e.target]
      if (!s || !t) return
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
      ctx.strokeStyle = 'rgba(14, 165, 233, 0.3)'
      ctx.lineWidth = 1.5
      ctx.stroke()
      // Edge label
      const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2
      ctx.font = '9px Inter'
      ctx.fillStyle = 'rgba(148, 163, 184, 0.7)'
      ctx.textAlign = 'center'
      ctx.fillText(e.label, mx, my - 4)
    })

    // Draw nodes
    nodes.forEach(n => {
      const p = positions[n.id]
      if (!p) return
      const color = GROUP_COLORS[n.group] || '#94a3b8'

      // Glow
      ctx.beginPath()
      ctx.arc(p.x, p.y, 28, 0, Math.PI * 2)
      ctx.fillStyle = color + '15'
      ctx.fill()

      // Circle
      ctx.beginPath()
      ctx.arc(p.x, p.y, 22, 0, Math.PI * 2)
      ctx.fillStyle = '#0a1120'
      ctx.fill()
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.stroke()

      // Label
      ctx.font = 'bold 11px Inter'
      ctx.fillStyle = '#f8fafc'
      ctx.textAlign = 'center'
      ctx.fillText(n.label.length > 12 ? n.label.slice(0, 12) + '…' : n.label, p.x, p.y + 4)

      // Type badge
      ctx.font = '8px JetBrains Mono'
      ctx.fillStyle = color
      ctx.fillText(n.type, p.x, p.y + 40)
    })
  }, [nodes, edges, positions])

  if (!matchId) {
    return <div className="workspace-empty"><div className="empty-icon">🕸️</div><h3>Select a match to view its graph</h3></div>
  }

  if (nodes.length === 0) {
    return <div className="workspace-empty"><div className="empty-icon">🕸️</div><h3>No graph data available</h3><p>Run scenario engine first</p></div>
  }

  return (
    <div className="graph-panel">
      <div className="card">
        <div className="card-title">🕸️ Match Entity Graph</div>
        <canvas ref={canvasRef} style={{ width: 800, height: 600, maxWidth: '100%' }} />
        <div className="graph-legend">
          {Object.entries(GROUP_COLORS).map(([k, v]) => (
            <span key={k} className="graph-legend-item">
              <span className="graph-legend-dot" style={{ background: v }} />
              {k}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
