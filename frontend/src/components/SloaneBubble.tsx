import type { ReactNode } from 'react'
import SloaneMark from './SloaneMark'

// Sloane speaks in first person, with the brand mark as her avatar (PRD §9).
export default function SloaneBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <SloaneMark size={36} className="shrink-0" />
      <div className="rounded-2xl rounded-tl-sm bg-sloane-light px-4 py-2 text-sm text-gray-800">
        {children}
      </div>
    </div>
  )
}
