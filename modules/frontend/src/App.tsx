import { BrowserRouter, Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom'
import { useEffect } from 'react'
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
import WorkflowsPage from '@/pages/mission/workflows'
import RunLivePage from '@/pages/mission/run-live'

import ChatTab from '@/pages/mission/tabs/chat-tab'
import PlanTab from '@/pages/mission/tabs/plan-tab'
import NarrativeTab from '@/pages/mission/tabs/narrative-tab'
import StreamTab from '@/pages/mission/tabs/stream-tab'
import ContextTab from '@/pages/mission/tabs/context-tab'
import KnowledgeTab from '@/pages/mission/tabs/knowledge-tab'
import ArtifactsTab from '@/pages/mission/tabs/artifacts-tab'
import RunsTab from '@/pages/mission/tabs/runs-tab'
import WorkflowsTab from '@/pages/mission/tabs/workflows-tab'
import CostsTab from '@/pages/mission/tabs/costs-tab'

import AdminLayout from '@/pages/admin/layout'
import AdminCatalogPage from '@/pages/admin/catalog'
import AdminMetricsPage from '@/pages/admin/metrics'
import AdminConfigPage from '@/pages/admin/config'
import AdminHealthPage from '@/pages/admin/health'
import AdminUsersPage from '@/pages/admin/users'
import TokenEconomicsPage from '@/pages/admin/token-economics'

// Redirects /missions/:id to the last-visited tab (or 'chat' if none stored).
function MissionDefaultTab() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  useEffect(() => {
    const lastTab = id ? localStorage.getItem(`missions.lastTab.${id}`) : null
    navigate(`/missions/${id}/${lastTab ?? 'chat'}`, { replace: true })
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}

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

          {/* Mission workspace — all tabs under MissionLayout shell */}
          <Route path="missions/:id" element={<MissionLayout />}>
            <Route index element={<MissionDefaultTab />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="team" element={<TeamPage />} />
            <Route path="chat" element={<ChatTab />} />
            <Route path="chat/:threadId" element={<ChatTab />} />
            <Route path="plan" element={<PlanTab />} />
            <Route path="narrative" element={<NarrativeTab />} />
            <Route path="console" element={<StreamTab />} />
            <Route path="context" element={<ContextTab />} />
            <Route path="knowledge" element={<KnowledgeTab />} />
            <Route path="artifacts" element={<ArtifactsTab />} />
            <Route path="runs" element={<RunsTab />} />
            <Route path="runs/:runId" element={<RunLivePage />} />
            <Route path="workflows" element={<WorkflowsTab />} />
            <Route path="costs" element={<CostsTab />} />
            {/* Legacy drill-in: full workflows DAG viz */}
            <Route path="workflows/:workflowId" element={<WorkflowsPage />} />
          </Route>

          {/* Admin section */}
          <Route path="admin" element={<AdminGuard><AdminLayout /></AdminGuard>}>
            <Route index element={<Navigate to="catalog" replace />} />
            <Route path="catalog" element={<AdminCatalogPage />} />
            <Route path="metrics" element={<AdminMetricsPage />} />
            <Route path="config" element={<AdminConfigPage />} />
            <Route path="health" element={<AdminHealthPage />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="token-economics" element={<TokenEconomicsPage />} />
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
