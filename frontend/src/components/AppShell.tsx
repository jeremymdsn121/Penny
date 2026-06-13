import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  BarChart3,
  CalendarDays,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Palette,
  Plus,
  Scale,
  ShieldAlert,
  Sparkles,
  Sun,
  Users,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { brokerApi } from '../lib/api'
import PennyRibbon from './PennyRibbon'
import { useAuthStore } from '../store/auth'
import { useThemeStore } from '../store/theme'
import { useUiStore } from '../store/ui'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  exact?: boolean
}

const NAV: NavItem[] = [
  { to: '/', label: 'Ask Penny', icon: Sparkles, exact: true },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/review', label: 'Needs Review', icon: ShieldAlert },
  { to: '/listings', label: 'Listings', icon: Home },
  { to: '/reports', label: 'Reports', icon: BarChart3 },
  { to: '/knowledge', label: 'Brand & Style', icon: Palette },
  { to: '/agents', label: 'Team', icon: Users },
  { to: '/settings/whatsapp', label: 'Messaging', icon: MessageSquare },
  { to: '/settings/calendar', label: 'Calendar', icon: CalendarDays },
  { to: '/settings/compliance', label: 'Compliance', icon: Scale },
  { to: '/settings/autonomy', label: 'Autonomy', icon: Zap },
]

export default function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const brokerage = useAuthStore((s) => s.brokerage)
  const logout = useAuthStore((s) => s.logout)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)
  const chatStarted = useUiStore((s) => s.chatStarted)
  const [reviewCount, setReviewCount] = useState(0)
  // Mobile-only: the sidebar collapses into a slide-in drawer below `md`.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  // The home launcher ('/') uses its own pill grid for nav, so the sidebar is
  // redundant there — hide it until the user advances (into a page or a chat).
  const onLanding = location.pathname === '/' && !chatStarted

  const name = brokerage?.name ?? 'Penny'

  useEffect(() => {
    brokerApi
      .reviewQueue()
      .then((q) => setReviewCount(q.total))
      .catch(() => {/* badge is best-effort (non-admins 403) */})
  }, [location.pathname])

  // Close the mobile drawer on any navigation.
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  const isActive = (item: NavItem) =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to)

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

  // Shared sidebar body — rendered in the static desktop column and the mobile
  // drawer. Keep it identical in both so there's a single source of nav truth.
  const sidebarBody = (
    <>
      {/* Brand */}
      <Link to="/" className="flex items-center gap-2.5 px-5 py-5">
        <PennyRibbon size={32} />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{name}</p>
        </div>
      </Link>

      {/* Primary action */}
      <div className="px-3 pb-2">
        <button
          onClick={() => navigate('/transactions/new')}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-penny px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-penny-dark"
        >
          <Plus size={16} />
          New transaction
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {NAV.map((item) => {
          const Icon = item.icon
          const active = isActive(item)
          return (
            <Link
              key={item.to}
              to={item.to}
              className={`nav-item ${active ? 'nav-item-active' : ''}`}
            >
              <Icon size={18} strokeWidth={2} />
              <span className="flex-1">{item.label}</span>
              {item.to === '/review' && reviewCount > 0 && (
                <span className="rounded-full bg-red-500/15 px-1.5 py-0.5 text-xs font-semibold text-red-500">
                  {reviewCount}
                </span>
              )}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="space-y-1 border-t border-hairline px-3 py-3">
        <button onClick={toggleTheme} className="nav-item w-full">
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          <span className="flex-1 text-left">{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>
        <div className="flex items-center gap-2 px-3 pt-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-ink-muted">{brokerage?.email ?? ''}</p>
          </div>
          <button
            onClick={onLogout}
            title="Log out"
            className="rounded-md p-1.5 text-ink-subtle transition-colors hover:bg-surface-3 hover:text-ink"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </>
  )

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      {/* Mobile top bar — hamburger + brand. Hidden on the bare landing and md+. */}
      {!onLanding && (
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-hairline bg-surface-2 px-4 py-3 md:hidden">
          <button
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
            className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-surface-3 hover:text-ink"
          >
            <Menu size={20} />
          </button>
          <Link to="/" className="flex min-w-0 items-center gap-2">
            <PennyRibbon size={26} />
            <span className="truncate text-sm font-semibold text-ink">{name}</span>
          </Link>
        </header>
      )}

      {/* Desktop sidebar — static sticky column at md+. */}
      {!onLanding && (
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-hairline bg-surface-2 md:flex">
          {sidebarBody}
        </aside>
      )}

      {/* Mobile drawer — slide-in over a backdrop, below md only. */}
      {!onLanding && mobileNavOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
          <aside className="absolute inset-y-0 left-0 flex h-full w-64 max-w-[82%] flex-col border-r border-hairline bg-surface-2 shadow-xl">
            <button
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close menu"
              className="absolute right-3 top-4 z-10 rounded-md p-1.5 text-ink-subtle transition-colors hover:bg-surface-3 hover:text-ink"
            >
              <X size={18} />
            </button>
            {sidebarBody}
          </aside>
        </div>
      )}

      {/* Landing keeps only the theme + logout controls top-right. */}
      {onLanding && (
        <div className="fixed right-4 top-4 z-20 flex items-center gap-1">
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            className="rounded-md p-2 text-ink-subtle transition-colors hover:bg-surface-3 hover:text-ink"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            onClick={onLogout}
            title="Log out"
            className="rounded-md p-2 text-ink-subtle transition-colors hover:bg-surface-3 hover:text-ink"
          >
            <LogOut size={18} />
          </button>
        </div>
      )}

      {/* Main */}
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
