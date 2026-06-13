# Penny — Product Overview (Stage 3: Hardening & the Real-TC Bar)

**Penny** is a B2B SaaS "virtual transaction coordinator" for residential real
estate brokerages. One Penny instance per brokerage, priced by agent seat. She
runs the operational layer of a real estate transaction — contract intake,
deadline tracking, document drafting and routing, a compliance file, comparable
sales, scheduling, MLS listing prep, earnest-money tracking, client status
updates, and broker reporting — while keeping a human in the loop for anything
that leaves the building.

This is the third product document in a series. The first described Penny as a
single-channel assistant. The second described her growth into a brokerage-wide
operations layer. **This one is about the stage that mattered most for a broker
deciding whether to actually trust her with live deals: the hardening work, and
the additions that close the gap between "an AI that helps" and "a transaction
coordinator that does the job."**

It is written for working brokers — people who run an office, have paid a human
TC per file or per month, and understand why AI belongs in their business even if
they have not adopted it yet. It is meant to be read critically. Where Penny is
deliberately bounded, that is stated plainly. There is also a "Peek under the
hood" section so a technical reviewer can see how the claims are actually
enforced, not just asserted.

---

## 1. The Arc: From "Helpful" to "Does the Job"

By the end of the last stage, Penny could do a great deal: read a contract, track
deadlines, draft correspondence in the brokerage's voice, run a compliance file,
pull comps, schedule showings, prep listings, and surface a broker review queue —
across WhatsApp, SMS, web chat, and a full web app, all behind a human-in-the-loop
gate.

But "can do a great deal" and "I'd hand it my closings" are different bars. A real
transaction coordinator does not just answer when asked. She **chases**. She sends
the weekly "here's where we stand" note without being told. She combs every page
of a freshly executed contract for a missing initial. She follows up on the title
company three days from now, not when someone remembers. She never lets an email
fall through a crack, and she keeps a paper trail of everything she touched.

This stage was about meeting that bar in two directions at once:

1. **Hardening** — making the existing machine trustworthy under real conditions.
   Idempotent unattended scans, tested confirmation gates, email delivery
   feedback so nothing fails silently, session stability, contract-reading
   accuracy you can stake a price on, and a scope-bound assistant that stays in
   its lane.
2. **Closing the TC gap** — the capabilities a real coordinator has that an
   on-request assistant does not: recurring client status updates, two-way email
   (including drafted replies to outside parties and time/event-deferred
   follow-ups), a contract execution-completeness audit, proactive "what I'd
   tackle first" prioritization, live calendar coordination, and a full per-deal
   activity timeline.

The throughline: **Penny got more autonomous in the routine and more conservative
at the edges at the same time.** She now does more on her own, but every new path
that could reach an outside party still ends at a human tap — and the gates that
enforce that are now covered by automated tests, not just good intentions.

---

## 2. Closing the TC Gap (What's New, and Why a Coordinator Needs It)

These are the additions since the last document, framed by the coordinator job
they fill.

### 2.1 Recurring status updates — the weekly "where we stand"

A real TC sends parties a regular update: what's done, what's coming, what's still
outstanding. Penny now does this on a weekly cadence per deal.

- She builds a **deterministic digest** — no AI guesswork — from the deal's own
  record: current stage, a closing-date countdown ("on track to close on [date],
  N days away"), upcoming items in the next two weeks (unresolved deadlines and
  dated tasks), and outstanding items (missing required checklist documents,
  earnest money not yet received).
- It reads like a coordinator's note, in plain text and HTML, addressed to the
  parties who have email on file.
- **The human gate holds by default.** If the brokerage has *not* opted the
  `status-updates` task into autonomy, Penny drafts the update, queues it, and
  nudges the deal's agent to review and one-click send from the dashboard. If the
  brokerage *has* opted in, she sends directly — but a weekly cadence anchor
  (`last_status_update_at`) is claimed *before* the send, so a repeated or crashed
  scan can never double-send.
- Agents can also ask for an update on demand in chat (preview, then confirm).

This is the single clearest "she's doing the TC's job, not waiting to be asked"
addition in this stage.

### 2.2 Two-way email — she works the inbox, not just the outbox

Previously Penny could send email and thread inbound replies back onto the right
deal, but a human had to act on every reply. Now email is genuinely two-way, with
the gate placed by **who is writing**:

- **Brokerage's own agents.** When one of the brokerage's agents emails Penny, she
  runs her full assistant loop over the thread and replies in-line — the same
  Penny, just over email. This is gated by sender authentication (SPF/DKIM must
  pass) so a spoofed "from an agent" message can't unlock it, and by a brokerage
  opt-in toggle.
- **Outside parties** (buyer, seller, the other agent, lender, title). Penny
  **drafts** a suggested reply in the brokerage's voice and asks the responsible
  agent: send it, change it, hold it, or drop it. **She never auto-sends to an
  outside party.** The agent approves in plain language ("send it," "send it but
  add…," "hold until Friday").
- **Deferral — the part a TC actually needs.** An agent can arm a drafted reply
  to resurface on a **time** ("hold until Friday") or an **event** ("wait until it
  goes pending," "once the EMD is in," "when the inspection's checked off"). When
  the trigger fires, Penny brings the draft back for a *fresh* approval — she does
  not fire it blind, because the deal may have changed in the meantime. Manual
  holds get periodic reminders so nothing is forgotten.
- **Loop guard.** Penny never answers automated, no-reply, or bulk senders
  (bounce notices, mailing lists, "do-not-reply" addresses), and never replies to
  her own outbound mail.

The net effect: an agent can forward Penny into a deal's email traffic and trust
that she'll keep the thread moving and flag what needs a human — without ever
worrying she'll say something to the other side on her own.

### 2.3 The contract execution-completeness audit — "comb every page"

The compliance review already checked state-specific disclosures and required
forms. It did not check the most basic thing a TC does first on a freshly
executed contract: **is it actually fully signed?** That gap is now closed. Every
compliance review now also runs an execution-completeness pass — signatures,
initials, dates, and whether referenced addenda are actually attached — framed to
the model as the page-by-page comb a coordinator does on day one. It remains
surface-only: Penny flags, a human decides. The gate on compliance never moves.

### 2.4 Proactive next moves — "what I'd tackle first"

A coordinator walks in and knows what's on fire. Penny now has a single
prioritization engine that cross-references, across every active deal, the pending
tasks, missing required documents near closing, earnest money status, imminent
deadlines, compliance flags, and missing party contacts — and ranks them. The
output drives two things: the home-screen "what I'd tackle first" cards (click one
and it hands the concrete next step straight to Penny), and her answer when an
agent simply asks "what should I do?" — she proposes the next action ("draft the
title company an email asking for the receipt") rather than dumping a list.

### 2.5 Scheduling that holds up against a real calendar

Scheduling moved from "slot math against Penny's own appointments" to coordination
that respects the agent's real life:

- **Live Google Calendar sync** is now connected and verified, at two levels: each
  agent can connect their own calendar, and the brokerage has a shared fallback. A
  deal routes to its assigned agent's calendar when connected. Real free/busy is
  honored and events are created on booking.
- **Per-agent working hours** override the brokerage default, so proposed times fit
  the individual agent's day.
- **Conflict-aware booking** accounts for real appointment durations and existing
  calendar items, not just Penny-managed slots.
- **Coordination outreach** lets Penny propose times *to the parties* — always
  proposal-framed, never a unilateral "you're booked."

Microsoft/Outlook stays deferred behind the same seam.

### 2.6 A full per-deal activity timeline — the paper trail

A coordinator keeps a record. Penny now writes an append-only event log for the
actions that previously left no trace — stage changes, compliance decisions,
earnest-money receipt, and any autonomous or confirmed send — and merges it with
the email log, delivery events (bounces, spam reports), and appointments into one
newest-first timeline per deal. A broker can open any transaction and see exactly
what Penny did, when, through which channel, and whether she or a human did it.

---

## 3. The Hardening Work (Trustworthy Under Real Conditions)

The capabilities above only matter if the machine underneath them is dependable.
This stage put in the production plumbing and safety layers that let Penny run
unattended without quietly doing the wrong thing. Much of this is invisible to a
user — which is the point.

- **Unattended, idempotent scans.** Deadline reminders, scheduled-reply
  resurfacing, and status updates all run from a single secured cron endpoint that
  a scheduler hits every ~15 minutes. Every scan **claims its "done" flag before
  it sends**, so calling it twice — or recovering from a crash mid-run — never
  double-sends. One brokerage erroring out doesn't stop the others.
- **Confirmation gates are now tested invariants, not conventions.** Every action
  with an external effect — send email, send/route a document, record a compliance
  decision, book an appointment, push a listing, notify parties of a deadline,
  mark earnest money received, send a status update, send an e-signature envelope —
  is split into a read-only step and a confirm step that requires an explicit
  approval with no bypass flag. A dedicated test suite asserts each of these
  endpoints *rejects* an unconfirmed call. The gate is enforced by code that fails
  its tests if someone weakens it.
- **No more silent email failures.** When a party's email was captured with a
  typo, Penny's mail used to vanish into a bounce with no signal. Now bounce,
  dropped, and spam-report events from the email provider flow back, surface in the
  deal's Communications tab as "delivery problems," and nudge the agent. A broker
  finds out a message didn't land — instead of assuming it did.
- **Contract reading you can stake a price on.** Extraction is now **deterministic**
  (temperature pinned to zero), so the same contract reads the same way every time
  rather than sampling a different price on a re-run. **Scanned contracts** with no
  text layer are detected and re-rendered to crisp high-resolution images before
  reading, because a single misread digit moves a price by six figures. The prompts
  explicitly disambiguate the *purchase price* from the loan amount, down payment,
  earnest money, or option fee; pin dates to their correct meaning; capture
  **complete legal names** (a trust's full name, not a truncation); and handle
  **self-represented** parties correctly.
- **Sessions that don't drop you.** A token-refresh path keeps brokers logged in
  through the work day instead of bouncing them hourly.
- **Tamper-proof, expiring OAuth state.** The calendar-connect flow signs its state
  and rejects anything altered or older than its window.
- **SMS that's carrier-compliant.** The SMS channel implements A2P 10DLC **double
  opt-in**: a new number is `pending` until the agent texts YES (→ `active`),
  STOP opts out, HELP always answers — with the legally required disclosure copy
  and public terms/privacy pages backing the campaign.
- **An assistant that stays in her lane.** Penny's system prompt carries an explicit
  scope block: she answers transaction-coordination, deal-specific, and app-usage
  questions fully; gives one friendly redirect to genuinely off-topic asks; and
  treats **legal, tax, and financial advice as a hard line** — she declines and
  points to a licensed attorney, CPA, or the broker, while still stating plain
  facts already on the deal. A companion navigation reference lists the real pages
  and panels so she never invents a menu name or a path that doesn't exist.

---

## 4. Peek Under the Hood

For the technically inclined reviewer — how the above is actually built and
enforced. You do not need this to evaluate Penny as a product, but it's here so
the trust claims are inspectable rather than taken on faith.

### One engine, every channel

WhatsApp, SMS, web chat, and inbound email are all backed by **a single
tool-using AI agent loop** (Anthropic Claude). The agent has a fixed toolbox —
list and inspect transactions, update stages, manage deadlines and tasks, draft
documents, surface compliance findings, pull comps, propose and book appointments,
send status updates, approve/schedule/edit/dismiss drafted email replies, and
suggest next actions. Each tool that reaches outside the building enforces the
confirmation gate at the tool level. Because every channel shares this one loop, a
capability added once behaves identically everywhere, and a guardrail set once
applies everywhere. Only the tone adapts — plain text in the browser,
conversational on messaging.

### The confirmation-gate pattern

Every external action is two endpoints: a read-only preview/draft, and a confirm
endpoint that requires `confirmed=true` in the request body — there is no
"skip confirmation" flag anywhere. On messaging the gate is enforced
conversationally ("reply YES to send"); in the web app a confirmation dialog
enforces it. **Per-task autonomy** can lift specific gates (intro emails,
scheduling, deadline reminders, document routing, status updates) when a brokerage
opts in, per task, on a settings page. **Compliance review can never be made
autonomous** — it is locked off in policy and in code at every level, by design,
not by default.

### Deterministic where it can be, AI where it must be

A deliberate split runs through the product. The things that must be repeatable —
the status-update digest, the compliance *checklist* (are the documents in the
file?), deadline math, scheduling slot math, document-retention policy, the
next-actions prioritization — are **deterministic code**, not model output. The AI
is reserved for what genuinely needs judgment or language: reading a contract,
drafting correspondence in the brokerage voice, and the compliance *review* (an
advisory pass over the contract). This is why a "status update" is trustworthy and
a "compliance review" is explicitly advisory — the doc tells you which is which.

### How the AI reads documents

Contracts and listing packets are passed to the model as **native documents**
(the actual PDF or image bytes), not OCR'd text — except scanned PDFs with no text
layer, which are detected and re-rendered to high-resolution images first, because
the model reads a sharp raster more accurately than a coarsely-rendered scan.
Extraction runs at temperature zero for repeatability, with strict-JSON prompts
that instruct the model to **return an empty field rather than guess**. It never
fabricates a value it can't find.

### Per-brokerage isolation, two layers deep

Every database query is scoped by `brokerage_id`, and that scoping is enforced
twice: in application code, and by Postgres **row-level security** keyed off a
brokerage id baked into the auth token. Even if application code forgot a filter,
the database would refuse to return another brokerage's rows. The privileged
service key that bypasses RLS is server-side only and never reaches the browser.
No API key of any kind lives in frontend code; every AI and integration call goes
through the backend.

### The seam pattern

Integrations that can't yet be exercised against a real provider are built
**behind seams**: the calling code is complete and the seam reports "not
connected" until real credentials and approval land. This keeps the testable core
honest and lets the external piece drop in without touching callers. Calendar sync
already graduated from a seam to a live integration this way; MLS publishing and
DocuSign e-signature still sit behind theirs, waiting on per-market agreements and
partner review respectively, not on code.

### Tested and CI-gated

There is a real regression suite (well over a hundred backend tests) plus a
type-checked frontend, both run on every push and pull request. The tests
specifically cover the load-bearing invariants: confirmation gates reject
unconfirmed calls, scans fire at most once, tenant scoping holds, extraction is
deterministic, scanned-PDF detection works, and consent flows behave. The point is
not test count — it's that the safety properties this document claims are asserted
by code, so they can't silently regress.

### High-level shape

```
Channels:  WhatsApp · SMS · Web chat · Web app · Inbound email
                     │
                     ▼
Frontend (React 18 + TS + Vite + Tailwind + Zustand)
                     │  HTTPS / JSON
                     ▼
Backend (FastAPI + Python)
   │
   ├── one tool-using agent loop (Anthropic Claude) — backs every channel
   ├── Supabase        Postgres + Auth + Storage, RLS per brokerage
   ├── Anthropic Claude extraction · drafting · compliance review
   ├── OpenAI Whisper   voice-memo transcription
   ├── Twilio           WhatsApp + SMS, inbound and outbound (incl. media)
   ├── SendGrid         outbound email + inbound parse + delivery events
   ├── Rentcast         comparable sales + public property records
   └── Google Calendar  live free/busy + event creation (brokerage + per-agent)
   │
   └── unattended cron → idempotent scans (deadlines · scheduled replies · status updates)

Deferred behind seams: MLS publishing · DocuSign · Microsoft Calendar
```

---

## 5. Trust, Data, and the Honest Edges

Brokers handle nonpublic personal information — SSNs, bank statements, income
docs — and will ask about data handling before signing. The posture, stated
plainly:

- **Isolation and storage.** Files live in private storage; every query is scoped
  by brokerage and enforced by row-level security; the privileged key is
  server-only. The hosting foundation (Supabase) carries SOC 2 Type II / ISO 27001
  — that's the infrastructure floor, **not Penny's own attestation**.
- **Data handling in writing.** Brokerages operate under a written DPA and Privacy
  Policy that name the subprocessors and describe the security posture. SOC 2 Type
  II readiness is on the roadmap as the next step beyond the infrastructure floor;
  it is stated as in-progress, not claimed as complete.
- **Document retention is configurable** (default 7 years, opt-in enforcement). The
  policy math is built and tested; automated deletion is a separately-gated
  follow-up — **nothing is ever deleted blind.**
- **AI compliance review will occasionally misclassify.** That's a property of the
  technology, and it's why the human gate on compliance is permanent. Findings now
  carry a self-reported confidence and low-confidence ones are flagged "verify";
  a broker correct/incorrect feedback log is recorded for review, and the model is
  **never** auto-tuned in production.
- **AI disclosure + consent.** Outbound email can carry an optional, editable AI
  disclosure footer, and an optional signed party-consent link — both brokerage
  policy toggles.

### Scope boundaries (what Penny deliberately is not)

- **Not a forms library.** She works with documents the brokerage already has;
  distributing blank state-association forms requires licensing she doesn't hold.
- **Not accounting software.** Earnest-money support is *receipt tracking only* —
  amount, due date, where it's held, whether it arrived. No calculations,
  disbursements, or trust-account math.
- **Not a compliance authority.** Compliance review is a verification aid against a
  state ruleset, never legal advice, and never auto-approves.
- **Not an auto-responder to the outside world.** She threads, logs, and drafts —
  but never sends to an outside party without a human tap.
- **Not a live two-way sync with other TC tools.** She imports existing deals from
  a CSV as a one-time on-ramp; she becomes the system of record, not a mirror of
  one kept in Dotloop or SkySlope.

Several remaining gates are business and legal rather than engineering: state-form
distribution licensing, per-market MLS write agreements, WhatsApp Business API
production approval (the SMS channel is the production-ready mitigation), DocuSign
partner review, and SOC 2. The engineering seams are in place; only the seam
bodies change when each clears.

---

## 6. Status and Maturity

Everything described in Sections 2–4 is built, integrated, tested, and exercised
against live services in a working brokerage. The core engine, contract
intake, transactions, deadlines, document drafting and routing, the compliance
file and review (now including the execution-completeness audit), comps, scheduling
with live Google Calendar, MLS prep, EMD tracking, two-way inbound email with
deferral, recurring status updates, the broker review queue and reporting,
proactive next actions, the activity timeline, AI disclosure, document-retention
policy, and the per-task autonomy model are all in place. The backend test suite
and frontend type-check run in CI on every change.

The deployed backend is live, WhatsApp inbound is verified end-to-end, SMS is live
with carrier-compliant opt-in, email threading and delivery feedback are wired, and
unattended cron scans are verified idempotent in production logs.

What remains is concentrated in two places, and neither is blocked on writing more
code: the integrations deliberately left behind seams (MLS publishing, DocuSign,
Microsoft Calendar), which wait on provider credentials and approvals; and the
business/legal gates above (chiefly WhatsApp Business production approval and the
SOC 2 track). Pricing is per-seat, all features, no tiers.

---

## 7. Where Critique Is Most Useful

Because this document exists to be torn into, the questions most worth a working
broker's scrutiny:

1. **Does the status-update cadence and content match what your clients actually
   expect** — frequency, channel, and what's in it?
2. **Is the outside-party email gate in the right place?** Penny drafts and a human
   sends. Is "she never sends to the other side on her own" the right line, or do
   parts of it want to be autonomous for a mature office?
3. **Where else does a real TC act that Penny still only reacts?** The gap analysis
   surfaced status updates and the execution audit — what's the next gap?
4. **Is the compliance posture credible** — advisory AI review plus a deterministic
   document checklist plus a permanent human gate — or does it need to do more, or
   promise less?
5. **What would you need in writing on data handling** before putting a live deal
   (NPI and all) into Penny?

---

*For implementation detail, see the codebase and the engineering specs. This
overview is intended for product-level assessment and critique. Reflects the
codebase as of 2026-06-13.*
