import { create } from 'zustand'

import { reportError } from '@/components/error-boundary'

export type Theme = 'dark' | 'warm-white'

// Keep in sync with THEMES in the boot script in index.html. That script is
// the only place the initial theme is validated and applied (it must run
// before first paint); this store reads the result, and throws at start-up if
// the two ever disagree.
export const THEMES: readonly Theme[] = ['dark', 'warm-white']
export const THEME_STORAGE_KEY = 'mc.theme'

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggle: () => void
}

function appliedTheme(): Theme {
  const applied = THEMES.find((t) => document.documentElement.classList.contains(t))
  if (!applied) {
    throw new Error(
      `No theme class (${THEMES.join(' | ')}) on <html>: the boot script in index.html did not run or is out of sync with stores/theme.ts`,
    )
  }
  return applied
}

function reportStorageFailure(message: string) {
  reportError({ message, url: window.location.href })
}

export const useTheme = create<ThemeState>((set, get) => {
  const bootError = window.__mcThemeStorageError
  if (bootError !== undefined) {
    reportStorageFailure(`Theme preference could not be read: ${bootError}`)
    delete window.__mcThemeStorageError
  }

  return {
    theme: appliedTheme(),

    setTheme: (theme) => {
      const root = document.documentElement
      root.classList.remove(...THEMES)
      root.classList.add(theme)
      try {
        localStorage.setItem(THEME_STORAGE_KEY, theme)
      } catch (err) {
        reportStorageFailure(
          `Theme preference could not be saved: ${err instanceof Error ? err.message : String(err)}`,
        )
      }
      set({ theme })
    },

    toggle: () => get().setTheme(get().theme === 'dark' ? 'warm-white' : 'dark'),
  }
})
