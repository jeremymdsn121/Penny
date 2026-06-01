import { useEffect, useRef, useState } from 'react'

/**
 * SloaneMark — Sloane's wordmark-logo (the letter S), drawn as one continuous
 * stroke. Two opposing arcs meeting at the waist, like how you'd draw an S
 * with a single pen stroke: top arc hooks from right to left, transitions
 * through the middle, bottom arc hooks from left to right.
 *
 * Animation is opt-in via the `animated` prop:
 *   - default (static)  → the full S, no motion. Sidebar, login, favicon-ish.
 *   - animated          → the stroke draws itself top-to-bottom (~1.4s), then
 *                         the whole S breathes (~4% scale) forever. Use on
 *                         the landing page only.
 *
 * Pure SVG + CSS — no new deps. Honours `prefers-reduced-motion` (renders
 * the final frame, no motion). Depth treatment: inner highlight stroke
 * (rounded-surface sheen) + soft purple drop shadow (subtle lift).
 *
 * Usage:
 *   <SloaneMark size={160} animated />   // landing
 *   <SloaneMark size={32} />             // sidebar / login / inline
 */
interface SloaneMarkProps {
  size?: number
  /** Animate on mount + breathe forever. Off by default. */
  animated?: boolean
  label?: string
  className?: string
}

/**
 * Single-stroke S path (viewBox 0 0 120 120).
 *
 * Geometry: two opposing arcs joined by a cubic bezier through the waist.
 *   M 86 32                      → start at the top-right of the S (natural
 *                                  pen-start point)
 *   A 24 22 0 0 0 38 36          → top arc curves left, down, and around
 *                                  to the start of the waist
 *   C 30 50 90 70 82 84          → cubic through the waist — the belly of
 *                                  the S. Control points pull outward so
 *                                  the transition has sway, not a straight
 *                                  diagonal.
 *   A 24 22 0 0 0 34 88          → bottom arc curves right, down, and
 *                                  around to the bottom-left of the S.
 *
 * Stroke width 16, rounded caps + joins. Same depth treatment as the
 * previous P mark. Whole letterform fits inside a 120×120 viewBox with
 * breathing room.
 *
 * Path length comes out around ~245 in viewBox units; we measure the real
 * length at runtime via getTotalLength() so the draw is pixel-accurate.
 */
const S_PATH = 'M 86 32 A 24 22 0 0 0 38 36 C 30 50 90 70 82 84 A 24 22 0 0 0 34 88'
const PATH_LENGTH = 300

export default function SloaneMark({
  size = 120,
  animated = false,
  label = 'Sloane',
  className = '',
}: SloaneMarkProps) {
  // Gate the build-in to first paint so the keyframes actually run.
  const [armed, setArmed] = useState(false)
  // Measure the real path length on mount so the draw-in is pixel-accurate
  // regardless of font/SVG rendering quirks.
  const pathRef = useRef<SVGPathElement | null>(null)
  const [pathLen, setPathLen] = useState<number>(PATH_LENGTH)

  useEffect(() => {
    if (pathRef.current) {
      const measured = pathRef.current.getTotalLength()
      if (measured > 0) setPathLen(measured)
    }
    if (!animated) return
    const id = requestAnimationFrame(() => setArmed(true))
    return () => cancelAnimationFrame(id)
  }, [animated])

  const phase = !animated ? 'static' : armed ? 'in' : 'pre'

  return (
    <div
      role="img"
      aria-label={label}
      className={`sloane-mark sloane-mark--${phase} ${className}`}
      style={
        {
          width: size,
          height: size,
          // Pass the measured path length to CSS via a custom property so
          // the keyframes can use it for the stroke-draw effect.
          ['--sloane-mark-path-length' as string]: pathLen,
        } as React.CSSProperties
      }
    >
      <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
        <defs>
          {/* Main stroke gradient — the body of the S. */}
          <linearGradient id="sloaneMarkStroke" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#A78BFA" />
            <stop offset="100%" stopColor="#7C3AED" />
          </linearGradient>
          {/* Inner highlight — soft sheen at top-left, fades out diagonally.
              Low peak opacity + wider stroke (10px on a 16px body) reads as
              a rounded surface catching light, not a second line. */}
          <linearGradient id="sloaneMarkHighlight" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.4" />
            <stop offset="40%" stopColor="#FFFFFF" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </linearGradient>
          {/* Purple-tinted drop shadow — brand-native, soft, lifts the S
              off the surface without a halo. */}
          <filter id="sloaneMarkShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="3.5" />
            <feOffset dx="0" dy="2.5" result="offsetblur" />
            <feComponentTransfer>
              <feFuncA type="linear" slope="0.6" />
            </feComponentTransfer>
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 0.486
                      0 0 0 0 0.227
                      0 0 0 0 0.929
                      0 0 0 1 0"
            />
            <feMerge>
              <feMergeNode />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* The whole mark scales together during breathe. Drop shadow is
            applied to the group so the shadow scales with the stroke. */}
        <g className="sloane-mark__p" filter="url(#sloaneMarkShadow)">
          {/* Body stroke — this one carries the draw-in animation. */}
          <path
            ref={pathRef}
            className="sloane-mark__stroke"
            d={S_PATH}
            fill="none"
            stroke="url(#sloaneMarkStroke)"
            strokeWidth="16"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Inner highlight stroke — thinner, lighter, in lockstep with
              the body so it traces the same path during build-in. */}
          <path
            className="sloane-mark__highlight"
            d={S_PATH}
            fill="none"
            stroke="url(#sloaneMarkHighlight)"
            strokeWidth="10"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </svg>
    </div>
  )
}
