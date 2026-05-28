# Penny V2 — Claude Code Build Document
### Comprehensive Engineering Specification for Pre-Commercialization Development

---

## How to Use This Document

This is a single working document for Claude Code. Read it in full before writing any code.
Each section builds on the previous. Where a section says "extends existing," locate that
code in the codebase first and understand it before extending.

Do not generate placeholder implementations. Do not stub features that are listed as
required. If a section describes something the current codebase already does, verify
the existing implementation works before building on top of it.

When you encounter a section marked **[HARD LIMIT — NOT AN ENGINEERING PROBLEM]**, stop.
Do not attempt to engineer around it. Note it in a `BLOCKERS.md` file and move on.

---

## Product Mission

Penny is a virtual transaction coordinator for small real estate brokerages (2–10 agents)
that have never had a TC and currently coordinate transactions through Gmail, group texts,
and shared spreadsheets. Penny is not replacing a human TC — it is being the first TC
this brokerage has ever had.

The primary user is a broker-owner who is also a producing agent. She lists 20 homes a
year, manages her team's deals, handles her own compliance file review, and does all of
this today with Gmail, a shared Google Sheet, and DocuSign. She has never had a TC. She
is not evaluating Penny against SkySlope — she is evaluating it against her current chaos.

Every feature decision flows from this: does it make her Monday morning less overwhelming?
If a feature requires her to learn a new concept or maintain a second system, she will
stop using it. Default to simple. Surface complexity only when she asks for it.

---

## Existing Stack — Do Not Recreate

- **Backend:** FastAPI (Python), uvicorn, no ORM — direct httpx calls to Supabase REST
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS + Zustand + Axios + React Hook Form + Zod
- **Database:** Supabase Postgres with RLS. Every query scoped by `brokerage_id`
- **Auth:** Supabase Auth. `brokerage_id` stamped in JWT `app_metadata`. This is the
  single source of truth for all data scoping — never relax this
- **AI:** Anthropic Claude (claude-sonnet-4-20250514). Native document blocks, not OCR.
  Strict JSON extraction prompts. Empty string on uncertainty — never guess
- **Messaging:** Twilio (WhatsApp + SMS). Inbound webhook with signature validation
- **Email:** SendGrid
- **Storage:** Supabase Storage (buckets: contracts, knowledge-docs, listing-packets)
- **Voice transcription:** OpenAI Whisper (WhatsApp voice memos)
- **Market data:** Rentcast (AVM + comps)

Existing live-tested features: Auth, onboarding wizard, contract PDF extraction,
transaction management, WhatsApp text + voice agent, knowledge base, document generation,
deadline tracking, compliance review (AI + structural), comparable sales, scheduling,
MLS listing preparation.

---

## Security Constraints — Non-Negotiable, Do Not Modify

- No API keys in frontend code, ever. All AI and integration calls go through the backend
- `service_role` key is server-side only
- Every DB query scoped by `brokerage_id`. No exceptions
- Compliance review can never be autonomous. No setting, flag, or code path enables this
- Confirmation gates required for: email send, document send, compliance decision,
  appointment booking, listing push, deadline party notification
- Extracted fields are never hallucinated — empty string if not found
- `TWILIO_SKIP_VALIDATION` must be false in production

---

## Database Migration Strategy

All schema changes go in numbered migration files (continuing from existing 001–005).
Apply in order. Never modify existing migrations. Every new table requires:
- `id uuid DEFAULT gen_random_uuid() PRIMARY KEY`
- `brokerage_id uuid NOT NULL REFERENCES brokerages(id) ON DELETE CASCADE`
  (or scoped through parent transaction's brokerage_id where appropriate)
- `created_at timestamptz DEFAULT now()`
- RLS policy: `USING (brokerage_id = (SELECT brokerage_id FROM auth.users... ))` or
  equivalent pattern matching existing RLS implementations in the codebase

---

## BUILD SECTION 1 — Remove Adoption Blockers

These ship first. Without them, agents won't stay past the trial.

---

### 1A. WhatsApp & SMS: Inbound PDF / Image Processing

**The problem it solves:** Agents upload contracts from their phone while sitting in a
parking lot between showings. The current web-only upload flow means they have to
remember to do it later, from a computer. They don't. Deals fall through the cracks.

**What to build:**

Extend the existing Twilio inbound webhook handler to detect media attachments.

When Twilio delivers a message with `MediaUrl0` and `MediaContentType0` in the POST body:

1. Download the media file from Twilio using authenticated HTTP (Twilio requires
   credentials — use `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` as HTTP Basic Auth
   on the download request). Twilio media URLs expire; download immediately.

2. Determine handling by content type:
   - `application/pdf` → pass to the existing contract extraction pipeline
     (`POST /api/v1/transactions` multipart flow, or extract the extraction logic
     into a shared service callable from both web and WhatsApp paths)
   - `image/jpeg`, `image/png`, `image/heic`, `image/heif` → pass as an image content
     block to Claude with the same extraction prompt used for PDFs. HEIC/HEIF common
     from iPhone cameras — convert to JPEG via Pillow before passing if needed
   - Anything else → reply "I can read PDF contracts and contract photos. Please send
     the file as a PDF for best results."

3. Run the existing 25-field extraction. Return a WhatsApp text summary of extracted
   fields in this format:
   ```
   📋 I found a contract. Here's what I extracted:

   Property: 123 Main St, Austin TX 78701
   Buyer: Jane Smith
   Seller: Robert Johnson
   Price: $485,000
   Closing: July 15, 2026
   Inspection deadline: June 28, 2026
   Financing deadline: July 5, 2026

   ⚠️ I couldn't find: lender name, title company

   Reply YES to create this transaction, or tell me any corrections first.
   ```

4. Store extracted fields temporarily in a `pending_whatsapp_transactions` table
   (brokerage_id, whatsapp_contact_id, extracted_fields JSONB, pdf_storage_url,
   expires_at [now + 2 hours]). Do not write to `transactions` yet.

5. On the agent replying YES (or a confirmation variant — handle "yes", "yep", "correct",
   "looks good", "create it"): create the transaction via existing logic, clean up the
   pending record.

6. On corrections before confirmation: the agent can say "seller is Robert Johnson Jr"
   or "closing is July 20" — parse the correction, update the pending record, show the
   updated summary again.

7. Multi-page contracts: if the PDF exceeds 15MB, reply asking them to compress it or
   upload via the web dashboard. Under 15MB, process normally.

8. If no active WhatsApp session exists to attribute the upload to a known agent contact,
   reply asking them to register via the brokerage admin panel first.

**Edge cases:**
- Duplicate detection: if an extracted address already exists as an active transaction
  for this brokerage, warn before creating: "I already have an active transaction for
  123 Main St (under contract, closing July 10). Create a new one anyway? Reply YES or NO."
- Media download failure: catch HTTP errors, reply "I had trouble downloading that file.
  Can you try sending it again?"

---

### 1B. Per-Agent Style Profiles

**The problem it solves:** A top producer doesn't want Penny writing emails in the
same voice as the new agent who joined last month. Shared brokerage style is the
floor; agent style is the preference layer on top.

**What to build:**

Schema change (migration 006):
```sql
ALTER TABLE knowledge_rules ADD COLUMN agent_id uuid REFERENCES agents(id) ON DELETE CASCADE;
-- agent_id NULL means brokerage-wide. agent_id set means agent-specific.
-- Add index: CREATE INDEX ON knowledge_rules(brokerage_id, agent_id);
```

If an `agents` table doesn't exist yet, create it:
```sql
CREATE TABLE agents (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  brokerage_id uuid NOT NULL REFERENCES brokerages(id) ON DELETE CASCADE,
  name text NOT NULL,
  email text,
  phone text,
  whatsapp_number text,
  sms_number text,
  license_number text,
  created_at timestamptz DEFAULT now()
);
```

Update `get_confirmed_knowledge_rules(brokerage_id, agent_id=None)`:
- Fetch brokerage-wide rules (agent_id IS NULL) always
- If agent_id provided, also fetch agent-specific rules
- Merge: agent rules take precedence over brokerage rules on any conflicting
  instruction (e.g., if brokerage says "use Warm regards" but agent says "use
  Best," use "Best" for that agent's documents)
- Return merged list

Update all document generation and email draft calls to pass the requesting agent's
`agent_id` when known (it's known from the WhatsApp contact lookup and from web UI session).

**Web UI — "My Style" section:**
Add a tab or section on the agent's profile page:
- Upload a sample email or letter (PDF, image, or .docx)
- Penny reads it, proposes style rules, surfaces them as "unconfirmed" for the agent
  to confirm or reject (identical UX to the existing brokerage-level knowledge base flow)
- Confirmed rules apply only to that agent's generated documents

**Admin view:**
- Brokerage admin can see which agents have style profiles configured
- Admin can view (but not edit) an agent's style rules
- Admin can delete an agent's style profile if needed

---

### 1C. SMS Fallback Channel

**The problem it solves:** WhatsApp penetration among US real estate agents over 45
is low. Requiring agents to install WhatsApp to use Penny is a dealbreaker for a
meaningful portion of small brokerage teams.

**What to build:**

Rename or extend `whatsapp_contacts` to `agent_channels`:
```sql
CREATE TABLE agent_channels (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  brokerage_id uuid NOT NULL REFERENCES brokerages(id) ON DELETE CASCADE,
  agent_id uuid REFERENCES agents(id),
  channel text NOT NULL CHECK (channel IN ('whatsapp', 'sms')),
  phone_number text NOT NULL,
  display_name text,
  created_at timestamptz DEFAULT now(),
  UNIQUE(brokerage_id, phone_number, channel)
);
```

Migrate existing `whatsapp_contacts` data into `agent_channels` with `channel = 'whatsapp'`.

Add a second Twilio webhook route: `POST /api/v1/sms/inbound`
- Same signature validation pattern as the WhatsApp handler
- Same contact lookup (match phone number in `agent_channels` where channel = 'sms')
- Same tool-use loop with identical tools
- Text-only: no voice memo transcription on SMS (MMS audio not supported in this path)
- No media/PDF inbound on SMS in this phase (WhatsApp handles that)
- Replies via `client.messages.create(from_=SMS_NUMBER, to=..., body=...)` (not the
  WhatsApp from number)

**Onboarding wizard update:**
In the agent registration step (or a new step), let admin choose per agent:
- WhatsApp (register their WhatsApp number)
- SMS (register their mobile number for standard SMS)
- Both (register both — messages go to both channels, replies from either are handled)

**Configuration:**
Add `TWILIO_SMS_FROM` to environment variables (a standard Twilio phone number,
not the WhatsApp sender). Document in `.env.example`.

---

## BUILD SECTION 2 — The Broker Compliance File

This is what makes a broker-owner feel safe. Without it, Penny is a novelty. With it,
Penny is infrastructure.

---

### 2A. Compliance Checklist Engine

**The problem it solves:** State real estate commissions audit brokerages. The broker-
of-record needs a closed-file checklist — agency disclosure, lead-based paint, wire
fraud advisory, seller's disclosure, etc. — with timestamped uploads, completed-by
tracking, and a retention trail. The existing AI compliance review reads the contract
for issues. This is different: it tracks whether the required documents are in the file.

**Schema (migration 007):**

```sql
-- Template library (system defaults + brokerage customizations)
CREATE TABLE compliance_templates (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  brokerage_id uuid REFERENCES brokerages(id) ON DELETE CASCADE,
  -- NULL brokerage_id = system default template (readable by all, not editable)
  state text,
  transaction_type text NOT NULL CHECK (
    transaction_type IN ('buy_side', 'list_side', 'dual_agency', 'lease')
  ),
  name text NOT NULL,
  is_system_default boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);

-- Individual checklist items within a template
CREATE TABLE compliance_template_items (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  template_id uuid NOT NULL REFERENCES compliance_templates(id) ON DELETE CASCADE,
  sort_order integer NOT NULL DEFAULT 0,
  label text NOT NULL,
  description text,
  required boolean DEFAULT true,
  document_required boolean DEFAULT false,
  -- document_required: must the agent upload a file, or just check a box?
  notes text,
  created_at timestamptz DEFAULT now()
);

-- Per-transaction checklist (instantiated from template on transaction creation)
CREATE TABLE transaction_checklist_items (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  template_item_id uuid REFERENCES compliance_template_items(id),
  -- template_item_id NULL = manually added item
  label text NOT NULL,
  required boolean DEFAULT true,
  document_required boolean DEFAULT false,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'complete', 'waived', 'not_applicable')),
  completed_at timestamptz,
  completed_by uuid REFERENCES auth.users(id),
  document_url text,
  waiver_note text,
  sort_order integer DEFAULT 0,
  created_at timestamptz DEFAULT now()
);

-- Index for fast per-transaction queries
CREATE INDEX ON transaction_checklist_items(transaction_id);
```

**System default templates to seed on first run:**

Buy-side (generic, all states):
1. Buyer representation agreement (signed)
2. Agency disclosure (signed by buyer)
3. Wire fraud advisory (signed by buyer)
4. Purchase contract — fully executed copy
5. Earnest money receipt
6. Inspection report (received)
7. Inspection objection / resolution addendum (if applicable)
8. Financing commitment letter
9. Appraisal report (if applicable)
10. Title commitment / preliminary title report
11. HOA documents (if applicable)
12. Lead-based paint disclosure (pre-1978 properties)
13. Final walkthrough confirmation
14. Closing disclosure (reviewed)
15. Settlement statement / ALTA
16. Commission disbursement authorization (CDA)

List-side (generic, all states):
1. Listing agreement — fully executed
2. Seller's property disclosure statement
3. Agency disclosure (signed by seller)
4. Wire fraud advisory (signed by seller)
5. Lead-based paint disclosure (pre-1978 properties)
6. HOA addendum and documents (if applicable)
7. MLS input sheet / listing data verification
8. Professional photos received
9. Purchase contract — fully executed copy
10. Earnest money receipt
11. Inspection report (received by seller's side)
12. Repair request and resolution addendum (if applicable)
13. Appraisal report (if applicable)
14. Title commitment
15. Settlement statement / ALTA
16. Commission disbursement authorization (CDA)

**Backend endpoints:**

```
GET  /api/v1/compliance-templates
     — Returns system defaults + brokerage's custom templates

POST /api/v1/compliance-templates
     — Brokerage admin creates a custom template (clone from system default or new)

PUT  /api/v1/compliance-templates/:id
     — Update template name, add/remove/reorder items (brokerage-owned templates only)

GET  /api/v1/transactions/:id/checklist
     — Returns all checklist items for a transaction with status

POST /api/v1/transactions/:id/checklist/items
     — Manually add a checklist item to a specific transaction

PATCH /api/v1/transactions/:id/checklist/items/:item_id
      — Mark complete, waive, upload document
      — Body: { status, waiver_note, document_url }
      — Sets completed_at and completed_by from JWT

DELETE /api/v1/transactions/:id/checklist/items/:item_id
       — Remove a manually-added item (cannot delete template-derived items, only waive)
```

**Auto-instantiation on transaction creation:**
When a new transaction is created (`POST /api/v1/transactions`), determine transaction
type (buy_side is default; list_side if the brokerage agent is the listing agent — infer
from existing contract fields or let the agent specify). Find the best matching template
(brokerage custom > system default, matching state if available). Instantiate all template
items as `transaction_checklist_items` rows with status = 'pending'.

**Completion percentage:**
Add a computed field to transaction detail responses:
```python
checklist_total = count of required items
checklist_complete = count of required items where status IN ('complete', 'waived', 'not_applicable')
checklist_pct = round(checklist_complete / checklist_total * 100) if checklist_total > 0 else 0
```

Include `checklist_pct` in transaction list responses so the broker dashboard can show it.

**Web UI — Compliance Checklist panel:**
On the transaction detail page, add a "Compliance File" section (alongside existing panels):
- Shows each checklist item with its status (checkbox + label)
- Complete: green checkmark, completed by name, timestamp
- Pending: empty checkbox, agent can click to mark complete or upload a document
- Waived: strikethrough with waiver note visible on hover
- Document upload: if `document_required = true`, a file upload button appears;
  uploaded doc goes to Supabase Storage (`compliance-docs` bucket), URL stored
- Admin can add custom items to any transaction's checklist
- Progress bar showing `checklist_pct`% complete at the top of the section

**WhatsApp integration:**
- "What's missing from the compliance file for 123 Main?" →
  Penny lists pending required items only (not waived/complete)
- "Mark the inspection report complete for 123 Main" →
  Penny marks the matching item complete, confirms back (confirm-gated)

---

### 2B. Broker Review Queue

**The problem it solves:** The broker-owner currently has no single place to see
which deals need her attention. She finds out deals are in trouble when an agent
texts her in a panic.

**What to build:**

Add a "Needs Review" view to the web dashboard (top-level nav item, visible only
to admin role).

This view runs a single backend query and surfaces four categories:

```
GET /api/v1/broker/review-queue
```

Returns:

```json
{
  "compliance_attention": [
    // transactions where compliance_status = 'needs_attention'
  ],
  "closing_soon_incomplete": [
    // transactions closing within 5 days AND checklist_pct < 80
  ],
  "overdue_deadlines": [
    // transactions with at least one deadline past due_date and not marked resolved
    // (add a resolved boolean + resolved_note to deadlines table if not present)
  ],
  "stale_transactions": [
    // active transactions with no note, stage change, or checklist update in 7+ days
    // "stale" = last_activity_at is null or < now() - interval '7 days'
    // add last_activity_at to transactions, updated by a trigger or explicitly on mutations
  ]
}
```

Each item in each list includes: transaction id, address, buyer name, closing date,
stage, checklist_pct, assigned agent name, and a one-line reason string ("2 compliance
items need attention", "Closing in 3 days, file 60% complete", etc.).

**Web UI:**
- Four collapsible sections, each with a count badge
- Each transaction row is clickable → navigates to transaction detail
- Broker can add a review note from this view without navigating away (inline textarea,
  saves as a transaction note tagged `source: broker_review`)
- Empty state for each section: "No transactions need attention here" (green)
- Refresh button + auto-refresh every 5 minutes

**Dashboard widget:**
On the main dashboard, add a compact "🚨 N items need your review" banner that links
to the Review Queue when count > 0.

---

## BUILD SECTION 3 — Workflow Task Templates

**The problem it solves:** A human TC's core value is knowing what needs to happen next
without being asked. Penny currently waits to be asked. This makes it reactive, not
proactive — and reactive tools feel like extra work, not help.

**What to build:**

**Schema (migration 008):**

```sql
CREATE TABLE workflow_templates (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  brokerage_id uuid REFERENCES brokerages(id) ON DELETE CASCADE,
  -- NULL = system default
  name text NOT NULL,
  state text,
  transaction_type text CHECK (
    transaction_type IN ('buy_side', 'list_side', 'dual_agency', 'lease')
  ),
  is_system_default boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE workflow_steps (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  template_id uuid NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE,
  sort_order integer NOT NULL DEFAULT 0,
  label text NOT NULL,
  description text,
  -- When does this step become active?
  trigger_type text NOT NULL CHECK (
    trigger_type IN (
      'stage_entry',         -- when transaction enters a specific stage
      'days_before_deadline',-- N days before a named deadline
      'days_after_stage',    -- N days after entering a stage
      'manual'               -- only created when admin/agent explicitly adds it
    )
  ),
  trigger_stage text,        -- for stage_entry and days_after_stage
  trigger_deadline_label text, -- for days_before_deadline (matches deadline label)
  trigger_days integer,      -- for days_before/after variants
  assigned_to_role text CHECK (
    assigned_to_role IN ('agent', 'admin', 'buyer', 'seller', 'lender', 'title')
  ),
  due_offset_days integer DEFAULT 0,
  -- due_offset_days relative to the trigger event
  created_at timestamptz DEFAULT now()
);

CREATE TABLE transaction_tasks (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  step_id uuid REFERENCES workflow_steps(id),
  -- step_id NULL = manually created task
  label text NOT NULL,
  description text,
  due_date date,
  assigned_to_role text,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'complete', 'skipped')),
  completed_at timestamptz,
  completed_by uuid REFERENCES auth.users(id),
  skip_reason text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX ON transaction_tasks(transaction_id, status);
```

**System default workflow — buy-side (seed on first run):**

Stage: `under_contract` entry →
- Immediately: "Send intro email to all parties" (agent)
- Immediately: "Confirm earnest money receipt date" (agent)
- +1 day: "Order home inspection" (agent)
- +2 days: "Verify lender has application" (agent)

5 days before inspection deadline:
- "Confirm inspection is scheduled" (agent)

2 days before inspection deadline:
- "Inspection objection deadline approaching — prepare response if needed" (agent)

Stage: `pending` entry →
- Immediately: "Order appraisal (if applicable)" (agent)
- Immediately: "Request title commitment from title company" (agent)
- +3 days: "Confirm appraisal is ordered" (agent)

5 days before closing:
- "Request final closing disclosure from lender" (agent)
- "Confirm final walkthrough is scheduled" (agent)
- "Prepare commission disbursement authorization" (admin)

2 days before closing:
- "Confirm wire instructions sent (and wire fraud advisory on file)" (agent)
- "Confirm closing time and location with all parties" (agent)

**Task generation engine:**

```python
# Called on stage transitions and on transaction creation
def generate_tasks_for_trigger(transaction_id, trigger_type, trigger_value, brokerage_id):
    """
    Find all workflow steps matching this trigger for this brokerage
    (brokerage custom template > system default).
    Create transaction_tasks rows for any step not already present.
    Calculate due_date based on trigger event + due_offset_days.
    """
```

Hook this into:
- `POST /api/v1/transactions` (creation → trigger 'stage_entry' for 'under_contract')
- `PATCH /api/v1/transactions/:id/stage` (stage change → trigger 'stage_entry' for new stage)
- The deadline reminder run (check days_before_deadline triggers)

**WhatsApp integration (new tool: `get_pending_tasks`):**

When agent asks "What's next on 123 Main?" or "What do I need to do on Main St?":
- Penny returns pending tasks, sorted by due_date ascending
- Groups by urgency: overdue (red flag), due today, due this week, upcoming
- Format:
  ```
  📋 123 Main St — Pending Tasks

  🔴 OVERDUE
  • Order home inspection (was due June 25)

  📅 DUE TODAY
  • Confirm EMD received

  📅 THIS WEEK
  • Verify lender has application (June 29)
  • Confirm inspection scheduled (July 1)
  ```

When agent says "Mark inspection ordered for 123 Main" → Penny finds the matching task,
marks complete, confirms back (confirm-gated).

**Web UI:**
- Add a "Tasks" panel to the transaction detail page
- Pending tasks shown as a checklist with due dates and assigned roles
- Overdue tasks highlighted in red
- Admin can add custom tasks or skip tasks with a reason
- On the transaction list, show overdue task count as a badge

---

## BUILD SECTION 4 — Inbound Email Reply Threading

**The problem it solves:** Penny sends intro emails and party notifications, but when
a lender replies to ask a question or a buyer replies with a concern, that reply
disappears into whoever's Gmail is the from-address. The broker has no visibility.
The transaction has no record.

**What to build:**

Use SendGrid's Inbound Parse webhook to capture replies.

**Setup:**
1. Configure a reply subdomain: `reply.penny.app` (or equivalent). Point its MX record
   to `mx.sendgrid.net`. Document this as a DNS requirement in `DEPLOYMENT.md`.
2. In SendGrid dashboard: Settings → Inbound Parse → add the subdomain and point to
   `POST /api/v1/email/inbound`.

**Reply-to addressing scheme:**
Every outbound email Penny sends sets:
```
Reply-To: tx-{transaction_id}@reply.penny.app
```
This routes all replies to a single inbound endpoint where the transaction_id is
extractable from the recipient address.

**Schema (migration 009):**

```sql
CREATE TABLE transaction_emails (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  direction text NOT NULL CHECK (direction IN ('outbound', 'inbound')),
  sender_email text,
  sender_name text,
  recipient_emails text[],
  subject text,
  body_text text,
  body_html text,
  sendgrid_message_id text,
  read boolean DEFAULT false,
  read_at timestamptz,
  read_by uuid REFERENCES auth.users(id),
  received_at timestamptz DEFAULT now()
);

CREATE INDEX ON transaction_emails(transaction_id, direction, read);
```

**Inbound webhook handler:**

```
POST /api/v1/email/inbound  (no auth — SendGrid calls this)
```

Validate inbound Parse requests using SendGrid's signed webhook verification
(use `SENDGRID_WEBHOOK_KEY` env var — document setup).

Parse the POST body:
- `to` field → extract transaction_id from the recipient address
  (regex: `tx-([a-f0-9-]+)@reply\.penny\.app`)
- Look up transaction by ID, verify it belongs to a known brokerage (security check)
- Extract sender, subject, body_text, body_html
- Store in `transaction_emails` with direction = 'inbound'
- Mark all existing outbound emails in this thread as having received a reply (optional)

After storing: send a WhatsApp nudge to the brokerage's admin/agent channel:
```
📨 Reply received on 123 Main St
From: Jennifer Walsh (lender)
"Just wanted to confirm the appraisal is ordered — we..."

View full message in Penny dashboard.
```

Truncate the preview at 120 characters.

**Update outbound email logging:**
All existing SendGrid calls (intro email, document send, deadline notifications) should
log to `transaction_emails` with direction = 'outbound' and the SendGrid message ID.

**Web UI — Communications tab:**
Add a "Communications" tab to the transaction detail page showing the full email thread:
- Chronological, outbound and inbound interleaved
- Unread inbound messages highlighted
- Click to expand full message body
- "Mark as read" on expand
- Reply button: opens a draft in Penny's document generation flow, pre-addressed to the
  sender, pre-populated with transaction context. Agent reviews, edits, confirms send.
  Do not auto-reply. Human writes the response; Penny drafts it on request.

**API endpoints:**
```
GET  /api/v1/transactions/:id/emails       — all emails for a transaction
POST /api/v1/transactions/:id/emails/read  — mark all inbound as read
```

---

## BUILD SECTION 5 — Earnest Money Deposit Tracking

**The problem it solves:** Brokers are personally liable for trust account handling in
many states. If EMD isn't received by the deadline and no one noticed, the broker has
a legal problem. No one is tracking this today.

**What to build:**

Schema update (migration 010 — add columns to `transactions`):

```sql
ALTER TABLE transactions ADD COLUMN emd_amount numeric;
-- Wire to existing earnest_money field from contract extraction if present,
-- or keep separate if the data models differ

ALTER TABLE transactions ADD COLUMN emd_due_date date;
ALTER TABLE transactions ADD COLUMN emd_received boolean DEFAULT false;
ALTER TABLE transactions ADD COLUMN emd_received_date date;
ALTER TABLE transactions ADD COLUMN emd_receipt_document_url text;
ALTER TABLE transactions ADD COLUMN emd_held_by text
  CHECK (emd_held_by IN ('title', 'brokerage', 'escrow', 'other'));
ALTER TABLE transactions ADD COLUMN emd_notes text;
```

**Contract extraction update:**
The existing extraction prompt extracts `earnest_money` — wire that into `emd_amount`
on transaction creation. If the contract contains an EMD due date (common in many state
contracts as "earnest money to be delivered within X days of acceptance"), extract it
as `emd_due_date`.

**Broker review queue integration:**
Add an `emd_overdue` category to the review queue:
- Transactions where `emd_due_date < today` AND `emd_received = false` AND stage is active
- This is a high-priority alert — surface at the top of the review queue with a 🔴 indicator

**Web UI — EMD status card:**
On transaction detail, add an EMD card (alongside existing panels):
- Shows: amount, due date, held by, received status
- If not received: red "EMD Not Received" badge with due date
- Admin/agent clicks "Mark Received" → date picker, optional file upload for receipt
- File goes to Supabase Storage (`compliance-docs` bucket)
- If received: green "EMD Received" badge with received date and receipt link

**WhatsApp integration:**
- "Has EMD been received for 123 Main?" → Penny answers from record with date if received
- "Mark EMD received for 123 Main" → Penny asks for received date, confirm-gated

**Important constraint:**
Penny tracks receipt only. No calculations, no disbursements, no trust account math.
The UI label everywhere reads "EMD Receipt Tracking." This is not accounting software.

---

## BUILD SECTION 6 — AI Disclosure and Party Consent

**The problem it solves:** Several states (CA, CO, UT, TX) have or are passing AI
disclosure requirements for real estate communications. Build the mechanism now.
When competitors haven't built it, this becomes a differentiator with compliance-
conscious brokers.

**What to build:**

**Schema (migration 011):**

```sql
CREATE TABLE party_consents (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  transaction_id uuid NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  party_role text NOT NULL,
  -- 'buyer', 'seller', 'buyer_agent', 'listing_agent', 'lender', 'title'
  email text NOT NULL,
  consented_at timestamptz,
  ip_address text,
  user_agent text,
  consent_method text DEFAULT 'email_link'
  -- future: 'sms_link', 'docusign', 'in_person'
);

CREATE INDEX ON party_consents(transaction_id);
```

**Brokerage settings (add columns to `brokerages`):**
```sql
ALTER TABLE brokerages ADD COLUMN ai_disclosure_enabled boolean DEFAULT true;
ALTER TABLE brokerages ADD COLUMN ai_disclosure_text text DEFAULT
  'Communications from this office may be drafted or assisted by artificial intelligence.
   All communications are reviewed and authorized by a licensed real estate professional
   before sending.';
```

**Disclosure footer:**
When `ai_disclosure_enabled = true`, append the disclosure text to the HTML footer
of every outbound email Penny sends (intro email, document emails, deadline notifications).
Style it as small, muted text below the signature — not prominently. It is a disclosure,
not a marketing statement.

**Consent link (optional, for brokerages that want explicit consent):**
Add a one-time consent link to the intro email footer:
```
[Acknowledge AI disclosure]
→ GET /api/v1/consent/{transaction_id}/{party_role}?token={signed_token}
```

The token is an HMAC-signed payload of `{transaction_id}:{party_role}:{email}` using
a `CONSENT_SECRET` env var. On GET: verify token, record consent in `party_consents`,
return a simple HTML page: "Thank you — your acknowledgment has been recorded."

The consent link is optional per brokerage (add a `request_ai_consent` boolean setting).
Default: false (disclosure footer only, no explicit consent link).

**Web UI:**
In brokerage settings (or a new "Compliance Settings" section):
- Toggle: "Include AI disclosure in all outbound emails" (default on)
- Editable text area: the disclosure text (with a warning: "Have your attorney review
  this text. Penny cannot provide legal advice on disclosure requirements.")
- Toggle: "Request explicit consent from transaction parties" (default off)
- Consent status panel: per active transaction, shows which parties have acknowledged

---

## BUILD SECTION 7 — Broker Reporting

**The problem it solves:** Broker-owners think in pipeline and production. The current
dashboard is a transaction list. Monday morning, the broker wants one page that tells
her how the business is doing. Without reporting, Penny is a task tool. With reporting,
it's a business tool.

**What to build:**

All metrics computed from existing transaction data. No external BI. One page.

**Backend endpoint:**

```
GET /api/v1/reports/broker-summary?period=month|quarter|ytd
```

Returns:

```json
{
  "period": "month",
  "pipeline": {
    "active_transactions": 12,
    "active_volume": 4850000,
    "by_stage": {
      "under_contract": 5,
      "pending": 7
    },
    "closing_this_month": 4,
    "closing_this_month_volume": 1920000
  },
  "at_risk": {
    "overdue_deadlines": 2,
    "closing_soon_incomplete": 1,
    "stale_transactions": 3
  },
  "production": {
    "closed_count": 8,
    "closed_volume": 3200000,
    "avg_days_to_close": 34,
    "agent_breakdown": [
      { "agent_name": "Sarah M.", "closed": 3, "volume": 1100000 },
      { "agent_name": "Marcus T.", "closed": 5, "volume": 2100000 }
    ]
  },
  "compliance": {
    "avg_checklist_completion_at_close": 94,
    "open_compliance_items_total": 11
  }
}
```

Compute `avg_days_to_close` from `closed_at - created_at` on closed transactions.
Add `closed_at` timestamptz to transactions if not present; set it on stage transition
to 'closed'.

**CSV export:**
```
GET /api/v1/reports/transactions-export?period=month|quarter|ytd
```
Returns a CSV of closed transactions with: address, buyer, seller, price, close date,
agent, days to close, checklist completion %. Standard browser download.

**Web UI — Reports page:**
Top-level nav item. Three sections:

1. **Pipeline** — three stat cards (active deals, active volume, closing this month)
   plus a simple bar chart: transactions by stage. Use recharts (already in the stack).

2. **Production** — closed count, closed volume, avg days to close for the selected period.
   Agent leaderboard table: name, closed count, volume. Period selector: This Month /
   This Quarter / YTD.

3. **Compliance Health** — avg checklist completion at close (should trend toward 100%),
   open items across active transactions, count of files with compliance_status = needs_attention.

Keep it simple. No drill-down in V1. No date-range picker beyond the three period options.
A broker running a 4-agent shop does not need a BI tool — she needs a one-page readout
she can trust.

---

## BUILD SECTION 8 — DocuSign Integration

**Why this is here:** The current document generation creates correspondence (status
updates, cover letters, congratulations emails). It does not create signable documents.
A broker who cannot get contracts signed through Penny will maintain DocuSign separately,
which means maintaining two systems, which means abandoning Penny.

**Prerequisite (outside engineering scope):**
DocuSign developer account and integration key (client ID) required before this section
can be built. Start the DocuSign developer account registration now — it runs in parallel
with other engineering. Production use requires DocuSign partner review.

**What to build when credentials are available:**

OAuth flow: DocuSign uses OAuth 2.0 Authorization Code grant.
Store per-brokerage tokens in a `docusign_tokens` table (brokerage_id, access_token,
refresh_token, expires_at, docusign_account_id, docusign_user_id).

Add to brokerage settings: "Connect DocuSign" button → initiates OAuth flow →
on callback, store tokens → button becomes "DocuSign Connected."

**Envelope creation from a transaction:**

```
POST /api/v1/transactions/:id/docusign/send
Body: {
  document_url: "...",  // Supabase Storage URL of the contract PDF
  signers: [
    { name: "Jane Smith", email: "jane@email.com", role: "buyer" },
    { name: "Robert Johnson", email: "robert@email.com", role: "seller" }
  ],
  email_subject: "Please sign: 123 Main St Purchase Agreement",
  message: "..."
}
```

Creates a DocuSign envelope with the contract PDF, sets signers from party contacts
(pre-populated from transaction, agent can modify), sends for signature.

**Webhook for status updates:**

```
POST /api/v1/docusign/webhook
```

DocuSign Connect webhooks deliver envelope status changes (sent, delivered, completed,
declined, voided). On `completed`: fetch the signed document URL, store in the transaction's
`contract_pdf_url` (or add a `signed_contract_url` field), add a transaction note:
"Contract fully executed via DocuSign [timestamp]."

**Web UI:**
On transaction detail, add a "Signatures" card:
- "Send for Signature" button → pre-fills signers from party contacts → confirm → sends
- Status indicator: Draft / Sent / Partially Signed / Completed / Declined
- Link to signed document once completed
- Signing deadline (optional, DocuSign supports envelope expiration)

**Important scoping constraint:**
Do not attempt to build a forms library. DocuSign is for sending the documents Penny
already has (extracted contracts, generated correspondence). The agent uploads or
generates the document first, then sends it for signature through Penny. Penny is not
generating state association forms — that requires licensing agreements (see Hard Limits).

---

## HARD LIMITS — Not Engineering Problems

Document each of these in `BLOCKERS.md`. Do not engineer around them.
Brief the product owner; these require business or legal action.

### HARD LIMIT 1: State Association Forms / Forms Libraries

Dotloop and zipForm have licensing agreements with the National Association of REALTORS®
and state associations (CAR in CA, TAR in TX, etc.) to distribute and pre-fill
state-promulgated contract forms. Penny cannot generate, pre-fill, or reproduce these
forms without equivalent licensing agreements.

**What Penny can do:** extract data from forms the agent already has, track them in
the compliance file, send them for signature via DocuSign.
**What requires a business deal:** distributing the actual forms.
**Action required:** If form distribution is a roadmap goal, engage NAR and relevant
state associations. This is a 6–18 month legal and business process.

### HARD LIMIT 2: MLS Write APIs

There are approximately 580 MLSs in the United States. Each requires a separate data
access agreement, separate API credentials, and in some cases RESO Web API certification.
The engineering seam is in place (`mls_provider.py`). Connecting it to any specific MLS
requires a business development process per market.

**Action required:** Identify the 3–5 markets where initial broker-owner customers
are concentrated. Pursue MLS data access agreements for those markets only.
Do not attempt to build a universal MLS connector.

### HARD LIMIT 3: Google / Microsoft Calendar OAuth

Google's OAuth verification process for apps requesting calendar read/write scopes
from external users takes 4–12 weeks and may require a security assessment for apps
that handle sensitive data. Microsoft's equivalent (Azure AD app registration for
delegated Graph API permissions) is faster but still requires review.

The engineering (`calendar_provider.py` seam) is ready. The blocker is the platform
review process.

**Action required:** Submit Google OAuth verification request immediately. It runs in
parallel with all other engineering in this document.

### HARD LIMIT 4: WhatsApp Business API Production Approval

The current implementation uses the Twilio Sandbox (each contact must opt in manually).
Production use requires a WhatsApp Business Account and approved Business Profile.
Twilio handles the META approval process, but real-estate-adjacent bulk messaging
applications have been rejected or delayed.

**Action required:** Begin the Twilio/META WhatsApp Business API application now.
The SMS fallback (Section 1C) provides a production-ready channel while approval is pending.

### HARD LIMIT 5: AI Reliability in Compliance Review

The existing AI compliance review will occasionally mark a non-compliant item as
compliant, or flag a compliant item as an issue. This is a fundamental property of
LLMs — it cannot be eliminated by prompting or fine-tuning at the current scale.

**What this means for product design:**
- The human gate on compliance review is load-bearing. Never make it autonomous.
- Add a `confidence` field to AI compliance findings (ask the model to self-report
  confidence as high/medium/low per finding). Surface low-confidence findings
  with a distinct visual treatment ("⚠️ Uncertain — verify manually").
- Document clearly in the UI: "Penny's compliance review is a checklist aid, not
  a legal determination. The broker of record is responsible for all regulatory compliance."
- Over time, build a feedback loop: allow the admin to mark AI findings as
  correct/incorrect. Log these for future model improvement, but do not use them
  to auto-adjust the model in production.

### HARD LIMIT 6: SOC 2 / Data Handling for NPI

Broker-owners handling buyer SSNs, bank statements, and income documentation (which
flow through the transaction file) will ask about data handling before signing an
annual contract. Without a SOC 2 Type II report or equivalent, enterprise-adjacent
brokerages will not sign.

**Action required:** Begin SOC 2 readiness assessment. This is a 6–12 month process
depending on organizational maturity. In the interim:
- Document data handling practices in a Privacy Policy and DPA (Data Processing Agreement)
- Use Supabase's existing SOC 2 and ISO 27001 certifications as the infrastructure
  foundation and reference them in customer conversations
- Add data retention settings to the brokerage admin panel: configurable retention
  period for closed transaction documents (default: 7 years, matching most state
  commission requirements)

---

## Deployment Checklist for New Features

Before any section goes to production, verify:

- [ ] All new tables have RLS policies scoped by `brokerage_id`
- [ ] All new API endpoints require auth (JWT validation) except designated public webhooks
- [ ] Webhook endpoints (Twilio, SendGrid, DocuSign) validate signatures before processing
- [ ] New environment variables documented in `.env.example` with descriptions
- [ ] New DB migrations numbered sequentially and tested in order on a clean Supabase instance
- [ ] New Supabase Storage buckets created with appropriate access policies
- [ ] `BLOCKERS.md` updated if any section was blocked by a Hard Limit
- [ ] `DEPLOYMENT.md` updated with any new DNS, platform registration, or external
     configuration requirements

---

## Framing Note — Keep This in Mind Throughout

Penny's user is a broker-owner running a 6-agent shop in a mid-size market. She is also
a producing agent. She lists homes, manages her team's deals, and handles her own
compliance review. She has never had a TC. She is not comparing Penny to SkySlope —
she is comparing it to her current chaos: Gmail, a shared Google Sheet, and DocuSign.

Every feature should make her Monday morning less overwhelming.

If a feature requires her to learn a new concept or maintain a second system, she will
stop using it. Default to simple. Surface complexity only when she asks for it.

When in doubt, ask: would this make the broker-owner's Monday easier, or would she
have to think about it first? If she has to think about it, simplify it.

---

*Document version: 1.0 — compiled 2026-05-27*
*Reflects Penny codebase at git commit 829ca32*
*Intended for use with Claude Code (claude-sonnet-4-20250514 or later)*
