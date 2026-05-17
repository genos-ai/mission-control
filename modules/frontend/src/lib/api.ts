import { useAuthStore } from '@/stores/auth'
import { API_BASE, ROUTES } from './constants'

export class ApiClient {
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

    return globalThis.fetch(`${API_BASE}${path}`, {
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
    return ApiClient.refreshTokens()
  }

  /**
   * Attempt to refresh the auth session using the stored refresh token.
   * Updates the auth store on success. Shared by api client and AuthGuard.
   */
  static async refreshTokens(): Promise<boolean> {
    const refreshToken = useAuthStore.getState().refreshToken
    if (!refreshToken) return false

    try {
      const response = await globalThis.fetch(`${API_BASE}/auth/refresh`, {
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
}

export const api = new ApiClient()
