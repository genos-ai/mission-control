import { create } from 'zustand'

// ── Types ──────────────────────────────────────────────────────────

export interface SubQuestion {
  id: string
  text: string
  priority: number
  status: 'pending' | 'searching' | 'covered' | 'gap'
  sourceCount: number
}

export interface SourceCard {
  url: string
  title: string
  snippet: string
  relevanceScore: number
  subQuestionId: string
  provider: string
  iteration: number
}

export interface NarrativeEntry {
  timestamp: number
  phase: string
  message: string
}

export interface CitationVerdict {
  citationId: number
  claim: string
  sourceUrl: string
  verdict: string
  explanation: string
}

interface SseEvent {
  event_type: string
  data: Record<string, unknown>
}

// ── Store ──────────────────────────────────────────────────────────

interface ResearchState {
  // Identity
  researchId: string | null
  query: string
  depth: string
  isActive: boolean

  // Sub-questions (live tree)
  subQuestions: SubQuestion[]

  // Sources (live feed)
  sources: SourceCard[]

  // Coverage (live ring)
  coverageRatio: number
  iteration: number
  maxIterations: number
  gapsRemaining: number
  stopReason: string

  // Report (streaming)
  isSynthesizing: boolean
  reportChunks: string[]
  reportComplete: boolean

  // Verification
  verificationScore: number | null

  // Narrative (activity feed)
  narrativeEvents: NarrativeEntry[]

  // Metrics
  totalSources: number
  costUsd: number
  durationSeconds: number

  // Actions
  handleEvent: (event: SseEvent) => void
  reset: () => void
}

const INITIAL_STATE = {
  researchId: null as string | null,
  query: '',
  depth: 'comprehensive',
  isActive: false,
  subQuestions: [] as SubQuestion[],
  sources: [] as SourceCard[],
  coverageRatio: 0,
  iteration: 0,
  maxIterations: 5,
  gapsRemaining: 0,
  stopReason: '',
  isSynthesizing: false,
  reportChunks: [] as string[],
  reportComplete: false,
  verificationScore: null as number | null,
  narrativeEvents: [] as NarrativeEntry[],
  totalSources: 0,
  costUsd: 0,
  durationSeconds: 0,
}

export const useResearchStore = create<ResearchState>((set, get) => ({
  ...INITIAL_STATE,

  reset: () => set(INITIAL_STATE),

  handleEvent: (event: SseEvent) => {
    const state = get()
    const t = event.event_type
    const d = event.data ?? event

    switch (t) {
      case 'research.started': {
        set({
          ...INITIAL_STATE,
          researchId: String(d.research_id ?? ''),
          query: String(d.query ?? ''),
          depth: String(d.depth ?? 'comprehensive'),
          maxIterations: Number(d.max_iterations ?? 5),
          isActive: true,
        })
        return
      }

      case 'research.decomposed': {
        const raw = (d.sub_questions ?? []) as Array<Record<string, unknown>>
        set({
          subQuestions: raw.map((sq) => ({
            id: String(sq.id ?? ''),
            text: String(sq.text ?? ''),
            priority: Number(sq.priority ?? 3),
            status: 'pending' as const,
            sourceCount: 0,
          })),
        })
        return
      }

      case 'research.subquestion.updated': {
        const sqId = String(d.sub_question_id ?? '')
        const newStatus = String(d.status ?? 'pending') as SubQuestion['status']
        const count = Number(d.source_count ?? 0)
        set({
          subQuestions: state.subQuestions.map((sq) =>
            sq.id === sqId ? { ...sq, status: newStatus, sourceCount: count } : sq
          ),
        })
        return
      }

      case 'research.search.completed': {
        set({
          iteration: Number(d.iteration ?? state.iteration),
          totalSources: state.totalSources + Number(d.sources_found ?? 0),
        })
        return
      }

      case 'research.coverage.updated': {
        set({
          coverageRatio: Number(d.coverage_ratio ?? 0),
          iteration: Number(d.iteration ?? state.iteration),
          gapsRemaining: Number(d.gaps_remaining ?? 0),
          stopReason: String(d.stop_reason ?? ''),
        })
        return
      }

      case 'research.synthesizing': {
        set({
          isSynthesizing: true,
          reportChunks: [],
        })
        return
      }

      case 'research.completed': {
        set({
          isActive: false,
          isSynthesizing: false,
          reportComplete: true,
          verificationScore: d.verification_score != null
            ? Number(d.verification_score)
            : null,
          costUsd: Number(d.cost_usd ?? 0),
          durationSeconds: Number(d.duration_seconds ?? 0),
          totalSources: Number(d.total_sources ?? state.totalSources),
        })
        return
      }

      case 'research.failed': {
        set({
          isActive: false,
          isSynthesizing: false,
          costUsd: Number(d.cost_usd ?? 0),
        })
        return
      }

      // Streaming report chunks from the synthesizer agent
      case 'agent.response.chunk': {
        const agentId = String(d.agent_id ?? '')
        if (agentId === 'research.synthesizer.agent' && state.isSynthesizing) {
          const chunk = String(d.chunk ?? d.content ?? '')
          if (chunk) {
            set({ reportChunks: [...state.reportChunks, chunk] })
          }
        }
        return
      }

      // Narrative events (mission.narrative with research source)
      case 'mission.narrative': {
        const source = String(d.source ?? '')
        if (source.startsWith('research:')) {
          set({
            narrativeEvents: [
              ...state.narrativeEvents,
              {
                timestamp: Date.now(),
                phase: String(d.phase ?? ''),
                message: String(d.narrative ?? ''),
              },
            ].slice(-200),
          })
        }
        return
      }

      default:
        return
    }
  },
}))
