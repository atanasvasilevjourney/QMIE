import { motion } from 'framer-motion'
import type { DeskTab, DeskTheme } from '../types'

const TABS: { id: DeskTab; label: string; hint: string }[] = [
  { id: 'orbit', label: 'ORBIT', hint: 'Orbis Universe' },
  { id: 'ops', label: 'OPS', hint: 'Radar + strategy tables' },
  { id: 'charts', label: 'CHARTS', hint: 'Equity + trade marks' },
  { id: 'guide', label: 'GUIDE', hint: 'How to trade' },
  { id: 'agents', label: 'AGENTS', hint: 'Briefing + take' },
  { id: 'book', label: 'BOOK', hint: 'Ranked allocation' },
  { id: 'journal', label: 'JOURNAL', hint: 'Manual fills' },
  { id: 'flows', label: 'FLOWS', hint: 'Operator path' },
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
    <header className="relative z-20 border-b border-cyan/15 bg-void/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1920px] flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          <div className="relative grid h-12 w-12 place-items-center rounded-2xl neon-border glass">
            <span className="font-display text-sm font-bold text-cyan">Q</span>
            <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-lime shadow-[0_0_12px_currentColor]" />
          </div>
          <div>
            <h1 className="font-display text-lg font-bold tracking-[0.18em] text-ink uppercase sm:text-xl">
              QMIE <span className="text-magenta">DESK</span>
            </h1>
            <p className="font-mono text-[11px] text-chrome/70">
              signal-only · cyber radar · manual entry
            </p>
          </div>
        </div>

        <nav className="flex flex-wrap gap-2">
          {TABS.map((t) => {
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => onTab(t.id)}
                className={`min-w-[7.5rem] rounded-2xl px-4 py-3 text-left transition ${
                  active
                    ? 'neon-border bg-cyan/10 text-cyan'
                    : 'border border-line/15 bg-surface/40 text-chrome/80 hover:border-cyan/30 hover:text-ink'
                }`}
              >
                <div className="font-display text-xs tracking-[0.22em]">{t.label}</div>
                <div className="font-mono text-[11px] opacity-60">{t.hint}</div>
              </button>
            )
          })}
        </nav>

        <div className="flex flex-wrap items-center gap-2">
          <StatusChip ok={healthOk} label={healthOk ? 'ONLINE' : 'DEGRADED'} />
          <StatusChip ok label={`${universe} SYM`} />
          <StatusChip ok label={(source || '—').toUpperCase()} />
          <StatusChip ok label={`UP ${Math.floor(uptime)}s`} />
          <motion.button
            whileTap={{ scale: 0.97 }}
            type="button"
            onClick={onTheme}
            className={`min-w-[7.5rem] rounded-2xl px-4 py-3 text-left ${
              light
                ? 'border border-line/20 bg-surface text-ink'
                : 'border border-cyan/30 bg-cyan/10 text-cyan'
            }`}
          >
            <div className="font-display text-xs tracking-[0.22em]">{light ? 'LIGHT' : 'DARK'}</div>
            <div className="font-mono text-[11px] opacity-60">theme</div>
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            type="button"
            disabled={busy}
            onClick={onRefresh}
            className="rounded-2xl border border-cyan/30 bg-cyan/10 px-4 py-3 font-display text-xs tracking-widest text-cyan disabled:opacity-40"
          >
            SYNC
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            type="button"
            disabled={busy}
            onClick={onRadar}
            className="rounded-2xl border border-magenta/40 bg-magenta/10 px-4 py-3 font-display text-xs tracking-widest text-magenta disabled:opacity-40"
          >
            RADAR ONCE
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            type="button"
            disabled={busy}
            onClick={onPaper}
            className="rounded-2xl border border-lime/40 bg-lime/10 px-4 py-3 font-display text-xs tracking-widest text-lime disabled:opacity-40"
          >
            PAPER SYNC
          </motion.button>
        </div>
      </div>
    </header>
  )
}

function StatusChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`rounded-lg border px-2.5 py-1.5 font-mono text-[10px] tracking-wider ${
        ok
          ? 'border-lime/30 bg-lime/5 text-lime'
          : 'border-magenta/40 bg-magenta/10 text-magenta'
      }`}
    >
      {label}
    </span>
  )
}
