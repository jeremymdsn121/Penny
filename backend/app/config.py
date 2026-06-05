from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    ENV: str = "development"

    # Supabase — required for the app to start.
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # Reserved FastAPI signing key. Supabase issues the auth JWTs today; this is
    # here for any backend-minted tokens (e.g. signed webhook/state values).
    SECRET_KEY: str = "dev-insecure-change-me"
    # HMAC secret for AI-disclosure consent links (Section 6). Falls back to
    # SECRET_KEY when unset.
    CONSENT_SECRET: str | None = None
    # Public base URL of the backend, used to build absolute consent links in
    # outbound email (e.g. "https://api.poweredbypenny.com"). Defaults to localhost.
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # Public base URL of the frontend, used to redirect the browser back after the
    # calendar OAuth callback (e.g. "https://app.poweredbypenny.com"). Dev default.
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Optional integrations, wired up in later phases.
    ANTHROPIC_API_KEY: str | None = None
    SENDGRID_API_KEY: str | None = None
    # "From" address for outbound email. Must be a verified sender in SendGrid.
    SENDGRID_FROM_EMAIL: str = "hello@poweredbypenny.com"
    # Domain that routes inbound replies back to Penny via SendGrid Inbound Parse
    # (MX -> mx.sendgrid.net). Outbound mail sets Reply-To: tx-{id}@<this domain>.
    # When unset, reply threading is disabled (no Reply-To added).
    REPLY_EMAIL_DOMAIN: str | None = None
    # Shared secret for the inbound-parse webhook (passed as ?key=...). When unset,
    # the webhook is unauthenticated (dev only — set this in production).
    SENDGRID_WEBHOOK_KEY: str | None = None
    RENTCAST_API_KEY: str | None = None
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    REDIS_URL: str | None = None

    # Twilio — WhatsApp messaging
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    # E.g. "whatsapp:+14155238886" (sandbox) or "whatsapp:+1XXXXXXXXXX" (production)
    TWILIO_WHATSAPP_FROM: str | None = None
    # Standard Twilio phone number for the SMS fallback channel ("+1XXXXXXXXXX"),
    # distinct from the WhatsApp sender. Used by POST /sms/inbound replies.
    TWILIO_SMS_FROM: str | None = None
    # Set to True in local dev when using ngrok so signature validation is skipped
    TWILIO_SKIP_VALIDATION: bool = False

    # OpenAI — Whisper audio transcription for voice memos
    OPENAI_API_KEY: str | None = None

    # Frontend origins allowed by CORS (local dev defaults).
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # Additional comma-separated origins for deployed frontends, merged with
    # CORS_ORIGINS at startup. E.g.
    # "https://penny-web.onrender.com,https://app.poweredbypenny.com".
    EXTRA_CORS_ORIGINS: str = ""

    @property
    def cors_origins(self) -> list[str]:
        extra = [o.strip() for o in self.EXTRA_CORS_ORIGINS.split(",") if o.strip()]
        return [*self.CORS_ORIGINS, *extra]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
