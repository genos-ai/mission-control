import { Outlet } from 'react-router-dom'
import { Sidebar } from './sidebar'
import { StatusBar } from './status-bar'
import { RightDrawer } from './right-drawer'

export function AppShell() {
  return (
    <div className="flex h-screen min-h-[640px] flex-col bg-background text-foreground">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />
        {/* The well: floating panels sit on this darker surface. */}
        <div className="flex min-w-0 flex-1 overflow-hidden bg-well">
          <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            <Outlet />
          </main>
          <RightDrawer />
        </div>
      </div>
      <StatusBar />
    </div>
  )
}
