from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings

# The default SECRET_KEY signs consent links and the calendar OAuth state; with
# the public fallback value anyone can forge both for any brokerage. Refuse to
# boot in production rather than run with forgeable HMACs.
if settings.ENV.lower() == "production" and settings.SECRET_KEY == "dev-insecure-change-me":
    raise RuntimeError(
        "SECRET_KEY is still the dev default in ENV=production. "
        "Set SECRET_KEY (and ideally CONSENT_SECRET) in the environment."
    )

app = FastAPI(title="Penny API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.ENV}


app.include_router(api_router, prefix="/api/v1")
