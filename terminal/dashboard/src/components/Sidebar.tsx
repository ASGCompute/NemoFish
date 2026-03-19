


type TabId = 'live' | 'workspace' | 'graph' | 'simulation' | 'report' | 'research'

interface SidebarProps {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  collapsed: boolean
  onToggle: () => void
}

const TABS: { id: TabId; icon: string; label: string }[] = [
  { id: 'live', icon: '📡', label: 'Live' },
  { id: 'workspace', icon: '🎯', label: 'Match' },
  { id: 'graph', icon: '🕸️', label: 'Graph' },
  { id: 'simulation', icon: '🧪', label: 'Simulation' },
  { id: 'report', icon: '📝', label: 'Report' },
  { id: 'research', icon: '📊', label: 'Research' },
]

export default function Sidebar({ activeTab, onTabChange, collapsed, onToggle }: SidebarProps) {
  return (
    <nav className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-logo" onClick={onToggle}>
        <span className="sidebar-logo-icon">🐡</span>
        {!collapsed && <span className="sidebar-logo-text">NEMOFISH</span>}
      </div>
      <div className="sidebar-nav">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`sidebar-item ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => onTabChange(tab.id)}
            title={tab.label}
          >
            <span className="sidebar-icon">{tab.icon}</span>
            {!collapsed && <span className="sidebar-label">{tab.label}</span>}
          </button>
        ))}
      </div>
      <div className="sidebar-footer">
        <button className="sidebar-item" onClick={onToggle} title={collapsed ? 'Expand' : 'Collapse'}>
          <span className="sidebar-icon">{collapsed ? '→' : '←'}</span>
          {!collapsed && <span className="sidebar-label">Collapse</span>}
        </button>
      </div>
    </nav>
  )
}

export type { TabId }
