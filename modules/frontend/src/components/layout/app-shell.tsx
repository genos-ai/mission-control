import { Outlet } from 'react-router-dom'
import { Sidebar } from './sidebar'
import { RightDrawer } from './right-drawer'

export function AppShell() {
  return (
    <div className="flex h-screen min-h-[640px] overflow-hidden bg-background text-foreground">
      <Sidebar />
      {/* The well: floating panels sit on this darker surface. */}
      <div className="flex min-w-0 flex-1 overflow-hidden bg-well">
        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <Outlet />
        </main>
        <RightDrawer />
      </div>
    </div>
  )
}
