import { create } from 'zustand'

// Tracks whether the home chat has advanced past its bare landing state.
// Home sets this; AppShell reads it to decide whether to render the sidebar
// (the landing uses its own pill grid for nav, so the sidebar would be redundant).
interface UiState {
  chatStarted: boolean
  setChatStarted: (v: boolean) => void
}

export const useUiStore = create<UiState>((set) => ({
  chatStarted: false,
  setChatStarted: (v) => set({ chatStarted: v }),
}))
