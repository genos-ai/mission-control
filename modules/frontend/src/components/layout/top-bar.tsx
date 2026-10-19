import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

export interface TopBarSegment {
  label: string
  /** Makes the segment a link. The last segment is the current page and is never linked. */
  to?: string
}

export interface TopBarProps {
  segments: TopBarSegment[]
  /** Shown right after the breadcrumb, e.g. a status pill. */
  status?: ReactNode
  /** Controls at the right edge. */
  actions?: ReactNode
}

/** Breadcrumb, status and page actions. Generic: it knows nothing about missions. */
export function TopBar({ segments, status, actions }: TopBarProps) {
  return (
    <header className="sticky top-0 z-10 flex h-[52px] shrink-0 items-center gap-3 bg-well px-5">
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 overflow-hidden text-base">
        {segments.map((segment, i) => {
          const last = i === segments.length - 1
          return (
            <Fragment key={`${i}-${segment.label}`}>
              {i > 0 && <span className="text-faint">/</span>}
              {segment.to && !last ? (
                <Link to={segment.to} className="truncate text-muted-foreground hover:text-foreground">
                  {segment.label}
                </Link>
              ) : (
                <span
                  aria-current={last ? 'page' : undefined}
                  className={last ? 'truncate font-medium text-foreground' : 'truncate text-muted-foreground'}
                >
                  {segment.label}
                </span>
              )}
            </Fragment>
          )
        })}
      </nav>
      {status && <div className="shrink-0">{status}</div>}
      {actions && <div className="ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap">{actions}</div>}
    </header>
  )
}
