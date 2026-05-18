/**
 * Login/auth types, user response, API key types.
 */

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
  system_role: 'viewer' | 'user' | 'admin' | 'sysadmin'
  is_active: boolean
  is_service_account: boolean
  last_login_at: string | null
  current_mission_id: string | null
  current_mission_name: string | null
  created_at: string
  updated_at: string
}

export interface ApiKeyResponse {
  id: string
  name: string
  key_prefix: string
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreateResponse extends ApiKeyResponse {
  key: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}
