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
    <div
      className={cn(
        'prose prose-sm dark:prose-invert max-w-none',
        // Tune prose defaults to match our dark UI
        'prose-headings:font-semibold prose-headings:text-foreground',
        'prose-p:text-foreground/90 prose-p:leading-relaxed',
        'prose-a:text-primary prose-a:no-underline hover:prose-a:underline',
        'prose-strong:text-foreground prose-strong:font-semibold',
        'prose-code:text-primary prose-code:before:content-none prose-code:after:content-none',
        'prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono',
        'prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border prose-pre:rounded-md',
        'prose-pre:p-0 prose-pre:overflow-x-auto',
        'prose-blockquote:border-l-primary/40 prose-blockquote:text-muted-foreground',
        'prose-li:text-foreground/90',
        'prose-hr:border-border',
        'prose-table:text-sm',
        'prose-th:text-foreground prose-td:text-foreground/90',
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // Intercept citation links [N] rendered as plain text wrapped in <a>
          a({ href, children, ...props }) {
            const text = String(children)
            const citationMatch = text.match(/^\[(\d+)\]$/)
            if (citationMatch && onCitationClick) {
              return (
                <button
                  onClick={() => onCitationClick(Number(citationMatch[1]))}
                  className="text-primary text-xs font-mono hover:underline"
                  {...(props as React.ButtonHTMLAttributes<HTMLButtonElement>)}
                >
                  {children}
                </button>
              )
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                {children}
              </a>
            )
          },
          // Prevent pre/code double-wrapping from rehype-highlight
          pre({ children, ...props }) {
            return <pre {...props}>{children}</pre>
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
