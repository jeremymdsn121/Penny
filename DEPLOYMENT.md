# Penny — Deployment & External Configuration

External setup required before V2 features work end-to-end. Code-side everything
is wired; these are the out-of-band steps (DNS, platform registration, buckets,
migrations, env vars). See `BLOCKERS.md` for items that need business/legal action.

## 1. Database migrations

Run **in order** in the Supabase SQL Editor (paste file contents). V2 adds 006–015:

| File | Adds |
|------|------|
| `006_pending_whatsapp_transactions.sql` | WhatsApp inbound contract extraction (1A) |
| `007_agent_style.sql` | per-agent style: `knowledge_rules.agent_id`, `knowledge_documents.agent_id`, `whatsapp_contacts.agent_id` (1B) |
| `008_agent_channels.sql` | `agent_channels` (WhatsApp + SMS); migrates `whatsapp_contacts` (1C) |
| `009_compliance_checklist.sql` | `compliance_templates`, `compliance_template_items`, `transaction_checklist_items`, `transactions.transaction_type`; seeds buy/list defaults (2A) |
| `010_review_queue.sql` | `deadlines.resolved`/`resolved_note`, `transactions.last_activity_at` + triggers (2B) |
| `011_workflow_tasks.sql` | `workflow_templates`, `workflow_steps`, `transaction_tasks`; seeds buy-side workflow (3) |
| `012_transaction_emails.sql` | `transaction_emails` reply threading (4) |
| `013_emd_tracking.sql` | `transactions.emd_*` columns (5) |
| `014_party_consents.sql` | `party_consents`, `brokerages.ai_disclosure_*`, `request_ai_consent` (6) |
| `015_reporting.sql` | `transactions.closed_at` + backfill (7) |
| `016_reply_forwarding.sql` | `brokerages.forward_replies_to_agent` (forward inbound replies to the deal's agent) |
| `017_doc_routing.sql` | `doc_routing_rules` + `pending_doc_routes` (Autonomy task `doc-routing`) |
| `018_email_autoreply.sql` | two-way email Phase 1: `brokerages.email_*_enabled` + `pending_email_replies` |
| `019_scheduled_replies.sql` | two-way email Phase 2: scheduled/deferred reply columns on `pending_email_replies` |
| `020_ai_usage.sql` | per-brokerage AI token-usage log |
| `021_compliance_feedback.sql` | `compliance_feedback` — broker verdicts on AI findings (HL5) |
| `022_document_retention.sql` | `brokerages.document_retention_years` + `_enabled` (HL6 interim) |

(Earlier migrations `001`–`005` are unchanged; `004`/`005` must already be applied.)

## 2. Supabase Storage buckets

Auto-created on first use (private), but you can pre-create them:
- `contracts` — uploaded contract PDFs
- `knowledge-docs` — brand/style + per-agent style references
- `compliance-docs` — compliance checklist item documents + EMD receipts
- `listing-packets` — MLS listing packets (if used)

## 3. Twilio — WhatsApp + SMS (1A, 1C, HARD LIMIT 4)

- WhatsApp: `TWILIO_WHATSAPP_FROM` (sandbox `whatsapp:+14155238886` or production).
  Inbound webhook → `POST /api/v1/whatsapp/inbound`. Behind ngrok in dev, set
  `TWILIO_SKIP_VALIDATION=true` (never in prod).
- SMS fallback: provision a standard Twilio number, set `TWILIO_SMS_FROM`, and
  point its "A message comes in" webhook → `POST /api/v1/sms/inbound`.
- Media (PDF/photo) download uses Basic Auth with `TWILIO_ACCOUNT_SID` /
  `TWILIO_AUTH_TOKEN`. HEIC/HEIF photos need `Pillow` + `pillow-heif` (in
  `requirements.txt`).

### SMS A2P 10DLC go-live (US)

US SMS over a standard number requires **A2P 10DLC registration** before carriers
will reliably deliver — a number works in Twilio but messages get filtered until the
brand + campaign are approved. This is account-level setup in the Twilio console, not
a code change. Order of operations:

1. **Register the brand** (Twilio console → Messaging → Regulatory Compliance / A2P).
   The legal entity is the brokerage's company (e.g. *Madison Solutions LLC*).
2. **Create the campaign.** Use case *Low Volume Mixed* is the fast/cheap starter tier
   (low daily cap); graduate to *Standard* when volume grows. Required fields:
   - **Campaign description** — operational/transactional TC messaging (deadline
     reminders, status updates, EMD/document confirmations, paperwork requests,
     scheduling, replies to agent questions). Not marketing.
   - **Sample messages** — include the sender identity ("Penny … at <brokerage>") and
     `Reply STOP to opt out`.
   - **Opt-in description** — recipients give their number to the brokerage to be
     contacted by Penny; that registration is consent. **No keyword opt-in** (leave
     the opt-in keyword/message fields blank).
   - **Privacy Policy URL** → `https://<api-host>/api/v1/privacy`
   - **Terms URL** → `https://<api-host>/api/v1/terms` (see Section 4b — these must be
     live/redeployed before the carrier checks them).
3. After approval: **attach the 10DLC number to the campaign's Messaging Service**,
   set `TWILIO_SMS_FROM` (bare E.164), and set the **inbound webhook on the Messaging
   Service** → `POST /api/v1/sms/inbound` (on a Messaging Service, set it there, not on
   the number).
4. **Register agent numbers** via `POST /api/v1/sms/contacts`, then text the number to
   confirm a round-trip.

`HELP`/`STOP` are handled via Twilio Advanced Opt-Out, not the opt-in fields. The
`support@` HELP contact should be a real, monitored inbox.

## 4. SendGrid — inbound reply threading (4)

1. Pick a reply subdomain, e.g. `reply.poweredbypenny.com`. Add an **MX record** pointing
   to `mx.sendgrid.net`.
2. SendGrid dashboard → Settings → **Inbound Parse** → add the subdomain →
   destination URL `https://<api-host>/api/v1/email/inbound?key=<SENDGRID_WEBHOOK_KEY>`.
3. Env: set `REPLY_EMAIL_DOMAIN=reply.poweredbypenny.com` (enables `Reply-To: tx-{id}@…`)
   and `SENDGRID_WEBHOOK_KEY` to a random secret (the webhook checks `?key=`).
4. `SENDGRID_FROM_EMAIL` must be a verified SendGrid sender.

## 4b. Public legal pages (A2P privacy + terms)

Carrier A2P registration requires publicly reachable privacy + terms URLs. These are
served by the backend (no auth, no DB) from `app/api/v1/routes/legal.py`:

- `GET /api/v1/privacy` — privacy policy
- `GET /api/v1/terms` — SMS program terms (carrier-required: program name/description,
  message frequency, "message & data rates may apply", **HELP**/**STOP** instructions,
  carrier-liability disclaimer)

Business identity (company name, support email, address, last-updated) lives in the
constants at the top of `legal.py` — edit there. The pages must be **redeployed and
loading** before submitting/again whenever the carrier re-checks the URLs.

## 5. AI disclosure consent links (6)

- Set `CONSENT_SECRET` (HMAC for consent links; falls back to `SECRET_KEY`).
- Set `PUBLIC_BASE_URL` to the backend's public origin so consent links are
  absolute. Public endpoint: `GET /api/v1/consent/{tx}/{role}`.

## 6. Scheduled jobs

- **Unattended scans (all brokerages):** `POST /api/v1/cron/run-scans`, guarded by
  the `CRON_SECRET` shared secret (`X-Cron-Secret` header; 503 when unset). It loops
  every brokerage and runs both the deadline-reminder scan and the scheduled-reply
  scan (both idempotent). The Render blueprint wires this as the `penny-cron-scans`
  cron service (every 15 min, `backend/scripts/run_cron_scans.py`); it pulls
  `CRON_SECRET` from `penny-api` via `fromService` so the generated value matches on
  both sides. Without it, reminders + scheduled-reply resurfacing only run from the
  dashboard dev buttons.
- The per-brokerage `POST /api/v1/deadlines/run-reminders` (idempotent) still exists
  for the dashboard "Run reminders" button and JWT-scoped callers.
- The broker review queue auto-refreshes client-side every 5 minutes; no job needed.

## 7. Deferred integrations (see BLOCKERS.md)

Calendar OAuth (Google/Microsoft), MLS write APIs, and DocuSign are behind seams
(`calendar_provider.py`, `mls_provider.py`, `docusign_provider.py`) and report
"not connected" until credentials/approval exist. Their env vars
(`GOOGLE_*`, `MICROSOFT_*`, `DOCUSIGN_*`) are placeholders in `.env.example`.

## Pre-prod checklist

- [ ] Migrations 001–022 applied in order on the target Supabase instance
- [ ] Storage buckets exist and are private
- [ ] `TWILIO_SKIP_VALIDATION=false`; webhooks signature-validated
- [ ] SMS: A2P brand + campaign approved; number on the Messaging Service;
      `TWILIO_SMS_FROM` set; inbound webhook on the Messaging Service
- [ ] `/api/v1/privacy` and `/api/v1/terms` live (A2P URLs); `support@` inbox monitored
- [ ] `REPLY_EMAIL_DOMAIN` MX record live; `SENDGRID_WEBHOOK_KEY` set
- [ ] `CONSENT_SECRET`, `PUBLIC_BASE_URL` set
- [ ] `CRON_SECRET` set; `penny-cron-scans` cron job live (hits `/cron/run-scans`)
