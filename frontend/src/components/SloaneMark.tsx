import { useEffect, useId, useState } from 'react'

/**
 * SloaneMark — Sloane's brand mark: a location pin with a house tucked inside
 * (roof + door), in the brand purple with a glossy, rounded 3-D surface. House
 * + pin reads instantly as "real estate, tied to a place"; the rounded forms
 * keep it warm.
 *
 * Animation is opt-in via the `animated` prop:
 *   - default (static)  → the settled mark, no motion. Sidebar, login, favicon.
 *   - animated          → the pin drops in, squashes on impact, pings its
 *                         location (a ripple), the house settles in, then it
 *                         idles: a gentle breathe and an occasional door
 *                         "blink" (the door doubles as a friendly eye). Use on
 *                         the landing page only.
 *
 * Pure SVG + CSS — no new deps. Honours `prefers-reduced-motion` (renders the
 * settled mark, no motion). Per-instance ids (useId) so two marks on one page
 * (sidebar + landing) don't share gradient / clip / filter ids.
 *
 * Usage:
 *   <SloaneMark size={120} animated />   // landing
 *   <SloaneMark size={32} />             // sidebar / login / inline
 */
interface SloaneMarkProps {
  size?: number
  /** Run the drop-in + idle (breathe/blink) animation. Off by default. */
  animated?: boolean
  label?: string
  className?: string
}

/** Point-up teardrop pin (viewBox 0 0 120 120). */
const PIN = 'M 60 17 C 45 34 28 51 28 73 A 32 32 0 1 0 92 73 C 92 51 75 34 60 17 Z'
/** The house roof tucked inside the pin. */
const ROOF = 'M 41 63 L 60 45 L 79 63'

export default function SloaneMark({
  size = 120,
  animated = false,
  label = 'Sloane',
  className = '',
}: SloaneMarkProps) {
  // Gate the build-in to first paint so the keyframes actually run (and so the
  // pre-frame state is applied first, avoiding a flash of the settled mark).
  const [armed, setArmed] = useState(false)

  // Unique per-instance id suffix.
  const uid = useId().replace(/:/g, '')

  useEffect(() => {
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
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
        <defs>
          {/* Body gradient — top-lit lavender easing to a deep purple base. */}
          <linearGradient id={`g${uid}`} x1="0.12" y1="0.05" x2="0.85" y2="1">
            <stop offset="0%" stopColor="#CBBAFB" />
            <stop offset="50%" stopColor="#8B5CF6" />
            <stop offset="100%" stopColor="#5E22C6" />
          </linearGradient>
          {/* Sheen — gloss across the upper-left of the rounded surface. */}
          <linearGradient id={`sheen${uid}`} x1="0.12" y1="0.02" x2="0.5" y2="0.8">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.6" />
            <stop offset="34%" stopColor="#FFFFFF" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </linearGradient>
          {/* Specular hotspot on the shoulder. */}
          <radialGradient id={`hot${uid}`} cx="35%" cy="30%" r="24%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </radialGradient>
          {/* Form shadow pooling lower-right — gives the body roundness. */}
          <radialGradient id={`form${uid}`} cx="70%" cy="82%" r="46%">
            <stop offset="0%" stopColor="#2E1065" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#2E1065" stopOpacity="0" />
          </radialGradient>
          <clipPath id={`clip${uid}`}>
            <path d={PIN} />
          </clipPath>
          {/* Purple-tinted drop shadow — brand-native lift. */}
          <filter id={`shadow${uid}`} x="-35%" y="-30%" width="170%" height="175%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2.8" />
            <feOffset dy="3.5" />
            <feComponentTransfer>
              <feFuncA type="linear" slope="0.5" />
            </feComponentTransfer>
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 0.28
                      0 0 0 0 0.11
                      0 0 0 0 0.58
                      0 0 0 1 0"
            />
            <feMerge>
              <feMergeNode />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Contact shadow + location-ping ripples sit behind the pin and only
            show during the drop-in (idle/static keep them hidden). */}
        <ellipse className="sloane-mark__contact" cx="60" cy="104" rx="16" ry="3.4" fill="#000000" />
        <ellipse className="sloane-mark__ring sloane-mark__ring--1" cx="60" cy="103" rx="22" ry="7"
          fill="none" stroke="#A78BFA" strokeWidth="2.5" />
        <ellipse className="sloane-mark__ring sloane-mark__ring--2" cx="60" cy="103" rx="22" ry="7"
          fill="none" stroke="#A78BFA" strokeWidth="2.5" />

        {/* The mark drops + squashes on impact; the inner group breathes. */}
        <g className="sloane-mark__mark" filter={`url(#shadow${uid})`}>
          <g className="sloane-mark__breathe">
            <path d={PIN} fill={`url(#g${uid})`} />
            <g clipPath={`url(#clip${uid})`}>
              <rect width="120" height="120" fill={`url(#form${uid})`} />
              <rect width="120" height="120" fill={`url(#sheen${uid})`} />
              <ellipse cx="44" cy="44" rx="15" ry="19" fill={`url(#hot${uid})`} />
            </g>
            {/* House: roof + door (the door blinks like an eye when idle). */}
            <path
              className="sloane-mark__house"
              d={ROOF}
              fill="none"
              stroke="#F4F0FE"
              strokeWidth="8.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <rect className="sloane-mark__door" x="53" y="67" width="14" height="17" rx="4.5" fill="#F4F0FE" />
          </g>
        </g>
      </svg>
    </div>
  )
}
