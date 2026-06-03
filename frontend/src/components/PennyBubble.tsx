import type { ReactNode } from 'react'
import PennyMark from './PennyMark'

// Penny speaks in first person, with the brand mark as her avatar (PRD §9).
export default function PennyBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <PennyMark size={36} className="shrink-0" />
      <div className="rounded-2xl rounded-tl-sm bg-penny-light px-4 py-2 text-sm text-gray-800">
        {children}
      </div>
    </div>
  )
}
