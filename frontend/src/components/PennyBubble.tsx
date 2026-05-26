import type { ReactNode } from 'react'

// Penny speaks in first person, in a green-avatar speech bubble (PRD §9).
export default function PennyBubble({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-penny font-semibold text-white">
        P
      </div>
      <div className="rounded-2xl rounded-tl-sm bg-penny-light px-4 py-2 text-sm text-gray-800">
        {children}
      </div>
    </div>
  )
}
