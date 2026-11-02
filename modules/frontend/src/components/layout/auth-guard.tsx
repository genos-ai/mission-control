import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { useSessionRestore } from '@/hooks/use-session-restore'
import { FullPageSpinner } from '@/components/ui/spinner'
import { ROUTES } from '@/lib/constants'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const restoring = useSessionRestore()
  const location = useLocation()

  if (restoring) return <FullPageSpinner />

  if (!isAuthenticated) {
    return <Navigate to={ROUTES.LOGIN} state={{ from: location }} replace />
  }

  return <>{children}</>
}
