import { useEffect, useState } from 'react'
import { tasksApi, type TransactionTask } from '../lib/api'

function isOverdue(t: TransactionTask): boolean {
  if (t.status !== 'pending' || !t.due_date) return false
  return new Date(t.due_date) < new Date(new Date().toDateString())
}

const ROLE_LABEL: Record<string, string> = {
  agent: 'Agent',
  admin: 'Admin',
  buyer: 'Buyer',
  seller: 'Seller',
  lender: 'Lender',
  title: 'Title',
}

export default function TaskPanel({ txId }: { txId: string }) {
  const [tasks, setTasks] = useState<TransactionTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [newDue, setNewDue] = useState('')
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    let ignore = false
    setLoading(true)
    tasksApi
      .list(txId)
      .then((d) => { if (!ignore) setTasks(d) })
      .catch(() => { if (!ignore) setError('Could not load tasks.') })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [txId])

  async function setStatus(task: TransactionTask, status: string) {
    const updated = await tasksApi.patch(txId, task.id, { status })
    setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)))
  }

  async function remove(id: string) {
    await tasksApi.remove(txId, id)
    setTasks((prev) => prev.filter((t) => t.id !== id))
  }

  async function addTask() {
    if (!newLabel.trim()) return
    setAdding(true)
    try {
      const t = await tasksApi.add(txId, {
        label: newLabel.trim(),
        due_date: newDue || undefined,
      })
      setTasks((prev) => [...prev, t])
      setNewLabel('')
      setNewDue('')
    } catch {
      setError('Could not add task.')
    } finally {
      setAdding(false)
    }
  }

  const pending = tasks.filter((t) => t.status === 'pending')
  const done = tasks.filter((t) => t.status !== 'pending')

  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-gray-500">Tasks</h3>
      <p className="mb-4 text-xs text-gray-400">
        Penny generates these as the deal progresses — what needs to happen next.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="py-4 text-sm text-gray-400">Loading…</p>
      ) : (
        <>
          {pending.length === 0 ? (
            <p className="py-2 text-sm text-gray-400">No pending tasks.</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {pending.map((t) => (
                <li key={t.id} className="flex items-start justify-between gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-gray-800">{t.label}</p>
                    <p className="mt-0.5 text-xs">
                      {t.due_date && (
                        <span className={isOverdue(t) ? 'font-medium text-red-600' : 'text-gray-400'}>
                          Due {t.due_date}
                          {isOverdue(t) ? ' · overdue' : ''}
                        </span>
                      )}
                      {t.assigned_to_role && (
                        <span className="text-gray-400">
                          {t.due_date ? '  ·  ' : ''}
                          {ROLE_LABEL[t.assigned_to_role] ?? t.assigned_to_role}
                        </span>
                      )}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => setStatus(t, 'complete')}
                      className="text-xs font-semibold text-penny hover:underline"
                    >
                      Done
                    </button>
                    <button
                      onClick={() => setStatus(t, 'skipped')}
                      className="text-xs font-medium text-gray-400 hover:text-gray-700"
                    >
                      Skip
                    </button>
                    {!t.step_id && (
                      <button
                        onClick={() => remove(t.id)}
                        className="text-xs font-medium text-gray-300 hover:text-red-600"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {done.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-gray-400">
                {done.length} completed / skipped
              </summary>
              <ul className="mt-2 space-y-1">
                {done.map((t) => (
                  <li key={t.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-gray-400 line-through">{t.label}</span>
                    <button
                      onClick={() => setStatus(t, 'pending')}
                      className="text-gray-400 hover:text-gray-700"
                    >
                      Reopen
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="mt-4 flex items-center gap-2 border-t border-gray-100 pt-4">
            <input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Add a task…"
              className="input flex-1"
            />
            <input
              type="date"
              value={newDue}
              onChange={(e) => setNewDue(e.target.value)}
              className="input w-40"
            />
            <button
              onClick={addTask}
              disabled={!newLabel.trim() || adding}
              className="btn-primary disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </>
      )}
    </div>
  )
}
