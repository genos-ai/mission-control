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
