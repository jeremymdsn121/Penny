import { useEffect, useState } from 'react'
import {
  docRoutingApi,
  PARTY_ROLES,
  ROUTING_STAGES,
  type DocRoutingRule,
  type PendingDocRoute,
} from '../lib/api'

const STAGE_LABEL: Record<string, string> = Object.fromEntries(
  ROUTING_STAGES.map((s) => [s.key, s.label]),
)
const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  PARTY_ROLES.map((r) => [r.key, r.label]),
)

function rolesSummary(roles: string[]): string {
  if (!roles.length) return 'no parties selected'
  return roles.map((r) => ROLE_LABEL[r] ?? r).join(', ')
}

export default function DocRoutingSettings({ autonomous }: { autonomous: boolean }) {
  const [rules, setRules] = useState<DocRoutingRule[]>([])
  const [pending, setPending] = useState<PendingDocRoute[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  // New-rule form state.
  const [stage, setStage] = useState('under_contract')
  const [roles, setRoles] = useState<string[]>(['title', 'lender'])
  const [adding, setAdding] = useState(false)

  async function load() {
    try {
      const [r, p] = await Promise.all([
        docRoutingApi.listRules(),
        docRoutingApi.listPending(),
      ])
      setRules(r)
      setPending(p)
    } catch {
      setError('Could not load document routing.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function toggleRole(key: string) {
    setRoles((prev) =>
      prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key],
    )
  }

  async function addRule() {
    if (!roles.length) {
      setError('Pick at least one party to route to.')
      return
    }
    setAdding(true)
    setError(null)
    try {
      const created = await docRoutingApi.createRule({
        trigger_stage: stage,
        recipient_roles: roles,
      })
      setRules((prev) => [...prev, created])
      setRoles(['title', 'lender'])
    } catch {
      setError('Could not add the rule.')
    } finally {
      setAdding(false)
    }
  }

  async function toggleRule(rule: DocRoutingRule) {
    setBusyId(rule.id)
    try {
      const updated = await docRoutingApi.updateRule(rule.id, { enabled: !rule.enabled })
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)))
    } catch {
      setError('Could not update the rule.')
    } finally {
      setBusyId(null)
    }
  }

  async function removeRule(id: string) {
    setBusyId(id)
    try {
      await docRoutingApi.deleteRule(id)
      setRules((prev) => prev.filter((r) => r.id !== id))
    } catch {
      setError('Could not delete the rule.')
    } finally {
      setBusyId(null)
    }
  }

  async function sendRoute(id: string) {
    setBusyId(id)
    setError(null)
    try {
      await docRoutingApi.sendPending(id)
      setPending((prev) => prev.filter((p) => p.id !== id))
    } catch {
      setError('Could not send. Check that SendGrid is configured and the contract is on file.')
    } finally {
      setBusyId(null)
    }
  }

  async function dismissRoute(id: string) {
    setBusyId(id)
    try {
      await docRoutingApi.dismissPending(id)
      setPending((prev) => prev.filter((p) => p.id !== id))
    } catch {
      setError('Could not dismiss.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="card space-y-5 p-6">
      <div>
        <h2 className="text-lg font-semibold text-ink">Document routing</h2>
        <p className="mt-1 text-sm text-ink-muted">
          When a deal enters a stage, Penny sends the contract to the parties you choose.
          {autonomous
            ? ' Document routing is autonomous, so Penny sends automatically.'
            : ' Document routing needs approval, so Penny queues each send for you below.'}
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10">
          <div className="h-6 w-6 animate-spin rounded-full border-4 border-penny border-t-transparent" />
        </div>
      ) : (
        <>
          {/* Existing rules */}
          <div className="space-y-2">
            {rules.length === 0 ? (
              <p className="text-sm text-ink-muted">No routing rules yet.</p>
            ) : (
              rules.map((rule) => (
                <div
                  key={rule.id}
                  className="flex items-center justify-between gap-4 rounded-lg border border-hairline p-3"
                >
                  <div className="text-sm">
                    <span className="font-medium text-ink">
                      {STAGE_LABEL[rule.trigger_stage] ?? rule.trigger_stage}
                    </span>
                    <span className="text-ink-muted"> &rarr; contract to </span>
                    <span className="text-ink">{rolesSummary(rule.recipient_roles)}</span>
                    {!rule.enabled && (
                      <span className="ml-2 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-muted">
                        Off
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <button
                      type="button"
                      onClick={() => toggleRule(rule)}
                      disabled={busyId === rule.id}
                      className="text-xs font-medium text-penny hover:underline disabled:opacity-50"
                    >
                      {rule.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeRule(rule.id)}
                      disabled={busyId === rule.id}
                      className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Add rule */}
          <div className="rounded-lg border border-dashed border-hairline p-4">
            <p className="mb-3 text-sm font-medium text-ink">Add a routing rule</p>
            <div className="flex flex-wrap items-end gap-4">
              <label className="text-xs text-ink-muted">
                When a deal enters
                <select
                  value={stage}
                  onChange={(e) => setStage(e.target.value)}
                  className="input mt-1 block"
                >
                  {ROUTING_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-3">
              <p className="mb-2 text-xs text-ink-muted">Send the contract to:</p>
              <div className="flex flex-wrap gap-2">
                {PARTY_ROLES.map((r) => {
                  const on = roles.includes(r.key)
                  return (
                    <button
                      key={r.key}
                      type="button"
                      onClick={() => toggleRole(r.key)}
                      className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                        on
                          ? 'border-penny bg-penny-light text-penny-dark'
                          : 'border-hairline text-ink-muted hover:border-penny'
                      }`}
                    >
                      {r.label}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="mt-4 flex justify-end">
              <button onClick={addRule} disabled={adding} className="btn-primary">
                {adding ? 'Adding…' : 'Add rule'}
              </button>
            </div>
          </div>

          {/* Pending send queue */}
          {pending.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-medium text-ink">Waiting for your approval</p>
              {pending.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-4 rounded-lg border border-amber-200 bg-amber-50 p-3"
                >
                  <div className="text-sm">
                    <span className="font-medium text-ink">
                      {STAGE_LABEL[p.trigger_stage] ?? p.trigger_stage}
                    </span>
                    <span className="text-ink-muted"> &rarr; contract to </span>
                    <span className="text-ink">
                      {p.recipient_emails.length
                        ? p.recipient_emails.join(', ')
                        : rolesSummary(p.recipient_roles)}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <button
                      type="button"
                      onClick={() => sendRoute(p.id)}
                      disabled={busyId === p.id}
                      className="btn-primary !px-3 !py-1 text-xs"
                    >
                      {busyId === p.id ? 'Sending…' : 'Send now'}
                    </button>
                    <button
                      type="button"
                      onClick={() => dismissRoute(p.id)}
                      disabled={busyId === p.id}
                      className="text-xs font-medium text-ink-muted hover:underline disabled:opacity-50"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
