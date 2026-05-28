import { useEffect, useState } from 'react'
import { emailsApi, type TransactionEmail } from '../lib/api'

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

  useEffect(() => {
    emailsApi
      .list(txId)
      .then(setEmails)
      .catch(() => setError('Could not load communications.'))
      .finally(() => setLoading(false))
  }, [txId])

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
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          Communications
        </h3>
        {unread > 0 && (
          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-700">
            {unread} unread
          </span>
        )}
      </div>
      <p className="mb-4 text-xs text-gray-400">
        Emails Penny has sent, plus any replies routed back to this deal.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="py-2 text-sm text-gray-400">Loading…</p>
      ) : emails.length === 0 ? (
        <p className="py-2 text-sm text-gray-400">No emails yet for this transaction.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
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
                    <p className="flex items-center gap-2 text-sm font-medium text-gray-900">
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          isInbound
                            ? 'bg-green-100 text-green-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {isInbound ? 'In' : 'Out'}
                      </span>
                      <span className="truncate">{e.subject || '(no subject)'}</span>
                    </p>
                    <p className="mt-0.5 truncate text-xs text-gray-400">
                      {who} · {fmtWhen(e.received_at)}
                    </p>
                  </div>
                  {unreadRow && <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-violet-500" />}
                </button>
                {openId === e.id && (
                  <div className="px-1 pb-4">
                    <pre className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
                      {e.body_text || '(no text body)'}
                    </pre>
                    {isInbound && onReply && (
                      <button
                        onClick={() => onReply(e)}
                        className="mt-2 text-xs font-semibold text-penny hover:underline"
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
