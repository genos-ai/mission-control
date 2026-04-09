import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { cn } from '@/lib/cn'
import 'highlight.js/styles/github-dark.css'

interface MarkdownRendererProps {
  content: string
  className?: string
  /** Intercept [N] citation links — called with the citation number */
  onCitationClick?: (citationId: number) => void
}

export function MarkdownRenderer({
  content,
  className,
  onCitationClick,
}: MarkdownRendererProps) {
  return (
    <div className={cn('text-xs leading-relaxed', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          p: ({ children }) => (
            <p className="my-1.5">{children}</p>
          ),
          h1: ({ children }) => (
            <p className="mt-3 mb-1 font-semibold text-foreground">{children}</p>
          ),
          h2: ({ children }) => (
            <p className="mt-3 mb-1 font-semibold text-foreground">{children}</p>
          ),
          h3: ({ children }) => (
            <p className="mt-2 mb-1 font-medium text-foreground">{children}</p>
          ),
          h4: ({ children }) => (
            <p className="mt-1.5 mb-0.5 font-medium text-foreground">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="my-1 list-disc space-y-1 pl-4">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="my-1 list-decimal space-y-1 pl-4">{children}</ol>
          ),
          li: ({ children }) => (
            <li>{children}</li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-1.5 border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-2 border-border" />,
          strong: ({ children }) => (
            <strong className="font-semibold text-foreground">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          code: ({ children, className: cls }) => {
            const isBlock = cls?.includes('language-')
            if (isBlock) return <code className={cls}>{children}</code>
            return (
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs text-primary">
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-md border border-border bg-muted/50 p-3 text-xs">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full text-sm border-collapse">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1 text-left font-semibold text-foreground bg-muted/50">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1 text-foreground/90">
              {children}
            </td>
          ),
          a: ({ href, children }) => {
            const text = String(children)
            const citationMatch = text.match(/^\[(\d+)\]$/)
            if (citationMatch && onCitationClick) {
              return (
                <button
                  onClick={() => onCitationClick(Number(citationMatch[1]))}
                  className="font-mono text-xs text-primary hover:underline"
                >
                  {children}
                </button>
              )
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                {children}
              </a>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
