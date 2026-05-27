import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { whatsappApi, type WhatsAppContact, type WhatsAppConfig } from '../lib/api'

// WhatsApp green used only on this page for brand context
const WA_GREEN = '#25D366'

export default function WhatsAppSettings() {
  const navigate = useNavigate()

  const [config, setConfig] = useState<WhatsAppConfig | null>(null)
  const [contacts, setContacts] = useState<WhatsAppContact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Add-contact form
  const [phone, setPhone] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([whatsappApi.config(), whatsappApi.listContacts()])
      .then(([cfg, ctcts]) => {
        setConfig(cfg)
        setContacts(ctcts)
      })
      .catch(() => setError('Could not load WhatsApp settings.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!phone.trim()) return
    setAdding(true)
    setAddError(null)
    try {
      const contact = await whatsappApi.addContact(
        phone.trim(),
        displayName.trim() || undefined,
      )
      setContacts((prev) => [...prev, contact])
      setPhone('')
      setDisplayName('')
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddError(detail ?? 'Could not add contact. Make sure the number is in +1XXXXXXXXXX format.')
    } finally {
      setAdding(false)
    }
  }

  async function handleRemove(phoneNumber: string) {
    try {
      await whatsappApi.removeContact(phoneNumber)
      setContacts((prev) => prev.filter((c) => c.phone_number !== phoneNumber))
    } catch {
      setError('Could not remove contact.')
    }
  }

  const pennyNumber = config?.penny_whatsapp_number

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-gray-500 hover:text-gray-900"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-gray-900">WhatsApp Settings</h1>
        <div className="w-28" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Register your agents' WhatsApp numbers so they can text or voice-message me
          from the field — I'll handle the rest.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
          </div>
        ) : (
          <>
            {/* ── Penny's number ── */}
            <section className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
              <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-gray-500">
                Penny's WhatsApp Number
              </h2>
              {pennyNumber ? (
                <>
                  <p className="mt-3 font-mono text-2xl font-semibold text-gray-900">
                    {pennyNumber}
                  </p>
                  <p className="mt-2 text-sm text-gray-500">
                    Save this number as <strong>Penny</strong> in your phone's contacts,
                    then text or send a voice message to get started.
                  </p>

                  {/* Sandbox join instructions */}
                  <div className="mt-4 rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
                    <strong>Using the Twilio sandbox?</strong> Before your first message,
                    each agent must send{' '}
                    <code className="rounded bg-yellow-100 px-1 font-mono">join &lt;your-sandbox-word&gt;</code>{' '}
                    to this number to opt in. You'll find your sandbox word in the{' '}
                    <a
                      href="https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn"
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      Twilio console
                    </a>.
                  </div>
                </>
              ) : (
                <p className="mt-3 text-sm text-gray-500">
                  Not configured yet. Set{' '}
                  <code className="rounded bg-gray-100 px-1 font-mono text-xs">
                    TWILIO_WHATSAPP_FROM
                  </code>{' '}
                  on the backend to enable WhatsApp messaging.
                </p>
              )}
            </section>

            {/* ── What agents can do ── */}
            <section className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
                What Agents Can Do via WhatsApp
              </h2>
              <ul className="space-y-2 text-sm text-gray-700">
                {[
                  'Ask for a summary of all active transactions',
                  'Look up the status or details of a specific deal',
                  'Update a transaction\'s stage (e.g. "Move Oak Street to Pending")',
                  'Add notes to a transaction',
                  'Send a voice memo — Penny transcribes it automatically',
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <span style={{ color: WA_GREEN }} className="mt-0.5 text-base leading-none">✓</span>
                    {item}
                  </li>
                ))}
              </ul>
            </section>

            {/* ── Registered contacts ── */}
            <section className="rounded-2xl border border-gray-100 bg-white shadow-sm">
              <div className="border-b border-gray-100 px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Registered Agents
                </h2>
                <p className="mt-1 text-xs text-gray-400">
                  Only numbers listed here can message Penny. Unrecognised numbers are
                  politely rejected.
                </p>
              </div>

              {contacts.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-gray-400">
                  No agents registered yet — add one below.
                </p>
              ) : (
                <ul className="divide-y divide-gray-50">
                  {contacts.map((c) => (
                    <li
                      key={c.id}
                      className="flex items-center justify-between gap-4 px-6 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {c.display_name || c.phone_number}
                        </p>
                        {c.display_name && (
                          <p className="text-xs text-gray-400">{c.phone_number}</p>
                        )}
                      </div>
                      <button
                        onClick={() => handleRemove(c.phone_number)}
                        className="text-xs font-medium text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {/* Add contact form */}
              <form
                onSubmit={handleAdd}
                className="border-t border-gray-100 px-6 py-4"
              >
                <h3 className="mb-3 text-sm font-semibold text-gray-700">
                  Add an agent
                </h3>
                {addError && (
                  <p className="mb-3 text-xs text-red-600">{addError}</p>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      WhatsApp number <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="tel"
                      required
                      placeholder="+15551234567"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      Display name (optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Sarah — Listing Agent"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={adding}
                  className="btn-primary mt-3 flex items-center gap-2"
                >
                  {adding && (
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  )}
                  Add agent
                </button>
              </form>
            </section>
          </>
        )}
      </main>
    </div>
  )
}
