import { useEffect, useState } from 'react'
import { transactionsApi, type Transaction } from '../lib/api'

export default function SignaturesCard({ tx }: { tx: Transaction }) {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    transactionsApi
      .docusignStatus(tx.id)
      .then((s) => setConnected(s.connected))
      .catch(() => setConnected(false))
  }, [tx.id])

  async function send() {
    setSending(true)
    setReason(null)
    try {
      const signers = [
        tx.buyer_name && tx.buyer_email
          ? { name: tx.buyer_name, email: tx.buyer_email, role: 'buyer' }
          : null,
        tx.seller_name && tx.seller_email
          ? { name: tx.seller_name, email: tx.seller_email, role: 'seller' }
          : null,
      ].filter(Boolean) as { name: string; email: string; role: string }[]
      const res = await transactionsApi.docusignSend(tx.id, { signers, confirmed: true })
      setReason(res.reason)
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
      <button
        onClick={send}
        disabled={sending || !connected}
        className="btn-primary disabled:opacity-50"
        title={connected ? 'Send for signature' : 'DocuSign not connected'}
      >
        {sending ? 'Sending…' : 'Send for signature'}
      </button>
      {reason && <p className="mt-3 text-xs text-ink-muted">{reason}</p>}
    </div>
  )
}
