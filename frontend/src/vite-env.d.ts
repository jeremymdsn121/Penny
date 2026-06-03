/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Full API base URL for deployed builds (e.g. "https://api.poweredbypenny.com/api/v1").
  // Unset in dev — the app falls back to "/api/v1" via the Vite proxy.
  readonly VITE_API_BASE_URL?: string
}
