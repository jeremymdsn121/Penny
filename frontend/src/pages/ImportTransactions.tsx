import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, FileSpreadsheet, Upload } from 'lucide-react'
import { transactionsApi, type ImportPreview, type ImportPreviewRow } from '../lib/api'

type Phase = 'upload' | 'previewing' | 'preview' | 'importing' | 'done'

function cell(v: string | number | undefined): string {
  if (v === undefined || v === null || v === '') return '—'
  return String(v)
}

interface DoneSummary {
  created: number
  attempted: number
  // Rows that didn't make it in, each with a human reason.
  notImported: { label: string; reason: string }[]
}

export default function ImportTransactions() {
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [phase, setPhase] = useState<Phase>('upload')
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [includeDuplicates, setIncludeDuplicates] = useState(false)
  // Inline corrections keyed by row number (currently just the address — the
  // only hard error — so a row that came in blank can be fixed and imported
  // instead of silently dropped).
  const [edits, setEdits] = useState<Record<number, string>>({})
  const [summary, setSummary] = useState<DoneSummary | null>(null)
  const [exporting, setExporting] = useState<string | null>(null)

  async function handleFile(file: File | null) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Please select a CSV file.')
      return
    }
    setError(null)
    setEdits({})
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

  // Address after any inline edit (trimmed).
  function effectiveAddress(r: ImportPreviewRow): string {
    const raw = edits[r.row_number] ?? r.data.address ?? ''
    return String(raw).trim()
  }

  // A row imports when it has an address (after edits) — the only blocking
  // error normalize_row raises — and isn't an excluded duplicate.
  function willImport(r: ImportPreviewRow): boolean {
    return !!effectiveAddress(r) && (includeDuplicates || !r.duplicate)
  }

  function selectedRows(): ImportPreviewRow[] {
    return preview ? preview.rows.filter(willImport) : []
  }

  async function doImport() {
    if (!preview) return
    const chosen = selectedRows()
    if (chosen.length === 0) return
    const rows = chosen.map((r) => ({ ...r.data, address: effectiveAddress(r) }))

    // Snapshot what we're skipping (and why) before the round-trip, so the done
    // screen can say exactly what didn't come in.
    const notImported: { label: string; reason: string }[] = []
    for (const r of preview.rows) {
      if (willImport(r)) continue
      const label = effectiveAddress(r) || `Row ${r.row_number}`
      let reason: string
      if (!effectiveAddress(r)) reason = 'No property address'
      else if (r.duplicate) reason = 'Skipped as a possible duplicate'
      else reason = r.errors.join('; ') || 'Skipped'
      notImported.push({ label, reason })
    }

    setPhase('importing')
    setError(null)
    try {
      const res = await transactionsApi.importCommit(rows as Record<string, unknown>[])
      // Map any server-side failures back to addresses (failed.index is the
      // position in the array we submitted).
      for (const f of res.failed) {
        const r = chosen[f.index]
        notImported.push({
          label: r ? effectiveAddress(r) || `Row ${r.row_number}` : `Row ${f.index + 1}`,
          reason: f.reason,
        })
      }
      setSummary({ created: res.created, attempted: rows.length, notImported })
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

  async function runExport(
    kind: 'transactions' | 'activity' | 'documents',
    fn: () => Promise<void>,
  ) {
    setError(null)
    setExporting(kind)
    try {
      await fn()
    } catch {
      setError('Could not export. Please try again.')
    } finally {
      setExporting(null)
    }
  }

  function reset() {
    setPhase('upload')
    setPreview(null)
    setSummary(null)
    setEdits({})
    setIncludeDuplicates(false)
  }

  const selectedCount = selectedRows().length

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Import &amp; export</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Already have deals in another tool? Export them to CSV and bring them into Penny.
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
            className="inline-flex items-center gap-2 text-sm font-medium text-penny hover:underline"
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
              dragOver ? 'border-penny bg-penny-light/30' : 'border-hairline hover:border-penny/50'
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

          {/* Export — the round-trip out, for a compliance platform of record. */}
          <div className="rounded-2xl border border-hairline bg-surface p-5">
            <h2 className="text-sm font-semibold text-ink">Export your data</h2>
            <p className="mt-1 text-xs text-ink-muted">
              Run Penny as your working layer and keep SkySlope or Dotloop as your file of
              record. These CSVs round-trip back into Penny and feed most compliance platforms,
              so you never double-key.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => runExport('transactions', transactionsApi.exportTransactions)}
                disabled={exporting !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-hairline px-3 py-2 text-sm font-medium text-ink hover:border-penny/50 disabled:opacity-50"
              >
                <Download size={15} />
                {exporting === 'transactions' ? 'Exporting…' : 'Deals'}
              </button>
              <button
                onClick={() => runExport('activity', transactionsApi.exportActivity)}
                disabled={exporting !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-hairline px-3 py-2 text-sm font-medium text-ink hover:border-penny/50 disabled:opacity-50"
              >
                <Download size={15} />
                {exporting === 'activity' ? 'Exporting…' : 'Activity trail'}
              </button>
              <button
                onClick={() => runExport('documents', transactionsApi.exportDocuments)}
                disabled={exporting !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-hairline px-3 py-2 text-sm font-medium text-ink hover:border-penny/50 disabled:opacity-50"
              >
                <Download size={15} />
                {exporting === 'documents' ? 'Exporting…' : 'Document list'}
              </button>
            </div>
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
                  {selectedCount} will import
                </span>
                {preview.summary.duplicates > 0 && (
                  <span className="rounded-full bg-amber-500/10 px-3 py-1 text-amber-600 dark:text-amber-400">
                    {preview.summary.duplicates} possible duplicates
                  </span>
                )}
              </div>

              <p className="text-xs text-ink-subtle">
                Rows missing an address won&apos;t import. Fix the address inline below and
                they&apos;ll be included — no need to re-upload.
              </p>

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
                      const imports = willImport(r)
                      const hasAddress = !!effectiveAddress(r)
                      return (
                        <tr
                          key={r.row_number}
                          className={`border-t border-hairline ${imports ? '' : 'opacity-60'}`}
                        >
                          <td className="px-3 py-2 text-ink-subtle">{r.row_number}</td>
                          <td className="px-3 py-2">
                            {!hasAddress ? (
                              <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-xs text-red-500">Needs address</span>
                            ) : r.duplicate && !includeDuplicates ? (
                              <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400">Duplicate</span>
                            ) : (
                              <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600 dark:text-emerald-400">Ready</span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <input
                              value={String(edits[r.row_number] ?? r.data.address ?? '')}
                              onChange={(e) =>
                                setEdits((prev) => ({ ...prev, [r.row_number]: e.target.value }))
                              }
                              placeholder="Add an address…"
                              className={`w-44 rounded-md border bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-penny ${
                                hasAddress ? 'border-hairline' : 'border-red-400'
                              }`}
                            />
                          </td>
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
                  onClick={reset}
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
      {phase === 'done' && summary && (
        <div className="space-y-4 rounded-2xl border border-hairline bg-surface p-8">
          <p className="text-center text-lg font-semibold text-ink">
            Imported {summary.created} of {summary.attempted} deal{summary.attempted === 1 ? '' : 's'}.
          </p>

          {summary.notImported.length > 0 && (
            <div className="rounded-xl border border-hairline bg-surface-2 p-4">
              <p className="text-sm font-medium text-ink">
                {summary.notImported.length} couldn&apos;t be imported:
              </p>
              <ul className="mt-2 space-y-1 text-sm text-ink-muted">
                {summary.notImported.map((n, i) => (
                  <li key={i} className="flex justify-between gap-4">
                    <span className="text-ink">{n.label}</span>
                    <span className="text-right text-ink-subtle">{n.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex justify-center gap-3">
            <button onClick={() => navigate('/dashboard')} className="btn-primary">
              Go to dashboard
            </button>
            <button onClick={reset} className="text-sm text-ink-muted hover:text-ink">
              Import another file
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
