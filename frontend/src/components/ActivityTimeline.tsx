import { useEffect, useState } from 'react'
import { activityApi, type ActivityEntry } from '../lib/api'

function fmtWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

// A small dot colour per kind so the eye can scan the feed.
function dotClass(kind: string): string {
  if (kind === 'delivery_problem') return 'bg-red-500'
  if (kind === 'created') return 'bg-green-500'
  if (kind.startsWith('email')) return 'bg-sky-500'
  if (kind === 'document_routed' || kind === 'reply_sent') return 'bg-violet-500'
  return 'bg-ink-subtle'
}

// "Penny" entries are what she did autonomously — worth a subtle highlight so a
// broker can see at a glance what happened without a human in the loop.
function actorBadge(actor: string): string {
  if (actor === 'Penny') return 'bg-violet-100 text-violet-700'
  if (actor === 'System') return 'bg-surface-3 text-ink-muted'
  return 'bg-surface-3 text-ink-muted'
}

export default function ActivityTimeline({ txId }: { txId: string }) {
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    activityApi
      .list(txId)
      .then((d) => { if (!ignore) setEntries(d) })
      .catch(() => { if (!ignore) setError('Could not load the activity timeline.') })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [txId])

  return (
    <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Activity
      </h3>
      <p className="mb-4 text-xs text-ink-subtle">
        Everything that's happened on this deal, newest first — including what Penny did on her own.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-ink-subtle">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-ink-subtle">No activity recorded yet.</p>
      ) : (
        <ol className="space-y-3">
          {entries.map((e, i) => (
            <li key={`${e.at}-${i}`} className="flex gap-3">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dotClass(e.kind)}`} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm text-ink">{e.title}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${actorBadge(e.actor)}`}>
                    {e.actor}
                  </span>
                </div>
                {e.detail && <p className="text-xs text-ink-muted">{e.detail}</p>}
                <p className="text-xs text-ink-subtle">{fmtWhen(e.at)}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
