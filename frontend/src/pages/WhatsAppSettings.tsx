import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import {
  smsApi,
  whatsappApi,
  type MessagingSettings,
  type SmsConfig,
  type WhatsAppContact,
  type WhatsAppConfig,
} from '../lib/api'

// WhatsApp green used only on this page for brand context
const WA_GREEN = '#25D366'

// Grouped capability summary (not the full ~20-tool list) — keep it skimmable.
const CAPABILITIES: { title: string; detail: string }[] = [
  { title: 'Manage deals', detail: 'pipeline summary, look up any deal, update its stage, add notes' },
  { title: 'Set up a deal from a contract', detail: 'text a PDF or photo; Penny extracts the details and creates it' },
  { title: 'Deadlines & next steps', detail: 'add deadlines (with automatic reminders) and see what’s due' },
  { title: 'Check the file', detail: 'what’s missing for compliance, run a review, track earnest money' },
  { title: 'Comps & scheduling', detail: 'a value estimate and comps for any address; propose and book showings' },
  { title: 'Write for you', detail: 'draft a letter or email in your voice, or send the intro email to all parties' },
]

type Channel = 'whatsapp' | 'sms' | 'both'

export default function WhatsAppSettings() {
  const navigate = useNavigate()

  const [config, setConfig] = useState<WhatsAppConfig | null>(null)
  const [smsConfig, setSmsConfig] = useState<SmsConfig | null>(null)
  const [contacts, setContacts] = useState<WhatsAppContact[]>([])
  const [smsContacts, setSmsContacts] = useState<WhatsAppContact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Reply-handling settings
  const [forwardReplies, setForwardReplies] = useState(false)
  const [forwardSaving, setForwardSaving] = useState(false)

  // Add-contact form
  const [phone, setPhone] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [channel, setChannel] = useState<Channel>('whatsapp')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      whatsappApi.config(),
      whatsappApi.listContacts(),
      smsApi.config(),
      smsApi.listContacts(),
      whatsappApi.getSettings(),
    ])
      .then(([cfg, ctcts, scfg, sctcts, settings]) => {
        setConfig(cfg)
        setContacts(ctcts)
        setSmsConfig(scfg)
        setSmsContacts(sctcts)
        setForwardReplies(!!settings.forward_replies_to_agent)
      })
      .catch(() => setError('Could not load messaging settings.'))
      .finally(() => setLoading(false))
  }, [])

  async function toggleForwardReplies(next: boolean) {
    setForwardReplies(next) // optimistic
    setForwardSaving(true)
    try {
      const saved: MessagingSettings = await whatsappApi.updateSettings({
        forward_replies_to_agent: next,
      })
      setForwardReplies(!!saved.forward_replies_to_agent)
    } catch {
      setForwardReplies(!next) // revert on failure
      setError('Could not save the reply-forwarding setting.')
    } finally {
      setForwardSaving(false)
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!phone.trim()) return
    setAdding(true)
    setAddError(null)
    try {
      const name = displayName.trim() || undefined
      if (channel === 'whatsapp' || channel === 'both') {
        const c = await whatsappApi.addContact(phone.trim(), name)
        setContacts((prev) => [...prev.filter((p) => p.phone_number !== c.phone_number), c])
      }
      if (channel === 'sms' || channel === 'both') {
        const c = await smsApi.addContact(phone.trim(), name)
        setSmsContacts((prev) => [...prev.filter((p) => p.phone_number !== c.phone_number), c])
      }
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

  async function handleRemoveSms(phoneNumber: string) {
    try {
      await smsApi.removeContact(phoneNumber)
      setSmsContacts((prev) => prev.filter((c) => c.phone_number !== phoneNumber))
    } catch {
      setError('Could not remove contact.')
    }
  }

  const pennyNumber = config?.penny_whatsapp_number

  return (
    <div className="min-h-screen bg-surface-2">
      <header className="flex items-center justify-between border-b border-hairline bg-surface px-6 py-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-ink-muted hover:text-ink"
        >
          ← Dashboard
        </button>
        <h1 className="text-sm font-semibold text-ink">Messaging</h1>
        <div className="w-28" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Register your agents so they can reach me from the field. WhatsApp adds voice
          memos and contract photos; plain SMS works for anyone without WhatsApp. Pick the
          channel each agent prefers, or both.
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
            <section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
              <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Penny's WhatsApp Number
              </h2>
              {pennyNumber ? (
                <>
                  <p className="mt-3 font-mono text-2xl font-semibold text-ink">
                    {pennyNumber}
                  </p>
                  <p className="mt-2 text-sm text-ink-muted">
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
                <p className="mt-3 text-sm text-ink-muted">
                  Not configured yet. Set{' '}
                  <code className="rounded bg-surface-3 px-1 font-mono text-xs">
                    TWILIO_WHATSAPP_FROM
                  </code>{' '}
                  on the backend to enable WhatsApp messaging.
                </p>
              )}
            </section>

            {/* ── Reply handling ── */}
            <section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
              <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Reply Handling
              </h2>
              <p className="mb-4 text-xs text-ink-subtle">
                When a party replies to one of Penny's emails, the reply is always saved to the
                transaction and the deal's agent is nudged on WhatsApp. You can also have Penny
                forward each reply to that agent's email inbox.
              </p>
              <label className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={forwardReplies}
                  disabled={forwardSaving}
                  onChange={(e) => toggleForwardReplies(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-hairline text-penny focus:ring-penny disabled:opacity-50"
                />
                <span className="text-sm text-ink">
                  Forward email replies to the agent's inbox
                  <span className="mt-0.5 block text-xs text-ink-subtle">
                    The agent can reply straight from their email. Penny still logs the thread on
                    the transaction.
                  </span>
                </span>
              </label>
            </section>

            {/* ── What agents can do ── */}
            <section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
                What Agents Can Do via WhatsApp
              </h2>
              <ul className="space-y-2.5 text-sm text-ink">
                {CAPABILITIES.map((c) => (
                  <li key={c.title} className="flex items-start gap-2">
                    <span style={{ color: WA_GREEN }} className="mt-0.5 text-base leading-none">✓</span>
                    <span>
                      <span className="font-medium">{c.title}</span>
                      <span className="text-ink-muted"> — {c.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs text-ink-subtle">
                Send a voice memo for any of these and Penny transcribes it. Anything that
                sends or changes something asks you to confirm first, unless you’ve set it to
                run automatically (e.g. intro emails, in Automation settings).
              </p>
            </section>

            {/* ── Registered contacts ── */}
            <section className="rounded-2xl border border-hairline bg-surface shadow-sm">
              <div className="border-b border-hairline px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                  Registered Agents
                </h2>
                <p className="mt-1 text-xs text-ink-subtle">
                  Only numbers listed here can message Penny. Unrecognised numbers are
                  politely rejected.
                </p>
              </div>

              {contacts.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-ink-subtle">
                  No agents registered yet. Add one below.
                </p>
              ) : (
                <ul className="divide-y divide-hairline">
                  {contacts.map((c) => (
                    <li
                      key={c.id}
                      className="flex items-center justify-between gap-4 px-6 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium text-ink">
                          {c.display_name || c.phone_number}
                        </p>
                        {c.display_name && (
                          <p className="text-xs text-ink-subtle">{c.phone_number}</p>
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
                className="border-t border-hairline px-6 py-4"
              >
                <h3 className="mb-3 text-sm font-semibold text-ink">
                  Add an agent
                </h3>
                {addError && (
                  <p className="mb-3 text-xs text-red-600">{addError}</p>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-ink-muted">
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
                    <label className="mb-1 block text-xs font-medium text-ink-muted">
                      Display name (optional)
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Sarah, Listing Agent"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <label className="mb-1 block text-xs font-medium text-ink-muted">Channel</label>
                  <div className="flex gap-4 text-sm text-ink">
                    {(['whatsapp', 'sms', 'both'] as Channel[]).map((c) => (
                      <label key={c} className="flex items-center gap-1.5">
                        <input
                          type="radio"
                          name="channel"
                          value={c}
                          checked={channel === c}
                          onChange={() => setChannel(c)}
                        />
                        {c === 'whatsapp' ? 'WhatsApp' : c === 'sms' ? 'SMS' : 'Both'}
                      </label>
                    ))}
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

            {/* ── SMS channel ── */}
            <section className="rounded-2xl border border-hairline bg-surface shadow-sm">
              <div className="border-b border-hairline px-6 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                  SMS Channel
                </h2>
                {smsConfig?.penny_sms_number ? (
                  <p className="mt-1 text-xs text-ink-subtle">
                    Penny’s SMS number:{' '}
                    <span className="font-mono text-ink">{smsConfig.penny_sms_number}</span>.
                    Text-only. No voice memos or photos on this channel.
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-ink-subtle">
                    Not configured. Set{' '}
                    <code className="rounded bg-surface-3 px-1 font-mono">TWILIO_SMS_FROM</code> on
                    the backend to enable SMS.
                  </p>
                )}
              </div>
              {smsContacts.length === 0 ? (
                <p className="px-6 py-8 text-center text-sm text-ink-subtle">
                  No SMS agents registered yet.
                </p>
              ) : (
                <ul className="divide-y divide-hairline">
                  {smsContacts.map((c) => (
                    <li key={c.id} className="flex items-center justify-between gap-4 px-6 py-3">
                      <div>
                        <p className="text-sm font-medium text-ink">
                          {c.display_name || c.phone_number}
                        </p>
                        {c.display_name && (
                          <p className="text-xs text-ink-subtle">{c.phone_number}</p>
                        )}
                      </div>
                      <button
                        onClick={() => handleRemoveSms(c.phone_number)}
                        className="text-xs font-medium text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
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
