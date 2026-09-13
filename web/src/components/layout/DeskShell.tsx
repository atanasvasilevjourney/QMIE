import type { DeskTab } from '../../types'

const NAV: { id: DeskTab; label: string; hint: string }[] = [
  { id: 'orbit', label: 'Orbit', hint: '3D universe' },
  { id: 'ops', label: 'Ops', hint: 'Radar + tables' },
  { id: 'screens', label: 'Screens', hint: 'Combo list' },
  { id: 'charts', label: 'Charts', hint: 'Equity + price' },
  { id: 'guide', label: 'Guide', hint: 'Playbook' },
  { id: 'agents', label: 'Agents', hint: 'Briefing' },
  { id: 'book', label: 'Book', hint: 'Allocation' },
  { id: 'journal', label: 'Journal', hint: 'Fills' },
  { id: 'flows', label: 'Flows', hint: 'Pipeline' },
]

export function DeskSidebar({
  tab,
  onTab,
}: {
  tab: DeskTab
  onTab: (t: DeskTab) => void
}) {
  return (
    <aside className="desk-sidebar hidden lg:block" aria-label="Desk sections">
      <p className="desk-sidebar-kicker">Modules</p>
      <nav className="desk-sidebar-nav">
        {NAV.map((item) => {
          const active = tab === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onTab(item.id)}
              aria-current={active ? 'page' : undefined}
              className={`desk-sidebar-item ${active ? 'desk-sidebar-item-on' : ''}`}
            >
              <span className="desk-sidebar-label">{item.label}</span>
              <span className="desk-sidebar-hint">{item.hint}</span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}

export function DeskShell({
  sidebar,
  children,
}: {
  sidebar?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="desk-shell">
      {sidebar}
      <div className="desk-shell-main min-w-0 flex-1">{children}</div>
    </div>
  )
}
