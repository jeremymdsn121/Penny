import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { complianceSettingsApi, type ComplianceSettings } from '../lib/api'

export default function ComplianceSettingsPage() {
  const navigate = useNavigate()
  const [settings, setSettings] = useState<ComplianceSettings>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    complianceSettingsApi
      .get()
      .then(setSettings)
      .catch(() => setError('Could not load settings.'))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const updated = await complianceSettingsApi.update({
        ai_disclosure_enabled: settings.ai_disclosure_enabled ?? true,
        ai_disclosure_text: settings.ai_disclosure_text ?? '',
        request_ai_consent: settings.request_ai_consent ?? false,
        document_retention_years: settings.document_retention_years ?? 7,
        document_retention_enabled: settings.document_retention_enabled ?? false,
      })
      setSettings(updated)
      setNotice('Saved.')
    } catch {
      setError('Could not save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-ink">Compliance Settings</h1>
        <div className="w-28" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Several states require disclosing when AI assists real estate communications. I add
          a disclosure footer to outbound email by default. You can edit the wording or also
          ask parties to explicitly acknowledge it.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {notice && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            {notice}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
          </div>
        ) : (
          <section className="space-y-5 rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={settings.ai_disclosure_enabled ?? true}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, ai_disclosure_enabled: e.target.checked }))
                }
                className="mt-0.5"
              />
              <span className="text-sm text-ink">
                Include AI disclosure in all outbound emails
                <span className="block text-xs text-ink-subtle">On by default.</span>
              </span>
            </label>

            <div>
              <label className="mb-1 block text-xs font-medium text-ink-muted">
                Disclosure text
              </label>
              <textarea
                value={settings.ai_disclosure_text ?? ''}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, ai_disclosure_text: e.target.value }))
                }
                rows={4}
                className="input text-sm"
              />
              <p className="mt-1 text-xs text-yellow-700">
                Have your attorney review this text. Penny cannot provide legal advice on
                disclosure requirements.
              </p>
            </div>

            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={settings.request_ai_consent ?? false}
                onChange={(e) =>
                  setSettings((s) => ({ ...s, request_ai_consent: e.target.checked }))
                }
                className="mt-0.5"
              />
              <span className="text-sm text-ink">
                Request explicit consent from transaction parties
                <span className="block text-xs text-ink-subtle">
                  Adds a one-time acknowledgment link to intro emails. Off by default.
                </span>
              </span>
            </label>

            <div className="border-t border-hairline pt-5">
              <h2 className="text-sm font-semibold text-ink">Document retention</h2>
              <p className="mt-1 text-xs text-ink-subtle">
                State your record-keeping policy for transaction documents. Real estate
                commonly requires keeping files for several years (7 is typical). This is
                shown to brokers asking about data handling.
              </p>

              <label className="mt-4 block">
                <span className="mb-1 block text-xs font-medium text-ink-muted">
                  Retention period (years)
                </span>
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={settings.document_retention_years ?? 7}
                  onChange={(e) =>
                    setSettings((s) => ({
                      ...s,
                      document_retention_years: Number(e.target.value),
                    }))
                  }
                  className="w-28 rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink"
                />
              </label>

              <label className="mt-4 flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={settings.document_retention_enabled ?? false}
                  onChange={(e) =>
                    setSettings((s) => ({ ...s, document_retention_enabled: e.target.checked }))
                  }
                  className="mt-0.5"
                />
                <span className="text-sm text-ink">
                  Enforce this policy
                  <span className="block text-xs text-ink-subtle">
                    Records your intent to purge documents past the window. Automated
                    deletion is not enabled yet — it ships as a separately-reviewed step, so
                    nothing is deleted today. Off by default.
                  </span>
                </span>
              </label>
            </div>

            <button onClick={save} disabled={saving} className="btn-primary">
              {saving ? 'Saving…' : 'Save settings'}
            </button>
          </section>
        )}
      </main>
    </div>
  )
}
