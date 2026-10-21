import { Container } from 'lucide-react'

import { useMissionEnvironment } from '@/hooks/use-missions'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { cn } from '@/lib/cn'
import { formatUtc } from '@/lib/format-date'
import type { Tone } from '@/lib/status-tone'
import { TONE_DOT, TONE_TEXT } from '@/lib/tone-class'

/** The mission's container: running, stopped, or not created yet. */
export function EnvironmentStatusCard({ missionId }: { missionId: string }) {
  const { data: envData } = useMissionEnvironment(missionId)
  const active = envData?.active_environment
  const hasAny = (envData?.all_environments.length ?? 0) > 0

  const tone: Tone = active ? 'success' : hasAny ? 'warning' : 'neutral'
  const statusText = active ? 'Running' : hasAny ? 'Stopped' : 'No container'

  const details: [string, string][] = []
  if (active) {
    if (active.container_name) details.push(['Container', active.container_name])
    if (active.image) details.push(['Image', active.image])
    details.push(['Executions', String(active.execution_count)])
    if (active.last_execution_at) details.push(['Last active', formatUtc(active.last_execution_at)])
  }

  return (
    <Panel>
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            <Container className="h-4 w-4 text-subtle" />
            Execution environment
          </span>
        }
        actions={
          <span className="flex items-center gap-2 text-sm font-medium">
            <span className={cn('h-2 w-2 rounded-full', TONE_DOT[tone])} />
            <span className={TONE_TEXT[tone]}>{statusText}</span>
          </span>
        }
      />
      <PanelContent>
        {active ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs">
            {details.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-subtle">{label}</dt>
                <dd className="font-mono text-text-3">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          !hasAny && <p className="text-xs text-subtle">A container will be created on the first run.</p>
        )}
      </PanelContent>
    </Panel>
  )
}
