import { useEffect, useState } from 'react'
import {
  emailsApi,
  pendingRepliesApi,
  type PendingEmailReply,
  type TransactionEmail,
} from '../lib/api'

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

function eventLabel(event?: string | null): string {
  const e = (event || '').trim()
  if (e.startsWith('stage:')) return `goes ${e.slice(6).replace(/_/g, ' ')}`
  if (e === 'emd_received') return 'EMD is received'
  if (e.startsWith('checklist:')) return `"${e.slice(10)}" is done`
  return e
}

// A short badge describing a deferred send, or '' when awaiting a first decision.
function deferLabel(r: PendingEmailReply): string {
  if (r.status === 'scheduled' && r.scheduled_send_at)
    return `Resurfaces ${fmtWhen(r.scheduled_send_at)}`
  if (r.status === 'awaiting_event') return `Waiting until ${eventLabel(r.trigger_event)}`
  if (r.status === 'held') return 'On hold'
  return ''
}

export default function Communications({
  txId,
  onReply,
}: {
  txId: string
  onReply?: (email: TransactionEmail) => void
}) {
  const [emails, setEmails] = useState<TransactionEmail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  // Suggested replies (outside-party drafts awaiting the agent's approval).
  const [pending, setPending] = useState<PendingEmailReply[]>([])
  const [drafts, setDrafts] = useState<Record<string, { subject: string; body: string }>>({})
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    Promise.all([emailsApi.list(txId), pendingRepliesApi.listForTransaction(txId)])
      .then(([d, p]) => {
        if (ignore) return
        setEmails(d)
        setPending(p)
        setDrafts(
          Object.fromEntries(
            p.map((r) => [r.id, { subject: r.subject, body: r.draft_body }]),
          ),
        )
      })
      .catch(() => { if (!ignore) setError('Could not load communications.') })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [txId])

  async function sendSuggested(r: PendingEmailReply) {
    const draft = drafts[r.id] ?? { subject: r.subject, body: r.draft_body }
    setBusyId(r.id)
    setError(null)
    try {
      await pendingRepliesApi.send(r.id, {
        subject: draft.subject,
        body: draft.body,
        confirmed: true,
      })
      setPending((prev) => prev.filter((x) => x.id !== r.id))
      setConfirmId(null)
      const fresh = await emailsApi.list(txId)
      setEmails(fresh)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Could not send the reply.')
    } finally {
      setBusyId(null)
    }
  }

  async function dismissSuggested(id: string) {
    setBusyId(id)
    try {
      await pendingRepliesApi.dismiss(id)
      setPending((prev) => prev.filter((x) => x.id !== id))
    } catch {
      setError('Could not dismiss the suggestion.')
    } finally {
      setBusyId(null)
    }
  }

  async function expand(email: TransactionEmail) {
    const next = openId === email.id ? null : email.id
    setOpenId(next)
    if (next && email.direction === 'inbound' && !email.read) {
      try {
        await emailsApi.markRead(txId)
        setEmails((prev) =>
          prev.map((e) => (e.direction === 'inbound' ? { ...e, read: true } : e)),
        )
      } catch {
        /* ignore */
      }
    }
  }

  const unread = emails.filter((e) => e.direction === 'inbound' && !e.read).length

  return (
    <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Communications
        </h3>
        {unread > 0 && (
          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-700">
            {unread} unread
          </span>
        )}
      </div>
      <p className="mb-4 text-xs text-ink-subtle">
        Emails Sloane has sent, plus any replies routed back to this deal.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {pending.length > 0 && (
        <div className="mb-5 space-y-3">
          {pending.map((r) => {
            const draft = drafts[r.id] ?? { subject: r.subject, body: r.draft_body }
            const confirming = confirmId === r.id
            const busy = busyId === r.id
            return (
              <div
                key={r.id}
                className="rounded-xl border border-violet-200 bg-violet-50/60 p-4"
              >
                <p className="mb-2 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-700">
                  <span className="inline-block rounded bg-violet-200 px-1.5 py-0.5 text-[10px]">
                    Suggested reply
                  </span>
                  <span className="font-normal normal-case text-ink-subtle">
                    to {r.to_name || r.to_email}
                  </span>
                  {deferLabel(r) && (
                    <span className="inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] normal-case text-amber-700">
                      {deferLabel(r)}
                    </span>
                  )}
                </p>
                {r.summary && (
                  <p className="mb-1 text-sm text-ink">
                    <span className="font-medium">They said:</span> {r.summary}
                  </p>
                )}
                {r.recommendation && (
                  <p className="mb-2 text-sm italic text-ink-muted">{r.recommendation}</p>
                )}
                <input
                  value={draft.subject}
                  onChange={(ev) =>
                    setDrafts((d) => ({ ...d, [r.id]: { ...draft, subject: ev.target.value } }))
                  }
                  className="input mb-2 text-sm"
                  placeholder="Subject"
                />
                <textarea
                  value={draft.body}
                  onChange={(ev) =>
                    setDrafts((d) => ({ ...d, [r.id]: { ...draft, body: ev.target.value } }))
                  }
                  rows={6}
                  className="input mb-1 text-sm"
                  placeholder="Reply body"
                />
                <p className="mb-3 text-xs text-ink-subtle">
                  Sloane drafted this. Review and edit before it goes to {r.to_email}.
                </p>
                {!confirming ? (
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setConfirmId(r.id)}
                      disabled={busy || !draft.body.trim()}
                      className="btn-primary text-sm disabled:opacity-50"
                    >
                      Send…
                    </button>
                    <button
                      onClick={() => dismissSuggested(r.id)}
                      disabled={busy}
                      className="text-sm font-medium text-ink-muted hover:text-ink"
                    >
                      Dismiss
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-3 rounded-lg border border-violet-200 bg-white px-3 py-2">
                    <span className="text-sm text-violet-800">
                      Send this to <strong>{r.to_email}</strong>?
                    </span>
                    <button
                      onClick={() => sendSuggested(r)}
                      disabled={busy}
                      className="btn-primary text-sm"
                    >
                      {busy ? 'Sending…' : 'Confirm send'}
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      disabled={busy}
                      className="text-sm font-medium text-ink-muted hover:text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {loading ? (
        <p className="py-2 text-sm text-ink-subtle">Loading…</p>
      ) : emails.length === 0 ? (
        <p className="py-2 text-sm text-ink-subtle">No emails yet for this transaction.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {emails.map((e) => {
            const isInbound = e.direction === 'inbound'
            const who = isInbound
              ? e.sender_name || e.sender_email || 'Reply'
              : `To ${(e.recipient_emails ?? []).join(', ') || 'parties'}`
            const unreadRow = isInbound && !e.read
            return (
              <li key={e.id} className={unreadRow ? 'bg-violet-50/50' : ''}>
                <button
                  onClick={() => expand(e)}
                  className="flex w-full items-start justify-between gap-3 px-1 py-3 text-left"
                >
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-sm font-medium text-ink">
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          isInbound
                            ? 'bg-green-100 text-green-700'
                            : 'bg-surface-3 text-ink-muted'
                        }`}
                      >
                        {isInbound ? 'In' : 'Out'}
                      </span>
                      <span className="truncate">{e.subject || '(no subject)'}</span>
                    </p>
                    <p className="mt-0.5 truncate text-xs text-ink-subtle">
                      {who} · {fmtWhen(e.received_at)}
                    </p>
                  </div>
                  {unreadRow && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-violet-500" />}
                </button>
                {openId === e.id && (
                  <div className="px-1 pb-4">
                    {e.body_html ? (
                      <iframe
                        srcDoc={e.body_html}
                        sandbox=""
                        title="Email body"
                        className="w-full rounded-lg border border-hairline bg-white"
                        style={{ minHeight: '80px', maxHeight: '400px', overflow: 'auto' }}
                      />
                    ) : (
                      <pre className="whitespace-pre-wrap rounded-lg bg-surface-2 p-3 text-sm text-ink">
                        {e.body_text || '(no text body)'}
                      </pre>
                    )}
                    {isInbound && onReply && (
                      <button
                        onClick={() => onReply(e)}
                        className="mt-2 text-xs font-semibold text-sloane hover:underline"
                      >
                        Reply with a draft →
                      </button>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
