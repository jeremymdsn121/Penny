import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, FileSpreadsheet, Upload } from 'lucide-react'
import { transactionsApi, type ImportPreview } from '../lib/api'

type Phase = 'upload' | 'previewing' | 'preview' | 'importing' | 'done'

function cell(v: string | number | undefined): string {
  if (v === undefined || v === null || v === '') return '—'
  return String(v)
}

export default function ImportTransactions() {
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [phase, setPhase] = useState<Phase>('upload')
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [includeDuplicates, setIncludeDuplicates] = useState(false)
  const [result, setResult] = useState<{ created: number; failed: number } | null>(null)

  async function handleFile(file: File | null) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Please select a CSV file.')
      return
    }
    setError(null)
    setPhase('previewing')
    try {
      const p = await transactionsApi.importPreview(file)
      setPreview(p)
      setPhase('preview')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not read that file.')
      setPhase('upload')
    }
  }

  // Rows that will actually be imported, given the duplicate toggle.
  function selectedRows() {
    if (!preview) return []
    return preview.rows.filter((r) => r.importable && (includeDuplicates || !r.duplicate))
  }

  async function doImport() {
    const rows = selectedRows().map((r) => r.data)
    if (rows.length === 0) return
    setPhase('importing')
    setError(null)
    try {
      const res = await transactionsApi.importCommit(rows as Record<string, unknown>[])
      setResult({ created: res.created, failed: res.failed.length })
      setPhase('done')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed.')
      setPhase('preview')
    }
  }

  async function downloadTemplate() {
    try {
      await transactionsApi.downloadTemplate()
    } catch {
      setError('Could not download the template.')
    }
  }

  const selectedCount = selectedRows().length

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Import transactions</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Already have deals in another tool? Export them to CSV and bring them into Sloane.
          A lightly-edited Dotloop, SkySlope, or spreadsheet export usually maps automatically.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Upload */}
      {(phase === 'upload' || phase === 'previewing') && (
        <>
          <button
            onClick={downloadTemplate}
            className="inline-flex items-center gap-2 text-sm font-medium text-sloane hover:underline"
          >
            <Download size={16} />
            Download CSV template
          </button>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0] ?? null) }}
            onClick={() => fileRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-12 text-center transition-colors ${
              dragOver ? 'border-sloane bg-sloane-light/30' : 'border-hairline hover:border-sloane/50'
            }`}
          >
            <FileSpreadsheet size={32} className="mb-3 text-ink-subtle" />
            {phase === 'previewing' ? (
              <p className="text-sm text-ink-muted">Reading your file…</p>
            ) : (
              <>
                <p className="text-sm font-medium text-ink">Drop a CSV here, or click to browse</p>
                <p className="mt-1 text-xs text-ink-subtle">Up to 500 rows · 5 MB</p>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </>
      )}

      {/* Preview */}
      {(phase === 'preview' || phase === 'importing') && preview && (
        <>
          {preview.error ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {preview.error}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-3 text-sm">
                <span className="rounded-full bg-surface-3 px-3 py-1 text-ink-muted">
                  {preview.summary.total} rows
                </span>
                <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-emerald-600 dark:text-emerald-400">
                  {preview.summary.ready} ready
                </span>
                {preview.summary.errors > 0 && (
                  <span className="rounded-full bg-red-500/10 px-3 py-1 text-red-500">
                    {preview.summary.errors} with errors
                  </span>
                )}
                {preview.summary.duplicates > 0 && (
                  <span className="rounded-full bg-amber-500/10 px-3 py-1 text-amber-600 dark:text-amber-400">
                    {preview.summary.duplicates} possible duplicates
                  </span>
                )}
              </div>

              {preview.unmapped_columns.length > 0 && (
                <p className="text-xs text-ink-subtle">
                  Ignored unrecognized columns: {preview.unmapped_columns.join(', ')}
                </p>
              )}

              <div className="overflow-x-auto rounded-xl border border-hairline">
                <table className="w-full text-left text-sm">
                  <thead className="bg-surface-2 text-xs uppercase tracking-wide text-ink-subtle">
                    <tr>
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Address</th>
                      <th className="px-3 py-2">Buyer</th>
                      <th className="px-3 py-2">Price</th>
                      <th className="px-3 py-2">Closing</th>
                      <th className="px-3 py-2">Stage</th>
                      <th className="px-3 py-2">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r) => {
                      const willImport = r.importable && (includeDuplicates || !r.duplicate)
                      return (
                        <tr
                          key={r.row_number}
                          className={`border-t border-hairline ${willImport ? '' : 'opacity-50'}`}
                        >
                          <td className="px-3 py-2 text-ink-subtle">{r.row_number}</td>
                          <td className="px-3 py-2">
                            {!r.importable ? (
                              <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs text-red-500">Error</span>
                            ) : r.duplicate ? (
                              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400">Duplicate</span>
                            ) : (
                              <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400">Ready</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-ink">{cell(r.data.address)}</td>
                          <td className="px-3 py-2 text-ink-muted">{cell(r.data.buyer_name)}</td>
                          <td className="px-3 py-2 text-ink-muted">{cell(r.data.sale_price ?? r.data.list_price)}</td>
                          <td className="px-3 py-2 text-ink-muted">{cell(r.data.closing_date)}</td>
                          <td className="px-3 py-2 text-ink-muted">{cell(r.data.stage)}</td>
                          <td className="px-3 py-2 text-xs text-ink-subtle">
                            {[...r.errors, ...r.warnings].join(' · ') || '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {preview.summary.duplicates > 0 && (
                <label className="flex items-center gap-2 text-sm text-ink-muted">
                  <input
                    type="checkbox"
                    checked={includeDuplicates}
                    onChange={(e) => setIncludeDuplicates(e.target.checked)}
                  />
                  Import the {preview.summary.duplicates} possible duplicate(s) anyway
                </label>
              )}

              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={() => { setPhase('upload'); setPreview(null); setResult(null) }}
                  className="text-sm text-ink-muted hover:text-ink"
                >
                  Choose a different file
                </button>
                <button
                  onClick={doImport}
                  disabled={selectedCount === 0 || phase === 'importing'}
                  className="btn-primary inline-flex items-center gap-2"
                >
                  <Upload size={16} />
                  {phase === 'importing' ? 'Importing…' : `Import ${selectedCount} deal${selectedCount === 1 ? '' : 's'}`}
                </button>
              </div>
            </>
          )}
        </>
      )}

      {/* Done */}
      {phase === 'done' && result && (
        <div className="space-y-4 rounded-2xl border border-hairline bg-surface p-8 text-center">
          <p className="text-lg font-semibold text-ink">
            Imported {result.created} deal{result.created === 1 ? '' : 's'}.
          </p>
          {result.failed > 0 && (
            <p className="text-sm text-red-500">{result.failed} row(s) failed to import.</p>
          )}
          <div className="flex justify-center gap-3">
            <button onClick={() => navigate('/dashboard')} className="btn-primary">
              Go to dashboard
            </button>
            <button
              onClick={() => { setPhase('upload'); setPreview(null); setResult(null); setIncludeDuplicates(false) }}
              className="text-sm text-ink-muted hover:text-ink"
            >
              Import another file
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
