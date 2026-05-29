import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { transactionsApi, type ExtractResult } from '../lib/api'

// --------------------------------------------------------------------------- //
// Field definitions — mirrors CONTRACT_FIELDS in ai_extract.py
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
      { key: 'sale_price', label: 'Sale Price ($)' },
      { key: 'financing', label: 'Financing' },
      { key: 'contract_date', label: 'Contract Date (YYYY-MM-DD)' },
      { key: 'closing_date', label: 'Closing Date (YYYY-MM-DD)' },
    ],
  },
  {
    label: 'Buyer',
    fields: [
      { key: 'buyer_name', label: 'Name' },
    ],
  },
  {
    label: 'Seller',
    fields: [
      { key: 'seller_name', label: 'Name' },
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
    ],
  },
  {
    label: 'Title',
    fields: [
      { key: 'title_company', label: 'Company' },
    ],
  },
]

// Keys the AI extracts — used to decide ring color
const EXTRACTED_KEYS = new Set([
  'address', 'city', 'state', 'zip',
  'buyer_name',
  'seller_name',
  'sale_price', 'financing',
  'contract_date', 'closing_date',
  'listing_agent_name', 'listing_agent_email',
  'selling_agent_name', 'selling_agent_email',
  'lender_name',
  'title_company',
  'mls_number',
])

const BASE = 'w-full rounded-lg border px-3 py-2 text-sm text-ink shadow-sm outline-none'
const FOUND_CLS = `${BASE} border-green-400 focus:border-green-500 focus:ring-1 focus:ring-green-500`
const MISSING_CLS = `${BASE} border-red-400 focus:border-red-500 focus:ring-1 focus:ring-red-500`
const NEUTRAL_CLS = `${BASE} border-hairline focus:border-penny focus:ring-1 focus:ring-penny`

function fieldClass(key: string, notFound: string[]): string {
  if (!EXTRACTED_KEYS.has(key)) return NEUTRAL_CLS
  return notFound.includes(key) ? MISSING_CLS : FOUND_CLS
}

type Phase = 'upload' | 'extracting' | 'review' | 'creating'

// --------------------------------------------------------------------------- //
// Component
// --------------------------------------------------------------------------- //

export default function NewTransaction() {
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [phase, setPhase] = useState<Phase>('upload')
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Extraction result
  const [extractResult, setExtractResult] = useState<ExtractResult | null>(null)

  // Editable form values — always strings; converted on submit
  const [values, setValues] = useState<Record<string, string>>({})
  const [stage, setStage] = useState('under_contract')

  // ---------- upload helpers ----------

  async function handleFile(file: File | null) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      setError('Please select a PDF file.')
      return
    }
    setError(null)
    setPhase('extracting')
    try {
      const result = await transactionsApi.extract(file)
      // Convert all values to strings for the controlled inputs
      const initial: Record<string, string> = {}
      for (const [k, v] of Object.entries(result.fields)) {
        initial[k] = v != null ? String(v) : ''
      }
      setValues(initial)
      setExtractResult(result)
      setPhase('review')
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Extraction failed. Please try again.'
      setError(msg)
      setPhase('upload')
    }
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    handleFile(e.target.files?.[0] ?? null)
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files[0] ?? null)
  }

  // ---------- submit ----------

  async function handleCreate() {
    if (!extractResult) return
    setPhase('creating')
    setError(null)

    const PRICE_KEYS = new Set(['list_price', 'sale_price'])

    // Build payload: skip empty strings, cast prices to numbers
    const payload: Record<string, unknown> = { stage, contract_pdf_url: extractResult.contract_pdf_url }
    for (const [k, v] of Object.entries(values)) {
      if (v === '' || v == null) continue
      payload[k] = PRICE_KEYS.has(k) ? parseFloat(v) || undefined : v
    }
    // Drop keys where price cast failed
    for (const k of PRICE_KEYS) {
      if (payload[k] === undefined) delete payload[k]
    }

    try {
      const tx = await transactionsApi.create(payload)
      navigate(`/transactions/${tx.id}`)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Could not create transaction. Please try again.'
      setError(msg)
      setPhase('review')
    }
  }

  // ---------- counts ----------
  const foundCount = extractResult
    ? Object.values(extractResult.fields).filter((v) => v != null && v !== '').length
    : 0
  const missingCount = extractResult ? extractResult.not_found.length : 0

  // ---------- render ----------
  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-ink">New Transaction</h1>
        <div className="w-20" />
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        {/* Penny message */}
        <PennyBubble>
          {phase === 'upload' || phase === 'extracting'
            ? "Drop a PDF contract below. I'll pull out all the key details for you to review."
            : `I found ${foundCount} field${foundCount !== 1 ? 's' : ''}${
                missingCount > 0
                  ? `. ${missingCount} field${missingCount !== 1 ? 's are' : ' is'} highlighted in red — fill those in before saving.`
                  : '. Everything looks complete — review and confirm below.'
              }`}
        </PennyBubble>

        {/* Error banner */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ── Upload phase ── */}
        {(phase === 'upload' || phase === 'extracting') && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed bg-surface px-8 py-16 text-center transition-colors ${
              dragOver ? 'border-penny bg-penny-light' : 'border-hairline'
            }`}
          >
            {phase === 'extracting' ? (
              <>
                <div className="mb-4 h-8 w-8 animate-spin rounded-full border-4 border-penny border-t-transparent" />
                <p className="text-sm font-medium text-ink">Extracting fields…</p>
                <p className="mt-1 text-xs text-ink-subtle">This usually takes 10–20 seconds.</p>
              </>
            ) : (
              <>
                <svg className="mb-4 h-12 w-12 text-ink-subtle" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="mb-1 text-sm font-medium text-ink">
                  Drag &amp; drop a PDF here
                </p>
                <p className="mb-4 text-xs text-ink-subtle">or</p>
                <button
                  onClick={() => fileRef.current?.click()}
                  className="btn-primary"
                >
                  Browse file
                </button>
                <p className="mt-3 text-xs text-ink-subtle">Max 25 MB · PDF only</p>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={onFileInput}
                />
              </>
            )}
          </div>
        )}

        {/* ── Review phase ── */}
        {(phase === 'review' || phase === 'creating') && extractResult && (
          <>
            {/* Summary bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline bg-surface px-5 py-3 shadow-sm">
              <div className="flex items-center gap-4 text-sm">
                <span className="flex items-center gap-1.5 font-medium text-green-600">
                  <span className="inline-block h-2 w-2 rounded-full bg-green-400" />
                  {foundCount} found
                </span>
                {missingCount > 0 && (
                  <span className="flex items-center gap-1.5 font-medium text-red-600">
                    <span className="inline-block h-2 w-2 rounded-full bg-red-400" />
                    {missingCount} need input
                  </span>
                )}
                <span className="text-ink-subtle">·</span>
                <span className="text-ink-muted">{extractResult.page_count} pages</span>
              </div>
              {extractResult.signed_url && (
                <a
                  href={extractResult.signed_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-penny hover:underline"
                >
                  View PDF ↗
                </a>
              )}
            </div>

            {/* Stage selector */}
            <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Stage
              </h3>
              <select
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                className="input max-w-xs"
              >
                <option value="under_contract">Under Contract</option>
                <option value="pending">Pending</option>
                <option value="closed">Closed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>

            {/* Field groups */}
            {FIELD_GROUPS.map((group) => (
              <div
                key={group.label}
                className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm"
              >
                <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">
                  {group.label}
                </h3>
                <div className="grid gap-4 sm:grid-cols-2">
                  {group.fields.map(({ key, label }) => (
                    <div key={key}>
                      <label className="mb-1 block text-xs font-medium text-ink-muted">
                        {label}
                      </label>
                      <input
                        type="text"
                        value={values[key] ?? ''}
                        onChange={(e) =>
                          setValues((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                        placeholder={
                          extractResult.not_found.includes(key) ? 'Not found — enter manually' : ''
                        }
                        className={fieldClass(key, extractResult.not_found)}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {/* Actions */}
            <div className="flex items-center justify-between pb-10">
              <button
                onClick={() => { setPhase('upload'); setExtractResult(null); setValues({}) }}
                className="text-sm font-medium text-ink-muted hover:text-ink"
              >
                ← Upload a different PDF
              </button>
              <button
                onClick={handleCreate}
                disabled={phase === 'creating'}
                className="btn-primary flex items-center gap-2"
              >
                {phase === 'creating' && (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                )}
                Create transaction
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
