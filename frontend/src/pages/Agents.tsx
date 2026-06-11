import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PennyBubble from '../components/PennyBubble'
import { agentsApi, knowledgeApi, type Agent, type KnowledgeRule } from '../lib/api'

function cap(s?: string | null): string {
  if (!s) return 'General'
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function StyleProfile({ agent }: { agent: Agent }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [rules, setRules] = useState<KnowledgeRule[]>([])
  const [loading, setLoading] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setRules(await agentsApi.listStyleRules(agent.id))
  }

  useEffect(() => {
    agentsApi
      .listStyleRules(agent.id)
      .then(setRules)
      .catch(() => setError('Could not load this agent’s style rules.'))
      .finally(() => setLoading(false))
  }, [agent.id])

  async function handleUpload() {
    if (!file) return
    setUploading(true)
    setError(null)
    setNotice(null)
    try {
      const result = await agentsApi.uploadStyleDocument(agent.id, file)
      await refresh()
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      setNotice(
        result.extraction_error ??
          `Analyzed “${result.document.filename}” — ${result.rules.length} rule${
            result.rules.length !== 1 ? 's' : ''
          } proposed below.`,
      )
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail
      setError(detail ?? 'Upload failed. Use a PDF, image, or .docx under 25 MB.')
    } finally {
      setUploading(false)
    }
  }

  async function confirmRule(id: string) {
    try {
      await knowledgeApi.updateRule(id, { confirmed: true })
      setRules((prev) => prev.map((r) => (r.id === id ? { ...r, confirmed: true } : r)))
    } catch {
      setError('Could not confirm the rule.')
    }
  }

  async function removeRule(id: string) {
    try {
      await knowledgeApi.deleteRule(id)
      setRules((prev) => prev.filter((r) => r.id !== id))
    } catch {
      setError('Could not remove the rule.')
    }
  }

  const pending = rules.filter((r) => !r.confirmed)
  const confirmed = rules.filter((r) => r.confirmed)

  return (
    <div className="space-y-4 border-t border-hairline bg-surface-2/50 px-6 py-5">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">My Style</h3>
        <p className="mt-1 text-xs text-ink-subtle">
          Upload a sample email or letter in {agent.name || 'this agent'}’s voice. Confirmed
          rules layer on top of the brokerage style for their documents only.
        </p>
      </div>

      {error && <p className="text-xs text-red-600">{error}</p>}
      {notice && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-800">
          {notice}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf,image/*,.pdf,.docx"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block text-xs text-ink-muted file:mr-3 file:rounded-lg file:border-0 file:bg-surface-3 file:px-3 file:py-2 file:text-xs file:font-medium file:text-ink hover:file:bg-surface-3"
        />
        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className="btn-primary flex items-center gap-2 text-xs disabled:opacity-50"
        >
          {uploading && (
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
          )}
          {uploading ? 'Analyzing…' : 'Upload & analyze'}
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-ink-subtle">Loading…</p>
      ) : (
        <>
          {pending.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold text-ink-muted">Proposed — needs review</p>
              <ul className="space-y-1.5">
                {pending.map((r) => (
                  <li
                    key={r.id}
                    className="flex items-start justify-between gap-3 rounded-lg border border-hairline bg-surface px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="inline-block rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700">
                        {cap(r.category)}
                      </span>
                      <p className="mt-1 text-xs text-ink">{r.rule}</p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        onClick={() => confirmRule(r.id)}
                        className="text-xs font-semibold text-penny hover:underline"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => removeRule(r.id)}
                        className="text-xs font-medium text-red-500 hover:text-red-700"
                      >
                        Reject
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="mb-1.5 text-xs font-semibold text-ink-muted">Confirmed rules</p>
            {confirmed.length === 0 ? (
              <p className="text-xs text-ink-subtle">No confirmed rules yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {confirmed.map((r) => (
                  <li
                    key={r.id}
                    className="flex items-start justify-between gap-3 rounded-lg border border-hairline bg-surface px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="inline-block rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-medium text-green-700">
                        {cap(r.category)}
                      </span>
                      <p className="mt-1 text-xs text-ink">{r.rule}</p>
                    </div>
                    <button
                      onClick={() => removeRule(r.id)}
                      className="shrink-0 text-xs font-medium text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function Agents() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    agentsApi
      .list()
      .then(setAgents)
      .catch(() => setError('Could not load your agents.'))
      .finally(() => setLoading(false))
  }, [])

  async function addAgent() {
    if (!name.trim()) return
    setCreating(true)
    setError(null)
    try {
      const agent = await agentsApi.create({ name: name.trim(), email: email.trim() || null })
      setAgents((prev) => [...prev, { ...agent, style_rule_count: 0 }])
      setName('')
      setEmail('')
    } catch {
      setError('Could not add that agent.')
    } finally {
      setCreating(false)
    }
  }

  async function removeAgent(id: string) {
    if (!confirm('Remove this agent and their style profile?')) return
    try {
      await agentsApi.remove(id)
      setAgents((prev) => prev.filter((a) => a.id !== id))
    } catch {
      setError('Could not remove that agent.')
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
        <h1 className="text-sm font-semibold text-ink">Team &amp; Style</h1>
        <div className="w-28" />
      </header>

      <main className="mx-auto max-w-2xl space-y-6 px-6 py-10">
        <PennyBubble>
          Add your agents here. Each can build a personal “My Style” profile — upload a sample
          email and I’ll match their voice when I draft documents for them. The brokerage’s
          Brand &amp; Style is the floor; an agent’s rules win where they differ.
        </PennyBubble>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-muted">
            Add an agent
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              className="flex-1 rounded-lg border border-hairline px-3 py-2 text-sm"
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email (optional)"
              className="flex-1 rounded-lg border border-hairline px-3 py-2 text-sm"
            />
            <button
              onClick={addAgent}
              disabled={!name.trim() || creating}
              className="btn-primary disabled:opacity-50"
            >
              {creating ? 'Adding…' : 'Add'}
            </button>
          </div>
        </section>

        <section className="rounded-2xl border border-hairline bg-surface shadow-sm">
          <div className="border-b border-hairline px-6 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">Agents</h2>
          </div>
          {loading ? (
            <div className="flex justify-center py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
            </div>
          ) : agents.length === 0 ? (
            <p className="px-6 py-8 text-center text-sm text-ink-subtle">No agents yet.</p>
          ) : (
            <ul className="divide-y divide-hairline">
              {agents.map((a) => (
                <li key={a.id}>
                  <div className="flex items-center justify-between gap-4 px-6 py-4">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{a.name}</p>
                      <p className="mt-0.5 truncate text-xs text-ink-subtle">
                        {a.email || 'no email'}
                        {a.style_rule_count ? `  ·  ${a.style_rule_count} style rule(s)` : '  ·  no style profile'}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <button
                        onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                        className="text-xs font-semibold text-penny hover:underline"
                      >
                        {expanded === a.id ? 'Hide' : 'My Style'}
                      </button>
                      <button
                        onClick={() => removeAgent(a.id)}
                        className="text-xs font-medium text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                  {expanded === a.id && <StyleProfile agent={a} />}
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
    </div>
  )
}
