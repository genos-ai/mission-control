import type { ReactNode } from 'react'

/** A small labelled number inside a detail panel. For a page-level stat use `StatCard`. */
export function MetricTile({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return (
    <div className="rounded-card bg-raised px-2.5 py-2">
      <p className="text-2xs text-subtle">{label}</p>
      <div className="flex items-center gap-1">
        {icon}
        <p className="font-mono text-sm font-medium">{value}</p>
      </div>
    </div>
  )
}
