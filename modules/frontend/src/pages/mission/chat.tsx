import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  Plus,
  Send,
  Loader2,
  Bot,
  User,
  Circle,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import { useSessions, useMessages, useCreateSession } from '@/hooks/use-sessions'
import { API_BASE } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { cn } from '@/lib/cn'
import type { SessionMessage } from '@/types'

export default function ChatPage() {
  const { id: missionId, threadId } = useParams<{
    id: string
    threadId: string
  }>()
  const navigate = useNavigate()
  const { user } = useAuthStore()

  const { data: sessions, isLoading: loadingSessions } = useSessions(
    user ? { user_id: user.id } : undefined,
  )
  const createSession = useCreateSession()

  const handleNewChat = async () => {
    if (!user) return
    try {
      const session = await createSession.mutateAsync({
        goal: 'Chat session',
      })
      navigate(
        `/missions/${missionId}/chat/${session.id}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create session')
    }
  }

  return (
    <div className="flex h-full">
      {/* Thread list */}
      <div className="w-64 flex-shrink-0 border-r flex flex-col">
        <div className="flex items-center justify-between p-3 border-b">
          <span className="text-sm font-medium">Threads</span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleNewChat}
            disabled={createSession.isPending}
          >
            {createSession.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingSessions ? (
            <div className="flex justify-center p-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : !sessions?.length ? (
            <p className="p-3 text-xs text-muted-foreground">No threads yet</p>
          ) : (
            sessions.map((s) => (
              <button
                key={s.id}
                onClick={() =>
                  navigate(`/missions/${missionId}/chat/${s.id}`)
                }
                className={cn(
                  'flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-accent',
                  threadId === s.id && 'bg-accent',
                )}
              >
                <div className="flex items-center gap-2">
                  <Circle
                    className={cn(
                      'h-2 w-2',
                      s.status === 'active'
                        ? 'fill-emerald-500 text-emerald-500'
                        : 'fill-muted-foreground/30 text-muted-foreground/30',
                    )}
                  />
                  <span className="text-sm truncate">
                    {s.goal || s.id.slice(0, 8)}
                  </span>
                </div>
                <span className="text-[10px] text-muted-foreground pl-4">
                  {formatDistanceToNow(new Date(s.last_activity_at), {
                    addSuffix: true,
                  })}
                </span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Conversation area */}
      <div className="flex-1 flex flex-col min-w-0">
        {threadId ? (
          <ConversationView sessionId={threadId} />
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <EmptyState
              icon={
                <MessageSquare className="h-6 w-6 text-muted-foreground" />
              }
              title="No conversation selected"
              description="Select a thread or start a new conversation."
              action={{
                label: 'New Chat',
                onClick: handleNewChat,
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function ConversationView({ sessionId }: { sessionId: string }) {
  const { data: history, isLoading } = useMessages(sessionId)
  const { user } = useAuthStore()
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [streamingContent, setStreamingContent] = useState('')
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Reset local state when switching threads
  useEffect(() => {
    setMessages([])
    setStreamingContent('')
    setSending(false)
    abortRef.current?.abort()
    abortRef.current = null
  }, [sessionId])

  // Sync history into local state
  useEffect(() => {
    if (history) {
      setMessages(history)
    }
  }, [history])

  // Abort streaming on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, streamingContent])

  const sendMessage = useCallback(async () => {
    const content = input.trim()
    if (!content || sending) return

    setInput('')
    setSending(true)
    setStreamingContent('')

    // Optimistic user message
    const userMsg: SessionMessage = {
      id: `temp-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      sender_id: user?.id ?? null,
      model: null,
      input_tokens: null,
      output_tokens: null,
      cost_usd: null,
      tool_name: null,
      tool_call_id: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = useAuthStore.getState().accessToken
      const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          content,
          role: 'user',
          sender_id: user?.id,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error('Failed to send message')
      }

      // Read SSE stream from POST response
      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const raw = line.slice(6)
            if (raw === '{}') continue
            try {
              const event = JSON.parse(raw)
              if (event.event_type === 'assistant.message.delta') {
                accumulated += event.data?.content ?? ''
                setStreamingContent(accumulated)
              } else if (event.event_type === 'assistant.message.complete') {
                const assistantMsg: SessionMessage = {
                  id: event.data?.message_id ?? `resp-${Date.now()}`,
                  session_id: sessionId,
                  role: 'assistant',
                  content: event.data?.content ?? accumulated,
                  sender_id: null,
                  model: event.data?.model ?? null,
                  input_tokens: event.data?.input_tokens ?? null,
                  output_tokens: event.data?.output_tokens ?? null,
                  cost_usd: event.data?.cost_usd ?? null,
                  tool_name: null,
                  tool_call_id: null,
                  created_at: new Date().toISOString(),
                }
                setMessages((prev) => [...prev, assistantMsg])
                accumulated = ''
                setStreamingContent('')
              }
            } catch {
              // skip malformed SSE data
            }
          }
        }
      }

      // If we accumulated content but never got a complete event, add it
      if (accumulated) {
        const fallbackMsg: SessionMessage = {
          id: `resp-${Date.now()}`,
          session_id: sessionId,
          role: 'assistant',
          content: accumulated,
          sender_id: null,
          model: null,
          input_tokens: null,
          output_tokens: null,
          cost_usd: null,
          tool_name: null,
          tool_call_id: null,
          created_at: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, fallbackMsg])
        setStreamingContent('')
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      toast.error(err instanceof Error ? err.message : 'Send failed')
    } finally {
      abortRef.current = null
      setSending(false)
    }
  }, [input, sending, sessionId, user?.id])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      sendMessage()
    }
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <>
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

        {/* Streaming indicator */}
        {streamingContent && (
          <div className="flex gap-3">
            <div className="flex-shrink-0 mt-1">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1 rounded-lg bg-muted/50 p-3">
              <p className="text-sm whitespace-pre-wrap">{streamingContent}</p>
              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground mt-1" />
            </div>
          </div>
        )}

        {sending && !streamingContent && (
          <div className="flex gap-3">
            <Bot className="h-5 w-5 text-primary mt-1" />
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Thinking...
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message... (Cmd+Enter)"
            rows={2}
            className="resize-none text-sm"
            disabled={sending}
          />
          <Button
            size="icon"
            onClick={sendMessage}
            disabled={!input.trim() || sending}
            className="h-auto"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground mt-1">
          Cmd+Enter to send
        </p>
      </div>
    </>
  )
}

function MessageBubble({ message }: { message: SessionMessage }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div className="flex-shrink-0 mt-1">
        {isUser ? (
          <User className="h-5 w-5 text-muted-foreground" />
        ) : (
          <Bot className="h-5 w-5 text-primary" />
        )}
      </div>
      <div
        className={cn(
          'max-w-[75%] rounded-lg p-3',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted/50',
        )}
      >
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        <div
          className={cn(
            'flex items-center gap-2 mt-1 text-[10px]',
            isUser
              ? 'text-primary-foreground/60'
              : 'text-muted-foreground',
          )}
        >
          <span>
            {formatDistanceToNow(new Date(message.created_at), {
              addSuffix: true,
            })}
          </span>
          {message.cost_usd != null && (
            <Badge variant="secondary" className="text-[9px]">
              ${message.cost_usd.toFixed(4)}
            </Badge>
          )}
        </div>
      </div>
    </div>
  )
}
