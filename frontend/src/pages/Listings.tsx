import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { listingsApi, type Listing } from '../lib/api'

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  active: 'bg-green-100 text-green-700',
  pending: 'bg-yellow-100 text-yellow-700',
  sold: 'bg-blue-100 text-blue-700',
  withdrawn: 'bg-gray-100 text-gray-500',
}

function StatusBadge({ status }: { status?: string | null }) {
  const s = status ?? 'draft'
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
        STATUS_COLORS[s] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {s}
    </span>
  )
}

export default function Listings() {
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [listings, setListings] = useState<Listing[]>([])
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listingsApi
      .list()
      .then(setListings)
      .catch(() => {/* silently degrade */})
      .finally(() => setLoading(false))
  }, [])

  async function handleFile(file: File | null) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      setError('Please select a PDF file.')
      return
    }
    setError(null)
    setExtracting(true)
    try {
      const result = await listingsApi.extract(file)
      const draft = await listingsApi.create({
        ...(result.fields as Partial<Listing>),
        listing_packet_url: result.listing_packet_url,
        status: 'draft',
      })
      navigate(`/listings/${draft.id}`)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Could not read that packet. Please try again.')
      setExtracting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-gray-500 hover:text-gray-900"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-gray-900">Listings</h1>
        <div className="w-20" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Drop a listing packet and I'll pull the MLS fields for you to review. You can edit
          everything before it's ready to enter into the MLS.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Upload */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0] ?? null) }}
          className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed bg-white px-8 py-12 text-center transition-colors ${
            dragOver ? 'border-penny bg-penny-light' : 'border-gray-300'
          }`}
        >
          {extracting ? (
            <>
              <div className="mb-4 h-8 w-8 animate-spin rounded-full border-4 border-penny border-t-transparent" />
              <p className="text-sm font-medium text-gray-700">Reading the packet…</p>
              <p className="mt-1 text-xs text-gray-400">This usually takes 10–20 seconds.</p>
            </>
          ) : (
            <>
              <p className="mb-1 text-sm font-medium text-gray-700">Drag &amp; drop a listing packet</p>
              <p className="mb-4 text-xs text-gray-400">or</p>
              <button onClick={() => fileRef.current?.click()} className="btn-primary">
                Browse file
              </button>
              <p className="mt-3 text-xs text-gray-400">Max 25 MB · PDF only</p>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,application/pdf"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
              />
            </>
          )}
        </div>

        {/* Existing listings */}
        <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">Your listings</h2>
          </div>
          {loading ? (
            <div className="flex justify-center py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
            </div>
          ) : listings.length === 0 ? (
            <p className="px-6 py-10 text-center text-sm text-gray-400">
              No listings yet. Upload a packet to prepare one.
            </p>
          ) : (
            <ul className="divide-y divide-gray-50">
              {listings.map((l) => (
                <li key={l.id}>
                  <button
                    onClick={() => navigate(`/listings/${l.id}`)}
                    className="flex w-full items-start justify-between gap-4 px-6 py-4 text-left transition-colors hover:bg-gray-50"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-gray-900">
                        {l.address || 'Address not set'}
                        {l.city ? `, ${l.city}` : ''}
                      </p>
                      <p className="mt-0.5 text-xs text-gray-400">
                        {l.list_price != null ? `$${Math.round(l.list_price).toLocaleString()}` : 'No price'}
                        {l.bedrooms != null ? `  ·  ${l.bedrooms} bd` : ''}
                        {l.bathrooms != null ? ` / ${l.bathrooms} ba` : ''}
                      </p>
                    </div>
                    <StatusBadge status={l.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  )
}
