import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { listingsApi, type Listing } from '../lib/api'

const PROPERTY_TYPES = ['single_family', 'condo', 'townhouse', 'multi_family', 'land', 'other']
const STATUSES = ['draft', 'active', 'pending', 'sold', 'withdrawn']

const TEXT_FIELDS = [
  { key: 'address', label: 'Address' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'zip', label: 'ZIP' },
] as const

const NUMBER_FIELDS = [
  { key: 'list_price', label: 'List price ($)' },
  { key: 'bedrooms', label: 'Bedrooms' },
  { key: 'bathrooms', label: 'Bathrooms' },
  { key: 'square_footage', label: 'Square footage' },
  { key: 'lot_size_sqft', label: 'Lot size (sqft)' },
  { key: 'year_built', label: 'Year built' },
  { key: 'stories', label: 'Stories' },
  { key: 'garage_spaces', label: 'Garage spaces' },
  { key: 'hoa_fee', label: 'HOA fee ($)' },
  { key: 'annual_taxes', label: 'Annual taxes ($)' },
] as const

const MISC_TEXT_FIELDS = [
  { key: 'hoa_frequency', label: 'HOA frequency' },
  { key: 'parcel_number', label: 'Parcel / APN' },
  { key: 'mls_number', label: 'MLS #' },
  { key: 'school_district', label: 'School district' },
  { key: 'listing_agent_name', label: 'Listing agent' },
  { key: 'listing_agent_email', label: 'Listing agent email' },
  { key: 'seller_name', label: 'Seller' },
] as const

const INT_KEYS = new Set(['bedrooms', 'square_footage', 'year_built'])
const NUM_KEYS = new Set([
  'list_price', 'bathrooms', 'lot_size_sqft', 'stories', 'garage_spaces',
  'hoa_fee', 'annual_taxes',
])

function toStrings(l: Listing): Record<string, string> {
  const out: Record<string, string> = {}
  const keys = [
    ...TEXT_FIELDS.map((f) => f.key),
    ...NUMBER_FIELDS.map((f) => f.key),
    ...MISC_TEXT_FIELDS.map((f) => f.key),
    'property_type', 'public_remarks',
  ]
  for (const k of keys) {
    const v = (l as unknown as Record<string, unknown>)[k]
    out[k] = v != null ? String(v) : ''
  }
  out.status = l.status ?? 'draft'
  out.features = (l.features ?? []).join(', ')
  return out
}

export default function ListingDetail() {
  const { listing_id } = useParams<{ listing_id: string }>()
  const navigate = useNavigate()

  const [listing, setListing] = useState<Listing | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const [confirmPush, setConfirmPush] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [pushMsg, setPushMsg] = useState<string | null>(null)

  useEffect(() => {
    if (!listing_id) return
    listingsApi
      .get(listing_id)
      .then((l) => { setListing(l); setValues(toStrings(l)) })
      .catch(() => setError('Listing not found.'))
      .finally(() => setLoading(false))
  }, [listing_id])

  function set(key: string, v: string) {
    setValues((p) => ({ ...p, [key]: v }))
  }

  function buildPayload(): Partial<Listing> {
    const payload: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(values)) {
      if (k === 'features') {
        const items = v.split(',').map((s) => s.trim()).filter(Boolean)
        payload.features = items.length ? items : null
        continue
      }
      if (v === '') { payload[k] = null; continue }
      if (INT_KEYS.has(k)) payload[k] = parseInt(v, 10) || null
      else if (NUM_KEYS.has(k)) payload[k] = parseFloat(v) || null
      else payload[k] = v
    }
    return payload as Partial<Listing>
  }

  async function handleSave() {
    if (!listing) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const updated = await listingsApi.update(listing.id, buildPayload())
      setListing(updated)
      setValues(toStrings(updated))
      setNotice('Saved.')
    } catch {
      setError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!listing) return
    await listingsApi.remove(listing.id)
    navigate('/listings')
  }

  async function handlePush() {
    if (!listing) return
    setPushing(true)
    setPushMsg(null)
    try {
      const res = await listingsApi.push(listing.id, true)
      setPushMsg(res.reason)
      if (res.pushed) {
        const fresh = await listingsApi.get(listing.id)
        setListing(fresh)
        setValues(toStrings(fresh))
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPushMsg(detail ?? 'Could not push to the MLS.')
    } finally {
      setPushing(false)
      setConfirmPush(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-2">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-penny border-t-transparent" />
      </div>
    )
  }

  if (error && !listing) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-surface-2 text-center">
        <p className="text-sm text-ink-muted">{error}</p>
        <button onClick={() => navigate('/listings')} className="text-sm font-medium text-penny hover:underline">
          Back to Listings
        </button>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button onClick={() => navigate('/listings')} className="text-sm font-medium text-ink-muted hover:text-ink">
          ← Listings
        </button>
        <h1 className="max-w-xs truncate text-sm font-semibold text-ink">
          {listing?.address || 'Listing'}
        </h1>
        <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-2">
          {saving && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />}
          Save
        </button>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        <PennyBubble>
          Review the MLS fields I pulled from the packet. Edit anything, then it's ready to enter
          into your MLS.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        )}
        {notice && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">{notice}</div>
        )}

        {/* Status + type */}
        <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-muted">Status</label>
              <select value={values.status ?? 'draft'} onChange={(e) => set('status', e.target.value)} className="input">
                {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-muted">Property type</label>
              <select value={values.property_type ?? ''} onChange={(e) => set('property_type', e.target.value)} className="input">
                <option value="">—</option>
                {PROPERTY_TYPES.map((t) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}
              </select>
            </div>
          </div>
        </div>

        {/* Property + details */}
        <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">Property</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {TEXT_FIELDS.map(({ key, label }) => (
              <Field key={key} label={label} value={values[key] ?? ''} onChange={(v) => set(key, v)} />
            ))}
            {NUMBER_FIELDS.map(({ key, label }) => (
              <Field key={key} label={label} value={values[key] ?? ''} onChange={(v) => set(key, v)} />
            ))}
          </div>
        </div>

        {/* Misc */}
        <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">Details</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {MISC_TEXT_FIELDS.map(({ key, label }) => (
              <Field key={key} label={label} value={values[key] ?? ''} onChange={(v) => set(key, v)} />
            ))}
          </div>
          <div className="mt-4">
            <label className="mb-1 block text-xs font-medium text-ink-muted">Features (comma-separated)</label>
            <input type="text" value={values.features ?? ''} onChange={(e) => set('features', e.target.value)} className="input" />
          </div>
          <div className="mt-4">
            <label className="mb-1 block text-xs font-medium text-ink-muted">Public remarks</label>
            <textarea value={values.public_remarks ?? ''} onChange={(e) => set('public_remarks', e.target.value)} rows={5} className="input" />
          </div>
        </div>

        {/* Push to MLS */}
        <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">Publish to MLS</h3>
          <p className="mb-4 text-xs text-ink-subtle">
            Direct MLS publishing is a per-market add-on and isn't connected yet — for now this
            prepares the data to enter into your MLS.
          </p>
          {pushMsg && (
            <div className="mb-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-2 text-sm text-violet-800">
              {pushMsg}
            </div>
          )}
          {!confirmPush ? (
            <button
              onClick={() => setConfirmPush(true)}
              className="rounded-lg border border-hairline px-4 py-2 text-sm font-medium text-ink hover:border-hairline"
            >
              Push to MLS
            </button>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-ink">Attempt to publish this listing to the MLS?</span>
              <button onClick={handlePush} disabled={pushing} className="btn-primary flex items-center gap-2">
                {pushing && <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />}
                Confirm
              </button>
              <button onClick={() => setConfirmPush(false)} className="text-sm font-medium text-ink-muted hover:text-ink">
                Cancel
              </button>
            </div>
          )}
        </div>

        {/* Delete */}
        <div className="flex justify-end pb-10">
          <button onClick={handleDelete} className="text-sm font-medium text-ink-subtle hover:text-red-600">
            Delete listing
          </button>
        </div>
      </main>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-ink-muted">{label}</label>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} className="input" />
    </div>
  )
}
