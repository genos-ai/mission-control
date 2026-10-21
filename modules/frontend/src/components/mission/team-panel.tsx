import { useNavigate } from 'react-router-dom'

import { IconTile } from '@/components/ui/icon-tile'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { agentStyle } from '@/lib/agent-tone'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { agentShortName } from '@/lib/format'
import type { Tone } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import { useWorkspaceStore, type AgentStatusEntry } from '@/stores/workspace'
import type { MissionTeamMember } from '@/types'

/** What an agent is doing right now, from the live roster. */
function liveState(live: AgentStatusEntry | undefined): { text: string; tone: Tone; mono: boolean } {
  switch (live?.status) {
    case 'thinking':
      return { text: 'Thinking', tone: 'brand', mono: false }
    case 'running':
      return { text: live.currentTool ?? 'Running', tone: 'warning', mono: live.currentTool != null }
    case 'done':
      return { text: 'Done', tone: 'success', mono: false }
    case 'failed':
      return { text: 'Failed', tone: 'danger', mono: false }
    default:
      return { text: 'Idle', tone: 'neutral', mono: false }
  }
}

/** The mission's agents, each with its live state. */
export function TeamPanel({ missionId, members }: { missionId: string; members: MissionTeamMember[] }) {
  const navigate = useNavigate()
  const agentStatuses = useWorkspaceStore((s) => s.agentStatuses)

  return (
    <Panel>
      <PanelHeader title="Team" meta={`${members.length} ${members.length === 1 ? 'agent' : 'agents'}`} />
      <PanelContent className="px-0 pb-2">
        {members.length === 0 ? (
          <div className="px-4 pb-2">
            <p className="text-sm text-subtle">No agents yet.</p>
            <Button
              variant="link"
              size="sm"
              className="mt-1 h-auto p-0"
              onClick={() => navigate(ROUTES.MISSION_TEAM(missionId))}
            >
              Add agents &rarr;
            </Button>
          </div>
        ) : (
          members.map((member) => {
            const agentName = member.agent?.agent_name ?? member.agent_catalog_id
            const style = agentStyle(agentName)
            const state = liveState(agentStatuses[agentName])
            return (
              <div key={member.id} className="flex items-center gap-2.5 px-4 py-2 text-sm">
                <IconTile
                  icon={style.icon}
                  tone={style.tone}
                  size="sm"
                  live={state.tone === 'brand' || state.tone === 'warning'}
                />
                <span className="min-w-0 flex-1 truncate" title={agentName}>
                  {agentShortName(agentName)}
                </span>
                <span className={cn('shrink-0 text-xs', TONE_TEXT[state.tone], state.mono && 'font-mono')}>
                  {state.text}
                </span>
              </div>
            )
          })
        )}
      </PanelContent>
    </Panel>
  )
}
