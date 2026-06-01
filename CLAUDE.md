# Sloane — Virtual Brokerage Assistant

B2B SaaS "virtual transaction coordinator" for real estate brokerages. One Sloane
instance per brokerage, priced by agent seats. Built from a PRD; stack is fixed
by the PRD — **do not substitute libraries**.

```
sloane/
  backend/    FastAPI + Python (Supabase over httpx)
  frontend/   React 18 + TS + Vite + Tailwind + Zustand + Axios + RHF/Zod
```

**V1 → V2.** Phases 1–3 (V1) shipped: auth, onboarding, contract extraction,
transactions, WhatsApp+voice, knowledge base, doc generation, deadlines,
compliance review, comps, scheduling, MLS listing prep. The V2 build (sections
1A–8 in `SLOANE_V2_CLAUDE_CODE.md`) layered on: inbound media on WhatsApp,
per-agent style, SMS fallback, the compliance checklist + broker review queue,
workflow tasks, inbound email threading, EMD tracking, AI disclosure +
consent, broker reporting, and a DocuSign seam. The full V2 spec is in
`SLOANE_V2_CLAUDE_CODE.md`; a condensed navigational digest is in `.context` —
read that before touching V2 areas, fall back to the full doc for prose/seeds.

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

On Windows in the agent harness, prefer running uvicorn **without `--reload`** and
restart manually after edits: the `--reload` supervisor spawns a multiprocessing
worker that, when its parent is killed, can be orphaned and keep port 8000 bound
(`taskkill` may not see it). Free it with PowerShell:
`Get-NetTCPConnection -LocalPort 8000 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }`.

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
  (`app/services/sloane_agent.py`, tool-use loop), contract field extraction
  (`app/services/ai_extract.py`), and brand/style rule extraction
  (`app/services/style_extract.py`).
- **WhatsApp (text + voice):** inbound webhook `app/api/v1/routes/whatsapp.py`
  → Twilio signature check → contact lookup → optional Whisper transcription
  (`app/services/whisper.py`) for voice memos → Sloane agent → reply via Twilio
  (`app/services/twilio_client.py`). Conversation history persisted in
  `whatsapp_messages`. Agent tools: list transactions, get details, update
  stage, add note, preview/send intro email, draft document, list/add deadlines,
  review compliance (surface-only — never approves), comparable sales,
  propose/book/list appointments, checklist/EMD/tasks, and `suggest_next_actions`
  (the proactive synthesizer — see the Web chat bullet).
- **Email (SendGrid):** `app/services/email_client.py`. The **intro email**
  introduces all parties on a transaction (buyer, seller, agents, lender, title)
  and presents Sloane as coordinator. Sent on request via the WhatsApp agent —
  `preview_intro_email` (read-only) then `send_intro_email` (requires
  `confirmed=true`); confirmation is enforced unless the brokerage's `intro-email`
  task is autonomous. Flips `transactions.intro_email_sent` to prevent
  double-sends. No-op without `SENDGRID_API_KEY`.
- **Knowledge base (brand & style):** `app/api/v1/routes/knowledge.py` +
  `style_extract.py`. Admins upload style references (letterhead, sample letter,
  template as PDF/image/.docx); Sloane proposes style rules into `knowledge_rules`
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
- **Comparable sales (Rentcast):** `app/services/rentcast.py`. Thin async client
  over Rentcast `/avm/value` (header `X-Api-Key`) — given a property address it
  returns an estimated value, value range, and comparable properties.
  `POST /transactions/{id}/comps` composes the address from the transaction and
  returns the estimate + comps (read-only, nothing persisted). Agent tool
  `get_comparable_sales` takes a free-form address (works for any property, not
  just one on file). 503 without `RENTCAST_API_KEY`. Web UI: a Comparable sales
  panel on the transaction page. A second read-only call,
  `POST /transactions/{id}/property-record` (`rentcast.get_property_record` over
  Rentcast `/properties`), returns the public record — last sale, structure, and
  assessed-value / property-tax **history** by year (county assessor data). It's
  a **separate** Rentcast request from comps (own button in the panel) to keep
  the free-tier request quota honest. Assessed value ≠ market value — the UI says
  so. Nothing persisted; same 503/502 degradation as comps.
- **Scheduling (appointments):** `app/services/scheduling.py` (pure slot math:
  state→IANA tz map + `propose_slots` over working hours/buffer, filtering
  conflicts) + `app/api/v1/routes/appointments.py`. `appointments` table, scoped
  through the parent transaction. `POST /appointments/propose` returns open slots;
  `POST /appointments/book` is **confirm-gated** (required unless the `scheduling`
  task is autonomous) and records the appointment. Agent tools
  `propose_showing_times`, `book_appointment` (confirmed gate), `list_appointments`.
  Web UI: a Scheduling panel on the transaction page. **Live calendar sync is
  behind a seam** (`app/services/calendar_provider.py`): `status`/`get_busy`/
  `create_event` currently report "not connected" / no-op. The Google/Microsoft
  OAuth flow (connect, token storage in the existing `google_calendar_token` /
  `microsoft_token` jsonb columns, refresh, real free/busy + event creation) is
  **deferred** — to be wired once the OAuth apps are registered and testable.
  Only the `calendar_provider` bodies change then; callers stay the same.
- **MLS listing prep:** `app/services/mls_extract.py` + `app/api/v1/routes/listings.py`.
  Listing side (distinct from transactions): a `listings` table (migration 005,
  brokerage-scoped). `POST /listings/extract` AI-extracts MLS fields from an
  uploaded listing packet (PDF as native document, like `ai_extract`); the agent
  reviews/edits and saves via `listings` CRUD. **Pushing to an MLS goes through a
  seam** (`app/services/mls_provider.py`): `POST /listings/{id}/push` is
  confirm-gated but reports "not connected" — there's no universal MLS write API,
  so real publishing is a **deferred, per-market integration** (e.g. Spark API for
  Flexmls markets), wired when credentials/approval exist. Web UI: a Listings page
  (`/listings`, upload→review) + listing detail/edit.
- **Web chat ("Ask Sloane"):** `app/api/v1/routes/chat.py` — `POST /chat`
  (auth-scoped) reuses the **same** `sloane_agent` tool-use loop that powers
  WhatsApp/SMS, exposed over the browser. Stateless: the client replays recent
  turns each call, so **no table/migration**. `run_sloane_agent(channel="web")`
  only swaps the tone guidance (plain text, no markdown); tools + confirmation
  gates are identical to the messaging channels. The frontend home page
  (`/`, `src/pages/Home.tsx`) is the chat-forward landing — greeting + live
  briefing (active deals / needs-review / closing-soon, pulled from the same
  endpoints as the dashboard) + chat bar with browser-native voice input
  (Web Speech API, no new dep) + a "Jump to" pill grid mirroring the nav. The
  full operational **Dashboard stays at `/dashboard`** (sidebar + every pill).
- **Proactive next actions:** `app/services/next_actions.py` is the single
  source of truth that cross-references pending workflow tasks, missing required
  checklist items, EMD status, upcoming deadlines, and missing party contacts
  across active deals into a prioritized list (each item carries a display
  `headline`/`offer` plus a click-to-act `prompt`). Two consumers share it: the
  `suggest_next_actions` agent tool (Sloane's answer to open "what should I do?"
  questions — used instead of a raw task dump) and `GET /briefing/next-actions`
  (`routes/briefing.py`, brokerage-scoped, **not** admin-only — deterministic, no
  LLM round-trip), which feeds the home page's "What I'd tackle first" cards;
  clicking a card hands its `prompt` straight to Sloane in chat. The system prompt
  also gained a "Proactive next moves" section so Sloane proposes the concrete
  next action (propose times / draft email / chase receipt) and flags missing
  party emails, rather than only offering to "mark complete." Applies across web,
  WhatsApp, and SMS (same agent loop).
- **Frontend** state in Zustand (`src/store/auth.ts`); API layer in
  `src/lib/api.ts`; routes gated behind auth + onboarding in `src/App.tsx`.
  Pages: **Home** (`/`, Ask Sloane chat + briefing), **Dashboard** (`/dashboard`),
  transactions, **Listings** (`/listings`), WhatsApp settings,
  **Brand & Style** (`/knowledge`), plus V2 pages: **Review Queue**
  (`/review`, admin only), **Reports** (`/reports`), and per-agent settings
  surfaces (style profile, channels).

### V2 systems (sections 1A–8 in `SLOANE_V2_CLAUDE_CODE.md`)

- **WhatsApp/SMS media intake (1A):** `app/services/media_extract.py` +
  inbound webhook handlers. Twilio media (`MediaUrl0`/`MediaContentType0`) is
  downloaded with Basic Auth, HEIC/HEIF → JPEG via pillow-heif, PDFs/images
  routed through the existing 25-field extraction. Extracted fields land in
  `pending_whatsapp_transactions` (2h TTL); agent replies YES/correction to
  commit. 15MB cap; duplicate-address warning; unknown sender → register first.
- **Per-agent style (1B):** `knowledge_rules.agent_id` + `knowledge_documents.agent_id`
  added (migration 007). `get_confirmed_knowledge_rules(brokerage_id, agent_id)`
  merges brokerage-wide (agent_id NULL) with agent-specific; agent rules win on
  conflict. `agents.py` route exposes per-agent style CRUD. `whatsapp_contacts.agent_id`
  carries the lookup from WhatsApp into doc generation.
- **SMS fallback (1C):** `agent_channels` table (migration 008) supersedes the
  WhatsApp-only contact model — `channel` is `'whatsapp'` or `'sms'`, existing
  `whatsapp_contacts` migrated in. `app/api/v1/routes/sms.py` mirrors the WhatsApp
  inbound flow (signature check, contact lookup, same tool-use loop). Text-only on
  SMS — no voice memo, no media. Replies use `TWILIO_SMS_FROM` (standard number,
  not WhatsApp sender).
- **Compliance checklist (2A):** `compliance_templates` + `compliance_template_items`
  + `transaction_checklist_items` (migration 009). System defaults seeded on first
  run (buy-side 16 items, list-side 16 items). `app/services/compliance_checklist.py`
  auto-instantiates on transaction creation, picking the best matching template
  (brokerage custom > system default, matching state). `app/api/v1/routes/checklist.py`
  exposes per-transaction CRUD; `checklist_pct` is computed server-side and joined into
  transaction list responses. Distinct from `app/services/compliance.py` — that AI
  pass reads the contract for issues; this tracks whether required documents are in
  the file. WhatsApp tools added for "what's missing on 123 Main?" and confirm-gated
  "mark inspection complete."
- **Broker review queue (2B):** `app/api/v1/routes/broker.py` →
  `GET /broker/review-queue` returns four buckets: `compliance_attention`,
  `closing_soon_incomplete` (<5d AND <80% checklist), `overdue_deadlines`,
  `stale_transactions` (no activity 7+ days via `transactions.last_activity_at`,
  added in migration 010). Admin-only. Each row carries a one-line reason string.
  Dashboard banner surfaces totals; the Review Queue page (`/review`) has the
  four collapsible sections + inline review-note textarea + 5-min auto-refresh.
- **Workflow tasks (3):** `workflow_templates` + `workflow_steps` + `transaction_tasks`
  (migration 011). `app/services/workflow.py` generates tasks on transaction creation,
  stage transitions, and within the deadline reminder scan (`days_before_deadline`
  trigger). Trigger types: `stage_entry`, `days_before_deadline`, `days_after_stage`,
  `manual`. `app/api/v1/routes/tasks.py` exposes CRUD; WhatsApp `get_pending_tasks`
  groups by urgency (overdue/today/this week/upcoming); "mark X done" is confirm-gated.
- **Inbound email threading (4):** `transaction_emails` (migration 012) logs both
  directions. Outbound emails set `Reply-To: tx-{transaction_id}@reply.heysloane.io`
  (DNS: `reply.heysloane.io` MX → `mx.sendgrid.net`, configured in `DEPLOYMENT.md`).
  `POST /api/v1/email/inbound` (public, validates SendGrid Inbound Parse signature
  via `SENDGRID_WEBHOOK_KEY`) extracts the transaction_id from the recipient address,
  verifies brokerage ownership, stores the message, and WhatsApp-nudges **the deal's
  agent** — `transactions.agent_id` → the matching `agent_channels` contact (falls
  back to the brokerage's contacts only when the deal is unassigned; an agent with no
  registered number simply isn't nudged). **Reply routing is a brokerage setting**
  (`brokerages.forward_replies_to_agent`, migration 016, default off, edited on the
  Messaging page's "Reply Handling" card via `GET`/`PUT /whatsapp/settings`): when on,
  each inbound reply is also forwarded to the agent's email (`agents.email`, falling
  back to the deal's `listing_agent_email`/`selling_agent_email`) with `Reply-To` set
  to the per-transaction address so the agent can reply from their inbox and Sloane
  still logs the thread (the agent's own replies aren't echoed back). All existing
  SendGrid sends log to `transaction_emails` with `direction='outbound'`. Reply UX: the
  Communications tab opens a draft via the doc-generation flow — human reviews and
  confirms send. **Never auto-reply.**
- **EMD tracking (5):** Columns added to `transactions` (migration 013) —
  `emd_amount`, `emd_due_date`, `emd_received`, `emd_received_date`,
  `emd_receipt_document_url`, `emd_held_by` ∈ {title, brokerage, escrow, other},
  `emd_notes`. Contract extraction wires `earnest_money` → `emd_amount`; an EMD
  due date in the contract is extracted when present. Review queue gains an
  `emd_overdue` category (top priority). UI is an EMD card on transaction detail;
  receipt uploads land in the `compliance-docs` bucket. **Receipt tracking only —
  no calculations, no disbursements, no trust math.** UI label: "EMD Receipt Tracking."
- **AI disclosure + party consent (6):** `party_consents` table (migration 014)
  + `brokerages.ai_disclosure_enabled` / `ai_disclosure_text` /
  `request_ai_consent`. Disclosure footer is appended to every outbound email when
  enabled (small, muted, below sig). Optional HMAC-signed consent link
  (`CONSENT_SECRET`) — `GET /api/v1/consent/{transaction_id}/{party_role}?token=...`
  → verify → record → simple HTML thank-you. `app/api/v1/routes/consent.py` +
  `app/services/consent.py`. Compliance Settings UI exposes the toggles + editable
  disclosure text (with a "have your attorney review" warning).
- **Broker reporting (7):** `app/services/reporting.py` +
  `app/api/v1/routes/reports.py`. `GET /reports/broker-summary?period=month|quarter|ytd`
  returns pipeline (active/by_stage/closing_this_month), at_risk, production
  (closed_count, closed_volume, avg_days_to_close, agent_breakdown), and compliance
  (avg_checklist_completion_at_close, open items). `transactions.closed_at` was added
  (migration 015) and is set on stage → 'closed' so `avg_days_to_close` is computable.
  `GET /reports/transactions-export?period=...` returns CSV. Reports page (`/reports`)
  has three sections (Pipeline / Production / Compliance Health) + a lightweight
  CSS by-stage bar chart (no recharts dependency) + period selector. No
  drill-down, no custom date ranges in V1.
- **DocuSign (8) — deferred behind a seam.** `app/services/docusign_provider.py`
  reports "not connected"; `POST /api/v1/transactions/:id/docusign/send` and the
  Connect webhook are stubbed. Same pattern as `calendar_provider` and
  `mls_provider` — only the seam bodies change when DocuSign developer credentials
  + production partner review are in hand. **Scoping constraint: Sloane is not a
  forms library** — DocuSign sends documents Sloane already has (extracted
  contracts, generated correspondence). State association form distribution
  requires NAR/state licensing (see `BLOCKERS.md`, Hard Limit 1).

## Database

Migrations in `backend/migrations/`, run **in order** via the Supabase SQL
Editor (paste file *contents*, not the path). Every new migration must:
new tables carry `id uuid DEFAULT gen_random_uuid() PRIMARY KEY`, a `brokerage_id`
FK (or scope via the parent transaction's `brokerage_id`), `created_at timestamptz
DEFAULT now()`, and an RLS policy scoped by `brokerage_id`.

V1 (Phases 1–3):
- `001_*` initial schema (brokerages, transactions, RLS helpers, deadlines)
- `002_*` `onboarding_completed`
- `003_whatsapp.sql` `whatsapp_contacts`, `whatsapp_messages`, `transactions.notes`
- `004_knowledge.sql` `knowledge_documents` + `knowledge_rules.document_id`
- `005_listings.sql` `listings` table (MLS listing prep) + RLS

V2 (sections 1A–7 in `SLOANE_V2_CLAUDE_CODE.md`):
- `006_pending_whatsapp_transactions.sql` — 2h holding area for inbound media
  extractions before YES/correction commits (Section 1A)
- `007_agent_style.sql` — `agent_id` on `knowledge_rules` + `knowledge_documents`
  + `whatsapp_contacts` (Section 1B). **Requires 004 applied first**
- `008_agent_channels.sql` — `agent_channels` table + migrate `whatsapp_contacts`
  rows in with channel='whatsapp' (Section 1C)
- `009_compliance_checklist.sql` — templates + items + per-transaction instances,
  plus system-default seed rows (Section 2A)
- `010_review_queue.sql` — `transactions.last_activity_at` + `deadlines.resolved`
  / `resolved_note` (Section 2B)
- `011_workflow_tasks.sql` — `workflow_templates` + `workflow_steps` +
  `transaction_tasks` + system-default buy-side seed (Section 3)
- `012_transaction_emails.sql` — outbound + inbound email log (Section 4)
- `013_emd_tracking.sql` — EMD columns on `transactions` (Section 5)
- `014_party_consents.sql` — `party_consents` + brokerage AI-disclosure settings
  (Section 6)
- `015_reporting.sql` — `transactions.closed_at` set on stage → closed (Section 7)

Post-V2 (web-app work):
- `016_reply_forwarding.sql` — `brokerages.forward_replies_to_agent` boolean
  (default false): forward inbound email replies to the deal's agent. See the
  Inbound email threading (4) bullet.
- `017_doc_routing.sql` — `doc_routing_rules` + `pending_doc_routes` (Autonomy
  task `doc-routing`). See the Document routing bullet.

**Apply in strict order.** 007 depends on 004 (`knowledge_documents` must exist);
008 depends on 007 (its data-copy reads `whatsapp_contacts.agent_id`). If a paste
fails with `relation "X" does not exist`, the most likely cause is a skipped earlier
migration — `create table if not exists` + `add column if not exists` guards make it
safe to re-paste 004/005 if you're unsure they ran.

**Gotcha (learned the hard way with 008):** if the SQL editor reports *success* but a
table is still missing — PostgREST returns `PGRST205 ... "Could not find the table
'public.X' in the schema cache"` — a statement *after* the `create table` in that file
likely errored and the editor's single transaction rolled the whole thing back (the
error can scroll off). Confirm with `select to_regclass('public.X');` (returns `NULL`
when truly absent). Fix: run the bare `create table …` on its own, then the
indexes/insert/RLS in a second run so a later failure can't undo the table. Supabase
auto-reloads PostgREST's cache on DDL; if it lags, run `NOTIFY pgrst, 'reload schema';`
(the dashboard no longer has a reload button).

Deadline tracking + reminders themselves need **no new migration** — the
`deadlines` table (with `due_date`, `responsible_parties`, and the
`reminder_5day/2day/day_sent` flags) is already in `001`. 010 only adds the
`resolved` flag the review queue uses to filter out handled overdue deadlines.

## Env vars (names only — never print values)

V1: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (Whisper),
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
`TWILIO_SKIP_VALIDATION`, `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` (intro
email; the from address must be a verified SendGrid sender), `RENTCAST_API_KEY`
(comparable sales).

V2: `TWILIO_SMS_FROM` (Section 1C — standard Twilio number, not the WhatsApp
sender), `SENDGRID_WEBHOOK_KEY` (Section 4 — validates Inbound Parse posts),
`CONSENT_SECRET` (Section 6 — HMAC key for consent-link tokens).

Deferred (built behind seams, wired when credentials/approval exist):
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`,
`MICROSOFT_CLIENT_ID`/`MICROSOFT_CLIENT_SECRET` (calendar OAuth),
`DOCUSIGN_CLIENT_ID`/`DOCUSIGN_CLIENT_SECRET` (Section 8 e-signature),
`REDIS_URL`.

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
- Confirmation gates required for: email send, document send, compliance decision,
  appointment booking, listing push, deadline party notification, EMD mark-received,
  DocuSign envelope send. Don't add a flag to bypass any of these.
- Never let compliance review run autonomously — always surface findings to the agent.
- EMD is receipt tracking only. No calculations, disbursements, or trust math —
  Sloane is not accounting software. UI label is "EMD Receipt Tracking."
- Never auto-reply to inbound emails — Sloane drafts on request, human reviews and sends.
- Build phases in spec order (V1 = Phases 1–3, V2 = sections 1A–8); resist scope creep.
- **Sloane's name is fixed** ("Sloane", not user-editable) and Sloane is referred to as
  **she/her** in copy, never "it".
- **Copy style:** em dashes are allowed only as a headline→description separator (e.g.
  "Manage deals — pipeline summary…"); keep them out of body prose. Reword instead.
- When inspecting `.env`, show only key names + char counts, never the secret values.
- Deferred integrations (calendar OAuth, MLS publishing, DocuSign) live behind
  seams — don't wire them blind. Only the seam bodies change when credentials
  arrive. See `BLOCKERS.md` for the business/legal blockers.

## Status & next up

### Sloane proactivity + fixes — branch `sloane-proactivity-and-fixes` (not yet merged)

Latest session, **on a feature branch off `master`, browser-verified in the dev
brokerage but not yet pushed/merged**. Three commits:

- **Sloane proposes concrete next actions, not lists.** Previously she answered
  "what's overdue?" by enumerating tasks and only offering to mark them complete.
  Now: a "Proactive next moves" block in the system prompt (infer the next action
  per item — propose times / draft email / chase receipt — and flag missing party
  emails), a `suggest_next_actions` agent tool, the shared
  `services/next_actions.py` synthesizer, the `GET /briefing/next-actions`
  endpoint, and the home page's "What I'd tackle first" cards (click → hands the
  prompt to Sloane). See the Web chat / Proactive next actions architecture
  bullets. Verified live: briefing renders; clicking the inspection card had Sloane
  propose real slots.
- **Review queue bucket split.** `closing_soon_incomplete` no longer catches
  deals whose closing date is in the *past*; a new `past_closing_not_closed`
  bucket (red) flags active deals past their closing date (stage never moved).
  Same off-by-direction fix in `reporting.py`'s `at_risk` count.
- **§4 email fixes.** `doc_routing._send_route` now logs its sends to
  `transaction_emails` (routed PDFs were missing from the thread); the
  Communications panel renders inbound HTML bodies in a sandboxed iframe (was
  text-only).

Next step when resuming: push the branch + open a PR, or keep building (e.g.
refresh the briefing cards after Sloane acts — they're fetched once on load).

### Web app (post-V2) — shipped to `master`, live-verified

A round of web-app work on top of V1+V2, all merged to `master` and exercised
against live services in the dev brokerage:

- **"Ask Sloane" web chat** — `app/api/v1/routes/chat.py` (`POST /chat`) reuses the
  `sloane_agent` tool-use loop over the browser (`channel="web"`, plain-text tone;
  same tools + confirmation gates). Stateless, no migration. Verified end-to-end
  (real deal pulled across multiple tools).
- **Chat-forward home (`/`, `Home.tsx`)** — greeting + live briefing, chat hero with
  browser-native voice input (Web Speech API), an animated typewriter placeholder
  cycling **contextual** suggestions built client-side from the loaded transactions
  (EMD-due / what's-missing / status / closing-countdown + capability prompts), a
  "Jump to" pill grid, and a staggered fade-up entrance (`animate-fade-up` in
  `index.css`, 150px / 1.7s, `prefers-reduced-motion`-aware). The sidebar is hidden
  on the bare launcher (pills are the nav; `useUiStore.chatStarted` gates it in
  `AppShell`) and returns once a chat starts or you open any page. `/dashboard` is
  unchanged and one click away.
- **UI redesign** — dark-default theme + token system (`index.css`, `tailwind.config.js`),
  left sidebar shell (`AppShell.tsx`, lucide icons), transaction-page section nav
  (`SectionNav.tsx`).
- **Reply routing** — inbound email replies now nudge the deal's agent (not the whole
  brokerage) and can optionally forward to the agent's inbox. See Inbound email
  threading (4) + migration 016. Verified: toggle saves; nudge targeting needs the
  agent's number linked to their agent record (`agent_channels.agent_id`) and the deal
  assigned (`transactions.agent_id`) to resolve a specific recipient.
- **Autonomy settings page** (`/settings/autonomy`, `AutonomySettings.tsx`; labelled
  "Autonomy" in the sidebar) — post-onboarding editing of the task-autonomy toggles
  (`GET`/`PUT /autonomy` in `routes/autonomy.py`, same `task_autonomy` table + rules as
  onboarding; compliance stays locked off). `TaskToggle` was extracted to
  `components/TaskToggle.tsx` and is shared with the onboarding wizard. The `intro-email`
  executor now honours autonomy at the executor level (no longer prompt-only). Verified:
  load + save round-trip.
- **Document routing** (Autonomy task `doc-routing`, migration 017) — the previously
  inert `doc-routing` toggle now does something. `doc_routing_rules` (per-brokerage
  config: `trigger_stage` + `recipient_roles` + `document_source`) and
  `pending_doc_routes` (the one-click send queue) back it. On a transaction entering a
  stage (creation + stage PATCH, alongside `generate_stage_tasks`),
  `services/doc_routing.py` matches enabled rules, resolves roles to party emails on the
  deal, and grabs the contract PDF from the `contracts` bucket. If the `doc-routing`
  task is **autonomous**, it emails immediately (same opt-in gate as `intro-email`);
  otherwise it queues a `pending_doc_routes` row and WhatsApp-nudges the deal's agent.
  Sending is **confirm-gated** — `POST /doc-routing/pending/{id}/send` requires
  `confirmed=true` (no bypass flag), `/dismiss` drops it. `send_email` gained an
  `attachments` param for the PDF. Rules CRUD + queue live on the Autonomy page
  (`components/DocRoutingSettings.tsx`). VALID_STAGES are the real transaction stages
  (`under_contract`/`pending`/`closed`/`cancelled`), not deadline labels. Verified in
  the browser: rules CRUD round-trip; queue/send paths are import- + unit-checked
  (a live send needs SendGrid + a contract on file).
- **Assistant name is fixed to "Sloane"** — the onboarding rename field was removed and
  the backend hardcodes `assistant_name="Sloane"`. Refer to Sloane as she/her in copy.

### V1 (Phases 1–3)

Done & tested: scaffold, auth, onboarding (5 steps), contract PDF extraction +
transactions, and the full **WhatsApp text+voice channel** (register agent
numbers, text/voice-memo Sloane, agent acts on transactions).

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
- **Comparable sales (Rentcast)** — first Phase 3 feature. Address composer +
  response parser unit-checked; route registers; frontend typechecks; no-key path
  returns a clean 503. **Not** yet run against the live Rentcast API — needs
  `RENTCAST_API_KEY` (a key you can grab instantly from rentcast.io).
- **Scheduling (appointments)** — slot proposal + booking + confirmation gate +
  agent tools + Scheduling panel. Slot math unit-checked (buffer, work-hour
  bounds, past-time filtering, tz); routes register; frontend typechecks. Works
  today against working hours + local appointments. **Deferred:** live
  Google/Microsoft calendar sync (OAuth connect + free/busy + event creation) —
  built behind the `calendar_provider` seam, to be wired when the OAuth apps are
  registered so it can be verified against the real providers.
- **MLS listing prep** — `listings` table + AI packet extraction + Listings
  page/detail + confirm-gated push (no-op seam). Field cleaner unit-checked;
  routes register; frontend typechecks. Needs `005_listings.sql` applied +
  `ANTHROPIC_API_KEY` for extraction. **Deferred:** real MLS publishing — a
  per-market write integration behind the `mls_provider` seam (no universal MLS
  write API exists).

### V2 (sections 1A–7 in `SLOANE_V2_CLAUDE_CODE.md`)

All V2 build sections except DocuSign (8) have code committed; routes register,
typechecks pass, unit checks on the deterministic pieces (template instantiation,
checklist %, trigger matching, slot math, EMD overdue, reporting math) pass.
**Pending live end-to-end verification** (keys + migrations 006–015 applied):

- **1A WhatsApp/SMS media intake** — needs Twilio configured and the dev brokerage
  to test a real PDF/photo MMS round-trip. Image path uses Claude image blocks
  (no separate key beyond `ANTHROPIC_API_KEY`).
- **1B Per-agent style** — needs 007 applied (which itself depends on 004).
  Browser flow on the agent profile page not yet exercised end-to-end.
- **1C SMS fallback** — needs `TWILIO_SMS_FROM` set + the SMS-enabled Twilio
  number's webhook pointed at `/api/v1/sms/inbound`.
- **2A Compliance checklist** — needs 009 applied (seeds system defaults on
  first run). Browser walk-through of the Compliance File panel not yet done.
- **2B Review queue** — needs 010 applied (adds `last_activity_at` and
  `deadlines.resolved`). The `/review` page hasn't had a live render yet.
- **3 Workflow tasks** — needs 011 applied (seeds buy-side workflow). Trigger
  hooks wired into transaction creation, stage PATCH, and the reminder scan.
  WhatsApp `get_pending_tasks` tool registered.
- **4 Inbound email threading** — needs 012 + `SENDGRID_WEBHOOK_KEY` + DNS
  (`reply.heysloane.io` MX → `mx.sendgrid.net`) + SendGrid Inbound Parse pointed
  at `/api/v1/email/inbound`. **DNS is the gating step on Jeremy's side.**
- **5 EMD tracking** — needs 013 applied. Already feeds the review queue.
- **6 AI disclosure + consent** — needs 014 applied + `CONSENT_SECRET` set
  (the disclosure footer works without consent links; only the link path needs
  the secret).
- **7 Broker reporting** — needs 015 applied (adds `closed_at` for
  `avg_days_to_close`). `/reports` page registered.

### Outstanding setup (all on Jeremy's side)

Migrations **001 → 016 are all applied in the dev brokerage** (008 and 016 were
applied during the post-V2 web-app work). For a fresh environment, apply them in
order via the Supabase SQL editor (paste each file's contents) — mind the 008
caveat in the Database section. Set new env vars where their feature is being
exercised: `TWILIO_SMS_FROM` (1C), `SENDGRID_WEBHOOK_KEY` (4), `CONSENT_SECRET` (6).
V1 keys (`ANTHROPIC_API_KEY`, `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL`) cover most
V2 sections too. DNS for `reply.heysloane.io` is the long-lead item — it's the gating
step for Section 4 inbound replies **and** for the reply-forwarding toggle actually
firing (forwarding only runs on a real inbound reply).

### Deferred (built behind seams, do not build blind)

- **Calendar OAuth (V1)** — Google/Microsoft connect + token refresh + real
  free/busy + event creation. Wire when the OAuth apps are registered. Only
  `calendar_provider` bodies change.
- **MLS publishing (V1)** — per-beachhead-market write integration behind
  `mls_provider`. No universal MLS write API.
- **DocuSign e-signature (V2 Section 8)** — `docusign_provider.py` seam ships
  "not connected"; OAuth + envelope creation + Connect webhook wire in once the
  developer integration key is approved and production partner review is in
  hand. **Scoping rule:** Sloane is not a forms library — DocuSign sends
  documents Sloane already has (extracted contracts, generated correspondence),
  not state association forms.

Hard limits (business/legal, not engineering — see `BLOCKERS.md`): state
association form distribution, MLS write licensing, Google/Microsoft OAuth
verification, WhatsApp Business API production approval, AI reliability in
compliance review (the human gate is load-bearing — never make it autonomous),
SOC 2 for NPI handling.

Commercialization (planned, post-build): pricing model decided — all features,
per-seat, no tiers, small base, recurring. GTM next. See memory for details.

Dev note: the only onboarded test brokerage is **"Test"**
(`b8bfa04b-e94a-4495-82d5-68f5f70830a1`); registered WhatsApp/SMS test contact is
`+14054139444` ("Jeremy", not yet linked to an agent record). The brokerage admin
login is `jeremymdsn@gmail.com`; its password can be (re)set via the Supabase admin
API with the service-role key (`PUT /auth/v1/admin/users/{id}`) — the current dev
password is in agent memory, not committed here.
