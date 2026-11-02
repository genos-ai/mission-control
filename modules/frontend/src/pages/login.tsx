import { useState } from 'react'
import { Navigate, useLocation, type Location, type To } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { useSessionRestore } from '@/hooks/use-session-restore'
import { api, ApiError } from '@/lib/api'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { FullPageSpinner, Spinner } from '@/components/ui/spinner'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import type { LoginResponse } from '@/types'

// Development builds only: a production build folds `import.meta.env.DEV` to false and drops this list.
const DEV_ACCOUNTS = import.meta.env.DEV
  ? [
      { label: 'Sysadmin', email: 'sysadmin@missioncontrol.dev', password: 'sysadmin123', dot: 'bg-danger' },
      { label: 'Admin', email: 'admin@missioncontrol.dev', password: 'admin123', dot: 'bg-warning' },
      { label: 'User', email: 'user@missioncontrol.dev', password: 'user123', dot: 'bg-subtle' },
    ]
  : []

/** Where to go once signed in: the route AuthGuard recorded, else the Dashboard. */
function returnTarget(state: unknown): To {
  const from = (state as { from?: Location } | null)?.from
  if (!from || from.pathname === ROUTES.LOGIN) return ROUTES.DASHBOARD
  return { pathname: from.pathname, search: from.search, hash: from.hash }
}

/** 401 is the only status that means the credentials were wrong; anything else is not the user's doing. */
function signInErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'Invalid email or password'
    return err.status >= 500 ? `${err.message}. Try again shortly.` : err.message
  }
  if (err instanceof TypeError) return 'Cannot reach the server. Check your connection and try again.'
  return err instanceof Error ? err.message : 'Sign-in failed'
}

export default function LoginPage() {
  const location = useLocation()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const login = useAuthStore((s) => s.login)
  const restoring = useSessionRestore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // A stored refresh token means this may be a signed-in user opening /login on a fresh load.
  if (restoring) return <FullPageSpinner />

  // Signed in, either just now or before: leave. This is the only exit, so a successful
  // sign-in cannot race a second navigation to the Dashboard.
  if (isAuthenticated) return <Navigate to={returnTarget(location.state)} replace />

  async function signIn(accountEmail: string, accountPassword: string) {
    setError('')
    setLoading(true)

    try {
      const data = await api.post<LoginResponse>(
        '/auth/login',
        { email: accountEmail, password: accountPassword },
        { skipAuth: true },
      )
      login(data.access_token, data.refresh_token, data.user)
    } catch (err) {
      setError(signInErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    void signIn(email, password)
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="flex w-full max-w-[360px] flex-col gap-7">
        <div className="flex flex-col gap-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-primary font-mono text-[11px] text-primary-foreground">
            MC
          </div>
          <div className="flex flex-col gap-1.5">
            <h1 className="text-2xl font-semibold tracking-[-0.02em]">Sign in to Mission Control</h1>
            <p className="text-md text-muted-foreground">AI-first autonomous agent platform</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Field label="Email" htmlFor="login-email">
            <Input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="email"
            />
          </Field>
          <Field label="Password" htmlFor="login-password" error={error} describedById="login-error">
            <Input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? 'login-error' : undefined}
            />
          </Field>
          <Button type="submit" size="xl" className="w-full" disabled={loading}>
            {loading && <Spinner className="text-primary-foreground" />}
            Sign in
          </Button>
        </form>

        {DEV_ACCOUNTS.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <div className="flex-1 border-t border-line" />
              <span className="text-2xs text-subtle">Development quick login</span>
              <div className="flex-1 border-t border-line" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {DEV_ACCOUNTS.map((account) => (
                <Button
                  key={account.label}
                  type="button"
                  variant="secondary"
                  size="lg"
                  disabled={loading}
                  onClick={() => void signIn(account.email, account.password)}
                >
                  <span className={cn('h-1.5 w-1.5 rounded-full', account.dot)} />
                  {account.label}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
