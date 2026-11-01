import { useAuthStore } from '@/stores/auth'
import { DocumentPage } from '@/components/layout/document-page'
import { TopBar } from '@/components/layout/top-bar'
import { Spinner } from '@/components/ui/spinner'
import { AccountPanel } from '@/components/profile/account-panel'
import { ApiKeysPanel } from '@/components/profile/api-keys-panel'
import { AppearancePanel } from '@/components/profile/appearance-panel'

export default function ProfilePage() {
  const { user } = useAuthStore()

  const topBar = <TopBar segments={[{ label: 'Profile' }]} />

  if (!user) {
    return (
      <>
        {topBar}
        <div className="flex justify-center p-12">
          <Spinner />
        </div>
      </>
    )
  }

  return (
    <>
      {topBar}
      <DocumentPage className="max-w-[600px] gap-4">
        <div className="pt-2">
          <h1 className="text-lg font-semibold">Profile</h1>
          <p className="text-sm text-muted-foreground">Your account, appearance and API keys.</p>
        </div>
        <AccountPanel />
        <AppearancePanel />
        <ApiKeysPanel />
      </DocumentPage>
    </>
  )
}
