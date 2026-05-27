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
  agent_id?: string | null
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
  created_at: string
}

export interface WhatsAppConfig {
  penny_whatsapp_number: string | null
  configured: boolean
}

export const whatsappApi = {
  config: () => api.get<WhatsAppConfig>('/whatsapp/config').then((r) => r.data),
  listContacts: () => api.get<WhatsAppContact[]>('/whatsapp/contacts').then((r) => r.data),
  addContact: (phone_number: string, display_name?: string) =>
    api
      .post<WhatsAppContact>('/whatsapp/contacts', { phone_number, display_name })
      .then((r) => r.data),
  removeContact: (phone_number: string) =>
    api.delete(`/whatsapp/contacts/${encodeURIComponent(phone_number)}`),
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
