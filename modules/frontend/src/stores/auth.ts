import { create } from 'zustand'
import type { UserResponse } from '@/types'
import { queryClient } from '@/lib/query-client'

const REFRESH_TOKEN_KEY = 'mc_refresh_token'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: UserResponse | null

  isAuthenticated: boolean
  isAdmin: boolean
  isSysadmin: boolean

  setTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: UserResponse) => void
  login: (accessToken: string, refreshToken: string, user: UserResponse) => void
  logout: () => void
}

// Role hierarchy mirrors backend: viewer < user < admin < sysadmin.
// `isAdmin` means "has admin tier or higher" — sysadmins count as admins.
function adminFromRole(role: string | undefined): boolean {
  return role === 'admin' || role === 'sysadmin'
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
  user: null,

  isAuthenticated: false,
  isAdmin: false,
  isSysadmin: false,

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
      isAdmin: adminFromRole(user.system_role),
      isSysadmin: user.system_role === 'sysadmin',
    }),

  login: (accessToken, refreshToken, user) => {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
    set({
      accessToken,
      refreshToken,
      user,
      isAuthenticated: true,
      isAdmin: adminFromRole(user.system_role),
      isSysadmin: user.system_role === 'sysadmin',
    })
  },

  logout: () => {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    queryClient.clear()
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      isAdmin: false,
      isSysadmin: false,
    })
  },
}))
