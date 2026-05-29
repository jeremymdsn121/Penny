import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowUp,
  BarChart3,
  Home as HomeIcon,
  LayoutDashboard,
  MessageSquare,
  Mic,
  Palette,
  Scale,
  ShieldAlert,
  Sparkles,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { brokerApi, chatApi, transactionsApi, type ChatTurn, type Transaction } from '../lib/api'
import { useAuthStore } from '../store/auth'

const ACTIVE_STAGES = new Set(['under_contract', 'pending'])

interface Pill {
  to: string
  label: string
  hint: string
  icon: LucideIcon
}

const PILLS: Pill[] = [
  { to: '/dashboard', label: 'Dashboard', hint: 'Pipeline at a glance', icon: LayoutDashboard },
  { to: '/review', label: 'Needs Review', hint: 'What needs you', icon: ShieldAlert },
  { to: '/listings', label: 'Listings', hint: 'Prep & publish', icon: HomeIcon },
  { to: '/reports', label: 'Reports', hint: 'Production & health', icon: BarChart3 },
  { to: '/knowledge', label: 'Brand & Style', hint: 'Your voice', icon: Palette },
  { to: '/agents', label: 'Team', hint: 'Agents & profiles', icon: Users },
  { to: '/settings/whatsapp', label: 'Messaging', hint: 'WhatsApp & SMS', icon: MessageSquare },
  { to: '/settings/compliance', label: 'Compliance', hint: 'Disclosure & consent', icon: Scale },
]

const STARTERS = [
  'What needs my attention today?',
  'Which deals are closing this week?',
  "What's missing on my newest file?",
  'Show me my pipeline.',
]

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86_400_000)
}

// Browser-native speech-to-text (Chrome/Edge/Safari). Returns null where unsupported.
function getSpeechRecognition(): any | null {
  const w = window as any
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition
  return SR ? new SR() : null
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

export default function Home() {
  const navigate = useNavigate()
  const brokerage = useAuthStore((s) => s.brokerage)
  const assistant = brokerage?.assistant_name || 'Penny'

  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [reviewCount, setReviewCount] = useState(0)

  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [listening, setListening] = useState(false)

  const threadRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<any>(null)

  const speechSupported = useMemo(() => getSpeechRecognition() !== null, [])

  useEffect(() => {
    transactionsApi.list().then(setTransactions).catch(() => {})
    brokerApi.reviewQueue().then((q) => setReviewCount(q.total)).catch(() => {})
  }, [])

  // Keep the latest message in view as the thread grows.
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  const briefing = useMemo(() => {
    const active = transactions.filter((t) => ACTIVE_STAGES.has(t.stage ?? 'under_contract'))
    const closingSoon = active.filter((t) => {
      const d = daysUntil(t.closing_date)
      return d !== null && d >= 0 && d <= 7
    }).length
    const parts: string[] = []
    parts.push(`${active.length} active deal${active.length !== 1 ? 's' : ''}`)
    if (reviewCount > 0) parts.push(`${reviewCount} need${reviewCount !== 1 ? '' : 's'} your review`)
    if (closingSoon > 0) parts.push(`${closingSoon} closing this week`)
    return parts.join('  ·  ')
  }, [transactions, reviewCount])

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    stopListening()
    const history: ChatTurn[] = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev, { role: 'user', content: trimmed }])
    setInput('')
    setSending(true)
    try {
      const { reply } = await chatApi.send(trimmed, history)
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: "I couldn't reach the server just now. Please try again in a moment.",
        },
      ])
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  function stopListening() {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {/* ignore */}
      recognitionRef.current = null
    }
    setListening(false)
  }

  function toggleListening() {
    if (listening) {
      stopListening()
      return
    }
    const rec = getSpeechRecognition()
    if (!rec) return
    rec.lang = 'en-US'
    rec.interimResults = true
    rec.continuous = false
    let finalText = input ? input + ' ' : ''
    rec.onresult = (e: any) => {
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const chunk = e.results[i][0].transcript
        if (e.results[i].isFinal) finalText += chunk
        else interim += chunk
      }
      setInput((finalText + interim).trimStart())
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recognitionRef.current = rec
    setListening(true)
    rec.start()
  }

  useEffect(() => () => stopListening(), [])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  const started = messages.length > 0

  const ChatBar = (
    <div className="rounded-2xl border border-hairline bg-surface shadow-soft transition-colors focus-within:border-penny">
      <textarea
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        rows={started ? 1 : 2}
        placeholder={`Ask ${assistant} anything about your deals…`}
        className="w-full resize-none bg-transparent px-4 pt-3.5 text-sm text-ink outline-none placeholder:text-ink-subtle"
      />
      <div className="flex items-center justify-between px-3 pb-3">
        <span className="px-1 text-xs text-ink-subtle">
          {listening ? 'Listening…' : 'Enter to send · Shift+Enter for a new line'}
        </span>
        <div className="flex items-center gap-2">
          {speechSupported && (
            <button
              onClick={toggleListening}
              title={listening ? 'Stop voice input' : 'Voice input'}
              className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors ${
                listening
                  ? 'bg-red-500/15 text-red-500 ring-1 ring-red-500/40'
                  : 'text-ink-subtle hover:bg-surface-3 hover:text-ink'
              }`}
            >
              <Mic size={18} className={listening ? 'animate-pulse' : ''} />
            </button>
          )}
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || sending}
            title="Send"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-penny text-white transition-colors hover:bg-penny-dark disabled:cursor-not-allowed disabled:opacity-40"
          >
            {sending ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/60 border-t-transparent" />
            ) : (
              <ArrowUp size={18} />
            )}
          </button>
        </div>
      </div>
    </div>
  )

  // ── Active conversation view ─────────────────────────────────────────────
  if (started) {
    return (
      <div className="mx-auto flex h-screen max-w-3xl flex-col px-6">
        <div ref={threadRef} className="flex-1 space-y-5 overflow-y-auto py-8">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.role === 'assistant' && (
                <div className="mr-3 mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-penny to-penny-bright text-xs font-bold text-white">
                  {assistant.charAt(0)}
                </div>
              )}
              <div
                className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-penny text-white'
                    : 'border border-hairline bg-surface text-ink'
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex justify-start">
              <div className="mr-3 mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-penny to-penny-bright text-xs font-bold text-white">
                {assistant.charAt(0)}
              </div>
              <div className="flex items-center gap-1 rounded-2xl border border-hairline bg-surface px-4 py-3">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-subtle [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-subtle [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-subtle" />
              </div>
            </div>
          )}
        </div>
        <div className="pb-6 pt-2">{ChatBar}</div>
      </div>
    )
  }

  // ── Landing / empty state ────────────────────────────────────────────────
  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-12">
      {/* Brand mark */}
      <div className="mb-6 flex justify-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-penny to-penny-bright text-3xl font-bold text-white shadow-soft">
          {assistant.charAt(0)}
        </div>
      </div>

      {/* Greeting + briefing */}
      <h1 className="text-center text-3xl font-semibold tracking-tight text-ink">
        {greeting()}
      </h1>
      <p className="mt-2 text-center text-sm text-ink-muted">
        {transactions.length === 0
          ? `I'm ${assistant}. Drop a contract or ask me anything to get started.`
          : briefing}
      </p>

      {/* Chat bar */}
      <div className="mt-8">{ChatBar}</div>

      {/* Starter prompts */}
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {STARTERS.map((s) => (
          <button
            key={s}
            onClick={() => send(s)}
            className="rounded-full border border-hairline bg-surface px-3 py-1.5 text-xs text-ink-muted transition-colors hover:border-penny/40 hover:text-ink"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Nav pills */}
      <div className="mt-10">
        <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-subtle">
          <Sparkles size={14} />
          Jump to
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {PILLS.map((p) => {
            const Icon = p.icon
            return (
              <button
                key={p.to}
                onClick={() => navigate(p.to)}
                className="card group flex flex-col gap-2 p-4 text-left transition-colors hover:bg-surface-3"
              >
                <div className="flex items-center justify-between">
                  <Icon size={18} className="text-penny dark:text-penny-bright" />
                  {p.to === '/review' && reviewCount > 0 && (
                    <span className="rounded-full bg-red-500/15 px-1.5 py-0.5 text-xs font-semibold text-red-500">
                      {reviewCount}
                    </span>
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium text-ink">{p.label}</p>
                  <p className="text-xs text-ink-subtle">{p.hint}</p>
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
