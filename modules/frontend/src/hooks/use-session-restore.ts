import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { api, ApiClient } from '@/lib/api'
import type { UserResponse } from '@/types'

/**
 * Restore a session from the stored refresh token after a full page load, when the access token
 * and user are gone from memory. Returns true while the restore is running; `isAuthenticated`
 * flips before the user is loaded, so callers must wait for false before trusting it.
 * Clears the session if the refresh token is rejected.
 */
export function useSessionRestore(): boolean {
  const { isAuthenticated, refreshToken, setUser, logout } = useAuthStore()
  const [restoring, setRestoring] = useState(!isAuthenticated && !!refreshToken)

  useEffect(() => {
    if (isAuthenticated || !refreshToken) {
      setRestoring(false)
      return
    }

    let cancelled = false

    async function restore() {
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
        if (!cancelled) setRestoring(false)
      }
    }

    restore()
    return () => { cancelled = true }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return restoring
}
