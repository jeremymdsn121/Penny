import { useEffect, useState } from 'react'

export interface SectionNavItem {
  id: string
  label: string
}

// Sticky in-page navigator for the (long) transaction page. Clicking scrolls to
// the section; an IntersectionObserver highlights whichever section is in view.
export default function SectionNav({ items }: { items: SectionNavItem[] }) {
  const [active, setActive] = useState<string>(items[0]?.id ?? '')

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-20% 0px -70% 0px', threshold: 0 },
    )
    items.forEach((it) => {
      const el = document.getElementById(it.id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [items])

  const go = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setActive(id)
  }

  return (
    <nav className="sticky top-6 hidden h-fit w-44 shrink-0 lg:block">
      <ul className="space-y-0.5 border-l border-hairline">
        {items.map((it) => {
          const isActive = active === it.id
          return (
            <li key={it.id}>
              <button
                onClick={() => go(it.id)}
                className={`-ml-px block w-full border-l-2 py-1.5 pl-4 text-left text-sm transition-colors ${
                  isActive
                    ? 'border-sloane font-medium text-sloane dark:border-sloane-bright dark:text-sloane-bright'
                    : 'border-transparent text-ink-subtle hover:border-hairline hover:text-ink'
                }`}
              >
                {it.label}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
