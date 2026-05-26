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
  assistant_name?: string
  state?: string
  phone?: string
}

export const authApi = {
  signup: (data: SignupData) =>
    api.post<AuthResponse>('/auth/signup', data).then((r) => r.data),
  login: (email: string, password: string) =>
    api.post<AuthResponse>('/auth/login', { email, password }).then((r) => r.data),
  logout: () => api.post('/auth/logout'),
  me: () => api.get<Brokerage>('/auth/me').then((r) => r.data),
}
