import axios from 'axios'

// Token lives in a module variable so this file has no dependency on the store
// (the store calls setAuthToken on login/logout/rehydrate). Avoids a cycle.
let authToken: string | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

// Registered by the auth store: exchanges the stored refresh token for a new
// session and returns the fresh access token (null when refresh fails). Lives
// behind a callback for the same no-cycle reason as setAuthToken.
let refreshHandler: (() => Promise<string | null>) | null = null

export function setRefreshHandler(fn: (() => Promise<string | null>) | null): void {
  refreshHandler = fn
}

// Single in-flight refresh shared by all 401s that race in together.
let refreshing: Promise<string | null> | null = null

// In dev, the base is '/api/v1' and Vite proxies it to the local backend. In a
// deployed static build there's no proxy, so VITE_API_BASE_URL points at the
// backend's public origin (e.g. "https://api.poweredbypenny.com/api/v1").
// The raw fetch() calls below (multipart uploads, blob downloads) can't go
// through the axios instance — they MUST build URLs from this same base or
// they 404 against the static host in deployed builds.
const API_BASE: string = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`
  }
  return config
})

// When the server returns 401, the access token has likely expired (Supabase
// tokens last ~an hour) — try a silent refresh and retry the request once
// before giving up and redirecting to login. Auth endpoints are exempt: a
// failed login/signup is itself a 401, and reloading /login here wiped the
// "Invalid email or password" message before the user could see it.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const cfg = error.config ?? {}
    const url: string = cfg.url ?? ''
    const isAuthEndpoint =
      url === '/auth/login' || url === '/auth/signup' || url === '/auth/refresh'
    if (error.response?.status !== 401 || isAuthEndpoint) {
      return Promise.reject(error)
    }
    if (refreshHandler && !cfg._retriedAfterRefresh) {
      refreshing = refreshing ?? refreshHandler().finally(() => (refreshing = null))
      const newToken = await refreshing
      if (newToken) {
        cfg._retriedAfterRefresh = true
        cfg.headers = { ...cfg.headers, Authorization: `Bearer ${newToken}` }
        return api.request(cfg)
      }
    }
    // Refresh unavailable or failed — the session is really over.
    authToken = null
    // Wipe the persisted Zustand store so ProtectedRoute redirects properly.
    localStorage.removeItem('penny-auth')
    window.location.href = '/login'
    return Promise.reject(error)
  },
)

export interface Brokerage {
  id: string
  name: string
  assistant_name?: string | null
  state?: string | null
  email?: string | null
  phone?: string | null
  subscription_tier?: string | null
  onboarding_completed: boolean
  email_mode?: string | null
  monitor_email?: string | null
  calendar_provider?: string | null
  work_start?: string | null
  work_end?: string | null
  buffer_minutes?: number | null
  showing_method?: string | null
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in?: number | null
  brokerage: Brokerage
}

export interface SignupData {
  email: string
  password: string
  brokerage_name: string
}

export const authApi = {
  signup: (data: SignupData) =>
    api.post<AuthResponse>('/auth/signup', data).then((r) => r.data),
  login: (email: string, password: string) =>
    api.post<AuthResponse>('/auth/login', { email, password }).then((r) => r.data),
  // GoTrue rotates the refresh token on every exchange — persist BOTH tokens.
  refresh: (refresh_token: string) =>
    api
      .post<{ access_token: string; refresh_token: string; expires_in?: number }>(
        '/auth/refresh',
        { refresh_token },
      )
      .then((r) => r.data),
  logout: () => api.post('/auth/logout'),
  me: () => api.get<Brokerage>('/auth/me').then((r) => r.data),
}

export interface StateOption {
  code: string
  name: string
}

export interface TaskDefinition {
  task_id: string
  label: string
  description: string
  default_autonomous: boolean
  locked: boolean
}

export interface OnboardingOptions {
  states: StateOption[]
  detailed_ruleset_states: string[]
  tasks: TaskDefinition[]
}

export interface OnboardingSubmitData {
  state: string
  assistant_name: string
  name: string
  email?: string | null
  phone?: string | null
  email_mode: 'own' | 'monitor'
  monitor_email?: string | null
  calendar_provider?: 'google' | 'outlook' | null
  work_start: string
  work_end: string
  buffer_minutes: number
  showing_method: 'email' | 'showingtime'
  tasks: { task_id: string; autonomous: boolean }[]
}

export const onboardingApi = {
  options: () => api.get<OnboardingOptions>('/onboarding/options').then((r) => r.data),
  submit: (data: OnboardingSubmitData) =>
    api.post<Brokerage>('/onboarding', data).then((r) => r.data),
}

// A task definition joined with this brokerage's current autonomy flag.
export interface TaskAutonomy extends TaskDefinition {
  autonomous: boolean
}

export const autonomyApi = {
  get: () => api.get<{ tasks: TaskAutonomy[] }>('/autonomy').then((r) => r.data),
  update: (tasks: { task_id: string; autonomous: boolean }[]) =>
    api.put<{ tasks: TaskAutonomy[] }>('/autonomy', { tasks }).then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Calendar (Google) connection — brokerage + per-agent
// --------------------------------------------------------------------------- //

export interface CalendarAgentStatus {
  id: string
  name?: string | null
  email?: string | null
  provider?: string | null
  connected: boolean
}

export interface CalendarStatus {
  oauth_configured: boolean
  brokerage: { provider: string | null; connected: boolean; sync_enabled: boolean }
  agents: CalendarAgentStatus[]
}

export const calendarApi = {
  status: () => api.get<CalendarStatus>('/calendar/status').then((r) => r.data),
  // Returns the Google consent URL; redirect the admin to it, or copy it to send
  // to the agent so they sign into their own Google.
  connectUrl: (agentId?: string) =>
    api
      .get<{ auth_url: string }>('/calendar/google/connect', {
        params: agentId ? { agent_id: agentId } : {},
      })
      .then((r) => r.data.auth_url),
  disconnect: (agentId?: string) =>
    api.post('/calendar/disconnect', null, {
      params: agentId ? { agent_id: agentId } : {},
    }),
  updateWorkingHours: (data: WorkingHours) =>
    api.put<WorkingHours>('/calendar/working-hours', data).then((r) => r.data),
}

export interface WorkingHours {
  work_start: string
  work_end: string
  buffer_minutes: number
}

// --------------------------------------------------------------------------- //
// Document routing (Autonomy task `doc-routing`)
// --------------------------------------------------------------------------- //

export interface DocRoutingRule {
  id: string
  brokerage_id: string
  trigger_stage: string
  document_source: string
  recipient_roles: string[]
  enabled: boolean
  created_at?: string
}

export interface PendingDocRoute {
  id: string
  brokerage_id: string
  transaction_id: string
  rule_id?: string | null
  trigger_stage: string
  document_source: string
  document_url?: string | null
  recipient_roles: string[]
  recipient_emails: string[]
  status: 'pending' | 'sent' | 'dismissed'
  created_at?: string
}

export const docRoutingApi = {
  listRules: () => api.get<DocRoutingRule[]>('/doc-routing/rules').then((r) => r.data),
  createRule: (data: {
    trigger_stage: string
    recipient_roles: string[]
    document_source?: string
    enabled?: boolean
  }) => api.post<DocRoutingRule>('/doc-routing/rules', data).then((r) => r.data),
  updateRule: (id: string, data: Partial<Omit<DocRoutingRule, 'id' | 'brokerage_id'>>) =>
    api.patch<DocRoutingRule>(`/doc-routing/rules/${id}`, data).then((r) => r.data),
  deleteRule: (id: string) => api.delete(`/doc-routing/rules/${id}`),
  listPending: () => api.get<PendingDocRoute[]>('/doc-routing/pending').then((r) => r.data),
  sendPending: (id: string) =>
    api
      .post<PendingDocRoute>(`/doc-routing/pending/${id}/send`, { confirmed: true })
      .then((r) => r.data),
  dismissPending: (id: string) =>
    api.post<PendingDocRoute>(`/doc-routing/pending/${id}/dismiss`).then((r) => r.data),
}

// Transaction stages a routing rule can trigger on (mirrors backend VALID_STAGES).
export const ROUTING_STAGES: { key: string; label: string }[] = [
  { key: 'under_contract', label: 'Under Contract' },
  { key: 'pending', label: 'Pending' },
  { key: 'closed', label: 'Closed' },
  { key: 'cancelled', label: 'Cancelled' },
]

// --------------------------------------------------------------------------- //
// Transactions
// --------------------------------------------------------------------------- //

export interface Transaction {
  id: string
  brokerage_id: string
  address?: string | null
  city?: string | null
  state?: string | null
  zip?: string | null
  buyer_name?: string | null
  buyer_email?: string | null
  buyer_phone?: string | null
  seller_name?: string | null
  seller_email?: string | null
  seller_phone?: string | null
  list_price?: number | null
  sale_price?: number | null
  financing?: string | null
  contract_date?: string | null
  closing_date?: string | null
  stage?: string | null
  listing_agent_name?: string | null
  listing_agent_email?: string | null
  selling_agent_name?: string | null
  selling_agent_email?: string | null
  lender_name?: string | null
  lender_email?: string | null
  title_company?: string | null
  title_email?: string | null
  tc_name?: string | null
  tc_email?: string | null
  mls_number?: string | null
  contract_pdf_url?: string | null
  compliance_status?: string | null
  agent_id?: string | null
  transaction_type?: string | null
  checklist_pct?: number
  overdue_tasks?: number
  emd_amount?: number | null
  emd_due_date?: string | null
  emd_received?: boolean | null
  emd_received_date?: string | null
  emd_receipt_document_url?: string | null
  emd_held_by?: string | null
  emd_notes?: string | null
  created_at?: string
  updated_at?: string
}

export interface ExtractResult {
  contract_pdf_url: string
  signed_url?: string | null
  page_count: number
  fields: Record<string, string | number | null>
  not_found: string[]
}

export interface ImportPreviewRow {
  row_number: number
  data: Record<string, string | number>
  errors: string[]
  warnings: string[]
  duplicate: boolean
  importable: boolean
}

export interface ImportPreview {
  rows: ImportPreviewRow[]
  recognized_columns: string[]
  unmapped_columns: string[]
  summary: { total: number; ready: number; errors: number; duplicates: number }
  error?: string
}

export interface ImportResult {
  created: number
  failed: { index: number; reason: string }[]
}

// --------------------------------------------------------------------------- //
// WhatsApp
// --------------------------------------------------------------------------- //

export interface WhatsAppContact {
  id: string
  brokerage_id: string
  phone_number: string
  display_name?: string | null
  channel?: string | null
  agent_id?: string | null
  consent_status?: 'pending' | 'active' | 'opted_out' | null
  created_at: string
}

export interface WhatsAppConfig {
  penny_whatsapp_number: string | null
  configured: boolean
}

export interface MessagingSettings {
  forward_replies_to_agent?: boolean | null
  // Two-way email (Phase 1): let Penny reply by email to the brokerage's own
  // agents, and draft suggested replies to outside parties for agent approval.
  email_agent_autoreply_enabled?: boolean | null
  email_outside_draft_enabled?: boolean | null
}

export const whatsappApi = {
  config: () => api.get<WhatsAppConfig>('/whatsapp/config').then((r) => r.data),
  listContacts: () => api.get<WhatsAppContact[]>('/whatsapp/contacts').then((r) => r.data),
  addContact: (phone_number: string, display_name?: string, agent_id?: string) =>
    api
      .post<WhatsAppContact>('/whatsapp/contacts', { phone_number, display_name, agent_id })
      .then((r) => r.data),
  removeContact: (phone_number: string) =>
    api.delete(`/whatsapp/contacts/${encodeURIComponent(phone_number)}`),
  getSettings: () => api.get<MessagingSettings>('/whatsapp/settings').then((r) => r.data),
  updateSettings: (data: MessagingSettings) =>
    api.put<MessagingSettings>('/whatsapp/settings', data).then((r) => r.data),
}

export interface SmsConfig {
  penny_sms_number: string | null
  configured: boolean
}

export const smsApi = {
  config: () => api.get<SmsConfig>('/sms/config').then((r) => r.data),
  listContacts: () => api.get<WhatsAppContact[]>('/sms/contacts').then((r) => r.data),
  addContact: (phone_number: string, display_name?: string, agent_id?: string) =>
    api
      .post<WhatsAppContact>('/sms/contacts', { phone_number, display_name, agent_id })
      .then((r) => r.data),
  removeContact: (phone_number: string) =>
    api.delete(`/sms/contacts/${encodeURIComponent(phone_number)}`),
}

export const transactionsApi = {
  extract: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    // Use native fetch so the browser sets Content-Type: multipart/form-data
    // with the correct boundary — axios's default json Content-Type interferes.
    return fetch(`${API_BASE}/transactions/extract`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<ExtractResult>
    })
  },
  create: (data: Partial<Transaction>) =>
    api.post<Transaction>('/transactions', data).then((r) => r.data),
  list: () => api.get<Transaction[]>('/transactions').then((r) => r.data),
  get: (id: string) => api.get<Transaction>(`/transactions/${id}`).then((r) => r.data),
  update: (id: string, data: Partial<Transaction>) =>
    api.patch<Transaction>(`/transactions/${id}`, data).then((r) => r.data),

  // CSV import — migration path for brokerages with existing deals.
  importPreview: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/transactions/import/preview`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        throw new Error(data?.detail ?? 'Could not read that file')
      }
      return res.json() as Promise<ImportPreview>
    })
  },
  importCommit: (rows: Record<string, unknown>[]) =>
    api.post<ImportResult>('/transactions/import', { rows }).then((r) => r.data),
  downloadTemplate: async () => {
    const res = await fetch(`${API_BASE}/transactions/import/template`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    })
    if (!res.ok) throw new Error('Could not download template')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'penny-transactions-template.csv'
    a.click()
    URL.revokeObjectURL(url)
  },
  draftDocument: (
    id: string,
    data: { doc_type: string; recipient?: string; instructions?: string },
  ) =>
    api
      .post<{ doc_type: string; subject: string; body: string }>(
        `/transactions/${id}/draft-document`,
        data,
      )
      .then((r) => r.data),
  sendDocument: (
    id: string,
    data: { to_emails: string[]; subject: string; body: string; confirmed: boolean },
  ) =>
    api
      .post<{ sent: boolean; recipients: string[] }>(
        `/transactions/${id}/send-document`,
        data,
      )
      .then((r) => r.data),
  complianceReview: (id: string) =>
    api
      .post<ComplianceReview>(`/transactions/${id}/compliance-review`)
      .then((r) => r.data),
  complianceDecision: (id: string, status: string, confirmed: boolean) =>
    api
      .post<{ compliance_status: string | null }>(
        `/transactions/${id}/compliance-decision`,
        { status, confirmed },
      )
      .then((r) => r.data),
  complianceFeedback: (
    id: string,
    data: {
      rule_id: string
      human_verdict: 'correct' | 'incorrect'
      ai_status?: string | null
      ai_confidence?: string | null
      note?: string | null
    },
  ) =>
    api
      .post<ComplianceFeedback>(`/transactions/${id}/compliance-feedback`, data)
      .then((r) => r.data),
  comps: (id: string) =>
    api.post<CompsResult>(`/transactions/${id}/comps`).then((r) => r.data),
  propertyRecord: (id: string) =>
    api.post<PropertyRecord>(`/transactions/${id}/property-record`).then((r) => r.data),
  docusignStatus: (id: string) =>
    api
      .get<{ connected: boolean; provider: string | null }>(`/transactions/${id}/docusign/status`)
      .then((r) => r.data),
  docusignSend: (
    id: string,
    data: {
      signers: { name: string; email: string; role?: string }[]
      confirmed: boolean
      document_url?: string
      email_subject?: string
      message?: string
    },
  ) =>
    api
      .post<{ sent: boolean; envelope_id: string | null; reason: string }>(
        `/transactions/${id}/docusign/send`,
        data,
      )
      .then((r) => r.data),
  // Marking EMD received is confirmation-gated server-side; pass confirmed: true
  // only from an explicit confirm step in the UI.
  setEmdReceived: (
    id: string,
    data: { received: boolean; received_date?: string | null; confirmed: boolean },
  ) => api.post<Transaction>(`/transactions/${id}/emd-received`, data).then((r) => r.data),
  uploadEmdReceipt: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/transactions/${id}/emd-receipt`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<{
        emd_receipt_document_url: string
        transaction: Transaction
      }>
    })
  },
}

// --------------------------------------------------------------------------- //
// Compliance checklist (V2 Section 2A)
// --------------------------------------------------------------------------- //

export interface ChecklistItem {
  id: string
  transaction_id: string
  template_item_id?: string | null
  label: string
  required: boolean
  document_required: boolean
  status: 'pending' | 'complete' | 'waived' | 'not_applicable'
  completed_at?: string | null
  completed_by?: string | null
  document_url?: string | null
  waiver_note?: string | null
  sort_order?: number
}

export const checklistApi = {
  get: (txId: string) =>
    api.get<ChecklistItem[]>(`/transactions/${txId}/checklist`).then((r) => r.data),
  addItem: (
    txId: string,
    data: { label: string; required?: boolean; document_required?: boolean },
  ) =>
    api
      .post<ChecklistItem>(`/transactions/${txId}/checklist/items`, data)
      .then((r) => r.data),
  patchItem: (
    txId: string,
    itemId: string,
    data: { status?: string; waiver_note?: string; document_url?: string },
  ) =>
    api
      .patch<ChecklistItem>(`/transactions/${txId}/checklist/items/${itemId}`, data)
      .then((r) => r.data),
  deleteItem: (txId: string, itemId: string) =>
    api.delete(`/transactions/${txId}/checklist/items/${itemId}`),
  uploadDocument: (txId: string, itemId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/transactions/${txId}/checklist/items/${itemId}/document`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<ChecklistItem>
    })
  },
}

// --------------------------------------------------------------------------- //
// Transaction emails — Communications thread (V2 Section 4)
// --------------------------------------------------------------------------- //

export interface TransactionEmail {
  id: string
  transaction_id: string
  direction: 'outbound' | 'inbound'
  sender_email?: string | null
  sender_name?: string | null
  recipient_emails?: string[] | null
  subject?: string | null
  body_text?: string | null
  body_html?: string | null
  read: boolean
  received_at: string
}

// Delivery problems reported by the SendGrid Event Webhook (bounces etc.).
export interface EmailDeliveryEvent {
  id: string
  transaction_id?: string | null
  email: string
  event: 'bounce' | 'dropped' | 'spamreport'
  reason?: string | null
  created_at: string
}

export const emailsApi = {
  list: (txId: string) =>
    api.get<TransactionEmail[]>(`/transactions/${txId}/emails`).then((r) => r.data),
  markRead: (txId: string) =>
    api.post<{ ok: boolean }>(`/transactions/${txId}/emails/read`).then((r) => r.data),
  deliveryEvents: (txId: string) =>
    api
      .get<EmailDeliveryEvent[]>(`/transactions/${txId}/delivery-events`)
      .then((r) => r.data),
}

// Merged per-deal activity feed (audit events + emails + delivery + appts).
export interface ActivityEntry {
  at: string
  kind: string
  title: string
  detail?: string | null
  actor: string
  via: string
}

export const activityApi = {
  list: (txId: string) =>
    api.get<ActivityEntry[]>(`/transactions/${txId}/activity`).then((r) => r.data),
}

// Suggested replies to outside parties — Penny drafts, the agent confirm-sends.
export interface PendingEmailReply {
  id: string
  transaction_id: string
  inbound_email_id?: string | null
  to_email: string
  to_name?: string | null
  subject: string
  draft_body: string
  summary?: string | null
  recommendation?: string | null
  trigger_type?: 'none' | 'time' | 'event' | 'manual' | null
  scheduled_send_at?: string | null
  trigger_event?: string | null
  hold_note?: string | null
  status: 'pending' | 'scheduled' | 'awaiting_event' | 'held' | 'sent' | 'dismissed'
  created_at: string
}

export const pendingRepliesApi = {
  listForTransaction: (txId: string) =>
    api
      .get<PendingEmailReply[]>(`/transactions/${txId}/pending-replies`)
      .then((r) => r.data),
  send: (id: string, data: { subject?: string; body?: string; confirmed: boolean }) =>
    api
      .post<{ sent: boolean; recipient: string }>(
        `/email/pending-replies/${id}/send`,
        data,
      )
      .then((r) => r.data),
  dismiss: (id: string) =>
    api.post<{ ok: boolean }>(`/email/pending-replies/${id}/dismiss`).then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Workflow tasks (V2 Section 3)
// --------------------------------------------------------------------------- //

export interface TransactionTask {
  id: string
  transaction_id: string
  step_id?: string | null
  label: string
  description?: string | null
  due_date?: string | null
  assigned_to_role?: string | null
  status: 'pending' | 'complete' | 'skipped'
  completed_at?: string | null
  skip_reason?: string | null
}

export const tasksApi = {
  list: (txId: string) =>
    api.get<TransactionTask[]>(`/transactions/${txId}/tasks`).then((r) => r.data),
  add: (
    txId: string,
    data: { label: string; description?: string; due_date?: string; assigned_to_role?: string },
  ) => api.post<TransactionTask>(`/transactions/${txId}/tasks`, data).then((r) => r.data),
  patch: (
    txId: string,
    taskId: string,
    data: { status?: string; skip_reason?: string; due_date?: string; label?: string },
  ) =>
    api
      .patch<TransactionTask>(`/transactions/${txId}/tasks/${taskId}`, data)
      .then((r) => r.data),
  remove: (txId: string, taskId: string) =>
    api.delete(`/transactions/${txId}/tasks/${taskId}`),
}

// --------------------------------------------------------------------------- //
// Broker review queue (V2 Section 2B)
// --------------------------------------------------------------------------- //

export interface ReviewItem {
  id: string
  address?: string | null
  buyer_name?: string | null
  closing_date?: string | null
  stage?: string | null
  checklist_pct: number
  agent_name?: string | null
  reason: string
}

export interface ReviewQueue {
  compliance_attention: ReviewItem[]
  closing_soon_incomplete: ReviewItem[]
  past_closing_not_closed: ReviewItem[]
  overdue_deadlines: ReviewItem[]
  emd_overdue: ReviewItem[]
  stale_transactions: ReviewItem[]
  total: number
}

export const brokerApi = {
  reviewQueue: () => api.get<ReviewQueue>('/broker/review-queue').then((r) => r.data),
  addReviewNote: (txId: string, note: string) =>
    api
      .post<{ notes: string | null }>(`/broker/transactions/${txId}/review-note`, { note })
      .then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Home-page briefing — prioritized next actions across active deals
// --------------------------------------------------------------------------- //

export interface NextAction {
  priority: number
  transaction_id: string
  address: string
  headline: string
  offer: string
  prompt: string
}

export interface NextActionsBriefing {
  actions: NextAction[]
  remaining: number
  total: number
}

export const briefingApi = {
  nextActions: (limit = 3) =>
    api
      .get<NextActionsBriefing>('/briefing/next-actions', { params: { limit } })
      .then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Broker reporting (V2 Section 7)
// --------------------------------------------------------------------------- //

export interface BrokerSummary {
  period: string
  pipeline: {
    active_transactions: number
    active_volume: number
    by_stage: Record<string, number>
    closing_this_month: number
    closing_this_month_volume: number
  }
  at_risk: {
    overdue_deadlines: number
    closing_soon_incomplete: number
    stale_transactions: number
  }
  production: {
    closed_count: number
    closed_volume: number
    avg_days_to_close: number
    agent_breakdown: { agent_name: string; closed: number; volume: number }[]
  }
  compliance: {
    avg_checklist_completion_at_close: number
    open_compliance_items_total: number
    needs_attention: number
  }
}

export const reportsApi = {
  summary: (period: string) =>
    api
      .get<BrokerSummary>('/reports/broker-summary', { params: { period } })
      .then((r) => r.data),
  downloadExport: async (period: string) => {
    const res = await fetch(`${API_BASE}/reports/transactions-export?period=${period}`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    })
    if (!res.ok) throw new Error('export failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `penny-closed-${period}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },
}

// --------------------------------------------------------------------------- //
// Compliance settings + party consents (V2 Section 6)
// --------------------------------------------------------------------------- //

export interface ComplianceSettings {
  ai_disclosure_enabled?: boolean | null
  ai_disclosure_text?: string | null
  request_ai_consent?: boolean | null
  document_retention_years?: number | null
  document_retention_enabled?: boolean | null
}

export interface PartyConsent {
  id: string
  transaction_id: string
  party_role: string
  email: string
  consented_at?: string | null
  consent_method?: string | null
}

export const complianceSettingsApi = {
  get: () => api.get<ComplianceSettings>('/compliance-settings').then((r) => r.data),
  update: (data: ComplianceSettings) =>
    api.put<ComplianceSettings>('/compliance-settings', data).then((r) => r.data),
  consents: (txId: string) =>
    api.get<PartyConsent[]>(`/transactions/${txId}/consents`).then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Comparable sales (Rentcast)
// --------------------------------------------------------------------------- //

export interface Comparable {
  address?: string | null
  price?: number | null
  bedrooms?: number | null
  bathrooms?: number | null
  square_footage?: number | null
  year_built?: number | null
  property_type?: string | null
  listing_type?: string | null
  days_on_market?: number | null
  distance?: number | null
  correlation?: number | null
}

export interface CompsResult {
  subject_address: string
  estimate?: number | null
  range_low?: number | null
  range_high?: number | null
  comparables: Comparable[]
}

export interface TaxAssessment {
  year?: number | null
  value?: number | null
  land?: number | null
  improvements?: number | null
}

export interface PropertyTax {
  year?: number | null
  total?: number | null
}

export interface PropertyRecord {
  subject_address: string
  year_built?: number | null
  lot_size?: number | null
  square_footage?: number | null
  bedrooms?: number | null
  bathrooms?: number | null
  property_type?: string | null
  owner_occupied?: boolean | null
  last_sale_price?: number | null
  last_sale_date?: string | null
  tax_assessments: TaxAssessment[]
  property_taxes: PropertyTax[]
}

// --------------------------------------------------------------------------- //
// Scheduling / appointments
// --------------------------------------------------------------------------- //

export interface Appointment {
  id: string
  transaction_id: string
  type?: string | null
  showing_method?: string | null
  scheduled_at?: string | null
  confirmed?: boolean
  calendar_event_id?: string | null
  attendees?: string[] | null
  created_at?: string
  updated_at?: string
}

export interface ProposeResult {
  timezone: string
  duration_minutes: number
  calendar: { provider: string | null; connected: boolean; owner: 'agent' | 'brokerage' | null }
  slots: string[]
}

export const appointmentsApi = {
  list: (transactionId: string) =>
    api
      .get<Appointment[]>('/appointments', { params: { transaction_id: transactionId } })
      .then((r) => r.data),
  propose: (data: {
    transaction_id: string
    days?: number
    start_date?: string
    duration_minutes?: number
  }) => api.post<ProposeResult>('/appointments/propose', data).then((r) => r.data),
  book: (data: {
    transaction_id: string
    type: string
    scheduled_at: string
    attendees?: string[]
    confirmed: boolean
  }) =>
    api
      .post<{ appointment: Appointment; calendar_event_created: boolean }>(
        '/appointments/book',
        data,
      )
      .then((r) => r.data),
  remove: (id: string) => api.delete(`/appointments/${id}`),
  notifyParties: (id: string, data: { confirmed: boolean; parties: string[] }) =>
    api
      .post<{ sent: boolean; recipients: string[] }>(
        `/appointments/${id}/notify-parties`,
        data,
      )
      .then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Compliance review
// --------------------------------------------------------------------------- //

export type AiConfidence = 'high' | 'medium' | 'low'

export interface ComplianceFinding {
  severity: 'issue' | 'warning' | 'info'
  category: string
  message: string
  source: 'structural' | 'contract'
  rule_id?: string
  confidence?: AiConfidence // present on AI (source='contract') findings only
}

export interface ComplianceChecklistItem {
  id: string
  category: string
  requirement: string
  ai_status: 'satisfied' | 'missing' | 'unclear' | 'not_reviewed'
  ai_note?: string | null
  ai_confidence?: AiConfidence | null
}

export interface ComplianceFeedback {
  id: string
  rule_id: string
  ai_status?: string | null
  ai_confidence?: string | null
  human_verdict: 'correct' | 'incorrect'
  note?: string | null
  created_at?: string
}

export interface ComplianceReview {
  ruleset_state: string
  state?: string | null
  contract_reviewed: boolean
  ai_error?: string | null
  findings: ComplianceFinding[]
  checklist: ComplianceChecklistItem[]
  counts: { issue: number; warning: number }
  suggested_status: 'approved' | 'needs_attention'
  disclaimer: string
}

// --------------------------------------------------------------------------- //
// Deadlines
// --------------------------------------------------------------------------- //

export interface Deadline {
  id: string
  transaction_id: string
  label: string
  due_date?: string | null
  responsible_parties?: string[] | null
  status?: string | null
  reminder_5day_sent?: boolean
  reminder_2day_sent?: boolean
  reminder_day_sent?: boolean
  created_at?: string
  updated_at?: string
}

// Party role keys, matching the backend (email_client.PARTY_KEYS).
export const PARTY_ROLES: { key: string; label: string }[] = [
  { key: 'buyer', label: 'Buyer' },
  { key: 'seller', label: 'Seller' },
  { key: 'listing_agent', label: 'Listing agent' },
  { key: 'selling_agent', label: 'Selling agent' },
  { key: 'lender', label: 'Lender' },
  { key: 'title', label: 'Title' },
  { key: 'tc', label: 'Transaction coordinator' },
]

export interface ReminderRunResult {
  processed: number
  items: {
    deadline_id: string
    label?: string | null
    address?: string | null
    mark: string
    days_until: number
    nudged: boolean
    party_action: string
    parties_emailed: string[]
  }[]
}

export const deadlinesApi = {
  list: (transactionId: string) =>
    api
      .get<Deadline[]>('/deadlines', { params: { transaction_id: transactionId } })
      .then((r) => r.data),
  create: (data: {
    transaction_id: string
    label: string
    due_date?: string
    responsible_parties?: string[]
  }) => api.post<Deadline>('/deadlines', data).then((r) => r.data),
  update: (
    id: string,
    data: { label?: string; due_date?: string; responsible_parties?: string[]; status?: string },
  ) => api.patch<Deadline>(`/deadlines/${id}`, data).then((r) => r.data),
  remove: (id: string) => api.delete(`/deadlines/${id}`),
  notifyParties: (id: string, confirmed: boolean) =>
    api
      .post<{ sent: boolean; recipients: string[] }>(`/deadlines/${id}/notify-parties`, {
        confirmed,
      })
      .then((r) => r.data),
  runReminders: () =>
    api.post<ReminderRunResult>('/deadlines/run-reminders').then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Listings (MLS prep)
// --------------------------------------------------------------------------- //

export interface Listing {
  id: string
  brokerage_id: string
  status?: string | null
  address?: string | null
  city?: string | null
  state?: string | null
  zip?: string | null
  property_type?: string | null
  list_price?: number | null
  bedrooms?: number | null
  bathrooms?: number | null
  square_footage?: number | null
  lot_size_sqft?: number | null
  year_built?: number | null
  stories?: number | null
  garage_spaces?: number | null
  hoa_fee?: number | null
  hoa_frequency?: string | null
  annual_taxes?: number | null
  parcel_number?: string | null
  mls_number?: string | null
  public_remarks?: string | null
  features?: string[] | null
  school_district?: string | null
  listing_agent_name?: string | null
  listing_agent_email?: string | null
  seller_name?: string | null
  listing_packet_url?: string | null
  created_at?: string
  updated_at?: string
}

export interface ListingExtractResult {
  listing_packet_url: string
  signed_url?: string | null
  page_count: number
  fields: Record<string, string | number | string[] | null>
  not_found: string[]
}

export const listingsApi = {
  extract: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/listings/extract`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<ListingExtractResult>
    })
  },
  create: (data: Partial<Listing>) =>
    api.post<Listing>('/listings', data).then((r) => r.data),
  list: () => api.get<Listing[]>('/listings').then((r) => r.data),
  get: (id: string) => api.get<Listing>(`/listings/${id}`).then((r) => r.data),
  update: (id: string, data: Partial<Listing>) =>
    api.patch<Listing>(`/listings/${id}`, data).then((r) => r.data),
  remove: (id: string) => api.delete(`/listings/${id}`),
  push: (id: string, confirmed: boolean) =>
    api
      .post<{ pushed: boolean; mls_number: string | null; reason: string }>(
        `/listings/${id}/push`,
        { confirmed },
      )
      .then((r) => r.data),
}

// --------------------------------------------------------------------------- //
// Knowledge base — brand & style
// --------------------------------------------------------------------------- //

export interface KnowledgeDocument {
  id: string
  brokerage_id: string
  filename: string
  storage_path: string
  content_type?: string | null
  file_size?: number | null
  status: string // 'processing' | 'processed' | 'failed'
  error?: string | null
  created_at: string
  updated_at?: string
}

export interface KnowledgeRule {
  id: string
  category?: string | null
  rule: string
  confirmed: boolean
  document_id?: string | null
  source_document?: string | null
  created_at?: string
}

export interface KnowledgeUploadResult {
  document: KnowledgeDocument
  rules: KnowledgeRule[]
  extraction_error?: string | null
}

export const knowledgeApi = {
  listDocuments: () =>
    api.get<KnowledgeDocument[]>('/knowledge/documents').then((r) => r.data),
  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    // Native fetch so the browser sets the multipart boundary (see extract above).
    return fetch(`${API_BASE}/knowledge/documents`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<KnowledgeUploadResult>
    })
  },
  deleteDocument: (id: string) => api.delete(`/knowledge/documents/${id}`),
  listRules: () => api.get<KnowledgeRule[]>('/knowledge/rules').then((r) => r.data),
  updateRule: (
    id: string,
    data: { confirmed?: boolean; category?: string; rule?: string },
  ) => api.patch<KnowledgeRule>(`/knowledge/rules/${id}`, data).then((r) => r.data),
  deleteRule: (id: string) => api.delete(`/knowledge/rules/${id}`),
}

// --------------------------------------------------------------------------- //
// Agents — roster + per-agent style profiles (V2 Section 1B)
// --------------------------------------------------------------------------- //

export interface Agent {
  id: string
  brokerage_id: string
  name?: string | null
  email?: string | null
  phone?: string | null
  license_number?: string | null
  role?: string | null
  style_rule_count?: number
  created_at?: string
}

export const agentsApi = {
  list: () => api.get<Agent[]>('/agents').then((r) => r.data),
  create: (data: Partial<Agent>) => api.post<Agent>('/agents', data).then((r) => r.data),
  update: (id: string, data: Partial<Agent>) =>
    api.patch<Agent>(`/agents/${id}`, data).then((r) => r.data),
  remove: (id: string) => api.delete(`/agents/${id}`),
  listStyleRules: (id: string) =>
    api.get<KnowledgeRule[]>(`/agents/${id}/style-rules`).then((r) => r.data),
  uploadStyleDocument: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${API_BASE}/agents/${id}/style-documents`, {
      method: 'POST',
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      body: form,
    }).then(async (res) => {
      if (!res.ok) {
        const err: { response: { status: number; data: unknown } } = {
          response: { status: res.status, data: await res.json().catch(() => null) },
        }
        throw err
      }
      return res.json() as Promise<KnowledgeUploadResult>
    })
  },
  deleteStyleProfile: (id: string) => api.delete(`/agents/${id}/style-profile`),
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export const chatApi = {
  // Send one turn; the client replays recent history so the backend stays stateless.
  send: (message: string, history: ChatTurn[]) =>
    api.post<{ reply: string }>('/chat', { message, history }).then((r) => r.data),
}
