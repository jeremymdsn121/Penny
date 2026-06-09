import { RIBBON_VIEWBOX, RIBBON_DOTS } from './pennyRibbonArt'
import pennyP from '../assets/penny-p.png'

/**
 * PennyRibbon — Penny's ribbon-"p" brand mark: a rolled violet ribbon forming a
 * lowercase p (stem, bowl, fold-over, underside curl into the centre), ringed by
 * 24 tiny gradient sparkles.
 *
 * The `p` is the approved, hand-tuned raster (marketing/_logo5 → baked to
 * assets/penny-p.png): a recoloured violet render on transparency, crisp and
 * smooth at the sizes the app uses (it's a 436px source — plenty for the hero;
 * the vector source marketing/_p_vector.svg is kept for any large-format need).
 * The 24 sparkles ride on top as SVG so they can twinkle, and the whole mark
 * breathes.
 *
 * Animation is opt-in via `animated` (matches PennyMark's convention):
 *   - default (static) → settled mark, no motion. Sidebar / inline / favicon.
 *   - animated         → fades + scales in, then idles: a gentle breathe while
 *                        the sparkles twinkle. Use on the landing / home hero.
 *
 * Honours prefers-reduced-motion (settles, no motion) via index.css.
 */
interface PennyRibbonProps {
  size?: number
  /** Run the fade/scale-in entrance + idle breathe + twinkle. Off by default. */
  animated?: boolean
  label?: string
  className?: string
}

export default function PennyRibbon({
  size = 120,
  animated = false,
  label = 'Penny',
  className = '',
}: PennyRibbonProps) {
  return (
    <div
      role="img"
      aria-label={label}
      className={`penny-ribbon ${animated ? 'penny-ribbon--anim' : ''} ${className}`}
      style={{ width: size, height: size }}
    >
      <svg viewBox={RIBBON_VIEWBOX} width={size} height={size} aria-hidden="true">
        <g className="penny-ribbon__breathe">
          {/* The approved ribbon-p (recoloured raster, transparent). */}
          <image href={pennyP} x="0" y="0" width="436" height="447" />
          {/* Sparkles are the animated layer — only rendered when animated, so
              static instances are a clean p (no breathing, no twinkling). They
              live in negative space (the centre hole + around the edge), never
              over the p body. */}
          {animated && (
            <g className="penny-ribbon__dots">
              {RIBBON_DOTS.map((d, i) => (
                <circle
                  key={i}
                  cx={d.cx}
                  cy={d.cy}
                  r={d.r}
                  fill={d.fill}
                  style={{ animationDelay: `${d.delay}s` }}
                />
              ))}
            </g>
          )}
        </g>
      </svg>
    </div>
  )
}
