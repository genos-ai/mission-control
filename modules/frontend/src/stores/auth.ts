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

  setTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: UserResponse) => void
  login: (accessToken: string, refreshToken: string, user: UserResponse) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
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
    queryClient.clear()
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      isAdmin: false,
    })
  },
}))
