import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api, ApiClient } from '@/lib/api'
import { Spinner } from '@/components/ui/spinner'
import { ROUTES } from '@/lib/constants'
import type { UserResponse } from '@/types'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, refreshToken, setUser, logout } = useAuthStore()
  const [checking, setChecking] = useState(!isAuthenticated && !!refreshToken)
  const location = useLocation()

  useEffect(() => {
    if (isAuthenticated || !refreshToken) {
      setChecking(false)
      return
    }

    let cancelled = false

    async function silentRefresh() {
      try {
        const refreshed = await ApiClient.refreshTokens()
        if (cancelled) return
        if (!refreshed) throw new Error('Refresh failed')

        const user = await api.get<UserResponse>('/auth/me')
        if (cancelled) return
        setUser(user)
      } catch {
        if (!cancelled) logout()
      } finally {
        if (!cancelled) setChecking(false)
      }
    }

    silentRefresh()
    return () => { cancelled = true }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to={ROUTES.LOGIN} state={{ from: location }} replace />
  }

  return <>{children}</>
}
