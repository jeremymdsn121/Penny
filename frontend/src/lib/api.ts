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

export const transactionsApi = {
  extract: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<ExtractResult>('/transactions/extract', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  create: (data: Partial<Transaction>) =>
    api.post<Transaction>('/transactions', data).then((r) => r.data),
  list: () => api.get<Transaction[]>('/transactions').then((r) => r.data),
  get: (id: string) => api.get<Transaction>(`/transactions/${id}`).then((r) => r.data),
  update: (id: string, data: Partial<Transaction>) =>
    api.patch<Transaction>(`/transactions/${id}`, data).then((r) => r.data),
}
