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

    # Optional integrations, wired up in later phases.
    ANTHROPIC_API_KEY: str | None = None
    SENDGRID_API_KEY: str | None = None
    # "From" address for outbound email. Must be verified in your SendGrid account.
    SENDGRID_FROM_EMAIL: str = "hello@usepenny.ai"
    # Public URL of the frontend — used in email CTAs.
    FRONTEND_URL: str = "http://localhost:5173"
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
    # Set to True in local dev when using ngrok so signature validation is skipped
    TWILIO_SKIP_VALIDATION: bool = False

    # OpenAI — Whisper audio transcription for voice memos
    OPENAI_API_KEY: str | None = None

    # Frontend origins allowed by CORS.
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
