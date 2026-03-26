import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/lib/constants'

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const isAdmin = useAuthStore((s) => s.isAdmin)

  if (!isAdmin) {
    return <Navigate to={ROUTES.DASHBOARD} replace />
  }

  return <>{children}</>
}
