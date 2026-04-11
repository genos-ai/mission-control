import { useState, useRef, useEffect } from 'react'
import { Send } from 'lucide-react'
import { useDrawerStore } from '@/stores/drawer'
import { useArchitectChat } from '@/hooks/use-workflows'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Spinner } from '@/components/ui/spinner'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'

interface Message {
  role: 'user' | 'architect'
  content: string
}

export function ArchitectChatPanel() {
  const { context } = useDrawerStore()
  const missionId = context.missionId as string | undefined

  if (!missionId) {
    return <p className="text-sm text-muted-foreground">No mission selected.</p>
  }

  return <ArchitectChat missionId={missionId} />
}

function ArchitectChat({ missionId }: { missionId: string }) {
  const chatMutation = useArchitectChat(missionId)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  const handleSend = () => {
    const text = input.trim()
    if (!text) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')

    chatMutation.mutate(text, {
      onSuccess: (data) => {
        setMessages((prev) => [
          ...prev,
          { role: 'architect', content: data.response },
        ])
      },
      onError: (err) => {
        setMessages((prev) => [
          ...prev,
          { role: 'architect', content: `Error: ${err.message}` },
        ])
      },
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3">
        <p className="text-xs text-muted-foreground">
          Describe what you want to automate. The Architect will design a
          workflow for your mission.
        </p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={
              msg.role === 'user'
                ? 'ml-8 rounded-lg bg-primary/10 p-3 text-sm'
                : 'mr-8 rounded-lg border p-3 text-sm'
            }
          >
            <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-foreground">
              {msg.role === 'user' ? 'You' : 'Architect'}
            </span>
            {msg.role === 'architect' ? (
              <MarkdownRenderer content={msg.content} />
            ) : (
              <div className="whitespace-pre-wrap">{msg.content}</div>
            )}
          </div>
        ))}

        {chatMutation.isPending && (
          <div className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
            <Spinner /> Thinking...
          </div>
        )}
      </div>

      {/* Input */}
      <div className="mt-3 flex items-end gap-2 border-t pt-3">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
          placeholder="Describe your workflow..."
          className="flex-1 resize-none"
        />
        <Button
          size="icon"
          onClick={handleSend}
          disabled={chatMutation.isPending || !input.trim()}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
