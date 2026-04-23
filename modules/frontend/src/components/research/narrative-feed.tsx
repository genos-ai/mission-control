import { useEffect, useRef } from 'react'
import { useResearchStore, NarrativeEntry } from '@/stores/research'

export function NarrativeFeed() {
  const events = useResearchStore((s) => s.narrativeEvents)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  if (events.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Waiting for research to start...
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 overflow-y-auto text-sm">
      {events.map((entry, i) => (
        <NarrativeRow key={i} entry={entry} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

function NarrativeRow({ entry }: { entry: NarrativeEntry }) {
  const time = new Date(entry.timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return (
    <div className="flex gap-2 px-2 py-0.5 text-muted-foreground hover:bg-muted/20">
      <span className="shrink-0 font-mono text-[10px] text-muted-foreground/50">
        {time}
      </span>
      <span className="text-foreground/80">{entry.message}</span>
    </div>
  )
}
