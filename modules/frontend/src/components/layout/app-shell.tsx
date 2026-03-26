import { Outlet } from 'react-router-dom'
import { Sidebar } from './sidebar'
import { StatusBar } from './status-bar'
import { RightDrawer } from './right-drawer'

export function AppShell() {
  return (
    <div className="flex h-screen flex-col bg-background">
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto">
            <Outlet />
          </main>
          <RightDrawer />
        </div>
      </div>
      <StatusBar />
    </div>
  )
}
