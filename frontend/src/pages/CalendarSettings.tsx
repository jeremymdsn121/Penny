import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Calendar, Check, Clock, Copy, Link2 } from 'lucide-react'
import {
  calendarApi,
  type CalendarAgentStatus,
  type CalendarStatus,
  type WorkingHours,
} from '../lib/api'
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
                  {status.brokerage.needs_reconnect ? (
                    <>
                      <span className="inline-flex items-center gap-1 text-sm font-medium text-amber-600">
                        <AlertTriangle size={16} /> Reconnect needed
                      </span>
                      <button
                        onClick={() => connect()}
                        disabled={!configured || busy === 'brokerage'}
                        className="text-sm font-medium text-penny hover:text-penny-dark"
                      >
                        {busy === 'brokerage' ? 'Reconnecting…' : 'Reconnect'}
                      </button>
                    </>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600">
                      <Check size={16} /> Connected
                    </span>
                  )}
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
                  <li key={a.id} className="py-3">
                    <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-ink">{a.name || a.email || 'Agent'}</p>
                      {a.email && <p className="truncate text-xs text-ink-muted">{a.email}</p>}
                    </div>
                    {a.connected ? (
                      <div className="flex items-center gap-3">
                        {a.needs_reconnect ? (
                          <>
                            <span className="inline-flex items-center gap-1 text-sm font-medium text-amber-600">
                              <AlertTriangle size={16} /> Reconnect needed
                            </span>
                            <button
                              onClick={() => connect(a.id)}
                              disabled={!configured || busy === a.id}
                              className="text-sm font-medium text-penny hover:text-penny-dark"
                            >
                              {busy === a.id ? 'Reconnecting…' : 'Reconnect'}
                            </button>
                          </>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600">
                            <Check size={16} /> Connected
                          </span>
                        )}
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
                    </div>
                    <AgentHours
                      agent={a}
                      fb={{ work_start: workStart, work_end: workEnd, buffer_minutes: buffer }}
                      setBanner={setBanner}
                    />
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

// Per-agent working-hours override. Self-contained: edits its own state and
// reflects whether the agent is using a custom window or inheriting the
// brokerage's (`fb`). Saving sets all three; "Use brokerage hours" clears them.
function AgentHours({
  agent,
  fb,
  setBanner,
}: {
  agent: CalendarAgentStatus
  fb: WorkingHours
  setBanner: (b: { ok: boolean; text: string }) => void
}) {
  const who = agent.name || agent.email || 'Agent'
  const [override, setOverride] = useState(agent.work_start != null)
  const [start, setStart] = useState(agent.work_start ?? fb.work_start)
  const [end, setEnd] = useState(agent.work_end ?? fb.work_end)
  const [buffer, setBuffer] = useState<number>(agent.buffer_minutes ?? fb.buffer_minutes)
  const [saving, setSaving] = useState(false)

  async function save() {
    if (end <= start) {
      setBanner({ ok: false, text: 'End time must be after start time.' })
      return
    }
    setSaving(true)
    try {
      await calendarApi.updateAgentWorkingHours(agent.id, {
        work_start: start,
        work_end: end,
        buffer_minutes: buffer,
      })
      setOverride(true)
      setBanner({ ok: true, text: `Hours saved for ${who}.` })
    } catch {
      setBanner({ ok: false, text: 'Could not save agent hours.' })
    } finally {
      setSaving(false)
    }
  }

  async function clear() {
    setSaving(true)
    try {
      await calendarApi.clearAgentWorkingHours(agent.id)
      setOverride(false)
      setStart(fb.work_start)
      setEnd(fb.work_end)
      setBuffer(fb.buffer_minutes)
      setBanner({ ok: true, text: `${who} now uses brokerage hours.` })
    } catch {
      setBanner({ ok: false, text: 'Could not reset agent hours.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-hairline bg-surface-2 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-ink-muted">Working hours</span>
        <span className="text-xs text-ink-subtle">
          {override ? 'Custom' : 'Using brokerage hours'}
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs text-ink-subtle">Start</span>
          <input
            className="input w-28 py-1"
            type="time"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-ink-subtle">End</span>
          <input
            className="input w-28 py-1"
            type="time"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-ink-subtle">Buffer</span>
          <select
            className="input w-24 py-1"
            value={buffer}
            onChange={(e) => setBuffer(Number(e.target.value))}
          >
            {[0, 15, 30, 45, 60].map((m) => (
              <option key={m} value={m}>
                {m}m
              </option>
            ))}
          </select>
        </label>
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? 'Saving…' : 'Save'}
        </button>
        {override && (
          <button
            onClick={clear}
            disabled={saving}
            className="text-sm font-medium text-ink-muted hover:text-ink"
          >
            Use brokerage hours
          </button>
        )}
      </div>
    </div>
  )
}
