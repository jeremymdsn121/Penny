import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Check, Clock, Copy, Link2 } from 'lucide-react'
import { calendarApi, type CalendarStatus } from '../lib/api'
import { useAuthStore } from '../store/auth'

export default function CalendarSettings() {
  const [status, setStatus] = useState<CalendarStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [banner, setBanner] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [params, setParams] = useSearchParams()

  // Working hours live on the brokerage; set in onboarding, edited here.
  const brokerage = useAuthStore((s) => s.brokerage)
  const setBrokerage = useAuthStore((s) => s.setBrokerage)
  const [workStart, setWorkStart] = useState(brokerage?.work_start ?? '09:00')
  const [workEnd, setWorkEnd] = useState(brokerage?.work_end ?? '17:00')
  const [buffer, setBuffer] = useState<number>(brokerage?.buffer_minutes ?? 15)
  const [savingHours, setSavingHours] = useState(false)

  async function saveHours() {
    if (workEnd <= workStart) {
      setBanner({ ok: false, text: 'End time must be after start time.' })
      return
    }
    setSavingHours(true)
    try {
      const saved = await calendarApi.updateWorkingHours({
        work_start: workStart,
        work_end: workEnd,
        buffer_minutes: buffer,
      })
      if (brokerage) setBrokerage({ ...brokerage, ...saved })
      setBanner({ ok: true, text: 'Working hours saved.' })
    } catch {
      setBanner({ ok: false, text: 'Could not save working hours.' })
    } finally {
      setSavingHours(false)
    }
  }

  function load() {
    setLoading(true)
    calendarApi
      .status()
      .then(setStatus)
      .catch(() => setError('Could not load calendar settings.'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // Surface the callback's ?connected / ?calendar_error, then clean the URL.
  useEffect(() => {
    const connected = params.get('connected')
    const err = params.get('calendar_error')
    if (connected) setBanner({ ok: true, text: 'Calendar connected.' })
    else if (err) setBanner({ ok: false, text: `Could not connect the calendar (${err}).` })
    if (connected || err) {
      params.delete('connected')
      params.delete('calendar_error')
      setParams(params, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function connect(agentId?: string) {
    setBusy(agentId ?? 'brokerage')
    try {
      window.location.href = await calendarApi.connectUrl(agentId)
    } catch {
      setBanner({ ok: false, text: 'Could not start the calendar connection.' })
      setBusy(null)
    }
  }

  async function copyLink(agentId: string) {
    try {
      await navigator.clipboard.writeText(await calendarApi.connectUrl(agentId))
      setCopied(agentId)
      setTimeout(() => setCopied((c) => (c === agentId ? null : c)), 2500)
    } catch {
      setBanner({ ok: false, text: 'Could not copy the connect link.' })
    }
  }

  async function disconnect(agentId?: string) {
    setBusy(agentId ?? 'brokerage')
    try {
      await calendarApi.disconnect(agentId)
      load()
    } catch {
      setBanner({ ok: false, text: 'Could not disconnect.' })
    } finally {
      setBusy(null)
    }
  }

  const configured = status?.oauth_configured ?? false

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Calendar</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Connect Google Calendar so Penny reads free/busy when proposing times and puts
          booked showings on the right calendar.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {banner && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            banner.ok
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {banner.text}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Working hours — independent of any calendar connection. */}
          <section className="card space-y-4 p-6">
            <div className="flex items-center gap-3">
              <Clock size={20} className="text-ink-muted" />
              <div>
                <p className="text-sm font-medium text-ink">Working hours</p>
                <p className="text-xs text-ink-muted">
                  The window Penny proposes showing times within, and the gap she leaves
                  between appointments.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-ink">Start</span>
                <input
                  className="input"
                  type="time"
                  value={workStart}
                  onChange={(e) => setWorkStart(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-ink">End</span>
                <input
                  className="input"
                  type="time"
                  value={workEnd}
                  onChange={(e) => setWorkEnd(e.target.value)}
                />
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-ink">
                Buffer between appointments
              </span>
              <select
                className="input"
                value={buffer}
                onChange={(e) => setBuffer(Number(e.target.value))}
              >
                {[0, 15, 30, 45, 60].map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </label>
            <div className="flex justify-end">
              <button onClick={saveHours} disabled={savingHours} className="btn-primary">
                {savingHours ? 'Saving…' : 'Save'}
              </button>
            </div>
          </section>

          {!configured && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Google Calendar isn&rsquo;t configured on the server yet, so connecting is
              disabled. (Set the Google OAuth credentials to enable it.)
            </div>
          )}

          {/* Brokerage calendar */}
          <section className="card space-y-4 p-6">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Calendar size={20} className="text-ink-muted" />
                <div>
                  <p className="text-sm font-medium text-ink">Brokerage calendar</p>
                  <p className="text-xs text-ink-muted">
                    Shared fallback for deals whose agent hasn&rsquo;t connected their own.
                  </p>
                </div>
              </div>
              {status?.brokerage.connected ? (
                <div className="flex items-center gap-3">
                  <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600">
                    <Check size={16} /> Connected
                  </span>
                  <button
                    onClick={() => disconnect()}
                    disabled={busy === 'brokerage'}
                    className="text-sm font-medium text-ink-muted hover:text-ink"
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => connect()}
                  disabled={!configured || busy === 'brokerage'}
                  className="btn-primary"
                >
                  {busy === 'brokerage' ? 'Connecting…' : 'Connect'}
                </button>
              )}
            </div>
          </section>

          {/* Per-agent calendars */}
          <section className="card p-6">
            <p className="mb-1 text-sm font-medium text-ink">Agent calendars</p>
            <p className="mb-4 text-xs text-ink-muted">
              Each agent&rsquo;s showings go on their own calendar when connected. Connect on
              their behalf, or copy a link to send them so they sign into their own Google.
            </p>
            {status && status.agents.length === 0 ? (
              <p className="text-sm text-ink-subtle">No agents on this brokerage yet.</p>
            ) : (
              <ul className="divide-y divide-hairline">
                {status?.agents.map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-4 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-ink">{a.name || a.email || 'Agent'}</p>
                      {a.email && <p className="truncate text-xs text-ink-muted">{a.email}</p>}
                    </div>
                    {a.connected ? (
                      <div className="flex items-center gap-3">
                        <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600">
                          <Check size={16} /> Connected
                        </span>
                        <button
                          onClick={() => disconnect(a.id)}
                          disabled={busy === a.id}
                          className="text-sm font-medium text-ink-muted hover:text-ink"
                        >
                          Disconnect
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => copyLink(a.id)}
                          disabled={!configured}
                          title="Copy a connect link to send the agent"
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-ink-muted hover:bg-surface-3 hover:text-ink disabled:opacity-50"
                        >
                          {copied === a.id ? <Check size={15} /> : <Copy size={15} />}
                          {copied === a.id ? 'Copied' : 'Copy link'}
                        </button>
                        <button
                          onClick={() => connect(a.id)}
                          disabled={!configured || busy === a.id}
                          className="inline-flex items-center gap-1 rounded-md bg-penny px-3 py-1.5 text-sm font-medium text-white hover:bg-penny-dark disabled:opacity-50"
                        >
                          <Link2 size={15} />
                          {busy === a.id ? 'Connecting…' : 'Connect'}
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
