import { useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/stores/auth'
import { api, SessionExpiredError } from '@/lib/api'
import { LOGOUT_TIMEOUT_MS, ROUTES } from '@/lib/constants'

/**
 * End the session on the server, then clear it here and go to the login page.
 * The user always ends up signed out on this device: if the server cannot end the session
 * (error, unreachable, or no answer within LOGOUT_TIMEOUT_MS), the refresh token it issued
 * stays valid until it expires, and the toast says so.
 */
export function useSignOut() {
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const [signingOut, setSigningOut] = useState(false)
  // A ref, not the state: two clicks in quick succession both see the same stale state.
  const inFlight = useRef(false)

  async function signOut() {
    if (inFlight.current) return
    inFlight.current = true
    setSigningOut(true)
    try {
      // Before clearing state: the request authenticates with the access token held there.
      await api.post('/auth/logout', undefined, {
        signal: AbortSignal.timeout(LOGOUT_TIMEOUT_MS),
        keepSessionOnExpiry: true,
      })
    } catch (err) {
      // A session that could not even be refreshed is already over; there is nothing to revoke.
      if (!(err instanceof SessionExpiredError)) {
        toast.error(
          'Signed out on this device, but the server could not end the session. It stays valid until it expires.',
        )
      }
    } finally {
      // One render for both: the store update alone re-renders AuthGuard first, which would redirect
      // to /login as an expired session and record this page as the place to return to.
      flushSync(() => {
        logout()
        navigate(ROUTES.LOGIN)
      })
    }
  }

  return { signOut, signingOut }
}
