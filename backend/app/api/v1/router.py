from fastapi import APIRouter

from app.api.v1.routes import auth, onboarding, transactions, whatsapp

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(transactions.router)
api_router.include_router(whatsapp.router)
