import { useResearchStore, SourceCard } from '@/stores/research'

export function SourcePanel() {
  const sources = useResearchStore((s) => s.sources)
  const totalSources = useResearchStore((s) => s.totalSources)
  const verificationScore = useResearchStore((s) => s.verificationScore)

  return (
    <div className="flex flex-col gap-2 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Sources ({totalSources})
        </h4>
        {verificationScore != null && (
          <span className="rounded bg-green-500/10 px-2 py-0.5 text-xs font-medium text-green-500">
            {Math.round(verificationScore * 100)}% verified
          </span>
        )}
      </div>

      {sources.length === 0 && (
        <div className="text-sm text-muted-foreground">
          Sources will appear here as searchers discover them...
        </div>
      )}

      {sources.map((source, i) => (
        <SourceCardRow key={`${source.url}-${i}`} source={source} />
      ))}
    </div>
  )
}

function SourceCardRow({ source }: { source: SourceCard }) {
  const domain = getDomain(source.url)

  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded border border-border bg-card p-2 text-sm hover:border-primary/50 hover:bg-card/80"
    >
      <div className="flex items-center justify-between">
        <span className="truncate font-medium text-foreground">{source.title || domain}</span>
        <span className="ml-2 shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-mono text-primary">
          {Math.round(source.relevanceScore * 100)}%
        </span>
      </div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">{domain}</div>
      {source.snippet && (
        <div className="mt-1 line-clamp-2 text-xs text-muted-foreground/70">
          {source.snippet}
        </div>
      )}
    </a>
  )
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url.slice(0, 40)
  }
}
