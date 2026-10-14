import { navForPersona } from '../../deskNav'
import type { DeskPersona } from '../../hooks/usePersona'
import type { DeskTab } from '../../types'

export function DeskSidebar({
  tab,
  persona,
  onTab,
}: {
  tab: DeskTab
  persona: DeskPersona | null
  onTab: (t: DeskTab) => void
}) {
  const nav = navForPersona(persona)

  return (
    <aside className="desk-sidebar hidden lg:block" aria-label="Desk sections">
      <p className="desk-sidebar-kicker">{persona ? (persona === 'observer' ? 'Observer path' : 'Spaceman path') : 'Modules'}</p>
      <nav className="desk-sidebar-nav">
        {nav.map((item) => {
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
