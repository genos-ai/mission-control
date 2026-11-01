import { useAuthStore } from '@/stores/auth'
import { Badge } from '@/components/ui/badge'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { ChangePasswordForm } from '@/components/profile/change-password-form'
import { DisplayNameForm } from '@/components/profile/display-name-form'

/** Who the signed-in user is, and the two things they can change about it. */
export function AccountPanel() {
  const user = useAuthStore((s) => s.user)

  return (
    <Panel>
      <PanelHeader title="Account" />
      <PanelContent className="flex flex-col gap-4">
        <div className="flex items-center gap-2 text-sm text-text-2">
          <span>{user?.email}</span>
          <Badge>{user?.system_role}</Badge>
        </div>
        <DisplayNameForm />
        <div className="h-px bg-line" />
        <ChangePasswordForm />
      </PanelContent>
    </Panel>
  )
}
