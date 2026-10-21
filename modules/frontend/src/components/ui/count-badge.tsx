/** A small round count, for a number of things waiting (the sidebar's pending items). */
export function CountBadge({ count, label }: { count: number; label: string }) {
  return (
    <span
      aria-label={label}
      className="flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full bg-brand/15 px-1 font-mono text-2xs text-brand-text"
    >
      {count}
    </span>
  )
}
