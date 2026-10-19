import { useResearchStore, SubQuestion } from '@/stores/research'

const STATUS_ICON: Record<string, string> = {
  pending: '\u25CB',    // ○
  searching: '\u25C9',  // ◉
  covered: '\u2713',    // ✓
  gap: '\u2717',        // ✗
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-muted-foreground',
  searching: 'text-warning animate-pulse motion-reduce:animate-none',
  covered: 'text-success',
  gap: 'text-danger',
}

export function SubQuestionTree() {
  const subQuestions = useResearchStore((s) => s.subQuestions)

  if (subQuestions.length === 0) return null

  return (
    <div className="space-y-1">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Sub-questions
      </h4>
      {subQuestions.map((sq) => (
        <SubQuestionRow key={sq.id} sq={sq} />
      ))}
    </div>
  )
}

function SubQuestionRow({ sq }: { sq: SubQuestion }) {
  return (
    <div className="flex items-start gap-2 rounded px-2 py-1 text-sm hover:bg-muted/30">
      <span className={`mt-0.5 font-mono text-base ${STATUS_COLOR[sq.status]}`}>
        {STATUS_ICON[sq.status] ?? '\u25CB'}
      </span>
      <div className="min-w-0 flex-1">
        <span className="text-foreground">{sq.text}</span>
        {sq.sourceCount > 0 && (
          <span className="ml-2 text-xs text-muted-foreground">
            {sq.sourceCount} source{sq.sourceCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>
    </div>
  )
}
