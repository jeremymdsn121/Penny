import { useRef, useState } from 'react'
import { transactionsApi, type Transaction } from '../lib/api'

const HELD_OPTIONS = ['title', 'brokerage', 'escrow', 'other']

function fmtMoney(v?: number | null): string {
  return typeof v === 'number' ? `$${Math.round(v).toLocaleString()}` : '—'
}

export default function EmdCard({
  tx,
  onChange,
}: {
  tx: Transaction
  onChange: (updated: Transaction) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState(false)
  const [amount, setAmount] = useState(tx.emd_amount != null ? String(tx.emd_amount) : '')
  const [due, setDue] = useState(tx.emd_due_date ?? '')
  const [heldBy, setHeldBy] = useState(tx.emd_held_by ?? '')
  const [notes, setNotes] = useState(tx.emd_notes ?? '')
  const [receivedDate, setReceivedDate] = useState(
    tx.emd_received_date ?? new Date().toISOString().slice(0, 10),
  )
  const [busy, setBusy] = useState(false)
  const [marking, setMarking] = useState(false)
  const [unmarking, setUnmarking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function saveDetails() {
    setBusy(true)
    setError(null)
    try {
      const updated = await transactionsApi.update(tx.id, {
        emd_amount: amount ? parseFloat(amount) : null,
        emd_due_date: due || null,
        emd_held_by: heldBy || null,
        emd_notes: notes || null,
      })
      onChange(updated)
      setEditing(false)
    } catch {
      setError('Could not save EMD details.')
    } finally {
      setBusy(false)
    }
  }

  async function markReceived() {
    setBusy(true)
    setError(null)
    try {
      const updated = await transactionsApi.update(tx.id, {
        emd_received: true,
        emd_received_date: receivedDate || null,
      })
      onChange(updated)
      setMarking(false)
    } catch {
      setError('Could not mark EMD received.')
    } finally {
      setBusy(false)
    }
  }

  async function markNotReceived() {
    setBusy(true)
    setError(null)
    try {
      const updated = await transactionsApi.update(tx.id, {
        emd_received: false,
        emd_received_date: null,
      })
      onChange(updated)
      setUnmarking(false)
    } catch {
      setError('Could not update EMD status.')
    } finally {
      setBusy(false)
    }
  }

  async function uploadReceipt(file: File) {
    setBusy(true)
    setError(null)
    try {
      const res = await transactionsApi.uploadEmdReceipt(tx.id, file)
      onChange(res.transaction)
    } catch {
      setError('Could not upload the receipt.')
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          EMD Receipt Tracking
        </h3>
        {tx.emd_received ? (
          <span className="rounded-full bg-green-100 px-3 py-0.5 text-xs font-medium text-green-700">
            Received{tx.emd_received_date ? ` · ${tx.emd_received_date}` : ''}
          </span>
        ) : (
          <span className="rounded-full bg-red-100 px-3 py-0.5 text-xs font-medium text-red-700">
            Not received{tx.emd_due_date ? ` · due ${tx.emd_due_date}` : ''}
          </span>
        )}
      </div>
      <p className="mb-4 text-xs text-gray-400">
        Receipt tracking only — no trust-account math or disbursements.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {editing ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Amount</label>
              <input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 10000"
                className="input"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Due date</label>
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="input" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Held by</label>
              <select value={heldBy} onChange={(e) => setHeldBy(e.target.value)} className="input">
                <option value="">—</option>
                {HELD_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o.charAt(0).toUpperCase() + o.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Notes</label>
              <input value={notes} onChange={(e) => setNotes(e.target.value)} className="input" />
            </div>
          </div>
          <div className="flex gap-3">
            <button onClick={saveDetails} disabled={busy} className="btn-primary">
              Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="text-sm font-medium text-gray-500 hover:text-gray-900"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <dl className="grid gap-y-2 sm:grid-cols-2">
            <dt className="text-xs font-medium text-gray-500">Amount</dt>
            <dd className="text-sm text-gray-900">{fmtMoney(tx.emd_amount)}</dd>
            <dt className="text-xs font-medium text-gray-500">Due date</dt>
            <dd className="text-sm text-gray-900">{tx.emd_due_date || '—'}</dd>
            <dt className="text-xs font-medium text-gray-500">Held by</dt>
            <dd className="text-sm capitalize text-gray-900">{tx.emd_held_by || '—'}</dd>
            {tx.emd_receipt_document_url && (
              <>
                <dt className="text-xs font-medium text-gray-500">Receipt</dt>
                <dd className="truncate text-xs text-violet-600">on file</dd>
              </>
            )}
          </dl>

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-gray-100 pt-4">
            <button
              onClick={() => setEditing(true)}
              className="text-sm font-medium text-penny hover:underline"
            >
              Edit details
            </button>
            {!tx.emd_received ? (
              marking ? (
                <span className="flex items-center gap-2">
                  <input
                    type="date"
                    value={receivedDate}
                    onChange={(e) => setReceivedDate(e.target.value)}
                    className="input w-40"
                  />
                  <button onClick={markReceived} disabled={busy} className="btn-primary">
                    Confirm received
                  </button>
                  <button
                    onClick={() => setMarking(false)}
                    className="text-sm font-medium text-gray-500 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  onClick={() => setMarking(true)}
                  className="rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100"
                >
                  Mark received
                </button>
              )
            ) : unmarking ? (
              <span className="flex items-center gap-2">
                <span className="text-sm text-gray-600">Clear received status?</span>
                <button
                  onClick={markNotReceived}
                  disabled={busy}
                  className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setUnmarking(false)}
                  className="text-sm font-medium text-gray-500 hover:text-gray-900"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                onClick={() => setUnmarking(true)}
                disabled={busy}
                className="text-sm font-medium text-gray-400 hover:text-gray-700"
              >
                Mark not received
              </button>
            )}
            <button
              onClick={() => fileInput.current?.click()}
              disabled={busy}
              className="text-sm font-medium text-gray-500 hover:text-gray-900"
            >
              Upload receipt
            </button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadReceipt(f)
              }}
            />
          </div>
        </>
      )}
    </div>
  )
}
