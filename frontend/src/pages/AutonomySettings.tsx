import { useEffect, useState } from 'react'
import DocRoutingSettings from '../components/DocRoutingSettings'
import PennyBubble from '../components/PennyBubble'
import TaskToggle from '../components/TaskToggle'
import { autonomyApi, type TaskAutonomy } from '../lib/api'

export default function AutonomySettings() {
  const [tasks, setTasks] = useState<TaskAutonomy[]>([])
  const [autonomy, setAutonomy] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    autonomyApi
      .get()
      .then((d) => {
        setTasks(d.tasks)
        const map: Record<string, boolean> = {}
        for (const t of d.tasks) map[t.task_id] = t.locked ? false : t.autonomous
        setAutonomy(map)
      })
      .catch(() => setError('Could not load automation settings.'))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const d = await autonomyApi.update(
        tasks.map((t) => ({
          task_id: t.task_id,
          autonomous: t.locked ? false : !!autonomy[t.task_id],
        })),
      )
      setTasks(d.tasks)
      const map: Record<string, boolean> = {}
      for (const t of d.tasks) map[t.task_id] = t.locked ? false : t.autonomous
      setAutonomy(map)
      setSaved(true)
    } catch {
      setError('Could not save automation settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-6 py-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Autonomy</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Choose what Penny does on her own, and what she drafts for your approval.
        </p>
      </div>

      <PennyBubble>
        I&rsquo;ll act on my own for anything you switch on here. Everything else I&rsquo;ll draft
        and hold for your approval. Compliance review always needs a human, so it can&rsquo;t be
        automated.
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
          <section className="card space-y-3 p-6">
            {tasks.map((t) => (
              <TaskToggle
                key={t.task_id}
                task={t}
                value={t.locked ? false : !!autonomy[t.task_id]}
                onChange={(v) => {
                  setSaved(false)
                  setAutonomy((prev) => ({ ...prev, [t.task_id]: v }))
                }}
              />
            ))}
          </section>

          <div className="flex items-center justify-end gap-3">
            {saved && <span className="text-sm text-ink-muted">Saved.</span>}
            <button onClick={save} disabled={saving} className="btn-primary">
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>

          <DocRoutingSettings autonomous={!!autonomy['doc-routing']} />
        </>
      )}
    </div>
  )
}
