import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'

import { AppShell } from '@/components/layout/app-shell'
import { AuthGuard } from '@/components/layout/auth-guard'
import { AdminGuard } from '@/components/layout/admin-guard'

import LoginPage from '@/pages/login'
import DashboardPage from '@/pages/dashboard'
import ProfilePage from '@/pages/profile'
import CatalogPage from '@/pages/catalog'
import NotFoundPage from '@/pages/not-found'

import NewMissionPage from '@/pages/mission/new'
import MissionLayout from '@/pages/mission/layout'
import OverviewPage from '@/pages/mission/overview'
import TeamPage from '@/pages/mission/team'
import ChatPage from '@/pages/mission/chat'
import WorkflowsPage from '@/pages/mission/workflows'
import RunsPage from '@/pages/mission/runs'
import WorkshopPage from '@/pages/mission/workshop'
import ContextPage from '@/pages/mission/context'

import AdminLayout from '@/pages/admin/layout'
import AdminCatalogPage from '@/pages/admin/catalog'
import AdminMetricsPage from '@/pages/admin/metrics'
import AdminConfigPage from '@/pages/admin/config'
import AdminHealthPage from '@/pages/admin/health'
import AdminUsersPage from '@/pages/admin/users'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public route */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected routes */}
        <Route
          element={
            <AuthGuard>
              <AppShell />
            </AuthGuard>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="catalog" element={<CatalogPage />} />

          {/* Create mission */}
          <Route path="missions/new" element={<NewMissionPage />} />

          {/* Mission workspace */}
          <Route path="missions/:id" element={<MissionLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="team" element={<TeamPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:threadId" element={<ChatPage />} />
            <Route path="workflows" element={<WorkflowsPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunsPage />} />
            <Route path="workshop" element={<WorkshopPage />} />
            <Route path="context" element={<ContextPage />} />
          </Route>

          {/* Admin section */}
          <Route path="admin" element={<AdminGuard><AdminLayout /></AdminGuard>}>
            <Route index element={<Navigate to="catalog" replace />} />
            <Route path="catalog" element={<AdminCatalogPage />} />
            <Route path="metrics" element={<AdminMetricsPage />} />
            <Route path="config" element={<AdminConfigPage />} />
            <Route path="health" element={<AdminHealthPage />} />
            <Route path="users" element={<AdminUsersPage />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>

      <Toaster
        position="bottom-right"
        toastOptions={{
          className: 'bg-card text-card-foreground border shadow-lg',
          duration: 8000,
        }}
      />
    </BrowserRouter>
  )
}
