/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_WS_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  /** Set by the theme boot script in index.html when localStorage was unreadable. */
  __mcThemeStorageError?: string
}

/** Dev-user passwords from config/.env, injected by vite.config.ts. Empty in a production build. */
declare const __DEV_PASSWORDS__: Partial<Record<'sysadmin' | 'admin' | 'user', string>>
