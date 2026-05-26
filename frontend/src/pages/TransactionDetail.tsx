import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { transactionsApi, type Transaction } from '../lib/api'

// --------------------------------------------------------------------------- //
// Field groups — same structure as NewTransaction for consistency
// --------------------------------------------------------------------------- //

const FIELD_GROUPS = [
  {
    label: 'Property',
    fields: [
      { key: 'address', label: 'Address' },
      { key: 'city', label: 'City' },
      { key: 'state', label: 'State' },
      { key: 'zip', label: 'ZIP' },
      { key: 'mls_number', label: 'MLS #' },
    ],
  },
  {
    label: 'Deal',
    fields: [
      { key: 'list_price', label: 'List Price' },
      { key: 'sale_price', label: 'Sale Price' },
      { key: 'financing', label: 'Financing' },
      { key: 'contract_date', label: 'Contract Date' },
      { key: 'closing_date', label: 'Closing Date' },
    ],
  },
  {
    label: 'Buyer',
    fields: [
      { key: 'buyer_name', label: 'Name' },
      { key: 'buyer_email', label: 'Email' },
      { key: 'buyer_phone', label: 'Phone' },
    ],
  },
  {
    label: 'Seller',
    fields: [
      { key: 'seller_name', label: 'Name' },
      { key: 'seller_email', label: 'Email' },
      { key: 'seller_phone', label: 'Phone' },
    ],
  },
  {
    label: 'Listing Agent',
    fields: [
      { key: 'listing_agent_name', label: 'Name' },
      { key: 'listing_agent_email', label: 'Email' },
    ],
  },
  {
    label: 'Selling Agent',
    fields: [
      { key: 'selling_agent_name', label: 'Name' },
      { key: 'selling_agent_email', label: 'Email' },
    ],
  },
  {
    label: 'Lender',
    fields: [
      { key: 'lender_name', label: 'Name' },
      { key: 'lender_email', label: 'Email' },
    ],
  },
  {
    label: 'Title',
    fields: [
      { key: 'title_company', label: 'Company' },
      { key: 'title_email', label: 'Email' },
    ],
  },
  {
    label: 'Transaction Coordinator',
    fields: [
      { key: 'tc_name', label: 'Name' },
      { key: 'tc_email', label: 'Email' },
    ],
  },
]

const STAGE_LABELS: Record<string, string> = {
  under_contract: 'Under Contract',
  pending: 'Pending',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const STAGE_COLORS: Record<string, string> = {
  under_contract: 'bg-blue-100 text-blue-700',
  pending: 'bg-yellow-100 text-yellow-700',
  closed: 'bg-green-100 text-green-700',
  cancelled: 'bg-gray-100 text-gray-600',
}

function StageBadge({ stage }: { stage?: string | null }) {
  const s = stage ?? 'under_contract'
  return (
    <span
      className={`inline-block rounded-full px-3 py-0.5 text-xs font-medium ${
        STAGE_COLORS[s] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {STAGE_LABELS[s] ?? s}
    </span>
  )
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

/** Flatten a Transaction row into a string map for controlled inputs */
function txToStrings(tx: Transaction): Record<string, string> {
  const result: Record<string, string> = {}
  const allKeys = FIELD_GROUPS.flatMap((g) => g.fields.map((f) => f.key))
  for (const key of allKeys) {
    const v = (tx as unknown as Record<string, unknown>)[key]
    result[key] = v != null ? String(v) : ''
  }
  result.stage = tx.stage ?? 'under_contract'
  return result
}

/** Build a Partial<Transaction> from form strings, dropping empty values */
function stringsToPayload(values: Record<string, string>): Partial<Transaction> {
  const PRICE_KEYS = new Set(['list_price', 'sale_price'])
  const payload: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(values)) {
    if (v === '' || v == null) {
      payload[k] = null // explicit null clears the field on PATCH
      continue
    }
    payload[k] = PRICE_KEYS.has(k) ? (parseFloat(v) || null) : v
  }
  return payload as Partial<Transaction>
}

// --------------------------------------------------------------------------- //
// Component
// --------------------------------------------------------------------------- //

export default function TransactionDetail() {
  const { transaction_id } = useParams<{ transaction_id: string }>()
  const navigate = useNavigate()

  const [tx, setTx] = useState<Transaction | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [editMode, setEditMode] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!transaction_id) return
    transactionsApi
      .get(transaction_id)
      .then((data) => {
        setTx(data)
        setValues(txToStrings(data))
      })
      .catch(() => setError('Transaction not found.'))
      .finally(() => setLoading(false))
  }, [transaction_id])

  async function handleSave() {
    if (!tx) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await transactionsApi.update(tx.id, stringsToPayload(values))
      setTx(updated)
      setValues(txToStrings(updated))
      setEditMode(false)
    } catch {
      setSaveError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    if (tx) setValues(txToStrings(tx))
    setEditMode(false)
    setSaveError(null)
  }

  // ---------- loading / error ----------
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-penny border-t-transparent" />
      </div>
    )
  }

  if (error || !tx) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50 text-center">
        <p className="text-sm text-gray-600">{error ?? 'Transaction not found.'}</p>
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-penny hover:underline"
        >
          Back to Dashboard
        </button>
      </div>
    )
  }

  const title = tx.address || 'Transaction'

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-gray-500 hover:text-gray-900"
        >
          ← Dashboard
        </button>
        <div className="flex items-center gap-3">
          <h1 className="max-w-xs truncate text-sm font-semibold text-gray-900">{title}</h1>
          {!editMode && <StageBadge stage={tx.stage} />}
        </div>
        <div>
          {editMode ? (
            <div className="flex items-center gap-3">
              <button
                onClick={handleCancel}
                className="text-sm font-medium text-gray-500 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="btn-primary flex items-center gap-2"
              >
                {saving && (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                )}
                Save
              </button>
            </div>
          ) : (
            <button
              onClick={() => setEditMode(true)}
              className="text-sm font-medium text-penny hover:underline"
            >
              Edit
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        {!editMode && (
          <PennyBubble>
            {tx.closing_date
              ? `Closing on ${tx.closing_date}. Let me know if you need anything.`
              : `Here are the details for this transaction. Hit Edit to update any field.`}
          </PennyBubble>
        )}

        {saveError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {saveError}
          </div>
        )}

        {/* Stage (edit mode only) */}
        {editMode && (
          <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">Stage</h3>
            <select
              value={values.stage ?? 'under_contract'}
              onChange={(e) => setValues((p) => ({ ...p, stage: e.target.value }))}
              className="input max-w-xs"
            >
              <option value="under_contract">Under Contract</option>
              <option value="pending">Pending</option>
              <option value="closed">Closed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        )}

        {/* Field groups */}
        {FIELD_GROUPS.map((group) => (
          <div
            key={group.label}
            className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm"
          >
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500">
              {group.label}
            </h3>
            {editMode ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {group.fields.map(({ key, label }) => (
                  <div key={key}>
                    <label className="mb-1 block text-xs font-medium text-gray-600">{label}</label>
                    <input
                      type="text"
                      value={values[key] ?? ''}
                      onChange={(e) => setValues((p) => ({ ...p, [key]: e.target.value }))}
                      className="input"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <dl className="grid gap-y-3 sm:grid-cols-2">
                {group.fields.map(({ key, label }) => {
                  const v = (tx as unknown as Record<string, unknown>)[key]
                  const display = v != null && v !== '' ? String(v) : '—'
                  return (
                    <div key={key} className="sm:contents">
                      <dt className="text-xs font-medium text-gray-500">{label}</dt>
                      <dd className="text-sm text-gray-900">{display}</dd>
                    </div>
                  )
                })}
              </dl>
            )}
          </div>
        ))}

        {/* Contract PDF */}
        {tx.contract_pdf_url && (
          <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Contract</h3>
            <p className="truncate text-xs text-gray-400">{tx.contract_pdf_url}</p>
          </div>
        )}

        <div className="pb-10" />
      </main>
    </div>
  )
}
