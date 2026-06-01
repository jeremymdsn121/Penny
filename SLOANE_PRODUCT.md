# Sloane — Virtual Transaction Coordinator
### Product Document for Critique & Pre-Commercialization Review
*Intended audience: AI critique partner or expert human reviewer. Goal: surface product gaps, missing capabilities, competitive weaknesses, and anything a real estate professional would find lacking before Sloane goes to market.*

---

## What Sloane Is

Sloane is a virtual transaction coordinator (TC) embedded inside a real estate brokerage. It is not a dashboard, a CRM add-on, or a chatbot. It is a staff member — one that works every channel the brokerage already uses, never forgets a deadline, never sleeps, and is onboarded once to serve every agent on the team.

The brokerage's experience of Sloane is threefold:

1. **WhatsApp** — agents talk to Sloane the way they'd talk to a human TC: text a question, voice-memo an update, get a real answer.
2. **Web dashboard** — the brokerage admin manages transactions, uploads contracts, reviews compliance, drafts correspondence, tracks deadlines, and preps listings from a browser.
3. **Email** — Sloane can introduce itself to all parties on a deal (buyer, seller, both agents, lender, title) and send branded correspondence on the brokerage's behalf.

Every action that has external consequences requires a human to confirm it first. Sloane never sends an email, books an appointment, or pushes a listing without a deliberate "yes." This is not a limitation — it is the product's core trust contract with the brokerage.

---

## Who It Serves

- **Primary buyer:** real estate brokerage owners (broker-of-record) who manage a team of agents and currently pay a human TC per file or per month.
- **Daily users:** agents on that team, who interact primarily through WhatsApp.
- **Indirect beneficiaries:** transaction parties (buyers, sellers, other-side agents, lenders, title reps) who receive communications Sloane drafts.

Sloane is priced per agent seat, all features included, recurring. There are no tiers and no feature gating. A small brokerage with three agents gets the same Sloane as a 30-agent office.

---

## How a Brokerage Gets Started

1. **Signup & onboarding wizard (5 steps):** brokerage name, state, contact info, assistant name (they can rename Sloane), WhatsApp number registration.
2. **Brand & style upload:** the admin drops in a letterhead, a sample letter, or a template. Sloane reads it, proposes style rules ("always use formal salutations," "sign off with the broker's name"), and the admin confirms each rule. Confirmed rules are injected into every document Sloane drafts from then on.
3. **First contract:** the admin or agent uploads a purchase contract PDF. Sloane extracts ~25 fields (buyer/seller names, address, price, contingency dates, closing date, agent contacts, lender, title company) and pre-populates the transaction. The agent reviews, corrects if needed, and the transaction is live.

---

## Feature Inventory

### 1. WhatsApp Channel (Text + Voice)

**What it does:** Agents text Sloane on WhatsApp. Sloane understands natural language, has context on every active transaction, and responds in plain text. Agents can also send voice memos — Sloane transcribes them (OpenAI Whisper) and processes them the same way.

**Agent-facing capabilities via WhatsApp:**
- List transactions and get deal summaries
- Ask about a specific transaction (parties, dates, stage, notes)
- Update a transaction's stage ("mark 123 Main St as pending")
- Add a note to a transaction
- Ask Sloane to preview or send an intro email to all parties on a deal
- Request a drafted document (status update, cover letter, follow-up, congratulations, custom)
- Ask about upcoming deadlines
- Add a deadline to a transaction
- Ask Sloane to propose showing times (Sloane checks availability based on brokerage work hours and existing appointments, proposes up to 8 slots)
- Book a showing slot (confirm-gated)
- Ask about existing appointments
- Request a compliance review of a transaction's contract
- Get comparable sales and an AVM estimate for a property

**Confirmation gate:** Any action with external effect (send email, book appointment, push listing) requires the agent to reply with explicit confirmation before Sloane acts. This prevents accidental sends.

**Autonomy exceptions:** For mature brokerages, the admin can mark specific tasks as autonomous (e.g., "party deadline notifications"). The WhatsApp agent respects this — if a task is autonomous, it acts without asking. The compliance task can never be made autonomous (hardcoded lock).

**Under the hood:** Inbound POST webhook from Twilio → signature validation → contact lookup (maps WhatsApp number to brokerage) → optional Whisper transcription if the message contains audio → Anthropic claude-sonnet (tool-use loop, up to 5 rounds) → Twilio reply. Conversation history is persisted per WhatsApp contact in `whatsapp_messages`.

---

### 2. Contract PDF Extraction

**What it does:** The agent or admin drops a purchase contract PDF into the "New Transaction" flow. Sloane sends it to the AI as a native document (not OCR'd text) and extracts ~25 structured fields, returning a pre-populated transaction form for human review before anything is saved.

**Fields extracted:** buyer name/email/phone, seller name/email/phone, property address/city/state/zip, purchase price, earnest money, closing date, inspection deadline, financing deadline, appraisal deadline, title deadline, agent on each side (name/email/phone), lender name, title company, and transaction stage.

**Honesty constraint:** The AI is instructed to return empty string for any field it cannot confidently locate. It never guesses. The human reviews the form before submitting.

**Under the hood:** PDF uploaded to Supabase Storage (`contracts` bucket) → bytes passed to Anthropic as a `document` content block → strict JSON extraction prompt → response parsed and cleaned → returned to the frontend without touching the database until the human submits.

---

### 3. Transaction Management

**What it does:** The full lifecycle of a real estate transaction, from under-contract through closed or cancelled.

**Data model core fields:** address, buyer/seller info, all party contacts (agents, lender, title), purchase price, earnest money, all contingency and closing dates, stage, notes, intro_email_sent flag, compliance_status, contract PDF URL.

**Web UI capabilities:**
- View and edit all fields
- Stage transitions (under_contract → pending → closed, with cancel path)
- Add free-text notes
- See all panels (deadlines, scheduling, compliance, comps, documents) in one scrollable view

**Agent count:** The dashboard shows total active transactions and lists them with address, buyer name, closing date, and stage badge. Clicking navigates to the full transaction detail.

---

### 4. Intro Email (Party Introduction)

**What it does:** When a deal goes under contract, Sloane can introduce itself — and all the parties — to everyone involved. The email is addressed to buyer, seller, buyer's agent, listing agent, lender, and title rep simultaneously. It presents Sloane as the transaction coordinator and establishes the communication channel.

**Workflow:**
1. Agent (via WhatsApp) asks Sloane to preview the intro email for a transaction.
2. Sloane assembles the party list from the transaction record, drafts the email, and shows a preview in the WhatsApp conversation.
3. Agent replies to confirm.
4. Sloane sends via SendGrid and flips `intro_email_sent` to prevent double-sends.

**Autonomy exception:** If the `intro-email` task is marked autonomous, Sloane skips the preview step and sends directly on request.

**Under the hood:** `email_client.py` → `gather_parties_by_keys()` resolves party records → branded HTML assembled → `SendGrid` API call → `intro_email_sent` flag set in DB.

---

### 5. Knowledge Base (Brand & Style)

**What it does:** Sloane learns the brokerage's voice, visual style, and correspondence conventions from reference documents uploaded by the admin. Those rules are then injected into every AI prompt that generates correspondence.

**Workflow:**
1. Admin uploads a letterhead, sample letter, or branded template (PDF, image, or .docx).
2. File stored in Supabase Storage (`knowledge-docs` bucket).
3. Sloane reads the document and proposes a set of style rules (e.g., "use 'Warm regards' as the sign-off," "always include the agent's license number in the footer," "do not use contractions in formal correspondence").
4. Rules are surfaced in the web UI as "unconfirmed." Admin confirms or rejects each.
5. Confirmed rules are fetched and prepended to document generation and email prompts from that point forward.

**Under the hood:** `style_extract.py` → Anthropic document extraction → JSON array of rules → stored in `knowledge_rules` table with `confirmed=false` → admin action flips `confirmed`. `get_confirmed_knowledge_rules(brokerage_id)` is called at generation time.

---

### 6. Document Generation

**What it does:** Sloane drafts formal correspondence for any transaction — in the brokerage's confirmed voice and style.

**Document types:** status update, cover letter, follow-up, congratulations, custom (free-form prompt).

**Workflow (web UI):**
1. Agent selects document type and optional custom instructions.
2. Sloane drafts the document, incorporating confirmed style rules and transaction details.
3. Agent reviews and edits the draft directly in the UI.
4. Agent confirms send → Sloane emails the document via SendGrid.

**Draft-only path (WhatsApp):** Via WhatsApp, Sloane can draft a document and return the text in-chat. Sending from WhatsApp is not currently supported (would require a separate confirmation flow in the chat thread).

**Under the hood:** `doc_generate.py` → `get_confirmed_knowledge_rules()` prepended to prompt → Anthropic claude-sonnet with transaction context + document type → structured JSON `{subject, body}` → parsed (strict=False to tolerate multi-line) → returned as draft. `POST /transactions/:id/send-document` (confirm-gated) → SendGrid.

---

### 7. Deadline Tracking & Reminders

**What it does:** Sloane tracks every important date on a transaction and reminds the agent (and optionally all responsible parties) as deadlines approach.

**Deadline structure:** each deadline belongs to a transaction and has a label, date, list of responsible parties (buyer, seller, buyer's agent, listing agent, lender, title), and per-threshold reminder flags.

**Reminder thresholds:** same-day (0 days), 2-day warning, 5-day warning. Sloane sends the most urgent uncommunicated reminder — if a deadline crossed the 5-day mark unseen, it fires the 5-day message; the 2-day fires separately when that threshold is crossed; same-day fires on the day. Each fires only once (flags flipped after send).

**Two reminder paths:**
1. **Agent nudge (always):** Sloane sends a WhatsApp message to the brokerage's registered agent number describing the approaching deadline and what action is needed.
2. **Party notification (autonomy-gated):** Sloane emails the responsible parties directly. This only fires if the `deadline-reminders` task is marked autonomous for that brokerage. If not, the admin must trigger party notifications explicitly (confirm-gated button in the web UI).

**Reminder trigger:** currently a manually triggered HTTP endpoint (`POST /deadlines/run-reminders`) with a "⏰ Run reminders" button on the Dashboard. In production, this would be called by an external cron (e.g., GitHub Actions schedule, Render cron job, etc.) — no in-process scheduler.

**Under the hood:** `deadline_reminders.py` → `run_reminders(brokerage_id)` → scans all deadlines across brokerage transactions → `due_marks()` evaluates thresholds → WhatsApp nudge via `twilio_client.py` → optional party email via `email_client.py` → flags updated in DB.

---

### 8. Compliance Review

**What it does:** Sloane reviews a transaction's contract against state-specific real estate compliance checklists and returns a structured finding report for a human to evaluate. It never makes a compliance determination — it surfaces findings, and a human approves or flags.

**Two layers of review:**
1. **Structural checks (always run, no AI needed):** verifies that required fields are populated (buyer/seller name, address, price, closing date, all agent contacts), that the closing date hasn't already passed, and that a contract PDF is attached.
2. **AI review (runs when contract PDF + Anthropic key are present):** Sloane reads the full contract as a native document and evaluates it against a per-state ruleset. State rulesets currently exist for DEFAULT (universal), TX, SC, FL, CA, and NY. Each ruleset is a list of verification questions (e.g., "Is the earnest money amount specified?", "Is the financing contingency period stated?"). The AI returns a status (`compliant`, `non_compliant`, `unclear`, `not_applicable`) and a note for each.

**Output:** findings list (with severity: error, warning, info), annotated state checklist with AI statuses, a suggested `compliance_status` (not_reviewed, needs_attention, approved). Only the `compliance_status` field is persisted — findings are recomputed on demand.

**Human gate:** The admin reviews findings in the web UI and clicks "Approve" or "Flag as needing attention." Both are confirm-gated. The compliance task cannot be made autonomous under any circumstances (hardcoded lock).

**Under the hood:** `compliance.py` → `run_structural_checks()` (deterministic) → `ai_review_contract()` (Anthropic, contract PDF as document block, strict JSON response) → `review_transaction()` merges + returns. Route: `POST /transactions/:id/compliance-review` (read-only, does not persist). `POST /transactions/:id/compliance-decision` (confirm-gated, persists `compliance_status`).

---

### 9. Comparable Sales (Market Valuation)

**What it does:** Sloane fetches an automated valuation model (AVM) estimate and a set of recent comparable sales for any transaction property, directly inside the transaction view.

**Output:** estimated value, low/high range, and up to 6 comparables (address, sale price, beds/baths, square footage, distance from subject).

**Under the hood:** `rentcast.py` → `compose_address(tx)` builds a full address string → `GET /avm/value` on Rentcast API with `X-Api-Key` header → response parsed → comparables cleaned and returned. 503 if `RENTCAST_API_KEY` is not configured.

**WhatsApp path:** Agent can ask "what are comps for 123 Main St?" — Sloane calls `get_comparable_sales` tool with a free-form address (not requiring an existing transaction).

---

### 10. Scheduling & Appointments

**What it does:** Sloane proposes available showing times based on the brokerage's work hours, existing appointment load, and optional calendar sync — then books confirmed appointments.

**Slot proposal:** Given a starting day and duration (default 30 minutes), Sloane generates candidate slots across the next N working days within configured work hours, excludes slots that collide with existing Sloane-managed appointments (plus future: live calendar busy intervals), and returns up to 8 options in the brokerage's local timezone (resolved from state).

**Confirmation gate:** The agent selects a slot from WhatsApp or the web UI. Sloane asks for confirmation. On confirm, Sloane inserts the appointment record, and (once calendar sync is live) creates a calendar event.

**Calendar sync seam:** `calendar_provider.py` is a documented no-op stub. `get_busy()` returns an empty list; `create_event()` does nothing. The OAuth flow (Google/Microsoft app registration, token exchange, refresh) is deferred until credentials are available. Slot proposal and appointment CRUD work now without live calendar sync.

**Under the hood:** `scheduling.py` → `propose_slots()` pure function (state→IANA tz via `STATE_TIMEZONES`, `zoneinfo`, buffer padding, busy interval filtering) → `appointments` table (CRUD) → `calendar_provider.py` stubs (future: real OAuth calls).

---

### 11. MLS Listing Preparation

**What it does:** Sloane reads a listing packet PDF and extracts the fields required to enter a property into the MLS — dramatically reducing the manual data-entry step for a listing agent.

**Fields extracted (23):** address/city/state/zip, property_type, list_price, bedrooms, bathrooms, square_footage, lot_size_sqft, year_built, stories, garage_spaces, hoa_fee, hoa_frequency, annual_taxes, parcel_number, mls_number, school_district, public_remarks, features (array), listing_agent_name/email, seller_name.

**Workflow:**
1. Agent uploads a listing packet PDF to the Listings page (drag-and-drop or browse).
2. Sloane extracts fields and opens the listing detail view pre-populated.
3. Agent reviews, corrects, and saves.
4. When ready, agent clicks "Push to MLS." The current response explains that direct MLS entry is a market-specific add-on and is not yet connected — the data is prepared and ready.

**MLS push seam:** `mls_provider.py` is a no-op stub, analogous to the calendar seam. `push_listing()` returns `{pushed: False, reason: "..."}`. No universal MLS write API exists — each market uses a different platform (Flexmls/Spark API, Rapattoni, Paragon, Stratus MLS, etc.), each requires separate approval and credentials. The seam isolates future per-market write integration from all callers.

**Under the hood:** `mls_extract.py` → PDF as Anthropic document block → 23-field strict JSON extraction → `_clean()` normalizes prices (strip `$`,), integers, floats, feature arrays, null-ish strings → stored in `listings` table → `mls_provider.push_listing()` called on push attempt.

---

## Integration Map

| Integration | What Sloane Uses It For | Status |
|---|---|---|
| **Anthropic (claude-sonnet-4-5)** | Contract extraction, MLS extraction, style rule extraction, document generation, compliance AI review, WhatsApp agent (tool-use loop) | Requires `ANTHROPIC_API_KEY` |
| **Twilio WhatsApp** | Inbound/outbound WhatsApp messages; signature validation on inbound webhook | Requires `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` (sandbox or approved number) |
| **OpenAI Whisper** | Transcription of voice memos sent via WhatsApp | Requires `OPENAI_API_KEY` |
| **SendGrid** | Intro email to transaction parties; deadline party notifications; document delivery email | Requires `SENDGRID_API_KEY` + verified `SENDGRID_FROM_EMAIL` |
| **Supabase Auth** | Identity provider; JWT issues `brokerage_id` claim; email auto-confirm in dev | Always active; `SUPABASE_URL` + keys required |
| **Supabase DB (Postgres)** | All persistent state: brokerages, transactions, deadlines, appointments, listings, knowledge rules, WhatsApp messages/contacts | Always active |
| **Supabase Storage** | Contract PDFs (`contracts` bucket), knowledge documents (`knowledge-docs`), listing packets (`listing-packets`) | Always active |
| **Rentcast** | AVM estimate + comparable sales | Requires `RENTCAST_API_KEY`; 503 graceful degradation without it |
| **Google / Microsoft Calendar** | (Deferred) Busy-interval sync for slot proposal; event creation on booking | Seam in place; OAuth registration pending |
| **MLS write APIs** | (Deferred) Per-market listing push (Spark/Flexmls, Rapattoni, etc.) | Seam in place; per-market approval pending |

---

## Architecture — Peek Under the Hood

### Stack

- **Backend:** FastAPI (Python), running on uvicorn. No ORM — direct HTTP calls to Supabase REST and Storage APIs via a thin `httpx` async wrapper (`supabase_client.py`). Service-role key used server-side only; bypasses Postgres RLS. All other access uses the anon key scoped by RLS policies.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS + Zustand (state) + Axios (API) + React Hook Form + Zod (forms). Auth state persisted in `localStorage` via Zustand.
- **Database:** Supabase-hosted Postgres. RLS (row-level security) enforces brokerage isolation at the database layer — even if a bug in application code skipped a `brokerage_id` filter, the DB would not return cross-brokerage rows.
- **Auth model:** Supabase Auth as IdP. On signup, the backend creates both the auth user (admin API, email auto-confirmed in dev) and a `brokerages` row, then stamps `app_metadata.brokerage_id` on the Supabase user. This claim travels in the JWT and is the single source of truth for scoping.
- **AI pattern:** All AI calls use native document blocks (PDF bytes or image bytes passed directly to the model), not OCR pre-processing. Extraction prompts use strict JSON schemas; the model is instructed to return empty string rather than guess.
- **Confirmation gate pattern:** Any action with external effect (email send, appointment book, listing push, compliance decision, document send) is split into two endpoints: a read-only preview/draft endpoint and a confirm endpoint that requires `confirmed=true` in the request body. The WhatsApp agent enforces this conversationally; the web UI enforces it with a confirmation dialog.
- **Autonomy system:** `task_autonomy` table holds per-brokerage per-task flags. The WhatsApp agent and reminder system check this table before deciding whether to act or ask. `compliance` is hardcoded locked — it cannot be made autonomous at any level of the code.

### Data Flow: WhatsApp Agent

```
Agent (WhatsApp) → Twilio webhook → FastAPI /api/v1/whatsapp/inbound
  → Twilio signature validation
  → WhatsApp contact lookup (maps number to brokerage_id)
  → [if audio] OpenAI Whisper transcription
  → conversation history fetch (last N messages)
  → Anthropic claude-sonnet tool-use loop (up to 5 rounds):
      Tools available: list_transactions, get_transaction_details,
        update_transaction_stage, add_transaction_note,
        preview_intro_email, send_intro_email,
        draft_document, send_document,
        list_deadlines, add_deadline,
        review_compliance, get_comparable_sales,
        propose_showing_times, book_appointment, list_appointments
  → Twilio reply (text message back to agent)
  → conversation history persist
```

### Data Flow: Contract Upload

```
Browser → POST /api/v1/transactions (multipart, PDF)
  → PDF uploaded to Supabase Storage (contracts bucket)
  → PDF bytes fetched
  → Anthropic: native document extraction (25 fields, strict JSON)
  → Fields cleaned and returned to browser
  → Human reviews form
  → POST /api/v1/transactions (JSON, confirmed fields)
  → Transaction row inserted with brokerage_id scope
```

### Security Constraints (Non-Negotiable)

- No API keys in frontend code, ever. All AI and integration calls go through the backend.
- `service_role` key is server-side only; it bypasses RLS and must never reach the client.
- Every DB query is scoped by `brokerage_id`. Deadlines are scoped through their parent transaction's `brokerage_id`.
- Compliance review can never be autonomous. No interface or setting exposes this option.
- Confirmation is required for: intro email send, document send, compliance decision, appointment booking, listing push, deadline party notification.
- Extracted fields are never hallucinated — empty string if not found.

---

## Current Completeness Map

| Feature | Backend | Frontend | Live-Tested |
|---|---|---|---|
| Auth (signup, login, JWT) | ✅ | ✅ | ✅ |
| Onboarding wizard (5 steps) | ✅ | ✅ | ✅ |
| Contract extraction + transactions | ✅ | ✅ | ✅ |
| WhatsApp text + voice | ✅ | N/A | ✅ |
| Intro email (WhatsApp agent) | ✅ | N/A | ⏳ needs SendGrid key |
| Knowledge base (brand & style) | ✅ | ✅ | ⏳ needs migration 004 + Anthropic key |
| Document generation (web) | ✅ | ✅ | ⏳ needs Anthropic key |
| Document generation (WhatsApp) | ✅ | N/A | ⏳ needs Anthropic key |
| Deadline tracking (CRUD) | ✅ | ✅ | ⏳ |
| Deadline reminders (agent nudge) | ✅ | ✅ | ⏳ needs Twilio + DB |
| Deadline reminders (party email) | ✅ | ✅ | ⏳ needs SendGrid key |
| Compliance review (structural) | ✅ | ✅ | ⏳ |
| Compliance review (AI) | ✅ | ✅ | ⏳ needs Anthropic key |
| Comparable sales (Rentcast) | ✅ | ✅ | ⏳ needs Rentcast key |
| Scheduling / appointments | ✅ | ✅ | ⏳ |
| Calendar sync (Google/MS OAuth) | 🔲 seam only | — | ⏳ registration pending |
| MLS listing prep (extraction) | ✅ | ✅ | ⏳ needs Anthropic key + migration 005 |
| MLS listing push | 🔲 seam only | ✅ | ⏳ per-market registration pending |

---

## Capability Boundaries (Honest Limits)

- **Sloane does not have memory across conversations beyond transaction context.** The WhatsApp agent is stateless except for the last N WhatsApp messages per contact. It does not remember what was said three weeks ago unless it's recorded in the transaction notes.
- **Sloane cannot send or receive files via WhatsApp.** MMS/media inbound is not yet wired. Agents cannot text a PDF to Sloane and have it process it — contract upload goes through the web UI.
- **Sloane does not integrate with agent-side tools** (dotloop, SkySlope, Docusign, etc.). It maintains its own transaction record. There is no sync or import from existing TC software.
- **Sloane does not handle money.** No earnest money tracking, escrow verification, or commission calculation.
- **Calendar sync is a no-op.** Slot proposals use only Sloane-managed appointment history and brokerage work hours. Live Google/Microsoft calendar free/busy data is not yet wired.
- **MLS push is a no-op.** The data is prepared; the actual submission to any MLS system is deferred.
- **Compliance review is advisory only.** Sloane flags potential issues; it does not interpret law. The disclaimer is injected into every compliance response.
- **State rulesets are manual.** Compliance checklists for TX, SC, FL, CA, NY exist. Every other state falls back to a DEFAULT ruleset. Expanding coverage requires adding rulesets to `compliance.py`.
- **Sloane does not handle inbound calls.** Voice memos sent through WhatsApp are transcribed; live phone calls are not supported.
- **One Sloane per brokerage.** There is no agent-level sub-account. All agents at a brokerage share the same Sloane instance and knowledge base.

---

## Operational Notes for Deployment

- **WhatsApp Business API approval** is the go-live gate. The current implementation uses the Twilio Sandbox (requires opt-in from each contact). Production requires a WhatsApp Business Account and approved Business Profile — a process that can take days to weeks.
- **Reminder scheduling** requires an external trigger in production. The `/deadlines/run-reminders` endpoint is idempotent and safe to call repeatedly — a nightly or twice-daily cron job via Render, Railway, GitHub Actions, or a simple cloud function is sufficient.
- **Migrations must be applied in order.** Migrations 004 (knowledge base) and 005 (listings) have not been applied to the dev Supabase instance. They must be pasted into the Supabase SQL Editor before those features work.
- **Verified SendGrid sender.** `SENDGRID_FROM_EMAIL` must be a verified sender domain or address in the SendGrid account before any email will actually deliver.
- **`TWILIO_SKIP_VALIDATION`** must be `false` (or unset) in production. It exists only to work around ngrok URL mismatch in local development.

---

*Document generated: 2026-05-27. Reflects the codebase at git commit 829ca32 and all commits in the current session.*
