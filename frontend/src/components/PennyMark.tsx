import { useEffect, useRef, useState } from 'react'

/**
 * PennyMark — Penny's wordmark-logo (the letter P), drawn as one continuous
 * stroke. Like a signature: pen down at the bottom of the stem, up the stem,
 * around the bowl, back to where the bowl meets the stem.
 *
 * Animation is opt-in via the `animated` prop:
 *   - default (static)  → the full P, no motion. Sidebar, login, favicon-ish.
 *   - animated          → the stroke draws itself top-to-bottom (~1.4s), then
 *                         the bowl breathes (~6% scale) forever. Use on the
 *                         landing page only.
 *
 * Pure SVG + CSS — no new deps. Honours `prefers-reduced-motion` (renders
 * the final frame, no motion).
 *
 * Usage:
 *   <PennyMark size={160} animated />   // landing
 *   <PennyMark size={32} />             // sidebar / login / inline
 */
interface PennyMarkProps {
  size?: number
  /** Animate on mount + breathe forever. Off by default. */
  animated?: boolean
  label?: string
  className?: string
}

/**
 * Single-stroke P path (viewBox 0 0 120 120). Softened: instead of sharp
 * right-angle corners (the geometric/angular read), the stem curves into
 * the bowl with a quadratic bezier, and the bowl is a slightly opened arc
 * — feminine, drawn-feeling, still confidently a P.
 *
 *   M 34 104                  → start near the bottom of the stem
 *   L 34 26                   → up the stem
 *   Q 34 14 46 14             → round the top-left into the bowl (no corner)
 *   A 30 26 0 1 1 34 64       → single elliptical sweep all the way around
 *                                until it terminates INSIDE the stem at
 *                                x=34. The rounded line cap is hidden by
 *                                the stem stroke, so the bowl reads as
 *                                seamlessly merging — no second curve,
 *                                no kinks.
 *
 * Bowl bbox: y=14..~66 (height ~52), peaking at roughly x=76 on the right.
 * Stem extends to y=104 — a real capital P with room beneath the bowl.
 *
 * Path length: ~265 in viewBox units; we measure the real length at runtime
 * via getTotalLength() so the draw is pixel-accurate.
 */
const P_PATH = 'M 34 104 L 34 26 Q 34 14 46 14 A 30 26 0 1 1 34 64'
const PATH_LENGTH = 300

export default function PennyMark({
  size = 120,
  animated = false,
  label = 'Penny',
  className = '',
}: PennyMarkProps) {
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
      className={`penny-mark penny-mark--${phase} ${className}`}
      style={
        {
          width: size,
          height: size,
          // Pass the measured path length to CSS via a custom property so
          // the keyframes can use it for the stroke-draw effect.
          ['--penny-mark-path-length' as string]: pathLen,
        } as React.CSSProperties
      }
    >
      <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
        <defs>
          {/* Main stroke gradient — the body of the P. */}
          <linearGradient id="pennyMarkStroke" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#A78BFA" />
            <stop offset="100%" stopColor="#7C3AED" />
          </linearGradient>
          {/* Inner highlight gradient — a soft sheen across the top-left of
              the stroke. Low peak opacity + a wider (10px) stroke makes it
              read as a rounded surface catching light, not a second line. */}
          <linearGradient id="pennyMarkHighlight" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.4" />
            <stop offset="40%" stopColor="#FFFFFF" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </linearGradient>
          {/* Soft drop shadow — purple-tinted so it feels brand-native, not
              a hard grey. Sits behind the whole P. */}
          <filter id="pennyMarkShadow" x="-20%" y="-20%" width="140%" height="140%">
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
        <g className="penny-mark__p" filter="url(#pennyMarkShadow)">
          {/* Body stroke — this one carries the draw-in animation. */}
          <path
            ref={pathRef}
            className="penny-mark__stroke"
            d={P_PATH}
            fill="none"
            stroke="url(#pennyMarkStroke)"
            strokeWidth="16"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Inner highlight stroke — thinner, lighter, sits on top of the
              main stroke to imply a rounded surface catching light. Drawn
              in lockstep with the main stroke (same dasharray) so it traces
              the same path during build-in. */}
          <path
            className="penny-mark__highlight"
            d={P_PATH}
            fill="none"
            stroke="url(#pennyMarkHighlight)"
            strokeWidth="10"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      </svg>
    </div>
  )
}
