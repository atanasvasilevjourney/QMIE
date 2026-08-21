import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useQmieDesk } from './hooks/useQmieDesk'
import type { DeskTab, SignalRow } from './types'
import { Scene3D } from './components/Scene3D'
import { TopBar } from './components/TopBar'
import { RadarPanel } from './components/RadarPanel'
import { SignalsPanel } from './components/SignalsPanel'
import { AllocationPanel } from './components/AllocationPanel'
import { JournalFlow } from './components/JournalFlow'
import { FlowsPanel } from './components/FlowsPanel'
import { AgentsPanel } from './components/AgentsPanel'

export default function App() {
  const [tab, setTab] = useState<DeskTab>('desk')
  const [selected, setSelected] = useState<SignalRow | null>(null)
  const [busy, setBusy] = useState(false)
  const [radarMsg, setRadarMsg] = useState<string | null>(null)
  const desk = useQmieDesk()

  const healthOk = desk.health?.status === 'ok' && !!desk.health?.db_ok
  const uptime = desk.health?.uptime_sec ?? 0
  const radarFailed = !!radarMsg && !radarMsg.startsWith('Radar pass')

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

  const gradeMix = useMemo(() => {
    const g = { A_PLUS: 0, A: 0, B: 0, C: 0 }
    for (const s of desk.signals) {
      const key = s.grade === 'A+' ? 'A_PLUS' : (s.grade as keyof typeof g)
      if (key in g) g[key] += 1
    }
    return g
  }, [desk.signals])

  return (
    <div className="relative min-h-screen overflow-x-hidden">
      <div className="pointer-events-none fixed inset-0 grid-floor opacity-40" />
      <div className="pointer-events-none fixed -left-24 top-10 h-80 w-80 rounded-full bg-magenta/20 blur-3xl" />
      <div className="pointer-events-none fixed right-0 top-32 h-96 w-96 rounded-full bg-cyan/15 blur-3xl" />

      <TopBar
        tab={tab}
        onTab={setTab}
        healthOk={healthOk}
        uptime={uptime}
        source={desk.health?.data_source}
        universe={desk.universeCount}
        onRefresh={() => void desk.refresh()}
        onRadar={() => void onRadar()}
        busy={busy || desk.loading}
      />

      <main className="relative z-10 mx-auto max-w-[1600px] px-4 py-5 sm:px-5">
        {(desk.error || radarMsg) && (
          <div
            className={`mb-4 rounded-2xl border px-4 py-3 font-mono text-xs ${
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
          {tab === 'desk' && (
            <motion.div
              key="desk"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
              className="grid gap-4 lg:grid-cols-12"
            >
              <div className="lg:col-span-5">
                <div className="mb-3">
                  <p className="font-display text-[11px] tracking-[0.35em] text-magenta uppercase">
                    Ops viewport
                  </p>
                  <h2 className="font-display text-xl tracking-wide text-white md:text-2xl">
                    Signal <span className="text-cyan">Universe</span>
                  </h2>
                </div>
                <div className="h-[min(62vh,560px)] min-h-[420px]">
                  <Scene3D radar={desk.radar} signalCount={desk.signals.length} />
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <MiniStat label="A / A+" value={gradeMix.A + gradeMix.A_PLUS} tone="text-amber" />
                  <MiniStat label="Signals" value={desk.signals.length} tone="text-cyan" />
                  <MiniStat
                    label="Synced"
                    value={desk.lastSync ? new Date(desk.lastSync).toLocaleTimeString() : '—'}
                    tone="text-chrome/70"
                    mono={false}
                  />
                </div>
              </div>
              <div className="grid gap-4 lg:col-span-7 lg:grid-cols-2">
                <RadarPanel radar={desk.radar} />
                <SignalsPanel
                  signals={desk.signals}
                  selectedId={selected?.id}
                  onSelect={(s) => {
                    setSelected(s)
                    setTab('journal')
                  }}
                />
              </div>
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

      <footer className="relative z-10 border-t border-white/5 px-4 py-4 text-center font-mono text-[10px] text-chrome/40">
        QMIE Desk · signal-only cyber ops · Discord/Telegram optional · never places orders
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
    <div className="rounded-2xl border border-white/10 bg-black/30 px-3 py-2">
      <div className="font-display text-[9px] tracking-widest text-chrome/50 uppercase">{label}</div>
      <div className={`mt-1 ${mono ? 'font-mono text-lg' : 'font-mono text-sm'} ${tone}`}>{value}</div>
    </div>
  )
}
