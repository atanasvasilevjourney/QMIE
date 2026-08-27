import type { DeskTab, DeskTheme } from '../types'

const TABS: { id: DeskTab; label: string }[] = [
  { id: 'orbit', label: 'Orbit' },
  { id: 'ops', label: 'Ops' },
  { id: 'screens', label: 'Screens' },
  { id: 'charts', label: 'Charts' },
  { id: 'guide', label: 'Guide' },
  { id: 'agents', label: 'Agents' },
  { id: 'book', label: 'Book' },
  { id: 'journal', label: 'Journal' },
  { id: 'flows', label: 'Flows' },
]

export function TopBar({
  tab,
  onTab,
  healthOk,
  uptime,
  source,
  universe,
  onRefresh,
  onRadar,
  onPaper,
  busy,
  theme,
  onTheme,
}: {
  tab: DeskTab
  onTab: (t: DeskTab) => void
  healthOk: boolean
  uptime: number
  source?: string
  universe: number
  onRefresh: () => void
  onRadar: () => void
  onPaper: () => void
  busy?: boolean
  theme: DeskTheme
  onTheme: () => void
}) {
  const light = theme === 'light'
  return (
    <header className="relative z-20 border-b border-line bg-void/95 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1920px] flex-col gap-3 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-panel">
              <span className="font-display text-sm font-bold text-cyan">Q</span>
            </div>
            <div>
              <h1 className="font-display text-lg font-bold tracking-tight text-ink">
                QMIE Desk
              </h1>
              <p className="text-sm text-muted">Signal-only · manual entry · never orders</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <StatusChip ok={healthOk} label={healthOk ? 'Online' : 'Degraded'} />
            <StatusChip ok label={`${universe} symbols`} />
            <StatusChip ok label={(source || '—').toUpperCase()} />
            <StatusChip ok label={`Up ${Math.floor(uptime)}s`} />
            <button
              type="button"
              onClick={onTheme}
              className="btn"
              aria-pressed={light}
              aria-label={light ? 'Switch to dark theme' : 'Switch to light theme'}
            >
              {light ? 'Light' : 'Dark'}
            </button>
            <button type="button" disabled={busy} onClick={onRefresh} className="btn btn-accent">
              Sync
            </button>
            <button type="button" disabled={busy} onClick={onRadar} className="btn btn-warn">
              Radar once
            </button>
            <button type="button" disabled={busy} onClick={onPaper} className="btn btn-ok">
              Paper sync
            </button>
          </div>
        </div>

        <nav className="flex flex-wrap gap-1" aria-label="Desk sections">
          {TABS.map((t) => {
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => onTab(t.id)}
                aria-current={active ? 'page' : undefined}
                className={`nav-tab ${active ? 'nav-tab-on' : ''}`}
              >
                {t.label}
              </button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`rounded-md border px-2.5 py-1 font-mono text-sm tabular ${
        ok
          ? 'border-line bg-panel text-ink'
          : 'border-magenta/40 bg-magenta/10 text-magenta'
      }`}
    >
      {ok && label === 'Online' ? (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-lime" aria-hidden="true" />
      ) : null}
      {label}
    </span>
  )
}
