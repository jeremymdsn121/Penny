import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  CalendarClock,
  Clock,
  Plus,
  ShieldAlert,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { brokerApi, deadlinesApi, transactionsApi, type Transaction } from '../lib/api'
import { useAuthStore } from '../store/auth'

const ACTIVE_STAGES = new Set(['under_contract', 'pending'])

const STAGE_LABELS: Record<string, string> = {
  under_contract: 'Under Contract',
  pending: 'Pending',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const STAGE_COLORS: Record<string, string> = {
  under_contract: 'bg-blue-500/10 text-blue-500 dark:text-blue-400',
  pending: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  closed: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  cancelled: 'bg-gray-500/10 text-ink-muted',
}

function StageBadge({ stage }: { stage?: string | null }) {
  const s = stage ?? 'under_contract'
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
        STAGE_COLORS[s] ?? 'bg-gray-500/10 text-ink-muted'
      }`}
    >
      {STAGE_LABELS[s] ?? s}
    </span>
  )
}

function fmtMoney(v?: number | null): string {
  if (typeof v !== 'number') return '$0'
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`
  return `$${v}`
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86_400_000)
}

function StatCard({
  label,
  value,
  icon: Icon,
  accent,
  onClick,
}: {
  label: string
  value: string | number
  icon: LucideIcon
  accent?: boolean
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`card flex flex-col gap-3 p-5 text-left transition-colors ${
        onClick ? 'hover:bg-surface-3' : 'cursor-default'
      } ${accent ? 'ring-1 ring-penny/40' : ''}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-subtle">
          {label}
        </span>
        <Icon size={18} className={accent ? 'text-penny dark:text-penny-bright' : 'text-ink-subtle'} />
      </div>
      <span className="text-3xl font-semibold tracking-tight text-ink">{value}</span>
    </button>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)

  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [txLoading, setTxLoading] = useState(true)
  const [reminderBusy, setReminderBusy] = useState(false)
  const [reminderNote, setReminderNote] = useState<string | null>(null)
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    transactionsApi
      .list()
      .then(setTransactions)
      .catch(() => {/* silently degrade */})
      .finally(() => setTxLoading(false))
    brokerApi
      .reviewQueue()
      .then((q) => setReviewCount(q.total))
      .catch(() => {/* review stat is best-effort */})
  }, [])

  const stats = useMemo(() => {
    const active = transactions.filter((t) => ACTIVE_STAGES.has(t.stage ?? 'under_contract'))
    const volume = active.reduce((sum, t) => sum + (t.sale_price ?? 0), 0)
    const closingSoon = active.filter((t) => {
      const d = daysUntil(t.closing_date)
      return d !== null && d >= 0 && d <= 14
    }).length
    return { activeCount: active.length, volume, closingSoon }
  }, [transactions])

  const onRunReminders = async () => {
    setReminderBusy(true)
    setReminderNote(null)
    try {
      const res = await deadlinesApi.runReminders()
      setReminderNote(
        res.processed === 0
          ? 'No deadlines are due for a reminder right now.'
          : `Sent ${res.processed} reminder${res.processed !== 1 ? 's' : ''}.`,
      )
    } catch {
      setReminderNote('Could not run reminders. Please try again.')
    } finally {
      setReminderBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      {/* Header */}
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {brokerage?.name ?? 'Dashboard'}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            {transactions.length === 0
              ? 'Drop a contract to get started — I’ll take it from there.'
              : `${transactions.length} transaction${transactions.length !== 1 ? 's' : ''} in your pipeline.`}
          </p>
        </div>
        <button
          onClick={onRunReminders}
          disabled={reminderBusy}
          className="btn-secondary"
          title="Run deadline reminders now"
        >
          {reminderBusy ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-subtle border-t-transparent" />
          ) : (
            <Clock size={16} />
          )}
          Run reminders
        </button>
      </div>

      {reminderNote && (
        <div className="mb-6 rounded-lg border border-penny/30 bg-penny/10 px-4 py-2.5 text-sm text-ink">
          {reminderNote}
        </div>
      )}

      {/* KPI stats */}
      <div className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Active deals" value={stats.activeCount} icon={TrendingUp} />
        <StatCard label="Pipeline volume" value={fmtMoney(stats.volume)} icon={Wallet} />
        <StatCard label="Closing ≤ 14d" value={stats.closingSoon} icon={CalendarClock} />
        <StatCard
          label="Needs review"
          value={reviewCount}
          icon={ShieldAlert}
          accent={reviewCount > 0}
          onClick={() => navigate('/review')}
        />
      </div>

      {/* Transactions */}
      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-hairline px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
            Transactions
          </h2>
          <button
            onClick={() => navigate('/transactions/new')}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-penny hover:text-penny-dark dark:text-penny-bright"
          >
            <Plus size={16} />
            New transaction
          </button>
        </div>

        {txLoading ? (
          <div className="flex justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
          </div>
        ) : transactions.length === 0 ? (
          <div className="px-6 py-14 text-center">
            <p className="text-sm text-ink-subtle">No transactions yet.</p>
            <button
              onClick={() => navigate('/transactions/new')}
              className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-penny hover:underline dark:text-penny-bright"
            >
              Upload your first contract <ArrowRight size={15} />
            </button>
          </div>
        ) : (
          <ul className="divide-y divide-hairline">
            {transactions.map((tx) => (
              <li key={tx.id}>
                <button
                  onClick={() => navigate(`/transactions/${tx.id}`)}
                  className="flex w-full items-center justify-between gap-4 px-6 py-4 text-left transition-colors hover:bg-surface-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {tx.address
                        ? `${tx.address}${tx.city ? `, ${tx.city}` : ''}`
                        : 'Address not set'}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-ink-subtle">
                      {tx.buyer_name ? `Buyer: ${tx.buyer_name}` : 'Buyer —'}
                      {tx.closing_date ? `  ·  Closes ${tx.closing_date}` : ''}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {typeof tx.checklist_pct === 'number' && (
                      <div className="hidden items-center gap-2 sm:flex" title="Compliance file completion">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-3">
                          <div
                            className="h-full rounded-full bg-penny dark:bg-penny-bright"
                            style={{ width: `${tx.checklist_pct}%` }}
                          />
                        </div>
                        <span className="w-9 text-right text-xs tabular-nums text-ink-subtle">
                          {tx.checklist_pct}%
                        </span>
                      </div>
                    )}
                    {!!tx.overdue_tasks && tx.overdue_tasks > 0 && (
                      <span
                        className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-semibold text-red-500"
                        title="Overdue tasks"
                      >
                        {tx.overdue_tasks} overdue
                      </span>
                    )}
                    <StageBadge stage={tx.stage} />
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
