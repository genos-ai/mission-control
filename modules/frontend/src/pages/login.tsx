import { useState } from 'react'
import { Navigate, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import type { LoginResponse } from '@/types'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const login = useAuthStore((s) => s.login)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || ROUTES.DASHBOARD

  // Already authenticated — skip login
  if (isAuthenticated) return <Navigate to={ROUTES.DASHBOARD} replace />

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const data = await api.post<LoginResponse>('/auth/login', { email, password }, { skipAuth: true })
      login(data.access_token, data.refresh_token, data.user)
      navigate(from, { replace: true })
    } catch (err) {
      setError('Invalid email or password')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Panel className="w-full max-w-sm">
        <PanelHeader
          title={<span className="text-2xl font-bold tracking-tight">MISSION CONTROL</span>}
          className="justify-center"
        />
        <p className="px-4 pb-6 text-center text-sm text-muted-foreground">
          AI-first autonomous agent platform
        </p>
        <PanelContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Input
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                autoComplete="email"
              />
            </div>
            <div className="space-y-2">
              <Input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            {error && (
              <p className="text-sm text-destructive">{error}</p>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? <Spinner className="mr-2" /> : null}
              Sign In
            </Button>
          </form>

          {/* Dev quick-login buttons */}
          <div className="mt-6 border-t pt-4">
            <p className="mb-3 text-center text-xs text-muted-foreground">
              Development quick login
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                className="flex-1 border-red-500/30 text-red-600 hover:bg-red-50"
                disabled={loading}
                onClick={() => {
                  setEmail('sysadmin@missioncontrol.dev')
                  setPassword('sysadmin123')
                  setTimeout(() => {
                    document.querySelector<HTMLFormElement>('form')?.requestSubmit()
                  }, 50)
                }}
              >
                Sysadmin
              </Button>
              <Button
                variant="secondary"
                className="flex-1 border-amber-500/30 text-amber-600 hover:bg-amber-50"
                disabled={loading}
                onClick={() => {
                  setEmail('admin@missioncontrol.dev')
                  setPassword('admin123')
                  setTimeout(() => {
                    document.querySelector<HTMLFormElement>('form')?.requestSubmit()
                  }, 50)
                }}
              >
                Admin
              </Button>
              <Button
                variant="secondary"
                className="flex-1"
                disabled={loading}
                onClick={() => {
                  setEmail('user@missioncontrol.dev')
                  setPassword('user123')
                  setTimeout(() => {
                    document.querySelector<HTMLFormElement>('form')?.requestSubmit()
                  }, 50)
                }}
              >
                User
              </Button>
            </div>
          </div>
        </PanelContent>
      </Panel>
    </div>
  )
}
