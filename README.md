# Penny — Virtual Brokerage Assistant

Monorepo for Penny, a virtual transaction-coordinator assistant for real estate brokerages.

```
penny/
  backend/    FastAPI + Supabase (Python 3.11+)
  frontend/   React 18 + TypeScript + Vite + Tailwind
```

## Current status

Phase 1 foundation in progress: **project scaffold + authentication** (Supabase Auth, JWT-protected API).

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then fill in secrets
uvicorn app.main:app --reload
```

API runs at http://localhost:8000, docs at http://localhost:8000/docs.
All routes are under `/api/v1`. Auth routes are public; everything else needs
`Authorization: Bearer <jwt>`.

### Database

Run the SQL in `backend/migrations/` (in order) via the Supabase SQL Editor
before using the auth endpoints — `/auth/signup` writes a `brokerages` row.

## Frontend

Requires Node.js 18+ (tested with v24).

```bash
cd frontend
npm install
npm run dev
```

Dev server runs at http://localhost:5173 and proxies `/api` to the backend.

## Auth model

- Supabase Auth is the identity provider. The backend creates the auth user
  (admin API, email auto-confirmed for dev) and a matching `brokerages` row,
  then stamps `app_metadata.brokerage_id` on the user.
- The brokerage id travels in the JWT (`app_metadata.brokerage_id`) and drives
  both backend scoping and Postgres row-level security.
