import { useEffect, useRef, useState } from 'react'
import { checklistApi, type ChecklistItem } from '../lib/api'

const DONE = new Set(['complete', 'waived', 'not_applicable'])

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  complete: 'Complete',
  waived: 'Waived',
  not_applicable: 'N/A',
}

function pct(items: ChecklistItem[]): number {
  const req = items.filter((i) => i.required)
  if (req.length === 0) return 0
  const done = req.filter((i) => DONE.has(i.status)).length
  return Math.round((done / req.length) * 100)
}

function ItemRow({
  item,
  txId,
  onChange,
}: {
  item: ChecklistItem
  txId: string
  onChange: (updated: ChecklistItem) => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const done = DONE.has(item.status)

  async function setStatus(status: string) {
    setBusy(true)
    try {
      onChange(await checklistApi.patchItem(txId, item.id, { status }))
    } finally {
      setBusy(false)
    }
  }

  async function upload(file: File) {
    setBusy(true)
    try {
      onChange(await checklistApi.uploadDocument(txId, item.id, file))
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[10px] ${
              item.status === 'complete'
                ? 'border-green-500 bg-green-500 text-white'
                : done
                  ? 'border-gray-300 bg-gray-200 text-gray-500'
                  : 'border-gray-300'
            }`}
          >
            {item.status === 'complete' ? '✓' : done ? '–' : ''}
          </span>
          <p
            className={`text-sm ${
              item.status === 'waived' ? 'text-gray-400 line-through' : 'text-gray-800'
            }`}
          >
            {item.label}
            {!item.required && <span className="ml-1 text-xs text-gray-400">(optional)</span>}
          </p>
        </div>
        <div className="ml-6 mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-500">
            {STATUS_LABEL[item.status]}
          </span>
          {item.completed_at && (
            <span>{new Date(item.completed_at).toLocaleDateString()}</span>
          )}
          {item.waiver_note && <span title={item.waiver_note}>· note</span>}
          {item.document_url && <span className="text-violet-600">· doc on file</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {item.status !== 'complete' && (
          <button
            onClick={() => setStatus('complete')}
            disabled={busy}
            className="text-xs font-semibold text-penny hover:underline disabled:opacity-50"
          >
            Complete
          </button>
        )}
        {item.document_required && item.status !== 'complete' && (
          <>
            <button
              onClick={() => fileInput.current?.click()}
              disabled={busy}
              className="text-xs font-medium text-gray-500 hover:text-gray-900 disabled:opacity-50"
            >
              Upload
            </button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) upload(f)
              }}
            />
          </>
        )}
        {item.status === 'pending' && (
          <button
            onClick={() => setStatus('waived')}
            disabled={busy}
            className="text-xs font-medium text-gray-400 hover:text-gray-700 disabled:opacity-50"
          >
            Waive
          </button>
        )}
        {done && (
          <button
            onClick={() => setStatus('pending')}
            disabled={busy}
            className="text-xs font-medium text-gray-400 hover:text-gray-700 disabled:opacity-50"
          >
            Reset
          </button>
        )}
      </div>
    </div>
  )
}

export default function ComplianceChecklist({ txId }: { txId: string }) {
  const [items, setItems] = useState<ChecklistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    checklistApi
      .get(txId)
      .then((d) => { if (!ignore) setItems(d) })
      .catch(() => { if (!ignore) setError('Could not load the compliance file.') })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [txId])

  function applyUpdate(updated: ChecklistItem) {
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
  }

  async function addItem() {
    if (!newLabel.trim()) return
    setAdding(true)
    try {
      const item = await checklistApi.addItem(txId, { label: newLabel.trim() })
      setItems((prev) => [...prev, item])
      setNewLabel('')
    } catch {
      setError('Could not add that item.')
    } finally {
      setAdding(false)
    }
  }

  async function removeItem(id: string) {
    try {
      await checklistApi.deleteItem(txId, id)
      setItems((prev) => prev.filter((i) => i.id !== id))
    } catch {
      setError('Template items can’t be deleted — waive them instead.')
    }
  }

  const percent = pct(items)

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          Compliance File
        </h3>
        <span className="text-xs font-medium text-gray-500">{percent}% complete</span>
      </div>
      <p className="mb-3 text-xs text-gray-400">
        Tracks whether the required documents are in the file — your audit-ready closed file.
      </p>

      {/* Progress bar */}
      <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-penny transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="py-4 text-sm text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="py-4 text-sm text-gray-400">
          No checklist yet — it’s created from a template when a transaction is set up.
        </p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((item) => (
            <li key={item.id} className="flex items-start">
              <div className="flex-1">
                <ItemRow item={item} txId={txId} onChange={applyUpdate} />
              </div>
              {!item.template_item_id && (
                <button
                  onClick={() => removeItem(item.id)}
                  className="mt-3 shrink-0 pl-2 text-xs font-medium text-gray-300 hover:text-red-600"
                  title="Remove custom item"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Add custom item */}
      <div className="mt-4 flex items-center gap-2 border-t border-gray-100 pt-4">
        <input
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          placeholder="Add a custom checklist item…"
          className="input flex-1"
        />
        <button
          onClick={addItem}
          disabled={!newLabel.trim() || adding}
          className="btn-primary disabled:opacity-50"
        >
          Add
        </button>
      </div>
    </div>
  )
}
