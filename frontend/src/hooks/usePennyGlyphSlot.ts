import { useEffect, useLayoutEffect, useRef } from 'react'
import { useGlyphStore, type GlyphRect } from '../store/glyph'

// usePennyGlyphSlot — a page renders an invisible `size`×`size` spacer and
// attaches this ref to it. The hook measures the spacer and registers its rect
// as the active glyph anchor; the persistent PennyGlyphLayer paints the visible
// glyph over it. Re-measures on resize / scroll / element resize so the glyph
// tracks layout shifts (e.g. async briefing data on the home page).
//
// `active=false` clears the anchor (the layer goes dormant) — used when a page
// has a slot only in certain states (e.g. Home's landing vs. active chat).
export function usePennyGlyphSlot(id: string, size: number, active = true) {
  const ref = useRef<HTMLDivElement>(null)
  const setAnchor = useGlyphStore((s) => s.setAnchor)

  useLayoutEffect(() => {
    if (!active) {
      setAnchor(id, null)
      return
    }
    const measure = () => {
      const el = ref.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const rect: GlyphRect = { x: r.left, y: r.top, size: r.width }
      setAnchor(id, rect)
    }
    measure()
    const ro = new ResizeObserver(measure)
    if (ref.current) ro.observe(ref.current)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true) // capture: inner scrollers too
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, size, active])

  // Clear the anchor when this slot unmounts (if it still owns it), so a stale
  // rect doesn't linger — the next page registers its own.
  useEffect(
    () => () => {
      const s = useGlyphStore.getState()
      if (s.anchorId === id) s.setAnchor(id, null)
    },
    [id],
  )

  return ref
}
