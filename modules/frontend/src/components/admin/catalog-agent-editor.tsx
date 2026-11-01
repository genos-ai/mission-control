import { useId, useState } from 'react'
import toast from 'react-hot-toast'
import { useAdminModels } from '@/hooks/use-admin'
import { useAuthStore } from '@/stores/auth'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { CATALOG_SELECT_CLASS } from '@/components/admin/catalog-select-class'
import type { AgentCatalogItem } from '@/types'

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

type ThinkingMode = 'off' | 'adaptive' | 'fixed'

/** Edits one catalogue entry: model, limits, thinking, engine and chat availability. */
export function CatalogAgentEditor({
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
  const id = useId()
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

  const initialThinking: ThinkingMode = agent.thinking_budget_json
    ? (agent.thinking_budget_json.max_thinking_tokens > 0 ? 'fixed' : 'adaptive')
    : 'off'
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>(initialThinking)
  const [thinkingTokens, setThinkingTokens] = useState(
    String(agent.thinking_budget_json?.max_thinking_tokens || 10000),
  )
  const thinkingEnabled = thinkingMode !== 'off'
  const modelSupportsThinking = THINKING_CAPABLE_MODELS.has(model)

  const handleSave = () => {
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
  }

  return (
    <Panel className="border-brand/30">
      <PanelHeader
        title={`Edit ${agent.agent_name}`}
        actions={
          <>
            <Button size="sm" onClick={handleSave} disabled={saving || (!!provider && !model_name)}>
              {saving && <Spinner className="h-3 w-3 text-current" />}
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </>
        }
      />
      <PanelContent className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Provider" htmlFor={`${id}-provider`}>
            <select
              id={`${id}-provider`}
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              disabled={!isSysadmin}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="">— select provider —</option>
              {providerList.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
              {provider && !providerList.includes(provider) && (
                <option value={provider}>{provider} (unregistered)</option>
              )}
            </select>
          </Field>
          <Field label="Model" htmlFor={`${id}-model`}>
            <select
              id={`${id}-model`}
              value={model_name}
              onChange={(e) => setModelName(e.target.value)}
              disabled={!isSysadmin || !provider}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="">— select model —</option>
              {modelList.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {model_name && !modelList.includes(model_name) && (
                <option value={model_name}>{model_name} (unregistered)</option>
              )}
            </select>
          </Field>
        </div>
        {!isSysadmin && (
          <p className="-mt-1 text-xs text-subtle">Provider and model can only be changed by sysadmins.</p>
        )}
        <div className="grid grid-cols-3 gap-3">
          <Field
            label="Temperature"
            htmlFor={`${id}-temperature`}
            hint={thinkingEnabled ? 'Locked to 1.0 (thinking requires it)' : undefined}
          >
            <Input
              id={`${id}-temperature`}
              value={thinkingEnabled ? '1.0' : temperature}
              onChange={(e) => setTemperature(e.target.value)}
              placeholder="0.0 - 1.0"
              type="number"
              step="0.1"
              min="0"
              max="1"
              disabled={thinkingEnabled}
            />
          </Field>
          <Field label="Max tokens" htmlFor={`${id}-max-tokens`}>
            <Input
              id={`${id}-max-tokens`}
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              placeholder="e.g. 4096"
              type="number"
            />
          </Field>
          <Field
            label="Thinking"
            htmlFor={`${id}-thinking`}
            hint={!modelSupportsThinking && model ? 'Not supported by this model' : undefined}
          >
            <select
              id={`${id}-thinking`}
              value={modelSupportsThinking ? thinkingMode : 'off'}
              onChange={(e) => setThinkingMode(e.target.value as ThinkingMode)}
              disabled={!modelSupportsThinking}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="off">Off</option>
              <option value="adaptive">Adaptive</option>
              <option value="fixed">Fixed Budget</option>
            </select>
          </Field>
        </div>
        {thinkingMode === 'fixed' && modelSupportsThinking && (
          <Field label="Thinking token budget" htmlFor={`${id}-thinking-tokens`}>
            <Input
              id={`${id}-thinking-tokens`}
              value={thinkingTokens}
              onChange={(e) => setThinkingTokens(e.target.value)}
              placeholder="e.g. 10000"
              type="number"
              min="1000"
              step="1000"
            />
          </Field>
        )}
        <Field label="Description" htmlFor={`${id}-description`}>
          <Textarea
            id={`${id}-description`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
          />
        </Field>
        <Field label="Version" htmlFor={`${id}-version`}>
          <Input id={`${id}-version`} value={version} onChange={(e) => setVersion(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Engine" htmlFor={`${id}-engine`}>
            <select
              id={`${id}-engine`}
              value={engine}
              onChange={(e) => setEngine(e.target.value as typeof engine)}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="pydantic_ai">PydanticAI (API Key)</option>
              <option value="claude_code">Claude Code (Subscription)</option>
              <option value="codex">OpenAI Codex (Subscription)</option>
              <option value="copilot">GitHub Copilot (Subscription)</option>
            </select>
          </Field>
          <Field label="Effort" htmlFor={`${id}-effort`}>
            <select
              id={`${id}-effort`}
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
              disabled={engine !== 'claude_code'}
              className={CATALOG_SELECT_CLASS}
            >
              <option value="">— default —</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </Field>
        </div>
        <div className="flex items-start gap-3 rounded-card bg-raised px-3.5 py-3">
          <Switch checked={chatEnabled} onChange={setChatEnabled} label="Chat-enabled" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-3">Chat-enabled</p>
            <p className="mt-0.5 text-xs text-subtle">
              When on, this agent appears as a clickable conversation target on mission Team and Chat pages. The
              agent's <code className="font-mono">create_agent()</code> must accept a{' '}
              <code className="font-mono">chat_mode</code> parameter to behave correctly in conversation; otherwise
              it runs its default path.
            </p>
          </div>
        </div>
      </PanelContent>
    </Panel>
  )
}
