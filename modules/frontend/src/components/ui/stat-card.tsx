import { Panel } from '@/components/ui/panel'

export function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon?: React.ReactNode
  label: string
  value: string | number
  /** A quiet line under the figure. */
  hint?: React.ReactNode
}) {
  return (
    <Panel className="flex flex-col gap-2 p-4">
      <div className="flex items-center gap-1.5 text-xs text-subtle">
        {icon}
        {label}
      </div>
      <p className="text-3xl font-medium tracking-[-0.03em]">{value}</p>
      {hint && <p className="text-xs text-subtle">{hint}</p>}
    </Panel>
  )
}
