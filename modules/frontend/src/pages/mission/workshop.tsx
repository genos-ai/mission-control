import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import {
  FlaskConical,
  Play,
  Loader2,
  RotateCcw,
  Copy,
  Check,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import { useTeam } from '@/hooks/use-team'
import { useCatalog } from '@/hooks/use-catalog'
import { API_BASE } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/cn'

interface TestRun {
  id: string
  agentName: string
  prompt: string
  input: string
  output: string
  cost: number | null
  durationMs: number
  timestamp: Date
}

export default function WorkshopPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const { user } = useAuthStore()
  const { data: team } = useTeam(missionId)
  const { data: catalog } = useCatalog()

  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [testInput, setTestInput] = useState('')
  const [running, setRunning] = useState(false)
  const [runs, setRuns] = useState<TestRun[]>([])
  const [compareIds, setCompareIds] = useState<[string, string] | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Abort streaming on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  // Map catalog IDs to agent names (memoized to avoid recreating on every render)
  const agentLookup = useMemo(
    () => new Map(catalog?.map((a) => [a.id, a]) ?? []),
    [catalog],
  )

  const runTest = useCallback(async () => {
    if (!selectedAgent || !prompt.trim() || running) return

    setRunning(true)
    const startTime = Date.now()
    let output = ''
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = useAuthStore.getState().accessToken
      // Create a temporary session for the test
      const createRes = await fetch(`${API_BASE}/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          goal: `Workshop test: ${prompt.slice(0, 50)}`,
          agent_id: selectedAgent,
        }),
        signal: controller.signal,
      })

      if (!createRes.ok) throw new Error('Failed to create test session')
      const sessionJson = await createRes.json()
      const sessionId = sessionJson.data.id

      // Send message with combined prompt + input
      const messageContent = testInput.trim()
        ? `${prompt}\n\n---\nInput:\n${testInput}`
        : prompt

      const response = await fetch(
        `${API_BASE}/sessions/${sessionId}/messages`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            content: messageContent,
            role: 'user',
            sender_id: user?.id,
          }),
          signal: controller.signal,
        },
      )

      if (!response.ok) throw new Error('Failed to send test message')

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

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
                output += event.data?.content ?? ''
              } else if (event.event_type === 'assistant.message.complete') {
                output = event.data?.content ?? output
              }
            } catch {
              // skip
            }
          }
        }
      }

      const agentInfo = agentLookup.get(selectedAgent)
      const run: TestRun = {
        id: `run-${Date.now()}`,
        agentName: agentInfo?.agent_name ?? selectedAgent.slice(0, 8),
        prompt,
        input: testInput,
        output: output || '(no output)',
        cost: null,
        durationMs: Date.now() - startTime,
        timestamp: new Date(),
      }
      setRuns((prev) => [run, ...prev])
      toast.success(`Test completed in ${((Date.now() - startTime) / 1000).toFixed(1)}s`)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      toast.error(err instanceof Error ? err.message : 'Test failed')
    } finally {
      abortRef.current = null
      setRunning(false)
    }
  }, [selectedAgent, prompt, testInput, running, user?.id, agentLookup])

  const toggleCompare = (runId: string) => {
    setCompareIds((prev) => {
      if (!prev) return [runId, '']
      if (prev[0] === runId) return null
      if (prev[1] === runId) return [prev[0], '']
      if (!prev[1]) return [prev[0], runId]
      return [runId, '']
    })
  }

  const comparedRuns = compareIds
    ? runs.filter((r) => compareIds.includes(r.id))
    : null

  return (
    <div className="flex h-full">
      {/* Left panel: config */}
      <div className="w-80 flex-shrink-0 border-r overflow-y-auto p-4 space-y-4">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <FlaskConical className="h-4 w-4" />
          Workshop
        </h2>

        {/* Agent selector */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            Agent
          </label>
          <div className="space-y-1">
            {team?.map((member) => {
              const agent = agentLookup.get(member.agent_catalog_id)
              return (
                <button
                  key={member.id}
                  onClick={() => setSelectedAgent(member.agent_catalog_id)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent',
                    selectedAgent === member.agent_catalog_id &&
                      'bg-accent text-accent-foreground',
                  )}
                >
                  <span
                    className={cn(
                      'h-2 w-2 rounded-full',
                      member.enabled ? 'bg-emerald-500' : 'bg-muted-foreground/30',
                    )}
                  />
                  <span className="truncate">
                    {agent?.agent_name ?? member.agent_catalog_id.slice(0, 8)}
                  </span>
                  <Badge variant="secondary" className="text-[9px] ml-auto">
                    {agent?.agent_type ?? 'agent'}
                  </Badge>
                </button>
              )
            })}
            {!team?.length && (
              <p className="text-xs text-muted-foreground">
                No agents on this mission's team.
              </p>
            )}
          </div>
        </div>

        {/* Prompt editor */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            Prompt
          </label>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Enter the prompt to test..."
            rows={6}
            className="text-sm"
          />
        </div>

        {/* Test input */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            Input Data (optional)
          </label>
          <Textarea
            value={testInput}
            onChange={(e) => setTestInput(e.target.value)}
            placeholder="Paste test input data..."
            rows={4}
            className="text-sm font-mono"
          />
        </div>

        {/* Run button */}
        <Button
          onClick={runTest}
          disabled={!selectedAgent || !prompt.trim() || running}
          className="w-full"
        >
          {running ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Running...
            </>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Run Test
            </>
          )}
        </Button>
      </div>

      {/* Right panel: results */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {comparedRuns && comparedRuns.length === 2 ? (
          <CompareView
            runs={comparedRuns as [TestRun, TestRun]}
            onClose={() => setCompareIds(null)}
          />
        ) : !runs.length ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Run a test to see results here.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium">
                Test Runs ({runs.length})
              </h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setRuns([])}
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1" />
                Clear
              </Button>
            </div>

            {runs.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                comparing={compareIds?.includes(run.id) ?? false}
                onToggleCompare={() => toggleCompare(run.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function RunCard({
  run,
  comparing,
  onToggleCompare,
}: {
  run: TestRun
  comparing: boolean
  onToggleCompare: () => void
}) {
  const [copied, setCopied] = useState(false)

  const copyOutput = () => {
    navigator.clipboard.writeText(run.output)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Card className={cn(comparing && 'ring-2 ring-primary')}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">{run.agentName}</CardTitle>
            <Badge variant="secondary" className="text-[9px]">
              {(run.durationMs / 1000).toFixed(1)}s
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={onToggleCompare}
            >
              {comparing ? 'Unselect' : 'Compare'}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={copyOutput}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="rounded-md bg-muted/50 p-3">
          <p className="text-sm whitespace-pre-wrap font-mono text-xs">
            {run.output}
          </p>
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground truncate">
          Prompt: {run.prompt.slice(0, 80)}
          {run.prompt.length > 80 ? '...' : ''}
        </p>
      </CardContent>
    </Card>
  )
}

function CompareView({
  runs,
  onClose,
}: {
  runs: [TestRun, TestRun]
  onClose: () => void
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Comparing Outputs</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {runs.map((run) => (
          <Card key={run.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <CardTitle className="text-sm">{run.agentName}</CardTitle>
                <Badge variant="secondary" className="text-[9px]">
                  {(run.durationMs / 1000).toFixed(1)}s
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="rounded-md bg-muted/50 p-3 max-h-96 overflow-y-auto">
                <p className="whitespace-pre-wrap font-mono text-xs">
                  {run.output}
                </p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
