import type { DeskPersona } from './hooks/usePersona'
import type { DeskTab } from './types'

export type NavItem = { id: DeskTab; label: string; hint: string }

const ALL: NavItem[] = [
  { id: 'orbit', label: 'Orbit', hint: '3D universe' },
  { id: 'ops', label: 'Ops', hint: 'Radar + tables' },
  { id: 'screens', label: 'Screens', hint: 'Combo list' },
  { id: 'flow', label: 'Flow', hint: 'OI · CVD · VA' },
  { id: 'charts', label: 'Charts', hint: 'Equity + price' },
  { id: 'guide', label: 'Guide', hint: 'Playbook' },
  { id: 'agents', label: 'Agents', hint: 'Briefing' },
  { id: 'book', label: 'Book', hint: 'Allocation' },
  { id: 'journal', label: 'Journal', hint: 'Fills' },
  { id: 'flows', label: 'Playbook', hint: 'Operator loop' },
]

const OBSERVER_IDS: DeskTab[] = ['orbit', 'screens', 'charts', 'guide', 'book', 'journal', 'flows']
const SPACEMAN_IDS: DeskTab[] = ['orbit', 'ops', 'flow', 'screens', 'charts', 'agents', 'book', 'journal', 'flows']

export function navForPersona(persona: DeskPersona | null): NavItem[] {
  const ids = persona === 'spaceman' ? SPACEMAN_IDS : persona === 'observer' ? OBSERVER_IDS : ALL.map((n) => n.id)
  const set = new Set(ids)
  return ALL.filter((n) => set.has(n.id))
}

export function defaultTabForPersona(persona: DeskPersona): DeskTab {
  return persona === 'observer' ? 'screens' : 'flow'
}
