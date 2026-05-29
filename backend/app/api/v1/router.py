from fastapi import APIRouter

from app.api.v1.routes import (
    agents,
    appointments,
    auth,
    autonomy,
    broker,
    chat,
    checklist,
    consent,
    deadlines,
    doc_routing,
    email,
    knowledge,
    listings,
    onboarding,
    reports,
    sms,
    tasks,
    transactions,
    whatsapp,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(transactions.router)
api_router.include_router(whatsapp.router)
api_router.include_router(sms.router)
api_router.include_router(knowledge.router)
api_router.include_router(deadlines.router)
api_router.include_router(appointments.router)
api_router.include_router(listings.router)
api_router.include_router(agents.router)
api_router.include_router(checklist.router)
api_router.include_router(broker.router)
api_router.include_router(tasks.router)
api_router.include_router(email.router)
api_router.include_router(consent.router)
api_router.include_router(reports.router)
api_router.include_router(chat.router)
api_router.include_router(autonomy.router)
api_router.include_router(doc_routing.router)
