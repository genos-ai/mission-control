import { create } from 'zustand'

export interface ConsoleEvent {
  event_id: string
  event_type: string
  category: 'execution' | 'chat' | 'system'
  timestamp: string
  source: string
  data: Record<string, unknown>
}

interface ConsoleState {
  events: ConsoleEvent[]

  // Filters
  categoryTab: 'all' | 'execution' | 'chat' | 'system'
  agentFilter: string | null
  errorsOnly: boolean

  // UI state
  autoScroll: boolean
  connected: boolean

  // Actions
  addEvent: (event: ConsoleEvent) => void
  addEvents: (events: ConsoleEvent[]) => void
  setCategoryTab: (tab: 'all' | 'execution' | 'chat' | 'system') => void
  setAgentFilter: (agent: string | null) => void
  setErrorsOnly: (v: boolean) => void
  toggleAutoScroll: () => void
  setConnected: (v: boolean) => void
  clear: () => void
  reset: () => void
}

const MAX_EVENTS = 1000

function isErrorEvent(event: ConsoleEvent): boolean {
  return (
    event.data.error === true ||
    event.event_type.includes('failed') ||
    event.event_type.includes('error')
  )
}

const INITIAL_STATE = {
  events: [] as ConsoleEvent[],
  categoryTab: 'all' as const,
  agentFilter: null as string | null,
  errorsOnly: false,
  autoScroll: true,
  connected: false,
}

export const useConsoleStore = create<ConsoleState>((set, get) => ({
  ...INITIAL_STATE,

  addEvent: (event) => {
    const state = get()
    set({ events: [...state.events, event].slice(-MAX_EVENTS) })
  },

  addEvents: (events) => {
    const state = get()
    set({ events: [...state.events, ...events].slice(-MAX_EVENTS) })
  },

  setCategoryTab: (tab) => set({ categoryTab: tab }),
  setAgentFilter: (agent) => set({ agentFilter: agent }),
  setErrorsOnly: (v) => set({ errorsOnly: v }),
  toggleAutoScroll: () => set({ autoScroll: !get().autoScroll }),
  setConnected: (v) => set({ connected: v }),
  clear: () => set({ events: [] }),
  reset: () => set(INITIAL_STATE),
}))

/** Select filtered events, optionally by category. Pass null for all. */
export function selectFilteredEvents(
  state: ConsoleState,
  category: 'execution' | 'chat' | 'system' | null,
): ConsoleEvent[] {
  let filtered = category
    ? state.events.filter((e) => e.category === category)
    : state.events

  if (state.agentFilter) {
    const agent = state.agentFilter
    filtered = filtered.filter(
      (e) =>
        e.source === agent ||
        String(e.data.agent_id ?? '') === agent ||
        String(e.data.agent_name ?? '') === agent,
    )
  }

  if (state.errorsOnly) {
    filtered = filtered.filter(isErrorEvent)
  }

  return filtered
}
