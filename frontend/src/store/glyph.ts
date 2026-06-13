import { create } from 'zustand'

// Shared state for the single persistent Penny glyph that flies between the
// onboarding screen and the home hero (a shared-element transition across a
// route change — see PennyGlyphLayer + usePennyGlyphSlot).
//
// /onboarding and / live in different layout subtrees, so the glyph itself is
// rendered once in App (above <Routes>) and never unmounts. Pages register an
// invisible slot (a sized spacer) as the `anchor`; the layer paints the visible
// glyph over the active anchor and FLIP-animates between anchors on change.
export interface GlyphRect {
  x: number // viewport left (getBoundingClientRect — layer is position:fixed)
  y: number // viewport top
  size: number // square edge in px
}

interface GlyphState {
  // The slot the active page wants the floating glyph to fill. null => dormant.
  anchor: GlyphRect | null
  anchorId: string | null
  // One-shot rect captured immediately before a route change, used as the FLIP
  // "from" so the travel survives the unmount of the origin slot.
  pendingFrom: GlyphRect | null
  // True while the layer is mid-travel; pages read it to swap their own static
  // glyph in once the flight lands.
  flying: boolean

  setAnchor: (id: string, rect: GlyphRect | null) => void
  beginHandoff: (from: GlyphRect) => void
  consumeHandoff: () => GlyphRect | null
  setFlying: (v: boolean) => void
}

export const useGlyphStore = create<GlyphState>((set, get) => ({
  anchor: null,
  anchorId: null,
  pendingFrom: null,
  flying: false,
  setAnchor: (id, rect) => set({ anchor: rect, anchorId: rect ? id : null }),
  beginHandoff: (from) => set({ pendingFrom: from }),
  consumeHandoff: () => {
    const f = get().pendingFrom
    if (f) set({ pendingFrom: null })
    return f
  },
  setFlying: (v) => set({ flying: v }),
}))
