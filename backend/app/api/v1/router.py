from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    deadlines,
    knowledge,
    onboarding,
    transactions,
    whatsapp,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(transactions.router)
api_router.include_router(whatsapp.router)
api_router.include_router(knowledge.router)
api_router.include_router(deadlines.router)
