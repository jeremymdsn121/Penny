# Penny — Pilot Runbook (internal)

How to take Penny from "code complete" to "a real broker is testing it with
real deals." Read this end-to-end before inviting a tester. Companion docs:
`DEPLOYMENT.md` (external setup) and `TESTER_GUIDE.md` (hand to the tester).

The goal of the first pilot is **a supervised, web-chat-first test with one
friendly design partner on a handful of real deals** — not an unattended launch.
Scope tightly; expand once the core path is proven against live services.

---

## 1. Readiness at a glance

**Verified-core (exercise these in the pilot):** auth, onboarding, contract PDF
extraction → transactions, web "Ask Penny" chat, document generation,
compliance review, comps, scheduling, the compliance checklist, review queue,
workflow tasks, EMD tracking, reporting, briefing / next actions.

**Off-limits (built behind seams — keep out of the test script):**
- Calendar sync (Google/Microsoft) — reports "not connected."
- MLS publishing — reports "not connected."
- DocuSign e-signature — reports "not connected."
- Inbound email reply threading — needs the `reply.poweredbypenny.com` MX record.

**Channel choice:** use the **web chat** for the pilot. WhatsApp is still the
Twilio sandbox (the tester must text `join <word>` to a shared number; production
needs Meta approval — see `BLOCKERS.md` Hard Limit 4). SMS fallback works but
needs a provisioned number + webhook.

---

## 2. Deploy (Render)

`render.yaml` is a Blueprint for both services. New > Blueprint in the Render
dashboard, point at this repo, fill the prompted secrets.

- [ ] Apply Supabase migrations `001`–`017` in order (already done in the dev
      brokerage; a fresh project needs them — see `DEPLOYMENT.md` §1).
- [ ] Deploy `penny-api` + `penny-web` from the Blueprint.
- [ ] Set `VITE_API_BASE_URL` on `penny-web` = `<api-url>/api/v1`, redeploy it
      (Vite inlines env at build time).
- [ ] Set `EXTRA_CORS_ORIGINS` on `penny-api` = the `penny-web` URL.
- [ ] Set `PUBLIC_BASE_URL` on `penny-api` = its own public URL.
- [ ] Confirm `GET <api-url>/health` returns `{"status":"ok","env":"production"}`.

### Minimum env for a useful pilot
| Var | Why |
|-----|-----|
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | the database + auth |
| `ANTHROPIC_API_KEY` | **load-bearing** — extraction, chat, compliance, doc generation |
| `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` | any email send (verified sender) |
| `RENTCAST_API_KEY` | comps (optional; 503s cleanly without it) |
| `REMINDER_CRON_SECRET` | enables the unattended reminder scan (see §4) |

Leave calendar/MLS/DocuSign/Twilio vars blank for a web-chat pilot — those
features no-op cleanly.

---

## 3. Pre-flight smoke test (do this yourself before the tester logs in)

Most features pass type/unit checks but have **not** been run against live
services. Walk the exact path the tester will, against the deployed instance,
with a real (or realistic) contract PDF. Each box is a stop-and-verify gate.

- [ ] **Sign up + onboard** a fresh brokerage. Lands on the home page after the
      5-step wizard.
- [ ] **Upload a contract PDF** → extraction returns sane fields (address,
      parties, price, dates). Spot-check 2–3 fields against the PDF. Empty is
      acceptable for a missing field; **wrong** is a bug.
- [ ] Transaction appears in the list with the right stage and a checklist %
      (the compliance checklist auto-instantiated).
- [ ] **Ask Penny** in chat: "what's on <address>?" → she pulls the real deal.
      Try "what should I do first?" → concrete next actions, not a raw list.
- [ ] **Draft a document** (status update or cover letter) → reads in the
      brokerage voice. Confirm-then-send works (only if SendGrid is set).
- [ ] **Run a compliance review** → surfaces findings + checklist + a *suggested*
      status. Recording a decision is confirm-gated. (Never auto-approves.)
- [ ] **Comps** (if Rentcast set) → estimate + comparables for the address.
- [ ] **Deadlines:** add one, then hit "Run reminders" on the dashboard → the
      internal WhatsApp/console nudge path runs without error.
- [ ] **Review queue / Reports** render with the test deal in the right buckets.

If any step errors, fix before inviting the tester. A short Loom of you walking
this path doubles as the tester's intro.

---

## 4. Deadline reminders (so "she chases your deadlines" is true)

Reminders only fire when something calls the scan. Two options:

- **Supervised pilot:** the dashboard "Run reminders" button is enough — click it
  daily.
- **Unattended:** set `CRON_SECRET` on the backend and point a scheduled job
  (e.g. a Render Cron Job) at `POST /api/v1/cron/run-scans` with header
  `X-Cron-Secret: <CRON_SECRET>` — it runs the deadline-reminder and
  scheduled-reply scans across all brokerages. The endpoint is JWT-less and
  shared-secret-guarded; it 503s until the secret is set.

---

## 5. Before real client PII goes in

Real deals carry SSNs / financials / NPI. No SOC 2 yet (`BLOCKERS.md` Hard
Limit 6) — fine for **one design partner under a simple written agreement**, not
for broad signups.

- [ ] Tester is under an NDA / pilot agreement.
- [ ] A basic Privacy Policy exists and is linked.
- [ ] Turn on the **AI-disclosure footer** (Compliance Settings, Section 6) so
      outbound email discloses AI involvement.
- [ ] Set expectations in writing (`TESTER_GUIDE.md`): compliance review is an
      assistant **not legal advice** (Hard Limit 5); EMD is **receipt tracking
      only**; reminders depend on §4 being set up.

---

## 6. During the pilot

- Stay in the loop — watch for errors, be ready to patch and redeploy.
- Start with 1–3 real deals, not the tester's whole book.
- Collect feedback against the verified-core path; defer anything that wanders
  into an off-limits seam.
