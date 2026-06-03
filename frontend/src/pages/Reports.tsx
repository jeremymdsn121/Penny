import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { reportsApi, type BrokerSummary } from '../lib/api'

const PERIODS: { key: string; label: string }[] = [
  { key: 'month', label: 'This Month' },
  { key: 'quarter', label: 'This Quarter' },
  { key: 'ytd', label: 'YTD' },
]

const STAGE_LABEL: Record<string, string> = {
  under_contract: 'Under Contract',
  pending: 'Pending',
}

function money(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`
  return `$${v}`
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-subtle">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
    </div>
  )
}

export default function Reports() {
  const navigate = useNavigate()
  const [period, setPeriod] = useState('month')
  const [data, setData] = useState<BrokerSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    reportsApi
      .summary(period)
      .then(setData)
      .catch(() => setError('Could not load the report.'))
      .finally(() => setLoading(false))
  }, [period])

  const stageEntries = data ? Object.entries(data.pipeline.by_stage) : []
  const maxStage = Math.max(1, ...stageEntries.map(([, n]) => n))

  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-ink">Reports</h1>
        <button
          onClick={() => reportsApi.downloadExport(period).catch(() => setError('Export failed.'))}
          className="text-sm font-medium text-penny hover:underline"
        >
          Export CSV
        </button>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        <PennyBubble>Here’s how the business is doing this {period === 'ytd' ? 'year' : period}.</PennyBubble>

        <div className="flex gap-2">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${
                period === p.key
                  ? 'border-violet-300 bg-violet-50 text-violet-700'
                  : 'border-hairline text-ink-muted hover:border-hairline'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading || !data ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
          </div>
        ) : (
          <>
            {/* Pipeline */}
            <section className="space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Pipeline
              </h2>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Active deals" value={String(data.pipeline.active_transactions)} />
                <Stat label="Active volume" value={money(data.pipeline.active_volume)} />
                <Stat label="Closing this month" value={String(data.pipeline.closing_this_month)} />
              </div>
              <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
                <p className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-subtle">
                  By stage
                </p>
                {stageEntries.length === 0 ? (
                  <p className="text-sm text-ink-subtle">No active deals.</p>
                ) : (
                  <div className="space-y-2">
                    {stageEntries.map(([stage, n]) => (
                      <div key={stage} className="flex items-center gap-3">
                        <span className="w-28 shrink-0 text-xs text-ink-muted">
                          {STAGE_LABEL[stage] ?? stage}
                        </span>
                        <div className="h-5 flex-1 overflow-hidden rounded bg-surface-3">
                          <div
                            className="flex h-full items-center justify-end rounded bg-penny px-2 text-[10px] font-semibold text-white"
                            style={{ width: `${(n / maxStage) * 100}%` }}
                          >
                            {n}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {/* Production */}
            <section className="space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Production
              </h2>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Closed" value={String(data.production.closed_count)} />
                <Stat label="Closed volume" value={money(data.production.closed_volume)} />
                <Stat label="Avg days to close" value={String(data.production.avg_days_to_close)} />
              </div>
              <div className="rounded-2xl border border-hairline bg-surface shadow-sm">
                <div className="border-b border-hairline px-6 py-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-ink-subtle">
                    Agent leaderboard
                  </p>
                </div>
                {data.production.agent_breakdown.length === 0 ? (
                  <p className="px-6 py-6 text-sm text-ink-subtle">No closings in this period.</p>
                ) : (
                  <table className="w-full text-left text-sm">
                    <tbody className="divide-y divide-hairline">
                      {data.production.agent_breakdown.map((a) => (
                        <tr key={a.agent_name}>
                          <td className="px-6 py-3 text-ink">{a.agent_name}</td>
                          <td className="px-6 py-3 text-right text-ink-muted">{a.closed} closed</td>
                          <td className="px-6 py-3 text-right font-medium text-ink">
                            {money(a.volume)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </section>

            {/* Compliance health */}
            <section className="space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Compliance Health
              </h2>
              <div className="grid grid-cols-3 gap-3">
                <Stat
                  label="Avg file at close"
                  value={`${data.compliance.avg_checklist_completion_at_close}%`}
                />
                <Stat label="Open items" value={String(data.compliance.open_compliance_items_total)} />
                <Stat label="Needs attention" value={String(data.compliance.needs_attention)} />
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
