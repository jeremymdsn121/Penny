// Date-only helpers. The backend stores date-only fields as YYYY-MM-DD strings;
// `new Date('YYYY-MM-DD')` parses them as UTC MIDNIGHT, which is "yesterday
// evening" everywhere west of UTC — so naive comparisons mark a task due today
// as overdue, and `toISOString()` after 5-7pm local yields tomorrow's date.
// Everything here works in the user's local calendar instead.

/** Today's date as a local-calendar YYYY-MM-DD string. */
export function todayLocalISO(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** Parse a YYYY-MM-DD (or full ISO) string as LOCAL midnight of that calendar day. */
export function parseLocalDate(dateStr?: string | null): Date | null {
  if (!dateStr) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr)
  if (!m) {
    const d = new Date(dateStr)
    return isNaN(d.getTime()) ? null : d
  }
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

/** Whole calendar days from today (local) until the given date. 0 = today, negative = past. */
export function daysUntil(dateStr?: string | null): number | null {
  const d = parseLocalDate(dateStr)
  if (!d) return null
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}
