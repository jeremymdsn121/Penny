import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import TaskToggle from '../components/TaskToggle'
import { usePennyGlyphSlot } from '../hooks/usePennyGlyphSlot'
import { useGlyphStore } from '../store/glyph'
import {
  onboardingApi,
  type OnboardingOptions,
} from '../lib/api'
import { useAuthStore } from '../store/auth'

// Onboarding is the user's first conversation with Penny: a large glyph greets
// them, then she asks the five setup questions ONE AT A TIME (greeting beat +
// five question beats), each a chat bubble with a clean answer board below.
// On finish the big glyph shrinks and flies to become the home hero (the glyph
// itself is the shared PennyGlyphLayer; this page just registers its slot and
// hands off the rect before navigating).

const STEP_LABELS = ['State', 'Identity', 'Email', 'Calendar', 'Autonomy'] as const
const STEP_COUNT = STEP_LABELS.length
// Deliberately larger than the home hero (198) — Penny is the focal point of her
// own introduction, and the shrink to 198 on finish reads as her settling in.
const GLYPH_SIZE = 264

type EmailMode = 'own' | 'monitor'
type CalendarProvider = 'google' | 'outlook' | ''
type ShowingMethod = 'email' | 'showingtime'

export default function Onboarding() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)
  const setBrokerage = useAuthStore((s) => s.setBrokerage)

  const [options, setOptions] = useState<OnboardingOptions | null>(null)
  // beat 0 = greeting, 1..STEP_COUNT = questions. step = beat - 1.
  const [beat, setBeat] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Question 1 — State
  const [state, setState] = useState(brokerage?.state ?? '')
  // Question 2 — Identity (assistant is always "Penny"; not user-editable)
  const [name, setName] = useState(brokerage?.name ?? '')
  const [email, setEmail] = useState(brokerage?.email ?? '')
  const [phone, setPhone] = useState(brokerage?.phone ?? '')
  // Question 3 — Email handling
  const [emailMode, setEmailMode] = useState<EmailMode>('own')
  const [monitorEmail, setMonitorEmail] = useState('')
  // Question 4 — Calendar / scheduling
  const [calendarProvider, setCalendarProvider] = useState<CalendarProvider>('')
  const [workStart, setWorkStart] = useState('09:00')
  const [workEnd, setWorkEnd] = useState('17:00')
  const [bufferMinutes, setBufferMinutes] = useState(15)
  const [showingMethod, setShowingMethod] = useState<ShowingMethod>('email')
  // Question 5 — Task autonomy
  const [autonomy, setAutonomy] = useState<Record<string, boolean>>({})

  // The invisible slot the floating glyph fills. The persistent layer paints the
  // big glyph here; on finish we hand off its rect so it can fly to the home hero.
  const slotRef = usePennyGlyphSlot('onboard-hero', GLYPH_SIZE)

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

  const assistant = 'Penny'
  const step = beat - 1
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
    'First, which state do you operate in? It sets your compliance rules.',
    "Let's get my details right. This is how I'll introduce myself to clients.",
    'How should I handle email? I can have my own address, or watch an inbox you already use.',
    'When can I schedule things, and how do showings get booked?',
    'Last step. Decide what I handle on my own versus draft for your approval.',
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
      // Capture the live glyph rect as the FLIP "from" BEFORE navigating — the
      // onboarding slot unmounts the instant we leave the route.
      const r = slotRef.current?.getBoundingClientRect()
      if (r) useGlyphStore.getState().beginHandoff({ x: r.left, y: r.top, size: r.width })
      navigate('/')
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Something went wrong saving your setup.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface-2 px-4 py-10">
      <div className="flex w-full max-w-lg flex-col items-center">
        {/* Large glyph slot — the persistent PennyGlyphLayer paints the big,
            animated glyph (hover + twinkle) over this invisible spacer. */}
        <div ref={slotRef} aria-hidden style={{ width: GLYPH_SIZE, height: GLYPH_SIZE }} />

        {/* Beat content cross-fades: key forces a remount so fade-up replays. */}
        <div key={beat} className="w-full animate-fade-up">
          {beat === 0 ? (
            <div className="space-y-5 text-center">
              <p className="text-2xl font-semibold tracking-tight text-ink">
                Hey there, I&rsquo;m Penny. Let&rsquo;s get you started.
              </p>
              <p className="text-sm text-ink-muted">
                A few quick questions and I&rsquo;ll be ready to run your transactions with you.
              </p>
              <button type="button" className="btn-primary" onClick={() => setBeat(1)} disabled={!options}>
                {options ? "Let's go" : 'Loading…'}
              </button>
              {error && <p className="text-sm text-red-600">{error}</p>}
            </div>
          ) : (
            <div className="space-y-5">
              <Progress step={step} />
              <PennyBubble>{bubble}</PennyBubble>

              <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
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
                          : `I'll use my default compliance checklist for ${state}. Verify state-specific addenda.`}
                      </p>
                    )}
                  </div>
                )}

                {step === 1 && options && (
                  <div className="space-y-4">
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
                      I&rsquo;ll connect to the live mailbox when we set up scheduling. For now this just records how you want it to work.
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
                          ShowingTime handles the booking itself. I step in afterward, confirming the showing and reminding everyone.
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

                {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
              </div>

              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setBeat((b) => Math.max(1, b - 1))}
                  disabled={beat === 1}
                  className="text-sm font-medium text-ink-muted hover:text-ink disabled:invisible"
                >
                  Back
                </button>
                {step < STEP_COUNT - 1 ? (
                  <button
                    type="button"
                    onClick={() => setBeat((b) => b + 1)}
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
          )}
        </div>
      </div>
    </div>
  )
}

// Slim dots progress — replaces the old numbered Stepper to keep the
// conversational flow uncluttered.
function Progress({ step }: { step: number }) {
  return (
    <div className="flex items-center justify-center gap-1.5" aria-label={`Step ${step + 1} of ${STEP_COUNT}: ${STEP_LABELS[step]}`}>
      {STEP_LABELS.map((label, i) => (
        <span
          key={label}
          className={`h-1.5 rounded-full transition-all ${
            i === step ? 'w-6 bg-penny' : i < step ? 'w-1.5 bg-penny/50' : 'w-1.5 bg-surface-3'
          }`}
        />
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
      className={`w-full rounded-xl border-2 p-4 text-left transition-colors ${
        selected
          ? 'border-penny bg-penny-light ring-2 ring-penny/20'
          : 'border-hairline hover:border-penny/40'
      }`}
    >
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{desc}</p>
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
      className={`rounded-xl border-2 px-4 py-3 text-sm transition-colors ${
        active
          ? 'border-penny bg-penny-light font-medium text-penny-dark'
          : 'border-hairline text-ink hover:border-penny/40'
      }`}
    >
      {label}
    </button>
  )
}
