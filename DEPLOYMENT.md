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

## 4. SendGrid — inbound reply threading (4)

1. Pick a reply subdomain, e.g. `reply.poweredbypenny.com`. Add an **MX record** pointing
   to `mx.sendgrid.net`.
2. SendGrid dashboard → Settings → **Inbound Parse** → add the subdomain →
   destination URL `https://<api-host>/api/v1/email/inbound?key=<SENDGRID_WEBHOOK_KEY>`.
3. Env: set `REPLY_EMAIL_DOMAIN=reply.poweredbypenny.com` (enables `Reply-To: tx-{id}@…`)
   and `SENDGRID_WEBHOOK_KEY` to a random secret (the webhook checks `?key=`).
4. `SENDGRID_FROM_EMAIL` must be a verified SendGrid sender.

## 5. AI disclosure consent links (6)

- Set `CONSENT_SECRET` (HMAC for consent links; falls back to `SECRET_KEY`).
- Set `PUBLIC_BASE_URL` to the backend's public origin so consent links are
  absolute. Public endpoint: `GET /api/v1/consent/{tx}/{role}`.

## 6. Scheduled jobs

- Deadline reminders + workflow `days_before_deadline` task generation run from
  `POST /api/v1/deadlines/run-reminders` (idempotent, per-brokerage). Point a cron
  at it. (For unattended all-brokerage runs, add a shared-secret variant.)
- The broker review queue auto-refreshes client-side every 5 minutes; no job needed.

## 7. Deferred integrations (see BLOCKERS.md)

Calendar OAuth (Google/Microsoft), MLS write APIs, and DocuSign are behind seams
(`calendar_provider.py`, `mls_provider.py`, `docusign_provider.py`) and report
"not connected" until credentials/approval exist. Their env vars
(`GOOGLE_*`, `MICROSOFT_*`, `DOCUSIGN_*`) are placeholders in `.env.example`.

## Pre-prod checklist

- [ ] Migrations 006–015 applied in order on the target Supabase instance
- [ ] Storage buckets exist and are private
- [ ] `TWILIO_SKIP_VALIDATION=false`; webhooks signature-validated
- [ ] `REPLY_EMAIL_DOMAIN` MX record live; `SENDGRID_WEBHOOK_KEY` set
- [ ] `CONSENT_SECRET`, `PUBLIC_BASE_URL` set
- [ ] Reminder cron pointed at `/deadlines/run-reminders`
