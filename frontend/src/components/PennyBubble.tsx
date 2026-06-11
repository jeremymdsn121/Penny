import type { ReactNode } from 'react'
import PennyRibbon from './PennyRibbon'

export default function PennyBubble({ children, animated }: { children: ReactNode; animated?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <PennyRibbon size={36} animated={animated} className="shrink-0" />
      <div className="rounded-2xl rounded-tl-sm bg-penny-light px-4 py-2 text-sm text-gray-800">
        {children}
      </div>
    </div>
  )
}
