import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQmieDesk } from './hooks/useQmieDesk'
import { useTheme } from './hooks/useTheme'
import type { DeskTab, SignalRow } from './types'
import { Scene3D } from './components/Scene3D'
import { TopBar } from './components/TopBar'
import { RadarPanel } from './components/RadarPanel'
import { SignalsPanel } from './components/SignalsPanel'
import { AllocationPanel } from './components/AllocationPanel'
import { JournalFlow } from './components/JournalFlow'
import { FlowsPanel } from './components/FlowsPanel'
import { AgentsPanel } from './components/AgentsPanel'
import { GuidePanel } from './components/GuidePanel'

export default function App() {
  const [tab, setTab] = useState<DeskTab>('orbit')
  const [selected, setSelected] = useState<SignalRow | null>(null)
  const [busy, setBusy] = useState(false)
  const [radarMsg, setRadarMsg] = useState<string | null>(null)
  const desk = useQmieDesk()
  const { theme, toggle: toggleTheme } = useTheme()

  const healthOk = desk.health?.status === 'ok' && !!desk.health?.db_ok
  const uptime = desk.health?.uptime_sec ?? 0
  const radarFailed = !!radarMsg && !radarMsg.startsWith('Radar pass') && !radarMsg.startsWith('Paper')

  const onRadar = async () => {
    setBusy(true)
    setRadarMsg(null)
    try {
      await desk.forceRadar()
      setRadarMsg('Radar pass queued — syncing snapshot')
    } catch (e) {
      setRadarMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const onPaper = async () => {
    setBusy(true)
    setRadarMsg(null)
    try {
      const result = await desk.forcePaper()
      setRadarMsg(
        `Paper sync · opened ${result.opened ?? 0} · exits ${result.closed ?? 0} · never orders`,
      )
    } catch (e) {
      setRadarMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const gradeMix = useMemo(() => {
    const g = { A_PLUS: 0, A: 0, B: 0, C: 0 }
    for (const s of desk.signals) {
      const key = s.grade === 'A+' ? 'A_PLUS' : (s.grade as keyof typeof g)
      if (key in g) g[key] += 1
    }
    return g
  }, [desk.signals])

  const goJournal = (s: SignalRow) => {
    setSelected(s)
    setTab('journal')
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      <div className="pointer-events-none fixed inset-0 grid-floor opacity-40" />
      <div className="pointer-events-none fixed -left-24 top-10 h-80 w-80 rounded-full bg-magenta/20 blur-3xl theme-blob" />
      <div className="pointer-events-none fixed right-0 top-32 h-96 w-96 rounded-full bg-cyan/15 blur-3xl theme-blob" />

      <TopBar
        tab={tab}
        onTab={setTab}
        healthOk={healthOk}
        uptime={uptime}
        source={desk.health?.data_source}
        universe={desk.universeCount}
        onRefresh={() => void desk.refresh()}
        onRadar={() => void onRadar()}
        onPaper={() => void onPaper()}
        busy={busy || desk.loading}
        theme={theme}
        onTheme={toggleTheme}
      />

      <main className="relative z-10 mx-auto max-w-[1920px] px-4 py-6 sm:px-6">
        {(desk.error || radarMsg) && (
          <div
            className={`mb-5 rounded-2xl border px-5 py-4 font-mono text-sm ${
              desk.error || radarFailed
                ? 'border-magenta/40 bg-magenta/10 text-magenta'
                : 'border-cyan/40 bg-cyan/10 text-cyan'
            }`}
          >
            {desk.error ? `Sync: ${desk.error}` : null}
            {desk.error && radarMsg ? ' · ' : null}
            {radarMsg}
          </div>
        )}

        <AnimatePresence mode="wait">
          {tab === 'orbit' && (
            <motion.div
              key="orbit"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="font-display text-xs tracking-[0.4em] text-magenta uppercase">Landing</p>
                  <h2 className="font-display text-3xl tracking-wide text-ink md:text-4xl">
                    Orbis <span className="text-cyan">Universe</span>
                  </h2>
                  <p className="mt-2 max-w-3xl font-mono text-sm text-chrome/60">
                    RGG nebula + orbit tokens. Operations (radar + TEMA / daily-breakout tables) live on OPS.
                    Signal-only — never orders.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setTab('ops')}
                  className="rounded-2xl border border-cyan/40 bg-cyan/10 px-6 py-4 font-display text-sm tracking-[0.22em] text-cyan"
                >
                  OPEN OPS
                </button>
              </div>
              <div className="h-[min(78vh,860px)] min-h-[520px]">
                <Scene3D radar={desk.radar} signalCount={desk.signals.length} allowZoom />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <MiniStat label="A / A+" value={gradeMix.A + gradeMix.A_PLUS} tone="text-amber" />
                <MiniStat label="Signals" value={desk.signals.length} tone="text-cyan" />
                <MiniStat label="Universe" value={desk.universeCount} tone="text-lime" />
                <MiniStat
                  label="Synced"
                  value={desk.lastSync ? new Date(desk.lastSync).toLocaleTimeString() : '—'}
                  tone="text-chrome/70"
                  mono={false}
                />
              </div>
            </motion.div>
          )}

          {tab === 'ops' && (
            <motion.div
              key="ops"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
              className="grid gap-5"
            >
              <div>
                <p className="font-display text-xs tracking-[0.4em] text-magenta uppercase">Operations</p>
                <h2 className="font-display text-2xl tracking-wide text-ink md:text-3xl">
                  Radar + <span className="text-cyan">strategy tables</span>
                </h2>
              </div>
              <RadarPanel radar={desk.radar} />
              {desk.paper && (
                <div className="card rounded-2xl px-5 py-4 font-mono text-sm text-chrome/80">
                  Paper book · {desk.paper.open} open · {desk.paper.closed} closed · PnL{' '}
                  <span className={desk.paper.closed_pnl >= 0 ? 'text-lime' : 'text-magenta'}>
                    {desk.paper.closed_pnl}
                  </span>{' '}
                  USDT · never orders
                </div>
              )}
              <SignalsPanel signals={desk.signals} selectedId={selected?.id} onSelect={goJournal} />
            </motion.div>
          )}

          {tab === 'guide' && (
            <motion.div
              key="guide"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <GuidePanel guide={desk.guide} />
            </motion.div>
          )}

          {tab === 'agents' && (
            <motion.div
              key="agents"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <AgentsPanel briefing={desk.briefing} graph={desk.desk} loading={desk.loading} />
            </motion.div>
          )}

          {tab === 'book' && (
            <motion.div
              key="book"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <AllocationPanel plan={desk.allocation} />
            </motion.div>
          )}

          {tab === 'journal' && (
            <motion.div
              key="journal"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <JournalFlow
                selected={selected}
                fills={desk.fills}
                stats={desk.stats}
                onDone={() => void desk.refresh()}
              />
            </motion.div>
          )}

          {tab === 'flows' && (
            <motion.div
              key="flows"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <FlowsPanel />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      <footer className="relative z-10 border-t border-line/10 px-4 py-4 text-center font-mono text-xs text-chrome/50">
        QMIE Desk · Orbis landing · OPS strategy tables · never places orders
      </footer>
    </div>
  )
}

function MiniStat({
  label,
  value,
  tone,
  mono = true,
}: {
  label: string
  value: string | number
  tone: string
  mono?: boolean
}) {
  return (
    <div className="card rounded-2xl px-5 py-4">
      <div className="font-display text-[10px] tracking-widest text-chrome/50 uppercase">{label}</div>
      <div className={`mt-1 ${mono ? 'font-mono text-xl' : 'font-mono text-base'} ${tone}`}>{value}</div>
    </div>
  )
}
