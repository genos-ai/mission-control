import { useState, useEffect } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  Loader2,
  FileCode,
  Sprout,
  Search,
  Brain,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import {
  useAdminCatalog,
  useAdminModels,
  useCreateAgent,
  useUpdateAgent,
  useDeleteAgent,
  useUpdateSystemPrompt,
  useSeedCatalog,
} from '@/hooks/use-admin'
import { useCatalogAgent } from '@/hooks/use-catalog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/cn'
import type { AgentCatalogItem } from '@/types'

export default function AdminCatalogPage() {
  const { data: agents, isLoading } = useAdminCatalog()
  const createAgent = useCreateAgent()
  const updateAgent = useUpdateAgent()
  const deleteAgent = useDeleteAgent()
  const updatePrompt = useUpdateSystemPrompt()
  const seedCatalog = useSeedCatalog()
  const { user } = useAuthStore()

  const [search, setSearch] = useState('')
  const [promptEditor, setPromptEditor] = useState<{
    agentName: string
    content: string
  } | null>(null)
  const [editingAgent, setEditingAgent] = useState<AgentCatalogItem | null>(null)
  const [creating, setCreating] = useState(false)
  const [newAgent, setNewAgent] = useState({
    agent_name: '',
    agent_type: 'vertical' as 'vertical' | 'horizontal' | 'system',
    description: '',
    version: '1.0.0',
  })

  const filtered = agents?.filter(
    (a) =>
      a.agent_name.toLowerCase().includes(search.toLowerCase()) ||
      a.description.toLowerCase().includes(search.toLowerCase()),
  )

  const handleCreate = async () => {
    try {
      await createAgent.mutateAsync(newAgent)
      toast.success('Agent created')
      setCreating(false)
      setNewAgent({
        agent_name: '',
        agent_type: 'vertical',
        description: '',
        version: '1.0.0',
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Create failed')
    }
  }

  const handleToggle = async (agent: AgentCatalogItem) => {
    try {
      await updateAgent.mutateAsync({
        agentName: agent.agent_name,
        data: { enabled: !agent.enabled },
      })
      toast.success(`${agent.agent_name} ${agent.enabled ? 'disabled' : 'enabled'}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Update failed')
    }
  }

  const handleDelete = async (agentName: string) => {
    try {
      await deleteAgent.mutateAsync(agentName)
      toast.success(`${agentName} deleted`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const handleSeed = async () => {
    try {
      await seedCatalog.mutateAsync()
      toast.success('Catalog seeded from YAML configs')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Seed failed')
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Agent Catalog</h2>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleSeed}
            disabled={seedCatalog.isPending}
          >
            {seedCatalog.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
            ) : (
              <Sprout className="h-3.5 w-3.5 mr-1" />
            )}
            Seed
          </Button>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5 mr-1" />
            New Agent
          </Button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search agents..."
          className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm"
        />
      </div>

      {/* Create form */}
      {creating && (
        <Panel>
          <PanelHeader title="Create Agent" />
          <PanelContent className="space-y-3">
            <input
              value={newAgent.agent_name}
              onChange={(e) =>
                setNewAgent((p) => ({ ...p, agent_name: e.target.value }))
              }
              placeholder="Agent name"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            <select
              value={newAgent.agent_type}
              onChange={(e) =>
                setNewAgent((p) => ({
                  ...p,
                  agent_type: e.target.value as 'vertical' | 'horizontal' | 'system',
                }))
              }
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="vertical">Vertical</option>
              <option value="horizontal">Horizontal</option>
              <option value="system">System</option>
            </select>
            <Textarea
              value={newAgent.description}
              onChange={(e) =>
                setNewAgent((p) => ({ ...p, description: e.target.value }))
              }
              placeholder="Description"
              rows={2}
              className="text-sm"
            />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={
                  !newAgent.agent_name.trim() || createAgent.isPending
                }
              >
                Create
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setCreating(false)}
              >
                Cancel
              </Button>
            </div>
          </PanelContent>
        </Panel>
      )}

      {/* Prompt editor modal */}
      {promptEditor && (
        <PromptEditor
          agentName={promptEditor.agentName}
          onSave={async (content) => {
            try {
              await updatePrompt.mutateAsync({
                agentName: promptEditor.agentName,
                content,
                changedBy: user?.id ?? 'admin',
                changeReason: 'Updated via admin UI',
              })
              toast.success('System prompt updated')
              setPromptEditor(null)
            } catch (err) {
              toast.error(err instanceof Error ? err.message : 'Update failed')
            }
          }}
          saving={updatePrompt.isPending}
          onClose={() => setPromptEditor(null)}
        />
      )}

      {/* Agent editor */}
      {editingAgent && (
        <AgentEditor
          agent={editingAgent}
          onSave={async (data) => {
            try {
              await updateAgent.mutateAsync({
                agentName: editingAgent.agent_name,
                data,
              })
              toast.success(`${editingAgent.agent_name} updated`)
              setEditingAgent(null)
            } catch (err) {
              toast.error(err instanceof Error ? err.message : 'Update failed')
            }
          }}
          saving={updateAgent.isPending}
          onClose={() => setEditingAgent(null)}
        />
      )}

      {/* Agent list */}
      <div className="space-y-2">
        {filtered?.map((agent) => (
          <Panel key={agent.id}>
            <PanelContent className="flex items-center justify-between py-3 px-4">
              <div className="flex items-center gap-3 min-w-0">
                <button
                  onClick={() => handleToggle(agent)}
                  className={cn(
                    'h-2.5 w-2.5 rounded-full flex-shrink-0 transition-colors',
                    agent.enabled ? 'bg-emerald-500' : 'bg-muted-foreground/30',
                  )}
                  title={agent.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {agent.agent_name}
                    </span>
                    <Badge variant="secondary" className="text-[9px]">
                      {agent.agent_type}
                    </Badge>
                    <Badge variant="outline" className="text-[9px]">
                      v{agent.version}
                    </Badge>
                    {agent.model_config_json?.name && (
                      <Badge variant="outline" className="text-[9px] border-blue-500/30 text-blue-400">
                        {agent.model_config_json.name}
                      </Badge>
                    )}
                    {agent.engine && agent.engine !== 'pydantic_ai' && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-green-500/40 text-green-400">
                        {agent.engine.replace('_', ' ')}
                      </Badge>
                    )}
                    {agent.thinking_budget_json && (
                      <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-purple-500/40 text-purple-400">
                        <Brain className="h-2.5 w-2.5 mr-0.5" />
                        {agent.thinking_budget_json.max_thinking_tokens > 0
                          ? `${(agent.thinking_budget_json.max_thinking_tokens / 1000).toFixed(0)}k`
                          : 'adaptive'}
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {agent.description}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0 ml-4">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() =>
                    setPromptEditor({
                      agentName: agent.agent_name,
                      content: '',
                    })
                  }
                  title="Edit system prompt"
                >
                  <FileCode className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => setEditingAgent(agent)}
                  title="Edit agent"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-destructive"
                  onClick={() => handleDelete(agent.agent_name)}
                  title="Delete agent"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </PanelContent>
          </Panel>
        ))}
      </div>
    </div>
  )
}

/** Models that support extended thinking (all Claude 4.5+ models). */
const THINKING_CAPABLE_MODELS = new Set([
  'anthropic:claude-sonnet-4-6',
  'anthropic:claude-opus-4-6',
  'anthropic:claude-haiku-4-5-20251001',
  'anthropic:claude-haiku-4-5',
  'copilot:claude-opus-4.6',
  'copilot:claude-sonnet-4.6',
  'copilot:claude-haiku-4.5',
])

function AgentEditor({
  agent,
  onSave,
  saving,
  onClose,
}: {
  agent: AgentCatalogItem
  onSave: (data: Partial<AgentCatalogItem>) => void
  saving: boolean
  onClose: () => void
}) {
  const isSysadmin = useAuthStore((s) => s.isSysadmin)
  const { data: modelsRegistry = {} } = useAdminModels()

  const [model, setModel] = useState(agent.model_config_json?.name ?? '')
  const [provider, model_name] = model.includes(':')
    ? model.split(':', 2) as [string, string]
    : ['', '']
  const providerList = Object.keys(modelsRegistry).sort()
  const modelList = provider ? (modelsRegistry[provider] ?? []) : []

  const setProvider = (newProvider: string) => {
    // Switching provider clears the model selection (since model lists differ)
    setModel(newProvider ? `${newProvider}:` : '')
  }
  const setModelName = (newModelName: string) => {
    setModel(provider && newModelName ? `${provider}:${newModelName}` : '')
  }

  const [temperature, setTemperature] = useState(
    String(agent.model_config_json?.temperature ?? ''),
  )
  const [maxTokens, setMaxTokens] = useState(
    String(agent.model_config_json?.max_tokens ?? ''),
  )
  const [description, setDescription] = useState(agent.description)
  const [version, setVersion] = useState(agent.version)
  const [engine, setEngine] = useState(agent.engine ?? 'pydantic_ai')
  const [effort, setEffort] = useState(agent.effort ?? '')
  const [chatEnabled, setChatEnabled] = useState(agent.chat_enabled ?? false)

  // Thinking mode: 'off' | 'adaptive' | 'fixed'
  const initialThinking = agent.thinking_budget_json
    ? (agent.thinking_budget_json.max_thinking_tokens > 0 ? 'fixed' : 'adaptive')
    : 'off'
  const [thinkingMode, setThinkingMode] = useState<'off' | 'adaptive' | 'fixed'>(initialThinking)
  const [thinkingTokens, setThinkingTokens] = useState(
    String(agent.thinking_budget_json?.max_thinking_tokens || 10000),
  )
  const thinkingEnabled = thinkingMode !== 'off'
  const modelSupportsThinking = THINKING_CAPABLE_MODELS.has(model)

  return (
    <Panel className="border-primary/30">
      <PanelHeader
        title={`Edit — ${agent.agent_name}`}
        actions={
          <>
            <Button
              size="sm"
              onClick={() => {
                if (provider && !model_name) {
                  toast.error('Pick a model for the selected provider, or clear the provider.')
                  return
                }
                const effectiveName = provider && model_name ? `${provider}:${model_name}` : ''
                const effectiveThinking = modelSupportsThinking ? thinkingMode : 'off'
                const effectiveTemp = effectiveThinking !== 'off' ? 1.0 : (temperature ? parseFloat(temperature) : undefined)
                const thinkingBudget = effectiveThinking === 'off'
                  ? null
                  : effectiveThinking === 'adaptive'
                    ? { max_thinking_tokens: 0 }
                    : { max_thinking_tokens: parseInt(thinkingTokens, 10) || 10000 }
                onSave({
                  description,
                  version,
                  engine,
                  effort: (effort || null) as AgentCatalogItem['effort'],
                  chat_enabled: chatEnabled,
                  thinking_budget_json: thinkingBudget,
                  model_config_json: {
                    ...agent.model_config_json,
                    name: effectiveName || undefined,
                    temperature: effectiveTemp,
                    max_tokens: maxTokens ? parseInt(maxTokens, 10) : undefined,
                  },
                })
              }}
              disabled={saving || (!!provider && !model_name)}
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </>
        }
      />
      <PanelContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              disabled={!isSysadmin}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1 disabled:opacity-50"
            >
              <option value="">— select provider —</option>
              {providerList.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
              {provider && !providerList.includes(provider) && (
                <option value={provider}>{provider} (unregistered)</option>
              )}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Model</label>
            <select
              value={model_name}
              onChange={(e) => setModelName(e.target.value)}
              disabled={!isSysadmin || !provider}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1 disabled:opacity-50"
            >
              <option value="">— select model —</option>
              {modelList.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {model_name && !modelList.includes(model_name) && (
                <option value={model_name}>{model_name} (unregistered)</option>
              )}
            </select>
          </div>
        </div>
        {!isSysadmin && (
          <p className="text-[10px] text-muted-foreground/60 -mt-2">
            Provider and model can only be changed by sysadmins.
          </p>
        )}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Temperature</label>
            <input
              value={thinkingEnabled ? '1.0' : temperature}
              onChange={(e) => setTemperature(e.target.value)}
              placeholder="0.0 - 1.0"
              type="number"
              step="0.1"
              min="0"
              max="1"
              disabled={thinkingEnabled}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1 disabled:opacity-50"
            />
            {thinkingEnabled && (
              <p className="text-[10px] text-muted-foreground/60 mt-0.5">Locked to 1.0 (thinking requires it)</p>
            )}
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Max Tokens</label>
            <input
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              placeholder="e.g. 4096"
              type="number"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Thinking</label>
            <select
              value={modelSupportsThinking ? thinkingMode : 'off'}
              onChange={(e) => setThinkingMode(e.target.value as typeof thinkingMode)}
              disabled={!modelSupportsThinking}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1 disabled:opacity-50"
            >
              <option value="off">Off</option>
              <option value="adaptive">Adaptive</option>
              <option value="fixed">Fixed Budget</option>
            </select>
            {!modelSupportsThinking && model && (
              <p className="text-[10px] text-muted-foreground/60 mt-0.5">Not supported by this model</p>
            )}
          </div>
        </div>
        {thinkingMode === 'fixed' && modelSupportsThinking && (
          <div>
            <label className="text-xs font-medium text-muted-foreground">Thinking Token Budget</label>
            <input
              value={thinkingTokens}
              onChange={(e) => setThinkingTokens(e.target.value)}
              placeholder="e.g. 10000"
              type="number"
              min="1000"
              step="1000"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1"
            />
          </div>
        )}
        <div>
          <label className="text-xs font-medium text-muted-foreground">Description</label>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="text-sm mt-1"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">Version</label>
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Engine</label>
            <select
              value={engine}
              onChange={(e) => setEngine(e.target.value as typeof engine)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1"
            >
              <option value="pydantic_ai">PydanticAI (API Key)</option>
              <option value="claude_code">Claude Code (Subscription)</option>
              <option value="codex">OpenAI Codex (Subscription)</option>
              <option value="copilot">GitHub Copilot (Subscription)</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Effort</label>
            <select
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm mt-1"
              disabled={engine !== 'claude_code'}
            >
              <option value="">— default —</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </div>
        </div>
        <label className="flex cursor-pointer items-start gap-2">
          <input
            type="checkbox"
            checked={chatEnabled}
            onChange={(e) => setChatEnabled(e.target.checked)}
            className="mt-0.5 h-4 w-4 cursor-pointer"
          />
          <div>
            <span className="text-xs font-medium">Chat-enabled</span>
            <p className="text-[10px] text-muted-foreground/70">
              When on, this agent appears as a clickable conversation target on
              mission Team and Chat pages. The agent's <code>create_agent()</code>{' '}
              must accept a <code>chat_mode</code> parameter to behave correctly
              in conversation; otherwise it runs its default path.
            </p>
          </div>
        </label>
      </PanelContent>
    </Panel>
  )
}

function PromptEditor({
  agentName,
  onSave,
  saving,
  onClose,
}: {
  agentName: string
  onSave: (content: string) => void
  saving: boolean
  onClose: () => void
}) {
  const { data: agentDetail, isLoading } = useCatalogAgent(agentName)
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)

  // Populate with existing prompt once loaded
  useEffect(() => {
    if (agentDetail && !loaded) {
      setContent(agentDetail.system_prompt ?? '')
      setLoaded(true)
    }
  }, [agentDetail, loaded])

  return (
    <Panel className="border-primary/30">
      <PanelHeader
        title={`System Prompt — ${agentName}`}
        actions={
          <>
            <Button
              size="sm"
              onClick={() => onSave(content)}
              disabled={saving || isLoading}
            >
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </>
        }
      />
      <PanelContent>
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
            className="font-mono text-xs"
          />
        )}
      </PanelContent>
    </Panel>
  )
}
