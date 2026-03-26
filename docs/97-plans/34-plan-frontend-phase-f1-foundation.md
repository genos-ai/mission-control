# Plan 34 — Frontend Phase F1: Foundation

| Field | Value |
|-------|-------|
| **Status** | Draft |
| **Created** | 2026-03-25 |
| **Depends on** | Plan 29 (Frontend Design Spec), Plan 28 (Platform Architecture) |
| **Target** | `modules/frontend/src/` |

---

## 1  Objective

Implement the foundational layer of the Mission Control web frontend: shell layout, routing, typed API client, authentication flow, Zustand stores, and shared UI primitives. After this phase, a developer can log in, see the AppShell with sidebar/status bar, navigate between placeholder routes, and the API client handles auth transparently.

---

## 2  Pre-Implementation Setup

### 2.1  Install missing dependencies

Run from `modules/frontend/`:

```bash
npm install react-router-dom@^6.22 react-hot-toast@^2.4 date-fns@^3.3
```

No other dependencies are needed — React 18, Vite 5, Tailwind 3.4, TanStack React Query 5, Zustand 4, React Hook Form 7, Zod, Lucide React, CVA, clsx, and tailwind-merge are already installed.

### 2.2  Add `/health` to Vite proxy

The existing proxy only forwards `/api`. Add `/health` so the frontend can reach health endpoints:

**File: `vite.config.ts`** — add to `server.proxy`:

```typescript
'/health': {
  target: 'http://localhost:8000',
  changeOrigin: true,
},
```

---

## 3  File Structure

After this phase, `modules/frontend/src/` will contain:

```
src/
├── main.tsx                          # Entry point (update: add Router + Toaster)
├── App.tsx                           # Router outlet (rewrite)
├── index.css                         # Tailwind + CSS variables (keep as-is)
├── vite-env.d.ts                     # Env types (keep as-is)
│
├── types/
│   └── index.ts                      # Update: add domain types
│
├── lib/
│   ├── api.ts                        # Typed fetch wrapper with auth
│   ├── cn.ts                         # clsx + tailwind-merge helper
│   └── constants.ts                  # Route paths, config constants
│
├── stores/
│   ├── auth.ts                       # useAuthStore (Zustand)
│   ├── notifications.ts              # useNotificationStore (Zustand)
│   └── drawer.ts                     # useDrawerStore (Zustand)
│
├── hooks/
│   └── use-role.ts                   # useRole(missionId) hook
│
├── components/
│   ├── ui/
│   │   ├── button.tsx                # Button with CVA variants
│   │   ├── badge.tsx                 # Badge (status, cost, role)
│   │   ├── card.tsx                  # Card container
│   │   ├── input.tsx                 # Text input
│   │   ├── textarea.tsx              # Textarea
│   │   ├── spinner.tsx               # Loading spinner
│   │   └── avatar.tsx                # User/agent avatar
│   │
│   └── layout/
│       ├── app-shell.tsx             # Top-level layout: sidebar + main + statusbar + drawer
│       ├── sidebar.tsx               # Navigation sidebar
│       ├── status-bar.tsx            # Bottom status bar
│       ├── right-drawer.tsx          # Slide-in contextual panel
│       └── auth-guard.tsx            # Route protection + silent re-auth
│
├── pages/
│   ├── login.tsx                     # Login page (full-screen, no shell)
│   ├── dashboard.tsx                 # Placeholder: "Dashboard"
│   ├── profile.tsx                   # Placeholder: "Profile"
│   ├── catalog.tsx                   # Placeholder: "Catalog"
│   ├── not-found.tsx                 # 404 page
│   │
│   ├── mission/
│   │   ├── layout.tsx                # Mission workspace shell (tab bar + header)
│   │   ├── overview.tsx              # Placeholder: "Overview"
│   │   ├── team.tsx                  # Placeholder: "Team"
│   │   ├── chat.tsx                  # Placeholder: "Chat"
│   │   ├── workflows.tsx             # Placeholder: "Workflows"
│   │   ├── runs.tsx                  # Placeholder: "Runs"
│   │   ├── workshop.tsx              # Placeholder: "Workshop"
│   │   └── context.tsx               # Placeholder: "Context"
│   │
│   └── admin/
│       ├── layout.tsx                # Admin layout with tab bar
│       ├── catalog.tsx               # Placeholder: "Admin Catalog"
│       ├── metrics.tsx               # Placeholder: "Admin Metrics"
│       ├── config.tsx                # Placeholder: "Admin Config"
│       ├── health.tsx                # Placeholder: "Admin Health"
│       └── users.tsx                 # Placeholder: "Admin Users"
```

---

## 4  Implementation Steps

### Step 1 — Utility layer (`lib/`)

#### 4.1.1  `lib/cn.ts`

Standard shadcn-style class merge utility:

```typescript
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

#### 4.1.2  `lib/constants.ts`

Route path constants used by the router and sidebar:

```typescript
export const ROUTES = {
  LOGIN: '/login',
  DASHBOARD: '/',
  PROFILE: '/profile',
  CATALOG: '/catalog',

  // Mission workspace
  MISSION: (id: string) => `/missions/${id}`,
  MISSION_OVERVIEW: (id: string) => `/missions/${id}/overview`,
  MISSION_TEAM: (id: string) => `/missions/${id}/team`,
  MISSION_CHAT: (id: string) => `/missions/${id}/chat`,
  MISSION_WORKFLOWS: (id: string) => `/missions/${id}/workflows`,
  MISSION_RUNS: (id: string) => `/missions/${id}/runs`,
  MISSION_WORKSHOP: (id: string) => `/missions/${id}/workshop`,
  MISSION_CONTEXT: (id: string) => `/missions/${id}/context`,

  // Admin
  ADMIN: '/admin',
  ADMIN_CATALOG: '/admin/catalog',
  ADMIN_METRICS: '/admin/metrics',
  ADMIN_CONFIG: '/admin/config',
  ADMIN_HEALTH: '/admin/health',
  ADMIN_USERS: '/admin/users',
} as const

export const API_BASE = '/api/v1'
```

#### 4.1.3  `lib/api.ts`

Typed fetch wrapper. This is the core API client. It must:

1. Inject `Authorization: Bearer <access_token>` on every request
2. On 401 response, attempt silent token refresh via `POST /api/v1/auth/refresh`
3. If refresh succeeds, update the auth store and retry the original request once
4. If refresh fails, clear auth state and redirect to `/login`
5. Provide an `sse()` helper that passes the token as a query parameter

```typescript
import { useAuthStore } from '@/stores/auth'
import { API_BASE, ROUTES } from './constants'

class ApiClient {
  private refreshPromise: Promise<boolean> | null = null

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: { skipAuth?: boolean },
  ): Promise<T> {
    const response = await this.fetch(method, path, body)

    if (response.status === 401 && !options?.skipAuth) {
      const refreshed = await this.tryRefresh()
      if (refreshed) {
        const retry = await this.fetch(method, path, body)
        if (!retry.ok) throw await this.toError(retry)
        return this.unwrap<T>(retry)
      }
      // Refresh failed — redirect to login
      useAuthStore.getState().logout()
      window.location.href = ROUTES.LOGIN
      throw new Error('Session expired')
    }

    if (!response.ok) throw await this.toError(response)
    return this.unwrap<T>(response)
  }

  private async fetch(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<Response> {
    const token = useAuthStore.getState().accessToken
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    return fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }

  private async tryRefresh(): Promise<boolean> {
    // Deduplicate concurrent refresh attempts
    if (this.refreshPromise) return this.refreshPromise
    this.refreshPromise = this.doRefresh()
    try {
      return await this.refreshPromise
    } finally {
      this.refreshPromise = null
    }
  }

  private async doRefresh(): Promise<boolean> {
    const refreshToken = useAuthStore.getState().refreshToken
    if (!refreshToken) return false

    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!response.ok) return false

      const json = await response.json()
      const data = json.data
      useAuthStore.getState().setTokens(
        data.access_token,
        data.refresh_token,
      )
      return true
    } catch {
      return false
    }
  }

  private async unwrap<T>(response: Response): Promise<T> {
    const json = await response.json()
    // Backend wraps everything in ApiResponse — extract .data
    return json.data as T
  }

  private async toError(response: Response): Promise<Error> {
    try {
      const json = await response.json()
      const msg = json.error?.message || json.detail || response.statusText
      return new Error(msg)
    } catch {
      return new Error(response.statusText)
    }
  }

  get<T>(path: string) {
    return this.request<T>('GET', path)
  }
  post<T>(path: string, body?: unknown, options?: { skipAuth?: boolean }) {
    return this.request<T>('POST', path, body, options)
  }
  put<T>(path: string, body: unknown) {
    return this.request<T>('PUT', path, body)
  }
  patch<T>(path: string, body: unknown) {
    return this.request<T>('PATCH', path, body)
  }
  del(path: string) {
    return this.request<void>('DELETE', path)
  }

  /**
   * Create an SSE EventSource connection.
   * EventSource cannot set custom headers, so pass token as query param.
   */
  sse(path: string): EventSource {
    const token = useAuthStore.getState().accessToken
    const separator = path.includes('?') ? '&' : '?'
    const url = `${API_BASE}${path}${token ? `${separator}token=${token}` : ''}`
    return new EventSource(url)
  }
}

export const api = new ApiClient()
```

**Key design decisions:**
- `unwrap()` extracts `.data` from the `ApiResponse` envelope so callers get clean typed data
- Refresh is deduplicated — if multiple 401s fire concurrently, only one refresh runs
- The `sse()` method uses the EventSource API (not fetch-based SSE) for simplicity; token is a query param per Plan 29 spec

---

### Step 2 — Types (`types/index.ts`)

Update the existing types file. Keep the existing `ApiResponse`, `ApiError`, etc. types and add domain types needed by this phase:

```typescript
// ---- Add below existing types ----

// Auth types
export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserResponse
}

export interface TokenRefreshResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// User types
export interface UserResponse {
  id: string
  email: string
  display_name: string
  system_role: 'viewer' | 'user' | 'admin'
  is_active: boolean
  is_service_account: boolean
  last_login_at: string | null
  current_mission_id: string | null
  current_mission_name: string | null
  created_at: string
  updated_at: string
}

// Mission types (minimal for sidebar)
export interface MissionListItem {
  id: string
  name: string
  description: string
  brief: string | null
  status: 'active' | 'paused' | 'archived'
  owner_id: string
  budget_ceiling_usd: number | null
  created_at: string
  updated_at: string
}

// Drawer types
export type DrawerContentType =
  | 'run-events'
  | 'agent-events'
  | 'prompt-history'
  | 'architect-chat'
  | 'event-log'
  | 'output-preview'
  | 'cost-breakdown'
  | 'agent-detail'

// Notification types
export interface Notification {
  id: string
  type: 'gate_approval' | 'run_failed' | 'run_completed' | 'budget_warning'
  title: string
  body: string
  mission_id: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string
}
```

---

### Step 3 — Zustand Stores (`stores/`)

#### 4.3.1  `stores/auth.ts`

```typescript
import { create } from 'zustand'
import type { UserResponse } from '@/types'

const REFRESH_TOKEN_KEY = 'mc_refresh_token'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: UserResponse | null

  // Derived
  isAuthenticated: boolean
  isAdmin: boolean

  // Actions
  setTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: UserResponse) => void
  login: (accessToken: string, refreshToken: string, user: UserResponse) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
  user: null,

  isAuthenticated: false,
  isAdmin: false,

  setTokens: (accessToken, refreshToken) => {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
    set({
      accessToken,
      refreshToken,
      isAuthenticated: true,
    })
  },

  setUser: (user) =>
    set({
      user,
      isAdmin: user.system_role === 'admin',
    }),

  login: (accessToken, refreshToken, user) => {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
    set({
      accessToken,
      refreshToken,
      user,
      isAuthenticated: true,
      isAdmin: user.system_role === 'admin',
    })
  },

  logout: () => {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      isAdmin: false,
    })
  },
}))
```

**Important:** `accessToken` is never persisted — memory only. `refreshToken` goes to `localStorage` under key `mc_refresh_token`. On page load, the `AuthGuard` component reads the stored refresh token and attempts silent re-auth.

#### 4.3.2  `stores/drawer.ts`

```typescript
import { create } from 'zustand'
import type { DrawerContentType } from '@/types'

interface DrawerState {
  isOpen: boolean
  contentType: DrawerContentType | null
  context: Record<string, unknown>

  open: (contentType: DrawerContentType, context?: Record<string, unknown>) => void
  close: () => void
}

export const useDrawerStore = create<DrawerState>((set) => ({
  isOpen: false,
  contentType: null,
  context: {},

  open: (contentType, context = {}) =>
    set({ isOpen: true, contentType, context }),

  close: () =>
    set({ isOpen: false, contentType: null, context: {} }),
}))
```

#### 4.3.3  `stores/notifications.ts`

```typescript
import { create } from 'zustand'
import type { Notification } from '@/types'

interface NotificationState {
  notifications: Notification[]
  unreadCount: number

  add: (notification: Notification) => void
  markRead: (id: string) => void
  markAllRead: () => void
  clear: () => void
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  unreadCount: 0,

  add: (notification) =>
    set((state) => ({
      notifications: [notification, ...state.notifications].slice(0, 100),
      unreadCount: state.unreadCount + 1,
    })),

  markRead: (id) =>
    set((state) => {
      const target = state.notifications.find((n) => n.id === id)
      const wasUnread = target && !target.read
      return {
        notifications: state.notifications.map((n) =>
          n.id === id ? { ...n, read: true } : n,
        ),
        unreadCount: wasUnread ? Math.max(0, state.unreadCount - 1) : state.unreadCount,
      }
    }),

  markAllRead: () =>
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    })),

  clear: () => set({ notifications: [], unreadCount: 0 }),
}))
```

---

### Step 4 — Hooks (`hooks/`)

#### 4.4.1  `hooks/use-role.ts`

Returns the current user's mission-level role for a given mission. In F1 this returns `null` (no mission member data loaded yet). It will be wired to React Query in F2.

```typescript
export type MissionRole = 'owner' | 'maintainer' | 'viewer'

/**
 * Get the current user's role within a specific mission.
 *
 * Phase F1: stub — returns null (unknown).
 * Phase F2+: backed by React Query cache of mission members.
 */
export function useRole(_missionId: string | undefined): {
  role: MissionRole | null
  isOwner: boolean
  isMaintainer: boolean
  isViewer: boolean
  canEdit: boolean
  canOperate: boolean
} {
  // TODO: Phase F2 — query GET /missions/:id/members and find current user
  const role: MissionRole | null = null

  return {
    role,
    isOwner: role === 'owner',
    isMaintainer: role === 'maintainer',
    isViewer: role === 'viewer',
    canEdit: role === 'owner',
    canOperate: role === 'owner' || role === 'maintainer',
  }
}
```

---

### Step 5 — UI Primitives (`components/ui/`)

All primitives use CVA for variants + the `cn()` helper. Follow the shadcn/ui pattern: simple, composable, no external UI library.

#### 4.5.1  `components/ui/button.tsx`

```typescript
import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground shadow hover:bg-primary/90',
        destructive: 'bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90',
        outline: 'border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground',
        secondary: 'bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-10 rounded-md px-8',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  ),
)
Button.displayName = 'Button'

export { Button, buttonVariants }
```

#### 4.5.2  `components/ui/badge.tsx`

```typescript
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        destructive: 'border-transparent bg-destructive text-destructive-foreground',
        outline: 'text-foreground',
        success: 'border-transparent bg-emerald-500/15 text-emerald-500',
        warning: 'border-transparent bg-amber-500/15 text-amber-500',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
```

#### 4.5.3  `components/ui/card.tsx`

```typescript
import * as React from 'react'
import { cn } from '@/lib/cn'

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('rounded-lg border bg-card text-card-foreground shadow-sm', className)}
      {...props}
    />
  ),
)
Card.displayName = 'Card'

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />
  ),
)
CardHeader.displayName = 'CardHeader'

const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn('font-semibold leading-none tracking-tight', className)} {...props} />
  ),
)
CardTitle.displayName = 'CardTitle'

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
  ),
)
CardContent.displayName = 'CardContent'

export { Card, CardHeader, CardTitle, CardContent }
```

#### 4.5.4  `components/ui/input.tsx`

```typescript
import * as React from 'react'
import { cn } from '@/lib/cn'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export { Input }
```

#### 4.5.5  `components/ui/textarea.tsx`

```typescript
import * as React from 'react'
import { cn } from '@/lib/cn'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      className={cn(
        'flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Textarea }
```

#### 4.5.6  `components/ui/spinner.tsx`

```typescript
import { cn } from '@/lib/cn'

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent',
        className,
      )}
    />
  )
}
```

#### 4.5.7  `components/ui/avatar.tsx`

```typescript
import { cn } from '@/lib/cn'

interface AvatarProps {
  name: string
  className?: string
}

export function Avatar({ name, className }: AvatarProps) {
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <div
      className={cn(
        'flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary',
        className,
      )}
    >
      {initials}
    </div>
  )
}
```

---

### Step 6 — Layout Components (`components/layout/`)

#### 4.6.1  `components/layout/auth-guard.tsx`

Wraps protected routes. On mount, if a refresh token exists but there's no access token, performs silent re-auth. Shows a loading spinner during re-auth. Redirects to `/login` if unauthenticated.

```typescript
import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { Spinner } from '@/components/ui/spinner'
import { ROUTES } from '@/lib/constants'
import type { UserResponse } from '@/types'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, refreshToken, setTokens, setUser, logout } = useAuthStore()
  const [checking, setChecking] = useState(!isAuthenticated && !!refreshToken)
  const location = useLocation()

  useEffect(() => {
    if (isAuthenticated || !refreshToken) {
      setChecking(false)
      return
    }

    // Attempt silent re-auth
    let cancelled = false

    async function silentRefresh() {
      try {
        const res = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!res.ok) throw new Error('Refresh failed')

        const json = await res.json()
        const data = json.data
        if (cancelled) return
        setTokens(data.access_token, data.refresh_token)

        // Hydrate user profile
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
```

#### 4.6.2  `components/layout/sidebar.tsx`

The persistent left navigation sidebar. In F1, the mission list comes from React Query (the `useMissions` query). The sidebar shows:
- Logo/wordmark
- Dashboard link
- "MISSIONS" section with mission list from API
- "PLATFORM" section with Catalog and Admin (admin-only)
- Footer with settings, notification bell, and profile icon

```typescript
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard,
  Plus,
  BookOpen,
  Shield,
  Settings,
  Bell,
  User,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { ROUTES } from '@/lib/constants'
import type { MissionListItem } from '@/types'

export function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, isAdmin } = useAuthStore()
  const { unreadCount } = useNotificationStore()

  const { data: missions } = useQuery({
    queryKey: ['missions'],
    queryFn: () =>
      api.get<{ missions: MissionListItem[]; total: number }>('/missions'),
    select: (data) => data.missions,
  })

  const currentMissionId = user?.current_mission_id

  const isActive = (path: string) => location.pathname === path
  const isMissionActive = (id: string) =>
    location.pathname.startsWith(`/missions/${id}`)

  return (
    <aside className="flex h-full w-60 flex-col border-r bg-card">
      {/* Logo */}
      <div className="flex h-14 items-center px-4">
        <Link to={ROUTES.DASHBOARD} className="text-lg font-bold tracking-tight">
          MISSION CONTROL
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {/* Dashboard */}
        <SidebarLink
          to={ROUTES.DASHBOARD}
          icon={<LayoutDashboard className="h-4 w-4" />}
          label="Dashboard"
          active={isActive(ROUTES.DASHBOARD)}
        />

        {/* Missions section */}
        <div className="mt-6 mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Missions
        </div>

        {missions?.map((mission) => (
          <button
            key={mission.id}
            onClick={() => navigate(ROUTES.MISSION_OVERVIEW(mission.id))}
            className={cn(
              'flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent',
              isMissionActive(mission.id) && 'bg-accent text-accent-foreground',
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                isMissionActive(mission.id)
                  ? 'bg-primary'
                  : currentMissionId === mission.id
                    ? 'bg-primary/50'
                    : 'bg-muted-foreground/30',
              )}
            />
            <span className="truncate">{mission.name}</span>
          </button>
        ))}

        <button
          onClick={() => navigate('/missions/new')}
          className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <Plus className="h-4 w-4" />
          New Mission
        </button>

        {/* Platform section */}
        <div className="mt-6 mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Platform
        </div>

        <SidebarLink
          to={ROUTES.CATALOG}
          icon={<BookOpen className="h-4 w-4" />}
          label="Catalog"
          active={isActive(ROUTES.CATALOG)}
        />

        {isAdmin && (
          <SidebarLink
            to={ROUTES.ADMIN}
            icon={<Shield className="h-4 w-4" />}
            label="Admin"
            active={location.pathname.startsWith(ROUTES.ADMIN)}
          />
        )}
      </nav>

      {/* Footer */}
      <div className="flex items-center justify-around border-t p-3">
        <button
          onClick={() => navigate(ROUTES.PROFILE)}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <Settings className="h-4 w-4" />
        </button>

        <button className="relative rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground">
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>

        <button
          onClick={() => navigate(ROUTES.PROFILE)}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <User className="h-4 w-4" />
        </button>
      </div>
    </aside>
  )
}

function SidebarLink({
  to,
  icon,
  label,
  active,
}: {
  to: string
  icon: React.ReactNode
  label: string
  active: boolean
}) {
  return (
    <Link
      to={to}
      className={cn(
        'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent',
        active && 'bg-accent text-accent-foreground font-medium',
      )}
    >
      {icon}
      {label}
    </Link>
  )
}
```

#### 4.6.3  `components/layout/status-bar.tsx`

Bottom bar showing cross-mission activity and connection status.

```typescript
export function StatusBar() {
  // Phase F6 will wire this to live SSE data.
  // For now, show a static "All quiet" message.

  return (
    <div className="flex h-8 items-center justify-between border-t bg-card px-4 text-xs text-muted-foreground">
      <span>All quiet</span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Connected
      </span>
    </div>
  )
}
```

#### 4.6.4  `components/layout/right-drawer.tsx`

Slide-in panel from the right. Compresses main content (not overlay).

```typescript
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useDrawerStore } from '@/stores/drawer'
import { Button } from '@/components/ui/button'

export function RightDrawer() {
  const { isOpen, contentType, close } = useDrawerStore()

  if (!isOpen) return null

  return (
    <div className="flex h-full w-[400px] flex-shrink-0 flex-col border-l bg-card">
      <div className="flex h-10 items-center justify-between border-b px-4">
        <span className="text-sm font-medium capitalize">
          {contentType?.replace(/-/g, ' ') ?? 'Details'}
        </span>
        <Button variant="ghost" size="icon" onClick={close} className="h-7 w-7">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {/* Drawer content will be rendered by feature components in later phases */}
        <p className="text-sm text-muted-foreground">
          {contentType} content goes here
        </p>
      </div>
    </div>
  )
}
```

#### 4.6.5  `components/layout/app-shell.tsx`

The top-level layout wrapper. Renders sidebar, main content (via `<Outlet />`), right drawer, and status bar.

```typescript
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
```

---

### Step 7 — Pages (Placeholder routes)

#### 4.7.1  `pages/login.tsx`

Full-screen login page. No sidebar. Centered card with email + password fields.

```typescript
import { useState } from 'react'
import { Navigate, useNavigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { ROUTES } from '@/lib/constants'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold tracking-tight">
            MISSION CONTROL
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            AI-first autonomous agent platform
          </p>
        </CardHeader>
        <CardContent>
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
        </CardContent>
      </Card>
    </div>
  )
}
```

#### 4.7.2  `pages/not-found.tsx`

```typescript
import { Link } from 'react-router-dom'
import { ROUTES } from '@/lib/constants'

export default function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">Page not found</p>
      <Link to={ROUTES.DASHBOARD} className="text-primary hover:underline">
        Back to Dashboard
      </Link>
    </div>
  )
}
```

#### 4.7.3  Placeholder pages pattern

All other pages follow the same pattern. Each is a default export with the tab name as a heading. Example for `pages/dashboard.tsx`:

```typescript
export default function DashboardPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <p className="mt-2 text-muted-foreground">Global overview goes here.</p>
    </div>
  )
}
```

Create these files using this pattern (replacing the heading text):
- `pages/dashboard.tsx` — "Dashboard"
- `pages/profile.tsx` — "Profile"
- `pages/catalog.tsx` — "Catalog"
- `pages/mission/overview.tsx` — "Overview"
- `pages/mission/team.tsx` — "Team"
- `pages/mission/chat.tsx` — "Chat"
- `pages/mission/workflows.tsx` — "Workflows"
- `pages/mission/runs.tsx` — "Runs"
- `pages/mission/workshop.tsx` — "Workshop"
- `pages/mission/context.tsx` — "Context"
- `pages/admin/catalog.tsx` — "Admin Catalog"
- `pages/admin/metrics.tsx` — "Admin Metrics"
- `pages/admin/config.tsx` — "Admin Config"
- `pages/admin/health.tsx` — "Admin Health"
- `pages/admin/users.tsx` — "Admin Users"

#### 4.7.4  `pages/mission/layout.tsx`

The mission workspace layout with a tab bar. Wraps all `/missions/:id/*` routes.

```typescript
import { NavLink, Outlet, useParams } from 'react-router-dom'
import {
  Activity,
  Users,
  MessageSquare,
  GitBranch,
  Play,
  FlaskConical,
  FileText,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'

const tabs = [
  { label: 'Overview', icon: Activity, path: 'overview' },
  { label: 'Team', icon: Users, path: 'team' },
  { label: 'Chat', icon: MessageSquare, path: 'chat' },
  { label: 'Workflows', icon: GitBranch, path: 'workflows' },
  { label: 'Runs', icon: Play, path: 'runs' },
  { label: 'Workshop', icon: FlaskConical, path: 'workshop' },
  { label: 'Context', icon: FileText, path: 'context' },
]

export default function MissionLayout() {
  const { id } = useParams<{ id: string }>()

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex border-b px-4">
        {tabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={`/missions/${id}/${tab.path}`}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </NavLink>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}
```

#### 4.7.5  `pages/admin/layout.tsx`

```typescript
import { NavLink, Outlet } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'

const tabs = [
  { label: 'Catalog', path: ROUTES.ADMIN_CATALOG },
  { label: 'Metrics', path: ROUTES.ADMIN_METRICS },
  { label: 'Config', path: ROUTES.ADMIN_CONFIG },
  { label: 'Health', path: ROUTES.ADMIN_HEALTH },
  { label: 'Users', path: ROUTES.ADMIN_USERS },
]

export default function AdminLayout() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex border-b px-4">
        {tabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) =>
              cn(
                'border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                isActive
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  )
}
```

---

### Step 8 — Router and App Entry Point

#### 4.8.1  `App.tsx` (rewrite)

```typescript
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'

import { AppShell } from '@/components/layout/app-shell'
import { AuthGuard } from '@/components/layout/auth-guard'

import LoginPage from '@/pages/login'
import DashboardPage from '@/pages/dashboard'
import ProfilePage from '@/pages/profile'
import CatalogPage from '@/pages/catalog'
import NotFoundPage from '@/pages/not-found'

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
          <Route path="admin" element={<AdminLayout />}>
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
```

#### 4.8.2  `main.tsx` (keep as-is)

No changes needed. React Query provider and StrictMode are already set up correctly.

---

### Step 9 — Dark Mode Default

The app should default to dark mode. Add the `dark` class to `<html>` in `index.html`:

**File: `index.html`** — change `<html lang="en">` to:

```html
<html lang="en" class="dark">
```

This activates the `.dark` CSS variables already defined in `index.css`. The light-mode toggle will be added in Phase F8.

---

## 5  Verification Checklist

After implementation, verify:

1. `npm run build` passes (TypeScript + Vite)
2. `npm run dev` starts without errors
3. Navigating to `http://localhost:5173` redirects to `/login`
4. Submitting valid credentials on `/login` redirects to `/` (Dashboard)
5. The AppShell renders: sidebar (with logo, Dashboard, Missions, Platform, footer), main content, and status bar
6. Clicking a mission in the sidebar navigates to `/missions/:id/overview` with the 7-tab bar
7. Clicking Admin in the sidebar navigates to `/admin/catalog` with the 5-tab bar (only visible if user is admin)
8. Refreshing the page preserves the authenticated session (silent re-auth via refresh token)
9. The right drawer opens/closes via the `useDrawerStore` (can test from browser console: `window.__drawer = ...` or React DevTools)
10. Dark mode is active by default
11. All placeholder pages render their heading text
12. Navigating to an unknown route shows 404

---

## 6  What This Phase Does NOT Include

- Mission CRUD (Phase F2)
- Team management / catalog browsing (Phase F3)
- Workflow DAG visualization (Phase F4)
- Event stream rendering (Phase F5)
- SSE integration / live monitoring (Phase F6)
- Chat / Workshop features (Phase F7)
- Admin CRUD / Profile editing / Polish (Phase F8)
- React Query hooks beyond the sidebar mission list
- Notification dropdown popover (just the bell icon with badge count)
- Responsive/collapsed sidebar mode
