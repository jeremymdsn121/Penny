import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import {
  onboardingApi,
  type OnboardingOptions,
  type TaskDefinition,
} from '../lib/api'
import { useAuthStore } from '../store/auth'

const STEPS = ['State', 'Identity', 'Email', 'Calendar', 'Autonomy'] as const

type EmailMode = 'own' | 'monitor'
type CalendarProvider = 'google' | 'outlook' | ''
type ShowingMethod = 'email' | 'showingtime'

export default function Onboarding() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)
  const setBrokerage = useAuthStore((s) => s.setBrokerage)

  const [options, setOptions] = useState<OnboardingOptions | null>(null)
  const [step, setStep] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Step 1 — State
  const [state, setState] = useState(brokerage?.state ?? '')
  // Step 2 — Identity
  const [assistantName, setAssistantName] = useState(brokerage?.assistant_name || 'Penny')
  const [name, setName] = useState(brokerage?.name ?? '')
  const [email, setEmail] = useState(brokerage?.email ?? '')
  const [phone, setPhone] = useState(brokerage?.phone ?? '')
  // Step 3 — Email handling
  const [emailMode, setEmailMode] = useState<EmailMode>('own')
  const [monitorEmail, setMonitorEmail] = useState('')
  // Step 4 — Calendar / scheduling
  const [calendarProvider, setCalendarProvider] = useState<CalendarProvider>('')
  const [workStart, setWorkStart] = useState('09:00')
  const [workEnd, setWorkEnd] = useState('17:00')
  const [bufferMinutes, setBufferMinutes] = useState(15)
  const [showingMethod, setShowingMethod] = useState<ShowingMethod>('email')
  // Step 5 — Task autonomy
  const [autonomy, setAutonomy] = useState<Record<string, boolean>>({})

  useEffect(() => {
    onboardingApi
      .options()
      .then((opts) => {
        setOptions(opts)
        const initial: Record<string, boolean> = {}
        for (const t of opts.tasks) initial[t.task_id] = t.locked ? false : t.default_autonomous
        setAutonomy(initial)
      })
      .catch(() => setError('Could not load setup options. Is the backend running?'))
  }, [])

  const assistant = assistantName || 'Penny'
  const isDetailedState = useMemo(
    () => !!state && (options?.detailed_ruleset_states.includes(state) ?? false),
    [state, options],
  )

  const emailValid = (v: string) => /.+@.+\..+/.test(v)
  const canNext =
    step === 0
      ? !!state
      : step === 1
        ? name.trim().length > 0
        : step === 2
          ? emailMode === 'own' || emailValid(monitorEmail)
          : true

  const bubble = [
    'First — which state do you operate in? It sets your compliance rules.',
    "Let's get my details right. This is how I'll introduce myself to clients.",
    'How should I handle email — have my own address, or watch an inbox you already use?',
    'When can I schedule things, and how do showings get booked?',
    'Last step — decide what I handle on my own versus draft for your approval.',
  ][step]

  const onFinish = async () => {
    if (!options) return
    setSubmitting(true)
    setError(null)
    try {
      const updated = await onboardingApi.submit({
        state,
        assistant_name: assistant,
        name,
        email: email || null,
        phone: phone || null,
        email_mode: emailMode,
        monitor_email: emailMode === 'monitor' ? monitorEmail : null,
        calendar_provider: calendarProvider || null,
        work_start: workStart,
        work_end: workEnd,
        buffer_minutes: bufferMinutes,
        showing_method: showingMethod,
        tasks: options.tasks.map((t) => ({
          task_id: t.task_id,
          autonomous: t.locked ? false : !!autonomy[t.task_id],
        })),
      })
      setBrokerage(updated)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Something went wrong saving your setup.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-2 px-4 py-10">
      <div className="mx-auto w-full max-w-lg space-y-6">
        <Stepper step={step} />
        <PennyBubble>{bubble}</PennyBubble>

        <div className="space-y-5 rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          {!options && !error && <p className="text-sm text-ink-muted">Loading…</p>}

          {step === 0 && options && (
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-ink">State</span>
                <select className="input" value={state} onChange={(e) => setState(e.target.value)}>
                  <option value="">Select a state…</option>
                  {options.states.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              {state && (
                <p className="text-xs text-ink-muted">
                  {isDetailedState
                    ? `I have detailed compliance rules for ${state}.`
                    : `I'll use my default compliance checklist for ${state} — verify state-specific addenda.`}
                </p>
              )}
            </div>
          )}

          {step === 1 && options && (
            <div className="space-y-4">
              <TextField label="Assistant name" value={assistantName} onChange={setAssistantName} />
              <TextField label="Brokerage name" value={name} onChange={setName} />
              <TextField label="Email" type="email" value={email} onChange={setEmail} placeholder="penny@yourbrokerage.com" />
              <TextField label="Phone" value={phone} onChange={setPhone} placeholder="(512) 555-0100" />
            </div>
          )}

          {step === 2 && options && (
            <div className="space-y-3">
              <OptionCard
                selected={emailMode === 'own'}
                onClick={() => setEmailMode('own')}
                title={`${assistant} gets her own address`}
                desc={`I send and receive as my own address${email ? ` (${email})` : ''}.`}
              />
              <OptionCard
                selected={emailMode === 'monitor'}
                onClick={() => setEmailMode('monitor')}
                title="I monitor an inbox you already use"
                desc="I watch an existing mailbox and act on what comes in."
              />
              {emailMode === 'monitor' && (
                <TextField
                  label="Inbox to monitor"
                  type="email"
                  value={monitorEmail}
                  onChange={setMonitorEmail}
                  placeholder="deals@yourbrokerage.com"
                />
              )}
              <p className="text-xs text-ink-muted">
                I&rsquo;ll connect to the live mailbox when we set up scheduling — for now this just records how you want it to work.
              </p>
            </div>
          )}

          {step === 3 && options && (
            <div className="space-y-4">
              <div>
                <span className="mb-1 block text-sm font-medium text-ink">Calendar</span>
                <div className="grid grid-cols-3 gap-2">
                  <ChoicePill label="Google" active={calendarProvider === 'google'} onClick={() => setCalendarProvider('google')} />
                  <ChoicePill label="Outlook" active={calendarProvider === 'outlook'} onClick={() => setCalendarProvider('outlook')} />
                  <ChoicePill label="Decide later" active={calendarProvider === ''} onClick={() => setCalendarProvider('')} />
                </div>
                <p className="mt-1 text-xs text-ink-muted">
                  I&rsquo;ll connect your calendar account when we turn on scheduling.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <TextField label="Working hours start" type="time" value={workStart} onChange={setWorkStart} />
                <TextField label="Working hours end" type="time" value={workEnd} onChange={setWorkEnd} />
              </div>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-ink">Buffer between appointments</span>
                <select
                  className="input"
                  value={bufferMinutes}
                  onChange={(e) => setBufferMinutes(Number(e.target.value))}
                >
                  {[0, 15, 30, 45, 60].map((m) => (
                    <option key={m} value={m}>
                      {m} minutes
                    </option>
                  ))}
                </select>
              </label>

              <div>
                <span className="mb-1 block text-sm font-medium text-ink">How showings get booked</span>
                <div className="grid grid-cols-2 gap-2">
                  <ChoicePill label="Email-based" active={showingMethod === 'email'} onClick={() => setShowingMethod('email')} />
                  <ChoicePill label="ShowingTime" active={showingMethod === 'showingtime'} onClick={() => setShowingMethod('showingtime')} />
                </div>
                {showingMethod === 'showingtime' && (
                  <p className="mt-1 text-xs text-ink-muted">
                    ShowingTime handles the booking itself. I step in afterward — confirming the showing and reminding everyone.
                  </p>
                )}
              </div>
            </div>
          )}

          {step === 4 && options && (
            <div className="space-y-3">
              {options.tasks.map((t) => (
                <TaskToggle
                  key={t.task_id}
                  task={t}
                  value={t.locked ? false : !!autonomy[t.task_id]}
                  onChange={(v) => setAutonomy((prev) => ({ ...prev, [t.task_id]: v }))}
                />
              ))}
            </div>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="text-sm font-medium text-ink-muted hover:text-ink disabled:invisible"
            >
              Back
            </button>
            {step < STEPS.length - 1 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                disabled={!canNext || !options}
                className="btn-primary"
              >
                Continue
              </button>
            ) : (
              <button type="button" onClick={onFinish} disabled={submitting} className="btn-primary">
                {submitting ? 'Finishing…' : 'Finish setup'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Stepper({ step }: { step: number }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      {STEPS.map((label, i) => (
        <div key={label} className="flex items-center gap-1.5">
          <div
            className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
              i <= step ? 'bg-penny text-white' : 'bg-surface-3 text-ink-muted'
            }`}
          >
            {i + 1}
          </div>
          <span className={`text-sm ${i === step ? 'font-medium text-ink' : 'text-ink-subtle'}`}>
            {label}
          </span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-4 bg-surface-3" />}
        </div>
      ))}
    </div>
  )
}

function TextField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      <input
        className="input"
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function OptionCard({
  selected,
  onClick,
  title,
  desc,
}: {
  selected: boolean
  onClick: () => void
  title: string
  desc: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        selected ? 'border-penny bg-penny-light' : 'border-hairline hover:border-hairline'
      }`}
    >
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="text-xs text-ink-muted">{desc}</p>
    </button>
  )
}

function ChoicePill({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
        active ? 'border-penny bg-penny-light font-medium text-penny-dark' : 'border-hairline text-ink hover:border-hairline'
      }`}
    >
      {label}
    </button>
  )
}

function TaskToggle({
  task,
  value,
  onChange,
}: {
  task: TaskDefinition
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-hairline p-3">
      <div>
        <p className="text-sm font-medium text-ink">{task.label}</p>
        <p className="text-xs text-ink-muted">{task.description}</p>
        <span
          className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${
            task.locked
              ? 'bg-surface-3 text-ink-muted'
              : value
                ? 'bg-penny-light text-penny-dark'
                : 'bg-blue-50 text-blue-700'
          }`}
        >
          {task.locked ? 'Always needs approval' : value ? 'Autonomous' : 'Needs approval'}
        </span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={task.label}
        disabled={task.locked}
        onClick={() => onChange(!value)}
        className={`mt-1 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
          task.locked ? 'cursor-not-allowed bg-surface-3' : value ? 'bg-penny' : 'bg-surface-3'
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-surface transition-transform ${
            value ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  )
}
