import { type TaskDefinition } from '../lib/api'

// A single task row with a switch. `locked` tasks (compliance) show a static
// "Always needs approval" badge and can't be toggled. Shared by the onboarding
// wizard and the Automation settings page.
export default function TaskToggle({
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
