/**
 * ContextPanel — Mission Context & Memory, a workspace screen.
 *
 * Shows the Mission Context Document (MCD): all sections are rendered
 * dynamically based on the data shape — no hardcoded section list.
 * The MCD is built automatically as agents run tasks — it represents
 * the mission's accumulated memory and learnings.
 */

import { FileText } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Panel } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { Spinner } from '@/components/ui/spinner'
import { ChangeList, ContextHistory } from '@/components/workspace/context-history'
import { formatLabel, isEmptyValue } from '@/components/workspace/context-document'
import { DynamicValue } from '@/components/workspace/context-dynamic-value'
import { ContextSection } from '@/components/workspace/context-section'
import { useMCD, useContextHistory } from '@/hooks/use-context'
import type { MCDData } from '@/hooks/use-context'
import type { Tone } from '@/lib/status-tone'

// Keys that are metadata, not content sections
const META_KEYS = new Set(['version', 'last_updated', 'last_updated_by'])

// Sections open on first view; the rest start collapsed so a long document stays scannable.
const OPEN_SECTIONS = 3

// How full the document is, as a share of its limit, decides how loudly the bar speaks.
function sizeTone(pct: number): Tone {
  if (pct > 85) return 'danger'
  if (pct > 50) return 'warning'
  return 'brand'
}

function ContextSize({ mcd }: { mcd: MCDData }) {
  return (
    <div className="flex shrink-0 items-center gap-2.5 pt-0.5">
      <Badge className="font-mono">v{mcd.version}</Badge>
      <span className="font-mono text-xs text-muted-foreground">
        {(mcd.size_characters / 1024).toFixed(1)} / {(mcd.max_characters / 1024).toFixed(0)} KB
      </span>
      <Progress value={mcd.pct_of_max} tone={sizeTone(mcd.pct_of_max)} label="Context size" className="w-20" />
    </div>
  )
}

export function ContextPanel({ missionId }: { missionId: string }) {
  const { data: mcd, isLoading } = useMCD(missionId)
  const { data: history, isLoading: historyLoading } = useContextHistory(missionId)

  const isEmpty =
    !mcd || !mcd.context_data || Object.keys(mcd.context_data).length === 0
  const updatedBy = mcd?.context_data?.last_updated_by

  // Render every non-meta key dynamically
  const sections =
    mcd && !isEmpty
      ? Object.entries(mcd.context_data).filter(
          ([key, val]) => !META_KEYS.has(key) && val != null && !isEmptyValue(val),
        )
      : []

  return (
    <div className="flex h-full min-h-0 gap-gutter px-2 pb-2">
      <Panel className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex shrink-0 flex-wrap items-start gap-x-4 gap-y-2 px-5 pb-1.5 pt-3.5">
          <div className="min-w-64 flex-1">
            <h2 className="text-md font-semibold">Mission context</h2>
            <p className="text-xs text-subtle">
              Shared memory every agent reads. Builds automatically as tasks finish.
              {typeof updatedBy === 'string' && (
                <>
                  {' '}Updated by <span className="font-medium text-muted-foreground">{updatedBy}</span>.
                </>
              )}
            </p>
          </div>
          {mcd && !isEmpty && <ContextSize mcd={mcd} />}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-2.5">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : isEmpty ? (
            <EmptyState
              icon={<FileText className="h-4 w-4" />}
              title="No context yet"
              description="The Mission Context Document builds automatically as agents run tasks. Start a run to populate it."
            />
          ) : (
            <div className="flex flex-col gap-2">
              {sections.map(([key, val], i) => (
                <ContextSection
                  key={key}
                  title={formatLabel(key)}
                  count={Array.isArray(val) ? val.length : undefined}
                  defaultOpen={i < OPEN_SECTIONS}
                >
                  <DynamicValue value={val} />
                </ContextSection>
              ))}
              {/* The side panel is hidden on narrow screens, so the changes follow the document instead. */}
              <div className="min-[960px]:hidden">
                <ContextSection title="Recent changes" count={history?.length}>
                  <ChangeList changes={history ?? []} isLoading={historyLoading} />
                </ContextSection>
              </div>
            </div>
          )}
        </div>
      </Panel>

      <ContextHistory changes={history ?? []} isLoading={historyLoading} />
    </div>
  )
}
