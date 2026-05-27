# Penny — Virtual Brokerage Assistant

B2B SaaS "virtual transaction coordinator" for real estate brokerages. One Penny
instance per brokerage, priced by agent seats. Built from a PRD; stack is fixed
by the PRD — **do not substitute libraries**.

```
penny/
  backend/    FastAPI + Python (Supabase over httpx)
  frontend/   React 18 + TS + Vite + Tailwind + Zustand + Axios + RHF/Zod
```

## Run

**Backend** (from `backend/`, uses the existing `.venv`):
```bash
# bash / git-bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
# PowerShell
.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload
```
API at http://localhost:8000 (docs `/docs`, health `/health`). All routes under
`/api/v1`; auth routes public, everything else needs `Authorization: Bearer <jwt>`.
`.env` is loaded **relative to the working dir**, so always run from `backend/`.

**Frontend** (from `frontend/`):
```bash
npm install   # first time
npm run dev    # http://localhost:5173, proxies /api -> backend
npm run typecheck
```
If `node`/`npm` reports "not found" mid-session, it's a Windows PATH quirk in a
stale shell — open a fresh terminal; the toolchain is fine.

**WhatsApp local testing** needs ngrok in front of the backend:
```bash
ngrok http 8000
```
Then set the Twilio WhatsApp sandbox "When a message comes in" webhook to
`https://<ngrok-host>/api/v1/whatsapp/inbound` (POST). The free-tier ngrok URL
**changes on every restart** — when inbound stops working, this stale URL is the
first thing to check (ngrok inspector: http://localhost:4040).

## Architecture

- **Auth:** Supabase Auth is the IdP. Backend creates the auth user (admin API,
  email auto-confirmed in dev) + a `brokerages` row, then stamps
  `app_metadata.brokerage_id` on the user. That id travels in the JWT and drives
  backend scoping **and** Postgres RLS.
- **Supabase access:** `app/core/supabase_client.py` — thin async httpx wrappers
  (not supabase-py). Service-role key is used server-side only and bypasses RLS.
- **AI:** Anthropic `claude-sonnet-4-5` for the WhatsApp agent
  (`app/services/penny_agent.py`, tool-use loop), contract field extraction
  (`app/services/ai_extract.py`), and brand/style rule extraction
  (`app/services/style_extract.py`).
- **WhatsApp (text + voice):** inbound webhook `app/api/v1/routes/whatsapp.py`
  → Twilio signature check → contact lookup → optional Whisper transcription
  (`app/services/whisper.py`) for voice memos → Penny agent → reply via Twilio
  (`app/services/twilio_client.py`). Conversation history persisted in
  `whatsapp_messages`. Agent tools: list transactions, get details, update
  stage, add note, preview/send intro email, draft document, list/add deadlines,
  review compliance (surface-only — never approves).
- **Email (SendGrid):** `app/services/email_client.py`. The **intro email**
  introduces all parties on a transaction (buyer, seller, agents, lender, title)
  and presents Penny as coordinator. Sent on request via the WhatsApp agent —
  `preview_intro_email` (read-only) then `send_intro_email` (requires
  `confirmed=true`); confirmation is enforced unless the brokerage's `intro-email`
  task is autonomous. Flips `transactions.intro_email_sent` to prevent
  double-sends. No-op without `SENDGRID_API_KEY`.
- **Knowledge base (brand & style):** `app/api/v1/routes/knowledge.py` +
  `style_extract.py`. Admins upload style references (letterhead, sample letter,
  template as PDF/image/.docx); Penny proposes style rules into `knowledge_rules`
  as **unconfirmed**; admin confirms; confirmed rules are injected into AI prompts
  via `get_confirmed_knowledge_rules`. Files stored in the `knowledge-docs` bucket.
- **Document generation:** `app/services/doc_generate.py`. Drafts correspondence
  (status update, cover letter, follow-up, congratulations, custom) for a
  transaction in the brokerage voice, injecting confirmed `knowledge_rules`.
  Endpoints `/transactions/{id}/draft-document` (read-only) and `/send-document`
  (requires `confirmed=true`, sends via SendGrid). Agent tool `draft_document`
  (WhatsApp, draft-only); web UI is the "Draft a document" panel on the
  transaction detail page (generate → edit → confirm-then-send).
- **Deadlines & reminders:** `app/api/v1/routes/deadlines.py` +
  `app/services/deadline_reminders.py`. Deadlines hang off a transaction
  (`deadlines` table, scoped through its parent — verify ownership in the route,
  service-role bypasses RLS). CRUD + agent tools (`add_deadline`, `list_deadlines`).
  Reminders fire from an **idempotent scan** `POST /deadlines/run-reminders`
  (no in-process scheduler — a scheduled job/cron calls it; dev has a "Run
  reminders" button on the Dashboard). At the 5-day / 2-day / day-of marks the
  scan WhatsApp-nudges the brokerage's registered contacts (internal, always) and
  flips the `reminder_*_sent` flags so a mark never repeats. Notifying outside
  parties is external comms, so it's gated: the scan auto-emails responsible
  parties only when `deadline-reminders` is autonomous; otherwise use the
  confirm-gated `POST /deadlines/{id}/notify-parties` (the "Notify parties"
  button). `responsible_parties` stores role keys (buyer/seller/listing_agent/
  selling_agent/lender/title/tc) resolved to emails via `email_client`.
- **Compliance review (locked, human-confirmed):** `app/services/compliance.py`.
  Hybrid: deterministic structural checks over the transaction record + an AI
  pass that reads the contract PDF and assesses it against the state ruleset
  (DEFAULT or the detailed TX/SC/FL/CA/NY checklist), mirroring `ai_extract`.
  `POST /transactions/{id}/compliance-review` only **surfaces** findings +
  annotated checklist + a *suggested* status (read-only, never approves);
  `POST /transactions/{id}/compliance-decision` (confirm-gated) records the
  human's decision into `transactions.compliance_status`. Degrades gracefully
  without a PDF or `ANTHROPIC_API_KEY` (structural + checklist only). Findings
  are recomputed on demand — only the status is persisted. State rulesets are
  verification prompts, **not legal advice**. Web UI: a Compliance panel on the
  transaction page; agent tool `review_compliance` is surface-only.
- **Frontend** state in Zustand (`src/store/auth.ts`); API layer in
  `src/lib/api.ts`; routes gated behind auth + onboarding in `src/App.tsx`.
  Pages: Dashboard, transactions, WhatsApp settings, **Brand & Style** (`/knowledge`).

## Database

Migrations in `backend/migrations/`, run **in order** via the Supabase SQL
Editor (paste file *contents*, not the path):
- `001_*` initial schema (brokerages, transactions, RLS helpers)
- `002_*` `onboarding_completed`
- `003_whatsapp.sql` `whatsapp_contacts`, `whatsapp_messages`, `transactions.notes`
- `004_knowledge.sql` `knowledge_documents` + `knowledge_rules.document_id`
  (**not yet applied to the dev DB** — run it before using the knowledge base)

Deadline tracking + reminders need **no new migration** — the `deadlines` table
(with `due_date`, `responsible_parties`, and the `reminder_5day/2day/day_sent`
flags) is already in `001`.

## Env vars (names only — never print values)

`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (Whisper),
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
`TWILIO_SKIP_VALIDATION`, `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` (intro
email; the from address must be a verified SendGrid sender). Later phases:
`RENTCAST_API_KEY`, Google/Microsoft OAuth, `REDIS_URL`.

WhatsApp specifics:
- `TWILIO_WHATSAPP_FROM` must be the **sandbox** number (`whatsapp:+14155238886`),
  not the assigned SMS number — replies must originate from a WhatsApp-enabled
  number. Sandbox agents must first send `join <sandbox-word>` to opt in.
- `TWILIO_SKIP_VALIDATION=true` in local dev: signature validation fails behind
  ngrok because the signed URL doesn't match the reconstructed one. Never skip
  in production.
- Phone numbers are canonicalised by `_normalise_phone` (US-first: a 10-digit
  number, even with a stray `+`, becomes `+1XXXXXXXXXX`; true international
  numbers pass through). Keep storage + lookup going through this helper.

## Conventions & security (hard rules)

- Never put API keys in frontend code — all AI/integration calls go through the backend.
- All API keys stored encrypted at rest; `service_role` key is server-only (bypasses RLS).
- Always scope DB queries by `brokerage_id` — never return data across brokerages.
- Never hallucinate extracted fields — return empty string if a field isn't found.
- Never skip the confirmation step for rules, document sending, or email approval.
- Never let compliance review run autonomously — always surface findings to the agent.
- Build phases in PRD order; resist scope creep — don't pre-build later-phase features.
- When inspecting `.env`, show only key names + char counts, never the secret values.

## Status & next up

Done & tested: scaffold, auth, onboarding (5 steps), contract PDF extraction +
transactions, and the full **WhatsApp text+voice channel** (register agent
numbers, text/voice-memo Penny, agent acts on transactions).

Built, pending live end-to-end verification (code + unit/type checks pass, but
not yet exercised against live services):
- **Intro email** (SendGrid) via the WhatsApp agent — needs `SENDGRID_API_KEY` +
  a verified `SENDGRID_FROM_EMAIL` to send for real (no-op without a key).
- **Knowledge base** brand/style ingestion (upload → extract → confirm) — needs
  migration `004_knowledge.sql` applied and `ANTHROPIC_API_KEY` set for extraction.
- **Document generation** (drafts + confirm-then-send, using confirmed style
  rules) — needs `ANTHROPIC_API_KEY` to draft and SendGrid configured to send.
  The transaction-detail "Draft a document" panel passed typecheck but has **not**
  had a live browser render yet (needs a loaded transaction).
- **Deadline tracking + reminders** — CRUD + agent tools + the idempotent scan
  endpoint. Marks logic unit-checked; routes import + register; frontend
  typechecks. **Not** yet browser-rendered or run against live Twilio/SendGrid.
  The reminder scan currently runs per-brokerage (the Dashboard "Run reminders"
  button); for unattended prod, point a scheduled job at it, or add a
  shared-secret all-brokerages variant when going live.
- **Compliance review** (locked, human-confirmed) — hybrid structural + AI
  contract review, surface-only with a confirm-gated human decision. Structural
  checks + ruleset selection unit-checked; routes register; frontend typechecks.
  **Not** yet browser-rendered; the AI contract pass needs `ANTHROPIC_API_KEY`
  (degrades to structural + checklist without it).

Outstanding setup before the above work end-to-end (all on Jeremy's side):
run `004_knowledge.sql` in the Supabase SQL editor; set `ANTHROPIC_API_KEY`,
`SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`. (Deadline reminders need no migration;
they no-op gracefully without Twilio/SendGrid.)

Not started:
- WhatsApp "actions": schedule a showing, photo upload via MMS, richer data capture.
- Phase 2 is now feature-complete (intro email, knowledge base, document
  generation, deadline reminders, compliance review) — all pending live
  end-to-end verification rather than further build.
- Phase 3: scheduling (needs Google/Microsoft calendar OAuth), comparable sales
  (Rentcast), MLS entry.

Commercialization (planned, post-build): pricing model decided — all features,
per-seat, no tiers, small base, recurring. GTM next. See memory for details.

Dev note: the only onboarded test brokerage is **"Test"**
(`b8bfa04b-e94a-4495-82d5-68f5f70830a1`); registered WhatsApp test contact is
`+14054139444` ("Jeremy").
