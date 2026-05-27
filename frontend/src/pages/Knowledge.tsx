import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import {
  knowledgeApi,
  type KnowledgeDocument,
  type KnowledgeRule,
} from '../lib/api'

const STATUS_STYLES: Record<string, string> = {
  processing: 'bg-yellow-100 text-yellow-700',
  processed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-600'
      }`}
    >
      {status}
    </span>
  )
}

function cap(s?: string | null): string {
  if (!s) return 'General'
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function Knowledge() {
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement>(null)

  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [rules, setRules] = useState<KnowledgeRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([knowledgeApi.listDocuments(), knowledgeApi.listRules()])
      .then(([docs, rls]) => {
        setDocuments(docs)
        setRules(rls)
      })
      .catch(() => setError('Could not load your knowledge base.'))
      .finally(() => setLoading(false))
  }, [])

  async function refresh() {
    const [docs, rls] = await Promise.all([
      knowledgeApi.listDocuments(),
      knowledgeApi.listRules(),
    ])
    setDocuments(docs)
    setRules(rls)
  }

  async function handleUpload() {
    if (!selectedFile) return
    setUploading(true)
    setUploadError(null)
    setNotice(null)
    try {
      const result = await knowledgeApi.uploadDocument(selectedFile)
      await refresh()
      setSelectedFile(null)
      if (fileInput.current) fileInput.current.value = ''
      if (result.extraction_error) {
        setNotice(result.extraction_error)
      } else {
        setNotice(
          `Analyzed “${result.document.filename}” — ${result.rules.length} style rule${
            result.rules.length !== 1 ? 's' : ''
          } proposed for your review below.`,
        )
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail
      setUploadError(detail ?? 'Upload failed. Use a PDF, image, or .docx under 25 MB.')
    } finally {
      setUploading(false)
    }
  }

  async function confirmRule(id: string) {
    try {
      await knowledgeApi.updateRule(id, { confirmed: true })
      setRules((prev) => prev.map((r) => (r.id === id ? { ...r, confirmed: true } : r)))
    } catch {
      setError('Could not confirm that rule.')
    }
  }

  async function removeRule(id: string) {
    try {
      await knowledgeApi.deleteRule(id)
      setRules((prev) => prev.filter((r) => r.id !== id))
    } catch {
      setError('Could not remove that rule.')
    }
  }

  async function removeDocument(id: string) {
    try {
      await knowledgeApi.deleteDocument(id)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
    } catch {
      setError('Could not remove that document.')
    }
  }

  const pending = rules.filter((r) => !r.confirmed)
  const confirmed = rules.filter((r) => r.confirmed)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-gray-500 hover:text-gray-900"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-gray-900">Brand &amp; Style</h1>
        <div className="w-28" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Upload your letterheads, sample letters, or email templates and I'll learn your
          brand's voice and formatting. I'll suggest style rules from each one — you confirm
          which to keep, and I'll follow them whenever I draft documents for you.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ── Upload ── */}
        <section className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Upload a style document
          </h2>
          {uploadError && <p className="mb-3 text-xs text-red-600">{uploadError}</p>}
          {notice && (
            <div className="mb-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
              {notice}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,image/*,.pdf,.docx"
              onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
              className="block text-sm text-gray-600 file:mr-3 file:rounded-lg file:border-0 file:bg-gray-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-gray-700 hover:file:bg-gray-200"
            />
            <button
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              className="btn-primary flex items-center gap-2 disabled:opacity-50"
            >
              {uploading && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {uploading ? 'Analyzing…' : 'Upload & analyze'}
            </button>
          </div>
          <p className="mt-2 text-xs text-gray-400">PDF, image, or Word (.docx) — up to 25 MB.</p>
        </section>

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
          </div>
        ) : (
          <>
            {/* ── Pending review ── */}
            <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
              <div className="border-b border-gray-100 px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Proposed rules — needs review
                </h2>
                <p className="mt-1 text-xs text-gray-400">
                  Confirm the rules that match your brand. Only confirmed rules guide Penny.
                </p>
              </div>
              {pending.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">
                  Nothing to review. Upload a document to get suggestions.
                </p>
              ) : (
                <ul className="divide-y divide-gray-50">
                  {pending.map((r) => (
                    <li key={r.id} className="flex items-start justify-between gap-4 px-6 py-4">
                      <div className="min-w-0 flex-1">
                        <span className="inline-block rounded bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">
                          {cap(r.category)}
                        </span>
                        <p className="mt-1.5 text-sm text-gray-800">{r.rule}</p>
                        {r.source_document && (
                          <p className="mt-1 text-xs text-gray-400">from {r.source_document}</p>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-3">
                        <button
                          onClick={() => confirmRule(r.id)}
                          className="text-xs font-semibold text-penny hover:underline"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => removeRule(r.id)}
                          className="text-xs font-medium text-red-500 hover:text-red-700"
                        >
                          Reject
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* ── Confirmed rules ── */}
            <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
              <div className="border-b border-gray-100 px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Confirmed style rules
                </h2>
                <p className="mt-1 text-xs text-gray-400">
                  These are injected into Penny's prompts so she stays on brand.
                </p>
              </div>
              {confirmed.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">
                  No confirmed rules yet.
                </p>
              ) : (
                <ul className="divide-y divide-gray-50">
                  {confirmed.map((r) => (
                    <li key={r.id} className="flex items-start justify-between gap-4 px-6 py-4">
                      <div className="min-w-0 flex-1">
                        <span className="inline-block rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                          {cap(r.category)}
                        </span>
                        <p className="mt-1.5 text-sm text-gray-800">{r.rule}</p>
                      </div>
                      <button
                        onClick={() => removeRule(r.id)}
                        className="shrink-0 text-xs font-medium text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* ── Uploaded documents ── */}
            <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
              <div className="border-b border-gray-100 px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Uploaded documents
                </h2>
              </div>
              {documents.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">
                  No documents uploaded yet.
                </p>
              ) : (
                <ul className="divide-y divide-gray-50">
                  {documents.map((d) => (
                    <li key={d.id} className="flex items-center justify-between gap-4 px-6 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">{d.filename}</p>
                        {d.error && <p className="mt-0.5 truncate text-xs text-red-500">{d.error}</p>}
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <StatusBadge status={d.status} />
                        <button
                          onClick={() => removeDocument(d.id)}
                          className="text-xs font-medium text-red-500 hover:text-red-700"
                        >
                          Delete
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  )
}
