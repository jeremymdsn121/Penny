import { useEffect, useState } from 'react'
import { transactionsApi, type Transaction } from '../lib/api'

export default function SignaturesCard({ tx }: { tx: Transaction }) {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    transactionsApi
      .docusignStatus(tx.id)
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false))
  }, [tx.id])

  const signers = [
    tx.buyer_name && tx.buyer_email
      ? { name: tx.buyer_name, email: tx.buyer_email, role: 'buyer' }
      : null,
    tx.seller_name && tx.seller_email
      ? { name: tx.seller_name, email: tx.seller_email, role: 'seller' }
      : null,
  ].filter(Boolean) as { name: string; email: string; role: string }[]

  // The Confirm button below is the human confirmation the gated endpoint
  // requires — confirmed: true must never ride on the first click.
  async function send() {
    setSending(true)
    setReason(null)
    try {
      const res = await transactionsApi.docusignSend(tx.id, { signers, confirmed: true })
      setReason(res.reason)
      setConfirming(false)
    } catch {
      setReason('Could not send for signature.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">Signatures</h3>
        <span
          className={`rounded-full px-3 py-0.5 text-xs font-medium ${
            connected ? 'bg-green-100 text-green-700' : 'bg-surface-3 text-ink-muted'
          }`}
        >
          {connected == null ? '…' : connected ? 'DocuSign connected' : 'Not connected'}
        </span>
      </div>
      <p className="mb-4 text-xs text-ink-subtle">
        Send the contract for e-signature via DocuSign. Connecting DocuSign needs an
        integration key and partner review (see BLOCKERS.md).
      </p>
      {confirming ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-ink-muted">
            Send to {signers.length > 0 ? signers.map((s) => s.name).join(' and ') : 'the parties on file'}?
          </span>
          <button onClick={send} disabled={sending} className="btn-primary disabled:opacity-50">
            {sending ? 'Sending…' : 'Confirm send'}
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="text-sm font-medium text-ink-muted hover:text-ink"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          disabled={!connected}
          className="btn-primary disabled:opacity-50"
          title={connected ? 'Send for signature' : 'DocuSign not connected'}
        >
          Send for signature
        </button>
      )}
      {reason && <p className="mt-3 text-xs text-ink-muted">{reason}</p>}
    </div>
  )
}
