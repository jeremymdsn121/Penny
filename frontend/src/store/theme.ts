import { create } from 'zustand'

export type Theme = 'dark' | 'light'

const KEY = 'sloane-theme'

function apply(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

function initial(): Theme {
  const stored = (typeof localStorage !== 'undefined' && localStorage.getItem(KEY)) as Theme | null
  return stored === 'light' ? 'light' : 'dark' // dark is the default
}

interface ThemeState {
  theme: Theme
  toggle: () => void
  setTheme: (theme: Theme) => void
}

const start = initial()
apply(start) // keep the <html> class in sync as soon as this module loads

export const useThemeStore = create<ThemeState>((set) => ({
  theme: start,
  toggle: () =>
    set((s) => {
      const next: Theme = s.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem(KEY, next)
      apply(next)
      return { theme: next }
    }),
  setTheme: (theme) => {
    localStorage.setItem(KEY, theme)
    apply(theme)
    set({ theme })
  },
}))
