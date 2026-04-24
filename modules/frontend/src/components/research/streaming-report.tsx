import { useEffect, useRef } from 'react'
import { useResearchStore } from '@/stores/research'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

export function StreamingReport() {
  const chunks = useResearchStore((s) => s.reportChunks)
  const isComplete = useResearchStore((s) => s.reportComplete)
  const isSynthesizing = useResearchStore((s) => s.isSynthesizing)
  const bottomRef = useRef<HTMLDivElement>(null)

  const content = chunks.join('')

  // Auto-scroll to bottom while streaming
  useEffect(() => {
    if (isSynthesizing && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chunks.length, isSynthesizing])

  if (!isSynthesizing && !isComplete && content.length === 0) return null

  return (
    <div className="mt-4 border-t border-border pt-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Report {isSynthesizing && !isComplete ? '(writing...)' : ''}
      </h4>
      <div className="max-h-[500px] overflow-y-auto rounded border border-border bg-card p-4">
        <MarkdownRenderer content={content} className="text-sm" />
        {isSynthesizing && !isComplete && (
          <span className="inline-block h-4 w-1 animate-pulse bg-primary" />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
