import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import {
  authApi,
  setAuthToken,
  setRefreshHandler,
  type Brokerage,
  type SignupData,
} from '../lib/api'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  brokerage: Brokerage | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (data: SignupData) => Promise<void>
  logout: () => Promise<void>
  setBrokerage: (brokerage: Brokerage) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      brokerage: null,
      isAuthenticated: false,

      login: async (email, password) => {
        const res = await authApi.login(email, password)
        setAuthToken(res.access_token)
        set({
          accessToken: res.access_token,
          refreshToken: res.refresh_token,
          brokerage: res.brokerage,
          isAuthenticated: true,
        })
      },

      signup: async (data) => {
        const res = await authApi.signup(data)
        setAuthToken(res.access_token)
        set({
          accessToken: res.access_token,
          refreshToken: res.refresh_token,
          brokerage: res.brokerage,
          isAuthenticated: true,
        })
      },

      logout: async () => {
        try {
          await authApi.logout()
        } catch {
          // Even if the server call fails, drop local credentials.
        }
        setAuthToken(null)
        set({
          accessToken: null,
          refreshToken: null,
          brokerage: null,
          isAuthenticated: false,
        })
      },

      setBrokerage: (brokerage) => set({ brokerage }),
    }),
    {
      name: 'penny-auth',
      onRehydrateStorage: () => (state) => {
        if (state?.accessToken) setAuthToken(state.accessToken)
      },
    },
  ),
)

// Silent session refresh: the api layer calls this on a 401 to swap the stored
// refresh token for a fresh session and retry, instead of logging the broker
// out every hour when the access token expires. Returns the new access token,
// or null when the refresh token itself is dead (the interceptor then logs out).
setRefreshHandler(async () => {
  const { refreshToken } = useAuthStore.getState()
  if (!refreshToken) return null
  try {
    const res = await authApi.refresh(refreshToken)
    setAuthToken(res.access_token)
    useAuthStore.setState({
      accessToken: res.access_token,
      refreshToken: res.refresh_token,
    })
    return res.access_token
  } catch {
    return null
  }
})
