import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { IconTile } from '@/components/ui/icon-tile'
import { Panel } from '@/components/ui/panel'
import { useAttention } from '@/hooks/use-attention'
import { formatRelative } from '@/lib/format-date'
import { attentionTone } from '@/lib/status-tone'

/** What needs a person across their missions. Renders nothing while loading, on failure, or when nothing waits. */
export function AttentionPanel() {
  const { data } = useAttention()
  const navigate = useNavigate()

  if (!data || data.items.length === 0) return null

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-medium text-subtle">Needs your attention</h2>
      <Panel className="divide-y divide-line overflow-hidden">
        {data.items.map((item) => {
          const { icon, tone } = attentionTone[item.kind]
          return (
            <div
              key={`${item.mission_id}:${item.kind}:${item.created_at}`}
              className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-hover"
            >
              <IconTile icon={icon} tone={tone} size="sm" shape="square" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-base">{item.title}</p>
                <p className="truncate text-xs text-subtle">
                  {item.mission_name} · {item.detail}
                </p>
              </div>
              <span className="shrink-0 font-mono text-2xs text-subtle">{formatRelative(item.created_at)}</span>
              <Button variant="secondary" size="sm" onClick={() => navigate(item.href)}>
                {item.kind === 'human_input' ? 'Respond' : 'Review'}
              </Button>
            </div>
          )
        })}
      </Panel>
    </section>
  )
}
