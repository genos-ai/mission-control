export interface NewAgentDraft {
  agent_name: string
  agent_type: 'vertical' | 'horizontal' | 'system'
  description: string
  version: string
}

export const EMPTY_NEW_AGENT: NewAgentDraft = {
  agent_name: '',
  agent_type: 'vertical',
  description: '',
  version: '1.0.0',
}
