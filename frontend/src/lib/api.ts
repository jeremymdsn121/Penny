import axios from 'axios'

// Token lives in a module variable so this file has no dependency on the store
// (the store calls setAuthToken on login/logout/rehydrate). Avoids a cycle.
let authToken: string | null = null

export function setAuthToken(token: string | null): void {
  authToken = token
}

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  if (authToken) {
    config.headers.Authorization = `Bearer ${authToken}`
  }
  return config
})

// When the server returns 401 the token is expired or missing — clear local
// auth state and redirect to login so the user gets a fresh token.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      authToken = null
      // Wipe the persisted Zustand store so ProtectedRoute redirects properly.
      localStorage.removeItem('penny-auth')
      window.location.href = '/login'
    }
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
  created_at: string
}

export interface WhatsAppConfig {
  penny_whatsapp_number: string | null
  configured: boolean
}

export interface MessagingSettings {
  forward_replies_to_agent?: boolean | null
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
    return fetch('/api/v1/transactions/extract', {
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
  uploadEmdReceipt: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`/api/v1/transactions/${id}/emd-receipt`, {
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
        emd_received: boolean
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
    return fetch(`/api/v1/transactions/${txId}/checklist/items/${itemId}/document`, {
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

export const emailsApi = {
  list: (txId: string) =>
    api.get<TransactionEmail[]>(`/transactions/${txId}/emails`).then((r) => r.data),
  markRead: (txId: string) =>
    api.post<{ ok: boolean }>(`/transactions/${txId}/emails/read`).then((r) => r.data),
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
    const res = await fetch(`/api/v1/reports/transactions-export?period=${period}`, {
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
  calendar: { provider: string | null; connected: boolean; sync_enabled: boolean }
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
}

// --------------------------------------------------------------------------- //
// Compliance review
// --------------------------------------------------------------------------- //

export interface ComplianceFinding {
  severity: 'issue' | 'warning' | 'info'
  category: string
  message: string
  source: 'structural' | 'contract'
  rule_id?: string
}

export interface ComplianceChecklistItem {
  id: string
  category: string
  requirement: string
  ai_status: 'satisfied' | 'missing' | 'unclear' | 'not_reviewed'
  ai_note?: string | null
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
    return fetch('/api/v1/listings/extract', {
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
    return fetch('/api/v1/knowledge/documents', {
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
    return fetch(`/api/v1/agents/${id}/style-documents`, {
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
