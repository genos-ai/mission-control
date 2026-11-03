import { useAuthStore } from '@/stores/auth'
import { API_BASE } from './constants'

/** An API response that was not 2xx. `status` lets callers tell "wrong credentials" from "server down". */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/** The access token expired and the refresh token was refused, so the session is over. */
export class SessionExpiredError extends Error {
  constructor() {
    super('Session expired')
    this.name = 'SessionExpiredError'
  }
}

interface RequestOptions {
  skipAuth?: boolean
  /** Cancels the request itself; a refresh it triggers is shared with other callers and is not cancelled. */
  signal?: AbortSignal
  /** For a caller that signs out itself: on SessionExpiredError the store is left for it to clear. */
  keepSessionOnExpiry?: boolean
}

export class ApiClient {
  private refreshPromise: Promise<boolean> | null = null

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions,
  ): Promise<T> {
    const response = await this.fetch(method, path, body, options?.signal)

    if (response.status === 401 && !options?.skipAuth) {
      const refreshed = await this.tryRefresh()
      if (refreshed) {
        const retry = await this.fetch(method, path, body, options?.signal)
        if (!retry.ok) throw await this.toError(retry)
        return this.unwrap<T>(retry)
      }
      // Refresh failed. Clearing the session is enough: AuthGuard redirects to /login and
      // records the current route, so signing in returns here. A full page load would lose it.
      if (!options?.keepSessionOnExpiry) useAuthStore.getState().logout()
      throw new SessionExpiredError()
    }

    if (!response.ok) throw await this.toError(response)
    return this.unwrap<T>(response)
  }

  private async fetch(
    method: string,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
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
      signal,
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
      // The user signed out while this request was in flight: writing the tokens would sign them back in.
      if (!useAuthStore.getState().refreshToken) return false
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

  private async toError(response: Response): Promise<ApiError> {
    try {
      const json = await response.json()
      const msg = json.error?.message || json.detail || response.statusText
      return new ApiError(msg, response.status)
    } catch {
      return new ApiError(response.statusText, response.status)
    }
  }

  get<T>(path: string) {
    return this.request<T>('GET', path)
  }
  post<T>(path: string, body?: unknown, options?: RequestOptions) {
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
