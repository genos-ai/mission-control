import { Settings2 } from 'lucide-react'
import { configSections } from '@/components/admin/config-rows'
import { ConfigSectionPanel } from '@/components/admin/config-section'
import { EmptyState } from '@/components/ui/empty-state'

/** The platform configuration as a responsive grid of section panels, or an empty state. */
export function ConfigSections({ config }: { config: Record<string, unknown> }) {
  const sections = configSections(config)

  if (sections.length === 0) {
    return (
      <EmptyState
        icon={<Settings2 className="h-4 w-4" />}
        title="No configuration values."
        description="The platform returned an empty configuration."
      />
    )
  }
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] items-start gap-4">
      {sections.map((section) => (
        <ConfigSectionPanel key={section.id} title={section.title} rows={section.rows} />
      ))}
    </div>
  )
}
