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
import { ChartsPanel } from './components/ChartsPanel'
import { ScreensPanel } from './components/ScreensPanel'
import { DeskShell, DeskSidebar } from './components/layout/DeskShell'
import { PageHeader } from './components/layout/ModuleCard'

export default function App() {
  const [tab, setTab] = useState<DeskTab>('orbit')
  const [selected, setSelected] = useState<SignalRow | null>(null)
  const [chartFocus, setChartFocus] = useState<{ symbol: string; timeframe?: string } | null>(null)
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

  const goChart = (symbol: string, timeframe?: string) => {
    setChartFocus({ symbol, timeframe })
    setTab('charts')
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      <a href="#desk-main" className="skip-link">Skip to desk</a>
      <div className="pointer-events-none fixed inset-0 grid-floor opacity-30" />
      <div className="pointer-events-none fixed -left-24 top-10 h-64 w-64 rounded-full bg-cyan/10 blur-3xl theme-blob" />
      <div className="pointer-events-none fixed right-0 top-32 h-72 w-72 rounded-full bg-lime/10 blur-3xl theme-blob" />

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

      <main id="desk-main" className="relative z-10 mx-auto max-w-[1920px] px-4 py-8 sm:px-8 lg:py-10">
        <DeskShell sidebar={<DeskSidebar tab={tab} onTab={setTab} />}>
        {(desk.error || radarMsg) && (
          <div
            role="status"
            aria-live="polite"
            className={`mb-6 rounded-xl border px-4 py-3 text-sm ${
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
              <PageHeader
                kicker="Landing"
                title="Orbis"
                highlight="Universe"
                lede="Glass core and crypto logos on the rails. Radar and strategy tables live on Ops. Signal-only — never orders."
                actions={
                  <button type="button" onClick={() => setTab('ops')} className="btn btn-accent">
                    Open Ops
                  </button>
                }
              />
              <div className="h-[min(78vh,860px)] min-h-[520px]">
                <Scene3D radar={desk.radar} signalCount={desk.signals.length} allowZoom />
              </div>
              <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
                <MiniStat label="A / A+" value={gradeMix.A + gradeMix.A_PLUS} tone="text-amber" />
                <MiniStat label="Signals" value={desk.signals.length} tone="text-cyan" />
                <MiniStat label="Universe" value={desk.universeCount} tone="text-lime" />
                <MiniStat
                  label="Synced"
                  value={desk.lastSync ? new Date(desk.lastSync).toLocaleTimeString() : '—'}
                  tone="text-muted"
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
              className="module-grid"
            >
              <PageHeader
                kicker="Operations"
                title="Radar +"
                highlight="strategy tables"
                lede="Trend Radar is the spot book (1D coil-UP). TEMA BUY is the leveraged USDT-perp add. Never orders."
              />
              <div className="grid gap-8 xl:grid-cols-12">
                <div className="xl:col-span-8">
                  <RadarPanel radar={desk.radar} />
                </div>
                <aside className="module-grid xl:col-span-4">
                  {desk.paper && (
                    <div className="module-card">
                      <header className="module-card-header">
                        <h2 className="module-card-title">Paper book</h2>
                      </header>
                      <div className="module-card-body grid gap-4">
                        <div className="grid grid-cols-2 gap-3">
                          <MiniStat label="Open" value={desk.paper.open} tone="text-cyan" />
                          <MiniStat label="Closed" value={desk.paper.closed} tone="text-muted" />
                        </div>
                        <p className="text-sm text-muted">
                          PnL{' '}
                          <span className={`font-mono tabular ${desk.paper.closed_pnl >= 0 ? 'text-lime' : 'text-magenta'}`}>
                            {desk.paper.closed_pnl} USDT
                          </span>
                          · never orders
                        </p>
                      </div>
                    </div>
                  )}
                  <div className="module-card">
                    <header className="module-card-header">
                      <h2 className="module-card-title">Quick read</h2>
                    </header>
                    <div className="module-card-body space-y-3 text-sm text-muted">
                      <p>
                        <span className="font-semibold text-ink">Spot:</span> Radar expansions &amp; daily flip
                      </p>
                      <p>
                        <span className="font-semibold text-ink">Leverage:</span> TEMA A/A+ on 4h
                      </p>
                      <p>
                        <span className="font-semibold text-ink">Alerts:</span> Discord / Telegram on the API host
                      </p>
                    </div>
                  </div>
                </aside>
              </div>
              <SignalsPanel
                signals={desk.signals}
                selectedId={selected?.id}
                onSelect={goJournal}
                onChart={goChart}
              />
            </motion.div>
          )}

          {tab === 'screens' && (
            <motion.div
              key="screens"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <PageHeader
                kicker="Screens"
                title="Combo"
                highlight="review list"
                lede="Unique symbols from 4h A/A+, spot expansions, color-flip, coils, and ranked book. Not a new score."
              />
              <ScreensPanel lastSync={desk.lastSync} fills={desk.fills} onChart={goChart} />
            </motion.div>
          )}

          {tab === 'charts' && (
            <motion.div
              key="charts"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              <PageHeader
                kicker="Charts"
                title="Equity +"
                highlight="visualised trades"
                lede="SVG from closed fills and closed klines. Not TradingView. Not an order ticket."
              />
              <ChartsPanel
                focusSymbol={chartFocus?.symbol}
                focusTimeframe={chartFocus?.timeframe}
                fills={desk.fills}
              />
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
                onViewChart={goChart}
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
        </DeskShell>
      </main>

      <footer className="relative z-10 border-t border-line px-4 py-4 text-center text-sm text-muted">
        QMIE Desk · Orbit landing · Ops strategy tables · never places orders
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
    <div className="stat-tile">
      <div className="text-sm font-semibold text-muted">{label}</div>
      <div className={`mt-1 ${mono ? 'font-mono text-xl tabular' : 'font-mono text-base tabular'} ${tone}`}>{value}</div>
    </div>
  )
}
