import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SloaneBubble from '../components/SloaneBubble'
import { brokerApi, type ReviewItem, type ReviewQueue } from '../lib/api'

const SECTIONS: { key: keyof ReviewQueue; title: string; tone: string }[] = [
  { key: 'emd_overdue', title: 'Earnest money overdue', tone: 'text-red-700' },
  { key: 'compliance_attention', title: 'Compliance needs attention', tone: 'text-red-700' },
  { key: 'past_closing_not_closed', title: 'Past closing date, not closed', tone: 'text-red-700' },
  { key: 'closing_soon_incomplete', title: 'Closing soon, file incomplete', tone: 'text-yellow-700' },
  { key: 'overdue_deadlines', title: 'Overdue deadlines', tone: 'text-yellow-700' },
  { key: 'stale_transactions', title: 'Stale transactions', tone: 'text-ink' },
]

function ReviewRow({ item }: { item: ReviewItem }) {
  const navigate = useNavigate()
  const [noteOpen, setNoteOpen] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  async function saveNote() {
    if (!note.trim()) return
    setSaving(true)
    try {
      await brokerApi.addReviewNote(item.id, note.trim())
      setSaved(true)
      setNote('')
      setNoteOpen(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className="px-6 py-3">
      <div className="flex items-start justify-between gap-3">
        <button
          onClick={() => navigate(`/transactions/${item.id}`)}
          className="min-w-0 flex-1 text-left"
        >
          <p className="truncate text-sm font-medium text-ink hover:text-sloane">
            {item.address || 'Address not set'}
          </p>
          <p className="mt-0.5 truncate text-xs text-ink-muted">{item.reason}</p>
          <p className="mt-0.5 truncate text-xs text-ink-subtle">
            {item.buyer_name ? `Buyer: ${item.buyer_name}` : ''}
            {item.closing_date ? `  ·  Closes ${item.closing_date}` : ''}
            {item.agent_name ? `  ·  ${item.agent_name}` : ''}
            {`  ·  File ${item.checklist_pct}%`}
          </p>
        </button>
        <button
          onClick={() => setNoteOpen((o) => !o)}
          className="shrink-0 text-xs font-medium text-sloane hover:underline"
        >
          {saved ? 'Note added' : 'Add note'}
        </button>
      </div>
      {noteOpen && (
        <div className="mt-2 flex items-center gap-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Review note…"
            className="input flex-1 text-sm"
          />
          <button
            onClick={saveNote}
            disabled={!note.trim() || saving}
            className="btn-primary disabled:opacity-50"
          >
            Save
          </button>
        </div>
      )}
    </li>
  )
}

export default function ReviewQueue() {
  const navigate = useNavigate()
  const [queue, setQueue] = useState<ReviewQueue | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    brokerApi
      .reviewQueue()
      .then(setQueue)
      .catch(() => setError('Could not load the review queue.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 5 * 60 * 1000) // auto-refresh every 5 minutes
    return () => clearInterval(id)
  }, [load])

  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-ink">Needs Review</h1>
        <button
          onClick={load}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          Refresh
        </button>
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <SloaneBubble>
          {queue && queue.total === 0
            ? 'Everything looks good — nothing needs your attention right now.'
            : 'Here’s what needs your attention across your active deals.'}
        </SloaneBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-sloane border-t-transparent" />
          </div>
        ) : (
          queue &&
          SECTIONS.map(({ key, title, tone }) => {
            const items = queue[key] as ReviewItem[]
            return (
              <section
                key={key}
                className="rounded-2xl border border-hairline bg-surface shadow-sm"
              >
                <div className="flex items-center justify-between border-b border-hairline px-6 py-4">
                  <h2 className={`text-sm font-semibold ${tone}`}>{title}</h2>
                  <span className="rounded-full bg-surface-3 px-2.5 py-0.5 text-xs font-medium text-ink-muted">
                    {items.length}
                  </span>
                </div>
                {items.length === 0 ? (
                  <p className="px-6 py-6 text-center text-sm text-green-600">
                    No transactions need attention here.
                  </p>
                ) : (
                  <ul className="divide-y divide-hairline">
                    {items.map((item) => (
                      <ReviewRow key={`${key}-${item.id}`} item={item} />
                    ))}
                  </ul>
                )}
              </section>
            )
          })
        )}
      </main>
    </div>
  )
}
