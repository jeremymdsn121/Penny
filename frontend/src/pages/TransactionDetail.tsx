import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Communications from '../components/Communications'
import ComplianceChecklist from '../components/ComplianceChecklist'
import EmdCard from '../components/EmdCard'
import PennyBubble from '../components/PennyBubble'
import SectionNav, { type SectionNavItem } from '../components/SectionNav'
import SignaturesCard from '../components/SignaturesCard'
import TaskPanel from '../components/TaskPanel'
import type { TransactionEmail } from '../lib/api'
import {
  appointmentsApi,
  deadlinesApi,
  PARTY_ROLES,
  transactionsApi,
  type Appointment,
  type CompsResult,
  type ComplianceReview,
  type Deadline,
  type ProposeResult,
  type PropertyRecord,
  type Transaction,
} from '../lib/api'

const SECTION_NAV: SectionNavItem[] = [
  { id: 'details', label: 'Details' },
  { id: 'deadlines', label: 'Deadlines' },
  { id: 'scheduling', label: 'Scheduling' },
  { id: 'emd', label: 'Earnest Money' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'checklist', label: 'Compliance File' },
  { id: 'compliance', label: 'Compliance Review' },
  { id: 'comps', label: 'Comparable Sales' },
  { id: 'comms', label: 'Communications' },
  { id: 'draft', label: 'Draft Document' },
  { id: 'signatures', label: 'Signatures' },
  { id: 'contract', label: 'Contract' },
]

function fmtMoney(v?: number | null): string {
  return typeof v === 'number' ? `$${Math.round(v).toLocaleString()}` : '—'
}

const PARTY_LABEL: Record<string, string> = Object.fromEntries(
  PARTY_ROLES.map((r) => [r.key, r.label]),
)

// --------------------------------------------------------------------------- //
// Field groups — same structure as NewTransaction for consistency
// --------------------------------------------------------------------------- //

const FIELD_GROUPS = [
  {
    label: 'Property',
    fields: [
      { key: 'address', label: 'Address' },
      { key: 'city', label: 'City' },
      { key: 'state', label: 'State' },
      { key: 'zip', label: 'ZIP' },
      { key: 'mls_number', label: 'MLS #' },
    ],
  },
  {
    label: 'Deal',
    fields: [
      { key: 'list_price', label: 'List Price' },
      { key: 'sale_price', label: 'Sale Price' },
      { key: 'financing', label: 'Financing' },
      { key: 'contract_date', label: 'Contract Date' },
      { key: 'closing_date', label: 'Closing Date' },
    ],
  },
  {
    label: 'Buyer',
    fields: [
      { key: 'buyer_name', label: 'Name' },
      { key: 'buyer_email', label: 'Email' },
      { key: 'buyer_phone', label: 'Phone' },
    ],
  },
  {
    label: 'Seller',
    fields: [
      { key: 'seller_name', label: 'Name' },
      { key: 'seller_email', label: 'Email' },
      { key: 'seller_phone', label: 'Phone' },
    ],
  },
  {
    label: 'Listing Agent',
    fields: [
      { key: 'listing_agent_name', label: 'Name' },
      { key: 'listing_agent_email', label: 'Email' },
    ],
  },
  {
    label: 'Selling Agent',
    fields: [
      { key: 'selling_agent_name', label: 'Name' },
      { key: 'selling_agent_email', label: 'Email' },
    ],
  },
  {
    label: 'Lender',
    fields: [
      { key: 'lender_name', label: 'Name' },
      { key: 'lender_email', label: 'Email' },
    ],
  },
  {
    label: 'Title',
    fields: [
      { key: 'title_company', label: 'Company' },
      { key: 'title_email', label: 'Email' },
    ],
  },
  {
    label: 'Transaction Coordinator',
    fields: [
      { key: 'tc_name', label: 'Name' },
      { key: 'tc_email', label: 'Email' },
    ],
  },
]

const STAGE_LABELS: Record<string, string> = {
  under_contract: 'Under Contract',
  pending: 'Pending',
  closed: 'Closed',
  cancelled: 'Cancelled',
}

const STAGE_COLORS: Record<string, string> = {
  under_contract: 'bg-blue-100 text-blue-700',
  pending: 'bg-yellow-100 text-yellow-700',
  closed: 'bg-green-100 text-green-700',
  cancelled: 'bg-surface-3 text-ink-muted',
}

const COMPLIANCE_STATUS: Record<string, { label: string; cls: string }> = {
  approved: { label: 'Approved', cls: 'bg-green-100 text-green-700' },
  needs_attention: { label: 'Needs attention', cls: 'bg-red-100 text-red-700' },
  not_reviewed: { label: 'Not reviewed', cls: 'bg-surface-3 text-ink-muted' },
}

const SEVERITY_CLS: Record<string, string> = {
  issue: 'bg-red-100 text-red-700',
  warning: 'bg-yellow-100 text-yellow-700',
  info: 'bg-surface-3 text-ink-muted',
}

const AI_STATUS_CLS: Record<string, string> = {
  satisfied: 'bg-green-100 text-green-700',
  missing: 'bg-red-100 text-red-700',
  unclear: 'bg-yellow-100 text-yellow-700',
  not_reviewed: 'bg-surface-3 text-ink-muted',
}

function StageBadge({ stage }: { stage?: string | null }) {
  const s = stage ?? 'under_contract'
  return (
    <span
      className={`inline-block rounded-full px-3 py-0.5 text-xs font-medium ${
        STAGE_COLORS[s] ?? 'bg-surface-3 text-ink-muted'
      }`}
    >
      {STAGE_LABELS[s] ?? s}
    </span>
  )
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

/** Flatten a Transaction row into a string map for controlled inputs */
function txToStrings(tx: Transaction): Record<string, string> {
  const result: Record<string, string> = {}
  const allKeys = FIELD_GROUPS.flatMap((g) => g.fields.map((f) => f.key))
  for (const key of allKeys) {
    const v = (tx as unknown as Record<string, unknown>)[key]
    result[key] = v != null ? String(v) : ''
  }
  result.stage = tx.stage ?? 'under_contract'
  return result
}

/** Build a Partial<Transaction> from form strings, dropping empty values */
function stringsToPayload(values: Record<string, string>): Partial<Transaction> {
  const PRICE_KEYS = new Set(['list_price', 'sale_price'])
  const payload: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(values)) {
    if (v === '' || v == null) {
      payload[k] = null // explicit null clears the field on PATCH
      continue
    }
    payload[k] = PRICE_KEYS.has(k) ? (parseFloat(v) || null) : v
  }
  return payload as Partial<Transaction>
}

// --------------------------------------------------------------------------- //
// Component
// --------------------------------------------------------------------------- //

export default function TransactionDetail() {
  const { transaction_id } = useParams<{ transaction_id: string }>()
  const navigate = useNavigate()

  const [tx, setTx] = useState<Transaction | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [editMode, setEditMode] = useState(false)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Document drafting
  const [docType, setDocType] = useState('status_update')
  const [docRecipient, setDocRecipient] = useState('')
  const [docInstructions, setDocInstructions] = useState('')
  const [generating, setGenerating] = useState(false)
  const [hasDraft, setHasDraft] = useState(false)
  const [draftSubject, setDraftSubject] = useState('')
  const [draftBody, setDraftBody] = useState('')
  const [toEmail, setToEmail] = useState('')
  const [confirmingSend, setConfirmingSend] = useState(false)
  const [sending, setSending] = useState(false)
  const [docError, setDocError] = useState<string | null>(null)
  const [docNotice, setDocNotice] = useState<string | null>(null)

  // Deadlines
  const [deadlines, setDeadlines] = useState<Deadline[]>([])
  const [dlLabel, setDlLabel] = useState('')
  const [dlDue, setDlDue] = useState('')
  const [dlParties, setDlParties] = useState<string[]>([])
  const [dlAdding, setDlAdding] = useState(false)
  const [dlError, setDlError] = useState<string | null>(null)
  const [dlNotice, setDlNotice] = useState<string | null>(null)
  const [confirmNotifyId, setConfirmNotifyId] = useState<string | null>(null)
  const [notifyBusyId, setNotifyBusyId] = useState<string | null>(null)

  // Compliance
  const [review, setReview] = useState<ComplianceReview | null>(null)
  const [compRunning, setCompRunning] = useState(false)
  const [compError, setCompError] = useState<string | null>(null)
  const [confirmDecision, setConfirmDecision] = useState<string | null>(null)
  const [decisionBusy, setDecisionBusy] = useState(false)

  // Comparable sales
  const [comps, setComps] = useState<CompsResult | null>(null)
  const [compsLoading, setCompsLoading] = useState(false)
  const [compsError, setCompsError] = useState<string | null>(null)
  // Property record + tax history (separate Rentcast call, quota-friendly)
  const [propRecord, setPropRecord] = useState<PropertyRecord | null>(null)
  const [propLoading, setPropLoading] = useState(false)
  const [propError, setPropError] = useState<string | null>(null)

  // Scheduling
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [proposal, setProposal] = useState<ProposeResult | null>(null)
  const [proposing, setProposing] = useState(false)
  const [selectedSlot, setSelectedSlot] = useState<string | null>(null)
  const [booking, setBooking] = useState(false)
  const [schedError, setSchedError] = useState<string | null>(null)
  const [schedNotice, setSchedNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!transaction_id) return
    transactionsApi
      .get(transaction_id)
      .then((data) => {
        setTx(data)
        setValues(txToStrings(data))
      })
      .catch(() => setError('Transaction not found.'))
      .finally(() => setLoading(false))
    deadlinesApi
      .list(transaction_id)
      .then(setDeadlines)
      .catch(() => {/* deadlines degrade silently */})
    appointmentsApi
      .list(transaction_id)
      .then(setAppointments)
      .catch(() => {/* appointments degrade silently */})
  }, [transaction_id])

  async function refreshDeadlines() {
    if (!transaction_id) return
    try {
      setDeadlines(await deadlinesApi.list(transaction_id))
    } catch {
      /* ignore */
    }
  }

  function toggleParty(key: string) {
    setDlParties((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  async function handleAddDeadline() {
    if (!tx || !dlLabel.trim() || !dlDue) return
    setDlAdding(true)
    setDlError(null)
    setDlNotice(null)
    try {
      await deadlinesApi.create({
        transaction_id: tx.id,
        label: dlLabel.trim(),
        due_date: dlDue,
        responsible_parties: dlParties,
      })
      setDlLabel('')
      setDlDue('')
      setDlParties([])
      await refreshDeadlines()
    } catch {
      setDlError('Could not add the deadline. Please try again.')
    } finally {
      setDlAdding(false)
    }
  }

  async function handleDeleteDeadline(id: string) {
    try {
      await deadlinesApi.remove(id)
      await refreshDeadlines()
    } catch {
      setDlError('Could not delete that deadline.')
    }
  }

  async function handleNotifyParties(id: string) {
    setNotifyBusyId(id)
    setDlError(null)
    setDlNotice(null)
    try {
      const res = await deadlinesApi.notifyParties(id, true)
      setDlNotice(`Notified ${res.recipients.length} part${res.recipients.length === 1 ? 'y' : 'ies'}.`)
      setConfirmNotifyId(null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setDlError(detail ?? 'Could not notify parties.')
    } finally {
      setNotifyBusyId(null)
    }
  }

  async function handleRunCompliance() {
    if (!tx) return
    setCompRunning(true)
    setCompError(null)
    try {
      setReview(await transactionsApi.complianceReview(tx.id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCompError(detail ?? 'Could not run the compliance review.')
    } finally {
      setCompRunning(false)
    }
  }

  async function handleDecision(status: string) {
    if (!tx) return
    setDecisionBusy(true)
    setCompError(null)
    try {
      const res = await transactionsApi.complianceDecision(tx.id, status, true)
      setTx({ ...tx, compliance_status: res.compliance_status })
      setConfirmDecision(null)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCompError(detail ?? 'Could not update compliance status.')
    } finally {
      setDecisionBusy(false)
    }
  }

  async function handleFindComps() {
    if (!tx) return
    setCompsLoading(true)
    setCompsError(null)
    try {
      setComps(await transactionsApi.comps(tx.id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCompsError(detail ?? 'Could not pull comparable sales.')
    } finally {
      setCompsLoading(false)
    }
  }

  async function handlePropertyRecord() {
    if (!tx) return
    setPropLoading(true)
    setPropError(null)
    try {
      setPropRecord(await transactionsApi.propertyRecord(tx.id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPropError(detail ?? 'Could not pull the property record.')
    } finally {
      setPropLoading(false)
    }
  }

  function fmtSlot(iso: string, tz?: string): string {
    try {
      return new Date(iso).toLocaleString('en-US', {
        timeZone: tz,
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
    } catch {
      return iso
    }
  }

  async function handleProposeSlots() {
    if (!tx) return
    setProposing(true)
    setSchedError(null)
    setSchedNotice(null)
    setSelectedSlot(null)
    try {
      setProposal(await appointmentsApi.propose({ transaction_id: tx.id, days: 7 }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSchedError(detail ?? 'Could not propose times.')
    } finally {
      setProposing(false)
    }
  }

  async function handleBook() {
    if (!tx || !selectedSlot) return
    setBooking(true)
    setSchedError(null)
    try {
      await appointmentsApi.book({
        transaction_id: tx.id,
        type: 'showing',
        scheduled_at: selectedSlot,
        confirmed: true,
      })
      setSchedNotice(`Booked for ${fmtSlot(selectedSlot, proposal?.timezone)}.`)
      setSelectedSlot(null)
      setProposal(null)
      setAppointments(await appointmentsApi.list(tx.id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSchedError(detail ?? 'Could not book the appointment.')
    } finally {
      setBooking(false)
    }
  }

  async function handleCancelAppointment(id: string) {
    try {
      await appointmentsApi.remove(id)
      if (tx) setAppointments(await appointmentsApi.list(tx.id))
    } catch {
      setSchedError('Could not cancel that appointment.')
    }
  }

  async function handleSave() {
    if (!tx) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await transactionsApi.update(tx.id, stringsToPayload(values))
      setTx(updated)
      setValues(txToStrings(updated))
      setEditMode(false)
    } catch {
      setSaveError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    if (tx) setValues(txToStrings(tx))
    setEditMode(false)
    setSaveError(null)
  }

  function handleReplyToEmail(email: TransactionEmail) {
    setDocType('follow_up')
    setDocRecipient(email.sender_name || email.sender_email || '')
    setDocInstructions(
      `Reply to this message: "${(email.body_text || '').slice(0, 400)}"`,
    )
    setToEmail(email.sender_email || '')
    setDocNotice('Reply prefilled below — generate, review, and send.')
  }

  async function handleGenerate() {
    if (!tx) return
    setGenerating(true)
    setDocError(null)
    setDocNotice(null)
    try {
      const draft = await transactionsApi.draftDocument(tx.id, {
        doc_type: docType,
        recipient: docRecipient.trim() || undefined,
        instructions: docInstructions.trim() || undefined,
      })
      setDraftSubject(draft.subject)
      setDraftBody(draft.body)
      setHasDraft(true)
      setConfirmingSend(false)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail
      setDocError(detail ?? 'Could not generate the draft.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleSend() {
    if (!tx) return
    setSending(true)
    setDocError(null)
    try {
      await transactionsApi.sendDocument(tx.id, {
        to_emails: [toEmail.trim()],
        subject: draftSubject,
        body: draftBody,
        confirmed: true,
      })
      setDocNotice(`Sent to ${toEmail.trim()}.`)
      setConfirmingSend(false)
      setHasDraft(false)
      setDraftSubject('')
      setDraftBody('')
      setToEmail('')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
        ?.detail
      setDocError(detail ?? 'Could not send. Check the email address and that SendGrid is configured.')
    } finally {
      setSending(false)
    }
  }

  // ---------- loading / error ----------
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-2">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-penny border-t-transparent" />
      </div>
    )
  }

  if (error || !tx) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-surface-2 text-center">
        <p className="text-sm text-ink-muted">{error ?? 'Transaction not found.'}</p>
        <button
          onClick={() => navigate('/dashboard')}
          className="text-sm font-medium text-penny hover:underline"
        >
          Back to Dashboard
        </button>
      </div>
    )
  }

  const title = tx.address || 'Transaction'

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {!editMode && <StageBadge stage={tx.stage} />}
        </div>
        <div className="shrink-0">
          {editMode ? (
            <div className="flex items-center gap-3">
              <button
                onClick={handleCancel}
                className="text-sm font-medium text-ink-muted hover:text-ink"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="btn-primary flex items-center gap-2"
              >
                {saving && (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                )}
                Save
              </button>
            </div>
          ) : (
            <button onClick={() => setEditMode(true)} className="btn-secondary">
              Edit
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-8">
        {!editMode && <SectionNav items={SECTION_NAV} />}
        <div className="min-w-0 flex-1 space-y-6">
        {!editMode && (
          <PennyBubble>
            {tx.closing_date
              ? `Closing on ${tx.closing_date}. Let me know if you need anything.`
              : `Here are the details for this transaction. Hit Edit to update any field.`}
          </PennyBubble>
        )}

        {saveError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {saveError}
          </div>
        )}

        {/* Stage (edit mode only) */}
        {editMode && (
          <div className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">Stage</h3>
            <select
              value={values.stage ?? 'under_contract'}
              onChange={(e) => setValues((p) => ({ ...p, stage: e.target.value }))}
              className="input max-w-xs"
            >
              <option value="under_contract">Under Contract</option>
              <option value="pending">Pending</option>
              <option value="closed">Closed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        )}

        {/* Field groups */}
        <section id="details" data-section className="space-y-6">
        {FIELD_GROUPS.map((group) => (
          <div
            key={group.label}
            className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm"
          >
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              {group.label}
            </h3>
            {editMode ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {group.fields.map(({ key, label }) => (
                  <div key={key}>
                    <label className="mb-1 block text-xs font-medium text-ink-muted">{label}</label>
                    <input
                      type="text"
                      value={values[key] ?? ''}
                      onChange={(e) => setValues((p) => ({ ...p, [key]: e.target.value }))}
                      className="input"
                    />
                  </div>
                ))}
              </div>
            ) : (
              <dl className="grid gap-y-3 sm:grid-cols-2">
                {group.fields.map(({ key, label }) => {
                  const v = (tx as unknown as Record<string, unknown>)[key]
                  const display = v != null && v !== '' ? String(v) : '—'
                  return (
                    <div key={key} className="sm:contents">
                      <dt className="text-xs font-medium text-ink-muted">{label}</dt>
                      <dd className="text-sm text-ink">{display}</dd>
                    </div>
                  )
                })}
              </dl>
            )}
          </div>
        ))}
        </section>

        {/* Deadlines */}
        {!editMode && (
          <div id="deadlines" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Deadlines
            </h3>
            <p className="mb-4 text-xs text-ink-subtle">
              Penny reminds you at the 5-day, 2-day, and day-of marks. Responsible parties
              are notified automatically only if you've made deadline reminders autonomous —
              otherwise use “Notify parties” to confirm and send.
            </p>

            {dlError && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {dlError}
              </div>
            )}
            {dlNotice && (
              <div className="mb-3 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
                {dlNotice}
              </div>
            )}

            {deadlines.length === 0 ? (
              <p className="mb-4 text-sm text-ink-subtle">No deadlines tracked yet.</p>
            ) : (
              <ul className="mb-5 divide-y divide-hairline">
                {deadlines.map((d) => {
                  const sent = [
                    d.reminder_5day_sent && '5-day',
                    d.reminder_2day_sent && '2-day',
                    d.reminder_day_sent && 'day-of',
                  ].filter(Boolean) as string[]
                  const parties = (d.responsible_parties ?? []).map(
                    (k) => PARTY_LABEL[k] ?? k,
                  )
                  return (
                    <li key={d.id} className="py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-ink">{d.label}</p>
                          <p className="mt-0.5 text-xs text-ink-muted">
                            Due {d.due_date || '—'}
                            {parties.length > 0 && <> · Parties: {parties.join(', ')}</>}
                          </p>
                          {sent.length > 0 && (
                            <p className="mt-1 text-xs text-violet-600">
                              Reminders sent: {sent.join(', ')}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-3">
                          {parties.length > 0 &&
                            (confirmNotifyId === d.id ? (
                              <span className="flex items-center gap-2">
                                <button
                                  onClick={() => handleNotifyParties(d.id)}
                                  disabled={notifyBusyId === d.id}
                                  className="text-xs font-medium text-violet-700 hover:underline disabled:opacity-50"
                                >
                                  Confirm
                                </button>
                                <button
                                  onClick={() => setConfirmNotifyId(null)}
                                  className="text-xs font-medium text-ink-subtle hover:text-ink"
                                >
                                  Cancel
                                </button>
                              </span>
                            ) : (
                              <button
                                onClick={() => setConfirmNotifyId(d.id)}
                                className="text-xs font-medium text-penny hover:underline"
                              >
                                Notify parties
                              </button>
                            ))}
                          <button
                            onClick={() => handleDeleteDeadline(d.id)}
                            className="text-xs font-medium text-ink-subtle hover:text-red-600"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}

            <div className="border-t border-hairline pt-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink-muted">Label</label>
                  <input
                    type="text"
                    value={dlLabel}
                    onChange={(e) => setDlLabel(e.target.value)}
                    placeholder="e.g. Inspection contingency"
                    className="input"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink-muted">Due date</label>
                  <input
                    type="date"
                    value={dlDue}
                    onChange={(e) => setDlDue(e.target.value)}
                    className="input"
                  />
                </div>
              </div>
              <div className="mt-3">
                <label className="mb-1 block text-xs font-medium text-ink-muted">
                  Responsible parties (optional)
                </label>
                <div className="flex flex-wrap gap-2">
                  {PARTY_ROLES.map((r) => {
                    const on = dlParties.includes(r.key)
                    return (
                      <button
                        key={r.key}
                        type="button"
                        onClick={() => toggleParty(r.key)}
                        className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                          on
                            ? 'border-violet-300 bg-violet-50 text-violet-700'
                            : 'border-hairline text-ink-muted hover:border-hairline'
                        }`}
                      >
                        {r.label}
                      </button>
                    )
                  })}
                </div>
              </div>
              <button
                onClick={handleAddDeadline}
                disabled={dlAdding || !dlLabel.trim() || !dlDue}
                className="btn-primary mt-3 flex items-center gap-2 disabled:opacity-50"
              >
                {dlAdding && (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                )}
                Add deadline
              </button>
            </div>
          </div>
        )}

        {/* Scheduling */}
        {!editMode && (
          <div id="scheduling" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Scheduling
            </h3>
            <p className="mb-4 text-xs text-ink-subtle">
              Penny proposes open times from your working hours and books showings or
              inspections. Calendar sync isn’t connected yet — times reflect your hours and
              existing appointments.
            </p>

            {schedError && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {schedError}
              </div>
            )}
            {schedNotice && (
              <div className="mb-3 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
                {schedNotice}
              </div>
            )}

            {appointments.length > 0 && (
              <ul className="mb-5 divide-y divide-hairline">
                {appointments.map((a) => (
                  <li key={a.id} className="flex items-center justify-between py-3">
                    <div>
                      <p className="text-sm font-medium capitalize text-ink">
                        {(a.type ?? 'appointment').replace('_', ' ')}
                      </p>
                      <p className="mt-0.5 text-xs text-ink-muted">
                        {a.scheduled_at ? fmtSlot(a.scheduled_at) : 'Time TBD'}
                        {a.calendar_event_id ? ' · on calendar' : ''}
                      </p>
                    </div>
                    <button
                      onClick={() => handleCancelAppointment(a.id)}
                      className="text-xs font-medium text-ink-subtle hover:text-red-600"
                    >
                      Cancel
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <button
              onClick={handleProposeSlots}
              disabled={proposing}
              className="btn-primary flex items-center gap-2"
            >
              {proposing && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {proposing ? 'Finding times…' : 'Propose times'}
            </button>

            {proposal && (
              <div className="mt-5 border-t border-hairline pt-5">
                {proposal.slots.length === 0 ? (
                  <p className="text-sm text-ink-subtle">
                    No open times in your working hours over the next week.
                  </p>
                ) : (
                  <>
                    <p className="mb-2 text-xs font-medium text-ink-muted">
                      Pick a time ({proposal.timezone}):
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {proposal.slots.map((slot) => (
                        <button
                          key={slot}
                          onClick={() => setSelectedSlot(slot)}
                          className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                            selectedSlot === slot
                              ? 'border-violet-300 bg-violet-50 text-violet-700'
                              : 'border-hairline text-ink-muted hover:border-hairline'
                          }`}
                        >
                          {fmtSlot(slot, proposal.timezone)}
                        </button>
                      ))}
                    </div>
                    {selectedSlot && (
                      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3">
                        <span className="text-sm text-violet-800">
                          Book a showing for{' '}
                          <strong>{fmtSlot(selectedSlot, proposal.timezone)}</strong>?
                        </span>
                        <button
                          onClick={handleBook}
                          disabled={booking}
                          className="btn-primary flex items-center gap-2"
                        >
                          {booking && (
                            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                          )}
                          Confirm booking
                        </button>
                        <button
                          onClick={() => setSelectedSlot(null)}
                          className="text-sm font-medium text-ink-muted hover:text-ink"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* Earnest money deposit */}
        {!editMode && tx && (
          <section id="emd" data-section>
            <EmdCard tx={tx} onChange={setTx} />
          </section>
        )}

        {/* Tasks (workflow) */}
        {!editMode && tx && (
          <section id="tasks" data-section>
            <TaskPanel txId={tx.id} />
          </section>
        )}

        {/* Compliance File (document checklist) */}
        {!editMode && tx && (
          <section id="checklist" data-section>
            <ComplianceChecklist txId={tx.id} />
          </section>
        )}

        {/* Compliance review */}
        {!editMode && (
          <div id="compliance" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Compliance review
              </h3>
              {(() => {
                const s = COMPLIANCE_STATUS[tx.compliance_status ?? 'not_reviewed'] ??
                  COMPLIANCE_STATUS.not_reviewed
                return (
                  <span className={`rounded-full px-3 py-0.5 text-xs font-medium ${s.cls}`}>
                    {s.label}
                  </span>
                )
              })()}
            </div>
            <p className="mb-4 text-xs text-ink-subtle">
              Penny surfaces findings to verify — she never approves compliance. A human
              must review and sign off below.
            </p>

            {compError && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {compError}
              </div>
            )}

            <button
              onClick={handleRunCompliance}
              disabled={compRunning}
              className="btn-primary flex items-center gap-2"
            >
              {compRunning && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {compRunning ? 'Reviewing…' : review ? 'Re-run review' : 'Run compliance review'}
            </button>

            {review && (
              <div className="mt-5 space-y-5 border-t border-hairline pt-5">
                <p className="text-sm text-ink-muted">
                  <strong>{review.counts.issue}</strong> issue
                  {review.counts.issue !== 1 ? 's' : ''}, <strong>{review.counts.warning}</strong>{' '}
                  warning{review.counts.warning !== 1 ? 's' : ''} · {review.ruleset_state} checklist
                  {review.contract_reviewed
                    ? ' · contract reviewed'
                    : ' · contract not AI-reviewed'}
                </p>
                {review.ai_error && (
                  <p className="rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
                    {review.ai_error}
                  </p>
                )}

                {/* Findings */}
                {review.findings.length > 0 && (
                  <div>
                    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
                      Findings
                    </h4>
                    <ul className="space-y-2">
                      {[...review.findings]
                        .sort((a, b) => {
                          const order = { issue: 0, warning: 1, info: 2 }
                          return order[a.severity] - order[b.severity]
                        })
                        .map((f, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <span
                              className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                                SEVERITY_CLS[f.severity] ?? SEVERITY_CLS.info
                              }`}
                            >
                              {f.severity}
                            </span>
                            <span className="text-ink">{f.message}</span>
                          </li>
                        ))}
                    </ul>
                  </div>
                )}

                {/* State checklist */}
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
                    {review.ruleset_state} checklist
                  </h4>
                  <ul className="space-y-2">
                    {review.checklist.map((item) => (
                      <li key={item.id} className="flex items-start gap-2 text-sm">
                        <span
                          className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                            AI_STATUS_CLS[item.ai_status] ?? AI_STATUS_CLS.not_reviewed
                          }`}
                        >
                          {item.ai_status.replace('_', ' ')}
                        </span>
                        <span className="text-ink">
                          {item.requirement}
                          {item.ai_note && (
                            <span className="text-ink-subtle"> — {item.ai_note}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <p className="text-xs text-ink-subtle">{review.disclaimer}</p>

                {/* Human decision */}
                <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
                  {confirmDecision ? (
                    <>
                      <span className="text-sm text-ink">
                        Set compliance to{' '}
                        <strong>
                          {COMPLIANCE_STATUS[confirmDecision]?.label ?? confirmDecision}
                        </strong>
                        ?
                      </span>
                      <button
                        onClick={() => handleDecision(confirmDecision)}
                        disabled={decisionBusy}
                        className="btn-primary flex items-center gap-2"
                      >
                        {decisionBusy && (
                          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                        )}
                        Confirm
                      </button>
                      <button
                        onClick={() => setConfirmDecision(null)}
                        className="text-sm font-medium text-ink-muted hover:text-ink"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setConfirmDecision('approved')}
                        className="rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100"
                      >
                        Approve compliance
                      </button>
                      <button
                        onClick={() => setConfirmDecision('needs_attention')}
                        className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
                      >
                        Flag for attention
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Comparable sales */}
        {!editMode && (
          <div id="comps" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Comparable sales
            </h3>
            <p className="mb-4 text-xs text-ink-subtle">
              Penny pulls recent comps and an estimated value for this property. Figures are
              estimates from Rentcast.
            </p>

            {compsError && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {compsError}
              </div>
            )}

            <button
              onClick={handleFindComps}
              disabled={compsLoading}
              className="btn-primary flex items-center gap-2"
            >
              {compsLoading && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {compsLoading ? 'Finding comps…' : comps ? 'Refresh comps' : 'Find comps'}
            </button>

            {comps && (
              <div className="mt-5 space-y-4 border-t border-hairline pt-5">
                {comps.estimate != null && (
                  <div>
                    <p className="text-2xl font-semibold text-ink">
                      {fmtMoney(comps.estimate)}
                    </p>
                    {comps.range_low != null && comps.range_high != null && (
                      <p className="text-xs text-ink-subtle">
                        Estimated range {fmtMoney(comps.range_low)} – {fmtMoney(comps.range_high)}
                      </p>
                    )}
                  </div>
                )}

                {comps.comparables.length === 0 ? (
                  <p className="text-sm text-ink-subtle">
                    No comparable properties came back for this address.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="text-xs uppercase tracking-wide text-ink-subtle">
                          <th className="pb-2 pr-3 font-medium">Address</th>
                          <th className="pb-2 pr-3 font-medium">Price</th>
                          <th className="pb-2 pr-3 font-medium">Bd/Ba</th>
                          <th className="pb-2 pr-3 font-medium">Sqft</th>
                          <th className="pb-2 font-medium">Dist.</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-hairline">
                        {comps.comparables.map((c, i) => (
                          <tr key={i} className="text-ink">
                            <td className="py-2 pr-3">{c.address ?? '—'}</td>
                            <td className="py-2 pr-3 font-medium">{fmtMoney(c.price)}</td>
                            <td className="py-2 pr-3 text-ink-muted">
                              {c.bedrooms ?? '—'}/{c.bathrooms ?? '—'}
                            </td>
                            <td className="py-2 pr-3 text-ink-muted">
                              {c.square_footage != null
                                ? c.square_footage.toLocaleString()
                                : '—'}
                            </td>
                            <td className="py-2 text-ink-muted">
                              {c.distance != null ? `${c.distance.toFixed(1)} mi` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Property record + tax history (separate Rentcast call) */}
            <div className="mt-6 border-t border-hairline pt-5">
              <p className="mb-3 text-xs text-ink-subtle">
                Pull the public record — last sale, structure, and assessed-value / property-tax
                history from the county assessor.
              </p>

              {propError && (
                <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                  {propError}
                </div>
              )}

              <button
                onClick={handlePropertyRecord}
                disabled={propLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-hairline bg-surface px-4 py-2 text-sm font-medium text-ink hover:bg-surface-3 disabled:opacity-50"
              >
                {propLoading && (
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-subtle border-t-transparent" />
                )}
                {propLoading
                  ? 'Loading record…'
                  : propRecord
                    ? 'Refresh property & tax history'
                    : 'Property & tax history'}
              </button>

              {propRecord && (
                <div className="mt-5 space-y-5">
                  <dl className="grid grid-cols-2 gap-y-2 text-sm sm:grid-cols-4">
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-subtle">Last sale</dt>
                      <dd className="text-ink">
                        {propRecord.last_sale_price != null
                          ? fmtMoney(propRecord.last_sale_price)
                          : '—'}
                        {propRecord.last_sale_date
                          ? ` · ${propRecord.last_sale_date.slice(0, 10)}`
                          : ''}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-subtle">Year built</dt>
                      <dd className="text-ink">{propRecord.year_built ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-subtle">Sqft</dt>
                      <dd className="text-ink">
                        {propRecord.square_footage != null
                          ? propRecord.square_footage.toLocaleString()
                          : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wide text-ink-subtle">Lot size</dt>
                      <dd className="text-ink">
                        {propRecord.lot_size != null
                          ? `${propRecord.lot_size.toLocaleString()} sqft`
                          : '—'}
                      </dd>
                    </div>
                  </dl>

                  <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                    Assessed values are set by the county for tax purposes and are{' '}
                    <strong>not market value</strong> — use the estimate above for valuation.
                  </p>

                  {propRecord.tax_assessments.length > 0 && (
                    <div className="overflow-x-auto">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                        Assessment history
                      </p>
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="text-xs uppercase tracking-wide text-ink-subtle">
                            <th className="pb-2 pr-3 font-medium">Year</th>
                            <th className="pb-2 pr-3 font-medium">Assessed</th>
                            <th className="pb-2 pr-3 font-medium">Land</th>
                            <th className="pb-2 font-medium">Improvements</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-hairline">
                          {propRecord.tax_assessments.map((a, i) => (
                            <tr key={i} className="text-ink">
                              <td className="py-2 pr-3 text-ink-muted">{a.year ?? '—'}</td>
                              <td className="py-2 pr-3 font-medium">{fmtMoney(a.value)}</td>
                              <td className="py-2 pr-3 text-ink-muted">{fmtMoney(a.land)}</td>
                              <td className="py-2 text-ink-muted">{fmtMoney(a.improvements)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {propRecord.property_taxes.length > 0 && (
                    <div className="overflow-x-auto">
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                        Property tax history
                      </p>
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="text-xs uppercase tracking-wide text-ink-subtle">
                            <th className="pb-2 pr-3 font-medium">Year</th>
                            <th className="pb-2 font-medium">Annual tax</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-hairline">
                          {propRecord.property_taxes.map((t, i) => (
                            <tr key={i} className="text-ink">
                              <td className="py-2 pr-3 text-ink-muted">{t.year ?? '—'}</td>
                              <td className="py-2 font-medium">{fmtMoney(t.total)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Communications (email thread) */}
        {!editMode && tx && (
          <section id="comms" data-section>
            <Communications txId={tx.id} onReply={handleReplyToEmail} />
          </section>
        )}

        {/* Draft a document */}
        {!editMode && (
          <div id="draft" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Draft a document
            </h3>
            <p className="mb-4 text-xs text-ink-subtle">
              Penny drafts in your brand voice using your confirmed Brand &amp; Style rules.
              Review before sending.
            </p>

            {docError && (
              <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
                {docError}
              </div>
            )}
            {docNotice && (
              <div className="mb-3 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm text-green-700">
                {docNotice}
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-ink-muted">Type</label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="input"
                >
                  <option value="status_update">Status update</option>
                  <option value="cover_letter">Cover letter</option>
                  <option value="follow_up">Follow-up</option>
                  <option value="congratulations">Congratulations</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-ink-muted">
                  Recipient (optional)
                </label>
                <input
                  type="text"
                  value={docRecipient}
                  onChange={(e) => setDocRecipient(e.target.value)}
                  placeholder="e.g. the buyer, the lender"
                  className="input"
                />
              </div>
            </div>
            <div className="mt-3">
              <label className="mb-1 block text-xs font-medium text-ink-muted">
                Instructions (optional)
              </label>
              <textarea
                value={docInstructions}
                onChange={(e) => setDocInstructions(e.target.value)}
                rows={2}
                placeholder="Anything specific to include…"
                className="input"
              />
            </div>
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="btn-primary mt-3 flex items-center gap-2"
            >
              {generating && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {generating ? 'Drafting…' : hasDraft ? 'Regenerate' : 'Generate draft'}
            </button>

            {hasDraft && (
              <div className="mt-5 border-t border-hairline pt-5">
                <label className="mb-1 block text-xs font-medium text-ink-muted">Subject</label>
                <input
                  type="text"
                  value={draftSubject}
                  onChange={(e) => setDraftSubject(e.target.value)}
                  className="input"
                />
                <label className="mb-1 mt-3 block text-xs font-medium text-ink-muted">Body</label>
                <textarea
                  value={draftBody}
                  onChange={(e) => setDraftBody(e.target.value)}
                  rows={12}
                  className="input text-sm"
                />
                <div className="mt-4 max-w-sm">
                  <label className="mb-1 block text-xs font-medium text-ink-muted">
                    Send to (email)
                  </label>
                  <input
                    type="email"
                    value={toEmail}
                    onChange={(e) => setToEmail(e.target.value)}
                    placeholder="recipient@example.com"
                    className="input"
                  />
                </div>
                {!confirmingSend ? (
                  <button
                    onClick={() => setConfirmingSend(true)}
                    disabled={!toEmail.trim()}
                    className="btn-primary mt-3 disabled:opacity-50"
                  >
                    Send…
                  </button>
                ) : (
                  <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3">
                    <span className="text-sm text-violet-800">
                      Send this to <strong>{toEmail.trim()}</strong>?
                    </span>
                    <button
                      onClick={handleSend}
                      disabled={sending}
                      className="btn-primary flex items-center gap-2"
                    >
                      {sending && (
                        <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      )}
                      Confirm send
                    </button>
                    <button
                      onClick={() => setConfirmingSend(false)}
                      className="text-sm font-medium text-ink-muted hover:text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Signatures (DocuSign seam) */}
        {!editMode && tx && (
          <section id="signatures" data-section>
            <SignaturesCard tx={tx} />
          </section>
        )}

        {/* Contract PDF */}
        {tx.contract_pdf_url && (
          <div id="contract" data-section className="rounded-2xl border border-hairline bg-surface p-6 shadow-sm">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">Contract</h3>
            <p className="truncate text-xs text-ink-subtle">{tx.contract_pdf_url}</p>
          </div>
        )}

          <div className="pb-10" />
        </div>
      </div>
    </div>
  )
}
