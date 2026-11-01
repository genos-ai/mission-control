import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
import type { ConfigSection } from '@/components/admin/config-rows'

function ConfigValue({ value }: { value: unknown }) {
  if (typeof value === 'boolean') {
    return (
      <StatusPill tone={value ? 'brand' : 'neutral'} dot={false}>
        {String(value)}
      </StatusPill>
    )
  }
  if (value === null) return <span className="text-subtle">null</span>
  if (typeof value === 'object') return <span className="break-all">{JSON.stringify(value)}</span>
  return <span className="break-all">{String(value)}</span>
}

/** One top-level section of the platform configuration as read-only key and value rows. */
export function ConfigSectionPanel({ title, rows }: Omit<ConfigSection, 'id'>) {
  return (
    <Panel>
      <PanelHeader title={title} meta={rows.length} />
      <PanelContent className="divide-y divide-line">
        {rows.map((row) => (
          <div key={row.key} className="flex items-baseline gap-3 py-2">
            <span className="min-w-0 flex-1 break-all font-mono text-xs text-muted-foreground">{row.key}</span>
            <span className="max-w-[55%] shrink-0 text-right font-mono text-xs">
              <ConfigValue value={row.value} />
            </span>
          </div>
        ))}
        {rows.length === 0 && <p className="py-2 text-xs text-subtle">No values.</p>}
      </PanelContent>
    </Panel>
  )
}
