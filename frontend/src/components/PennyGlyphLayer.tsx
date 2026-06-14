import { useEffect, useRef, useState } from 'react'
import PennyRibbon from './PennyRibbon'
import { useGlyphStore, type GlyphRect } from '../store/glyph'

// PennyGlyphLayer — the single persistent Penny glyph, rendered once in App as a
// sibling of <Routes> so it survives the /onboarding -> / route change. It paints
// a fixed-position ribbon over whatever slot is currently the active anchor and
// FLIP-animates (translate + scale) from the previous position to the new one,
// giving the "shrink and float to the home hero" transition.
//
// Dormant (renders nothing) on every route that doesn't register a slot.

const TRAVEL_MS = 700

const prefersReduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function PennyGlyphLayer() {
  const anchor = useGlyphStore((s) => s.anchor)
  const consumeHandoff = useGlyphStore((s) => s.consumeHandoff)
  const setFlying = useGlyphStore((s) => s.setFlying)

  const boxRef = useRef<HTMLDivElement>(null)
  const prevRect = useRef<GlyphRect | null>(null) // where the glyph currently sits
  const [base, setBase] = useState<GlyphRect | null>(null) // settled rect (no transform)

  useEffect(() => {
    if (!anchor) {
      prevRect.current = null
      setBase(null)
      return
    }

    // FLIP "first": prefer a handoff rect captured pre-navigation, else the
    // glyph's last settled rect. No `from` => appear directly (cold mount).
    const handoff = consumeHandoff()
    const from = handoff ?? prevRect.current

    // Settle the box at the destination (no transform) for this render.
    setBase(anchor)

    if (!from || prefersReduced()) {
      prevRect.current = anchor
      return
    }

    let cancelled = false
    requestAnimationFrame(() => {
      const el = boxRef.current
      if (!el || cancelled) return
      // Invert: paint the box back at `from` via transform, no transition.
      const dx = from.x - anchor.x
      const dy = from.y - anchor.y
      const scale = from.size / anchor.size
      el.style.transition = 'none'
      el.style.transform = `translate(${dx}px, ${dy}px) scale(${scale})`
      // Play: next frame, enable the transition and remove the transform.
      requestAnimationFrame(() => {
        if (!el || cancelled) return
        setFlying(true)
        el.style.transition = `transform ${TRAVEL_MS}ms cubic-bezier(0.16, 1, 0.3, 1)`
        el.style.transform = 'translate(0, 0) scale(1)'
        const done = () => {
          el.removeEventListener('transitionend', done)
          setFlying(false)
          prevRect.current = anchor
        }
        el.addEventListener('transitionend', done)
      })
    })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor])

  if (!base) return null
  return (
    <div
      ref={boxRef}
      aria-hidden
      style={{
        position: 'fixed',
        left: base.x,
        top: base.y,
        width: base.size,
        height: base.size,
        transformOrigin: 'top left', // must match the translate/scale math
        zIndex: 40,
        pointerEvents: 'none',
      }}
    >
      {/* Animated: she hovers + twinkles throughout (entrance plays once, on the
          layer's first mount during onboarding). The layer owns the travel via a
          transform on the wrapper above, which composes with the idle hover. */}
      <PennyRibbon size={base.size} animated />
    </div>
  )
}
