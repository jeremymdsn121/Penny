# Sloane — Product Overview

**Sloane** is a B2B SaaS "virtual transaction coordinator" for residential real
estate brokerages. One Sloane instance per brokerage, priced by agent seat. She
runs the operational layer of a real estate transaction (contract intake,
deadline tracking, document drafting and routing, a compliance file, comparable
sales, scheduling, MLS listing prep, earnest-money tracking, and broker
reporting) while keeping a human in the loop for anything that leaves the
building.

This document is a product overview, not a technical specification. It is
written to be read by people outside the project for assessment and critique.

---

## 1. What Sloane Is

Sloane is a **per-brokerage assistant**, not a consumer app. Each brokerage gets
its own isolated instance: its own data, its own branding and voice, its own
agent roster. A broker-owner or admin onboards once, sets policy, and then the
brokerage's agents work with Sloane day to day.

The product thesis is unchanged from day one: a brokerage's transaction
coordinator role is expensive, hard to staff, and mostly pattern-driven. Sloane
does the predictable majority of that work (chasing dates, drafting routine
correspondence, tracking what documents are missing, flagging compliance gaps,
routing paperwork) and escalates the judgment calls to a person.

What has changed is the **shape** of the product. Sloane began as a single-agent
assistant reachable over one channel. She is now a brokerage-wide operations
layer that meets agents on whatever channel they already use, works proactively
instead of only on request, and gives the broker a supervisory view across every
deal in the office. The three throughlines of that evolution:

- **One channel to omnichannel.** WhatsApp text was the entry point. Sloane now
  also handles WhatsApp voice memos and inbound photos/PDFs, an SMS fallback for
  agents who do not use WhatsApp, a browser chat, and a full web app.
- **Reactive to proactive.** Sloane used to act when asked. She now generates the
  next tasks on a deal as it moves through stages, surfaces a broker review queue
  of what needs attention, threads inbound email back onto the right
  transaction, and (where the brokerage opts in) routes documents on her own.
- **Individual tool to brokerage system.** Per-agent style, a broker review
  queue, production and compliance reporting, and per-task autonomy policy turn
  Sloane from a personal assistant into something the brokerage runs on.

---

## 2. Who Uses It

- **Broker-owner / admin.** Onboards the brokerage, sets policy (per-task
  autonomy, compliance settings, AI disclosure), and works the review queue and
  reports. The supervisory role is a first-class surface, not an afterthought.
- **Agents.** Manage their active deals day to day. Most reach Sloane over
  WhatsApp or SMS; the web app is there for heavier work and for the
  chat-forward "Ask Sloane" experience.
- **Transaction coordinators.** Where a brokerage has them, Sloane augments them
  and removes the rote chasing. Where it does not, Sloane fills the gap.

---

## 3. How Agents Reach Sloane (Channels)

Sloane is deliberately channel-flexible, because agents live in their phones.

- **WhatsApp (text, voice, and media).** The primary channel. Agents text Sloane,
  send a voice memo (transcribed automatically), or send a photo or PDF of a
  contract. Inbound media is downloaded, normalized (including HEIC/HEIF from
  iPhones), and run through the same extraction pipeline as a web upload; the
  agent confirms with a reply before anything is committed.
- **SMS fallback.** For agents who do not use WhatsApp, the same assistant is
  reachable over standard SMS (text only). Same tools, same confirmation gates.
- **Web chat ("Ask Sloane").** The same assistant, exposed in the browser. It is
  the centerpiece of the home screen: a chat-forward landing with a live
  briefing of active deals, what needs review, and what is closing soon.
- **Web app.** The full operational surface: dashboard, transaction detail,
  listings, review queue, reports, brand and style, team, and settings.

A single assistant engine backs every channel, so behavior and guardrails are
identical no matter how an agent reaches her. Only the tone adapts (plain text
in the browser, conversational on messaging).

---

## 4. Core Capabilities

| Capability | What it does | Human gate |
|---|---|---|
| Contract intake | Extracts ~25 structured fields from a contract PDF or photo, on web or messaging | Agent confirms |
| CSV import | Bulk-imports existing deals from a CSV export (Dotloop / SkySlope / spreadsheet), with header aliasing | Preview, then confirm |
| Transactions | The deal record: parties, dates, price, financing, stage | Agent edits |
| Deadline tracking | Tracks key dates, nudges internally at 5 / 2 / 0 days | Auto (internal); external notice gated |
| Workflow tasks | Generates the right next tasks on stage changes and as deadlines approach | Agent works the list |
| Document drafting | Status updates, cover letters, follow-ups in the brokerage voice | Agent confirms send |
| Document routing | Sends the contract to chosen parties (e.g. title, lender) when a deal enters a stage | Confirm-gated, or autonomous if opted in |
| Compliance file | Tracks whether required documents are present, per a per-brokerage checklist | Agent works the list |
| Compliance review | Structural + AI checks of the contract against a state ruleset | **Always human** |
| Comparable sales | Rentcast AVM, comps, and public property record for any address | Read-only |
| Scheduling | Proposes and books showings / inspections within working hours | Agent confirms booking |
| MLS listing prep | Extracts listing-packet fields for MLS entry | Agent reviews |
| EMD tracking | Tracks earnest-money receipt, due date, and where it is held | Mark-received is gated |
| Inbound email threading | Logs replies back onto the right deal and nudges the responsible agent | Never auto-replies |
| Broker review queue | Surfaces deals needing attention across the brokerage | Read / triage |
| Broker reporting | Pipeline, production, and compliance-health summaries with CSV export | Read-only |
| AI disclosure + consent | Optional disclosure footer and party-consent links on outbound email | Policy toggle |

### Adopting mid-stream (the migration path)

A brokerage signing up rarely starts from zero. It typically has a dozen or more
deals already live in another tool (Dotloop, SkySlope) or a spreadsheet, and
re-keying them by hand is a non-starter — so a tool with no on-ramp for existing
business is only adoptable by brand-new offices.

Sloane's answer is **CSV import**. The broker exports their open deals, drops the
file in, and Sloane maps the columns to its own fields. Because real exports never
use Sloane's exact headers, the importer **aliases the common variants** ("Property
Address," "Buyer," "Close Date," "Purchase Price," status and side labels, and so
on), so a lightly-edited export usually maps with no manual renaming. A
downloadable template documents the canonical columns for the spreadsheet case.

The flow follows the same confirmation discipline as everything else: the upload
is **parsed and validated into a preview** (ready rows, row-level errors,
warnings for values it had to drop or default, and **duplicate flags** against
deals already on file) and **nothing is written until the broker confirms**.
Each imported deal then runs the same setup as a hand-entered one — its
compliance checklist, workflow tasks, and document routing are all instantiated —
so an imported book of business is immediately first-class, not a second tier of
"imported" records.

This deliberately is **not** a live two-way integration with those tools (see
Scope Boundaries). It is a one-time on-ramp, which is what removes the adoption
blocker for a brokerage with an existing pipeline.

---

## 5. The Autonomy Model

The single most important design decision in Sloane is **where the human gate
sits**, and that decision is now an explicit, per-brokerage policy rather than a
hardcoded rule.

**Confirmation gates.** Anything with an external effect is split into two steps:
a read-only preview/draft, and a confirm step that requires explicit approval.
This applies to sending email, sending a document, routing a document, recording
a compliance decision, booking an appointment, pushing a listing, notifying
outside parties of a deadline, marking earnest money received, and sending an
e-signature envelope. On messaging Sloane enforces the gate conversationally; in
the web app a confirmation dialog enforces it.

**Per-task autonomy.** A brokerage can lift specific gates by marking individual
tasks autonomous (intro emails, scheduling, deadline reminders, document
routing, status updates, MLS prep). When a task is autonomous, Sloane acts
without asking for that task only. This is set during onboarding and editable
afterward on a dedicated Autonomy settings page. It is opt-in and per-task, so a
brokerage can let Sloane send routine intros on her own while still reviewing
everything else.

**One gate never lifts.** Compliance review can never be made autonomous. It is
locked off in policy and in code at every level. Sloane always surfaces findings
to a human and records only the human's decision. This is a deliberate
load-bearing constraint, not a configuration default.

This model is what lets Sloane scale from "drafts everything for review" to
"runs the routine parts unattended" at the brokerage's own pace and risk
tolerance, without ever turning the high-stakes judgment calls over to the
model.

---

## 6. Architecture (high level)

```
Channels:  WhatsApp · SMS · Web chat · Web app
                     │
                     ▼
Frontend (React 18 + TS + Vite + Tailwind + Zustand)
                     │  HTTPS / JSON (Axios)
                     ▼
Backend (FastAPI + Python)
   │
   ├── Supabase        Postgres + Auth + Storage, RLS per brokerage
   ├── Anthropic Claude extraction, drafting, compliance, the agent loop
   ├── OpenAI Whisper   voice-memo transcription
   ├── Twilio           WhatsApp + SMS (inbound and outbound)
   ├── SendGrid         email send + inbound reply parsing
   └── Rentcast         comparable sales + public property data

Deferred behind seams: Google/Microsoft Calendar · MLS publishing · DocuSign
```

Every AI and integration call goes through the backend. No keys ever live in the
frontend. Every database query is scoped by `brokerage_id`, enforced both in
application code and by Postgres row-level security, so data cannot cross
brokerage boundaries even if application code is wrong.

---

## 7. Frontend

A single-page React app (React 18, TypeScript, Vite, Tailwind, Zustand for
state, Axios for the API, React Hook Form + Zod for forms). It has matured from
a utilitarian dashboard into a chat-forward product with its own visual identity.

- **Chat-forward home.** The landing screen leads with "Ask Sloane": a greeting,
  a live briefing pulled from real deal data, a chat bar with browser-native
  voice input, and a jump-to grid. On the bare launcher the navigation chrome
  steps out of the way; it returns once the agent starts a chat or opens a page.
- **Operational dashboard and deal pages.** The full pipeline view, transaction
  detail with panels for documents, compliance, comps, scheduling, deadlines,
  EMD, and communications.
- **Brokerage surfaces.** Review queue (admin), reports, brand and style, team,
  messaging settings, compliance settings, and the Autonomy settings page.
- **Identity.** A dark-default theme with a token system, a left-sidebar shell,
  and an animated brand mark (a single-stroke "P" that signs itself in on the
  landing screen and sits static in the sidebar).

Sloane's name is fixed product-wide and she is referred to as she/her in all
copy.

---

## 8. Backend

FastAPI + Python. Supabase is reached through thin async HTTP wrappers rather
than a heavy SDK. The service-role key is used server-side only and bypasses RLS;
it never reaches the client.

The heart of the backend is a **single tool-using agent loop** (Anthropic
Claude) that powers every conversational channel. The agent has tools to list
and inspect transactions, update stages, add notes, draft and send documents,
manage deadlines, surface compliance findings, pull comps, propose and book
appointments, report on pending tasks, and more. Each tool that has an external
effect enforces the confirmation gate described above. Because every channel
shares this one loop, a capability added once is available everywhere.

Around that loop sit purpose-built services: contract field extraction
(documents passed natively to the model, never OCR pre-processing), brand/style
rule extraction, document generation in the brokerage voice, a hybrid
compliance engine (deterministic structural checks plus an AI pass over the
contract against a state ruleset), a deadline reminder scan, a workflow-task
engine, a document-routing engine, comparable-sales and property-record clients,
scheduling math, MLS extraction, and broker reporting.

Several integrations that cannot yet be tested against a real provider are built
**behind seams**: the calling code is complete and the seam reports "not
connected" until real credentials and approval exist. This keeps the testable
core honest and lets the external piece drop in without touching callers. The
calendar sync, MLS publishing, and DocuSign integrations all sit behind such
seams today.

---

## 9. Integrations

**Live:**

- **Supabase** — Postgres, Auth (the identity provider), and Storage. Auth
  metadata carries the brokerage id into the JWT, which drives both backend
  scoping and Postgres RLS.
- **Anthropic Claude** — contract extraction, document drafting, brand/style
  extraction, compliance review, and the conversational agent loop.
- **OpenAI Whisper** — transcription of WhatsApp voice memos.
- **Twilio** — WhatsApp and SMS, inbound and outbound, including media.
- **SendGrid** — outbound email and inbound reply parsing. Outbound mail carries
  a per-transaction reply address so replies thread back onto the right deal.
- **Rentcast** — comparable sales (AVM + comps) and public property records.

**Deferred, built behind seams** (wired when credentials and approval exist):

- **Google / Microsoft Calendar** — real free/busy and event creation for
  scheduling. Slot math and local appointments work today; live sync is the
  deferred part.
- **MLS publishing** — there is no universal MLS write API, so real publishing
  is a per-market integration. Listing prep works today; the push is the
  deferred part.
- **DocuSign** — e-signature send. Scoped narrowly on purpose: Sloane sends
  documents she already has, she is not a forms library.

---

## 10. Design Principles

1. **Human-in-the-loop for anything external.** Sloane drafts; humans approve.
   The gate is explicit, per-task configurable, and on compliance permanent.
2. **Never hallucinate data.** Extraction returns empty fields rather than
   guesses. Compliance findings cite their source and are advisory, not legal
   advice.
3. **Per-brokerage isolation.** Data never crosses brokerage boundaries, by
   application scoping and by row-level security.
4. **One engine, every channel.** A single agent loop backs WhatsApp, SMS, and
   web chat, so guardrails and behavior stay consistent.
5. **Build the testable core; seam the rest.** Do not write integration code
   blind against a provider you cannot exercise. Build behind a seam and wire it
   when it can be verified.
6. **Stay in scope.** Sloane is not a forms library, not accounting software, and
   not a system of record for legal advice. She coordinates; she does not
   replace the professionals.

---

## 11. Scope Boundaries (What Sloane Deliberately Is Not)

Being explicit about the edges, because they are where outside critique is most
useful:

- **Not a forms library.** Sloane sends and tracks documents she already has
  (extracted contracts, generated correspondence). Distributing blank state
  association forms requires licensing Sloane does not hold.
- **Not accounting software.** EMD support is receipt tracking only: amount, due
  date, where it is held, whether it arrived. No calculations, no disbursements,
  no trust-account math.
- **Not a compliance authority.** Compliance review surfaces findings against a
  state ruleset as a verification aid. It is never legal advice and never
  auto-approves.
- **Not an auto-responder.** Sloane threads and logs inbound email and drafts
  replies on request, but never sends a reply without a human.
- **Not a live integration with other TC tools.** Sloane imports existing deals
  from a CSV as a one-time on-ramp (see the migration path above), but she does
  not maintain a live two-way sync with Dotloop, SkySlope, or similar. She is the
  system of record once a deal is in, not a mirror of one kept elsewhere.

Several hard limits are business and legal rather than engineering: state
association form distribution, MLS write licensing, calendar-provider OAuth
verification, WhatsApp Business API production approval, and SOC 2 for handling
nonpublic personal information. These gate go-live for specific features
regardless of code readiness.

---

## 12. Status and Maturity

The full capability set described here is built and integrated. The core
conversational engine, contract intake, transactions, deadlines, document
drafting and routing, the compliance file and review, comps, scheduling, MLS
prep, EMD tracking, inbound email threading, the broker review queue and
reporting, AI disclosure, and the per-task autonomy model are all in place and
exercised in a development brokerage.

The remaining work is concentrated in two places: the integrations deliberately
left behind seams (calendar sync, MLS publishing, DocuSign), which wait on
provider credentials and approvals rather than on code; and the business and
legal gates listed above. Commercialization (per-seat, all features, no tiers)
is planned for after the build.

---

*For implementation detail, see the codebase and the engineering specs. This
overview is intended for product-level assessment and critique.*
