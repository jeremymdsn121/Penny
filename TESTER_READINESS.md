# Penny — Tester Readiness Checklist

The ordered punch-list to get Penny from "built" to "all features live" before
onboarding design-partner brokerages. **This is the working backlog**: when Jeremy
asks "what's next?" (or any variation), surface the **next unchecked, non-blocked
item** here — top to bottom — not a dump of the whole list. Check items off and add
dated notes as they're verified.

Legend: `[x]` live-verified · `[ ]` built but not yet verified live · 🔒 blocked on
external approval · ⏸ deferred (out of tester scope).

Last updated: 2026-06-11.

---

## Tier 0 — External gates (critical path, not engineering work)

These can't be coded around; they gate whether testers can use the channels at all.
Keep them moving in parallel with the verification sweep.

- [ ] 🔒 **WhatsApp Business API production approval** — primary channel. Number
  `+14053636555` in Meta review. Until approved it's the **sandbox** (testers must
  text `join <word>` — a non-starter). On approval: submit the 5 Utility templates
  in `WHATSAPP_TEMPLATES.md`, set `TWILIO_CONTENT_SIDS` (wiring already done), do the
  single-number cutover. See `project_whatsapp_production` memory + `BLOCKERS.md` HL4.
- [ ] 🔒 **A2P 10DLC SMS approval** — SMS fallback. Resubmitted 2026-06-11, carrier
  review. SMS delivery is filtered until approved. See `project_sms_channel` memory.

## Tier 1 — Live verification sweep (the real work, in your control)

Most of these are code-complete with passing unit/type checks but have **never been
exercised against live services / in a browser in a real brokerage**. Ordered by
tester impact. Each needs a real run + fix-what-breaks.

- [x] **1. Core deal flow, fresh brokerage** — VERIFIED 2026-06-11 via the real HTTP
  path on a throwaway tenant (since deleted): signup → JWT carries `brokerage_id` →
  onboarding completes (all tasks default non-autonomous) → extract on a 10-page
  contract returned clean fields with `not_found` correctly empty (no hallucination) →
  transaction created + scoped to the new brokerage; listing under its token returned
  only its own deal (tenant isolation holds). Run with SendGrid/Twilio keys blanked —
  zero outbound. **Remaining (low-risk):** a manual click-through of the 5-step browser
  wizard for UX (only the API path was driven).
- [ ] **2. WhatsApp media intake (1A)** — DEFERRED 2026-06-11 (needs a real photo/PDF
  MMS from a phone; revisit when one's available). Text round-trip is live-verified; the
  **PDF/photo MMS** round-trip through `media_extract` → `pending_whatsapp_transactions`
  → YES-commit is not yet exercised.
- [x] **3. Document generation — live send** — VERIFIED 2026-06-11 on a throwaway deal:
  `draft-document` produced a clean status update in Penny's voice; the send **confirm
  gate** rejected `confirmed=false` (400); a real `confirmed=true` SendGrid send returned
  `{sent: true}` to the operator's own inbox (no outside party). **Remaining:** the
  separate **intro-email** send path (`send_intro_email`) wasn't exercised here — quick
  follow-up.
- [ ] **4. Deadline reminders firing live** — run the scan against a deal with real
  marks (5/2/day-of) and confirm the WhatsApp nudge + the confirm-gated party email
  actually fire and flip the `reminder_*_sent` flags. Marks logic is unit-checked only.
- [ ] **5. Compliance review (AI pass) + checklist UI** — run `compliance-review` on a
  real contract PDF in the browser; confirm findings + suggested status surface and the
  confirm-gated decision records. Walk the checklist panel (2A).
- [ ] **6. Review queue page (2B)** — live render of `/review` with real bucket data
  (compliance attention / closing-soon-incomplete / past-closing / overdue / emd-overdue
  / stale). Page hasn't been rendered live.
- [ ] **7. Workflow tasks (3)** — confirm triggers fire on transaction create, stage
  PATCH, and inside the reminder scan; `get_pending_tasks` groups correctly.
- [ ] **8. EMD receipt tracking (5)** — browser walk of the EMD card: set amount/due,
  upload a receipt to `compliance-docs`, confirm-gated mark-received.
- [x] **9. Comparable sales + property record (Rentcast)** — VERIFIED 2026-06-11 against
  live Rentcast: `comps` returned an estimate ($224k) + 6 comparables; `property-record`
  returned the full public profile (year built, sqft, beds/baths, last sale, and
  tax-assessment / property-tax history). Note: Rentcast returned no value range for this
  address (estimate + comps only) — data variance, not a bug.
- [ ] **10. MLS listing prep** — upload a listing packet, AI-extract fields, save via
  `listings` CRUD. Push stays a no-op seam (expected).
- [ ] **11. Broker reporting (7)** — live render of `/reports` (pipeline / production /
  compliance health) + CSV export, against real closed/active deals.
- [ ] **12. AI disclosure + consent (6)** — disclosure footer on a real send; exercise
  the HMAC consent link path (`CONSENT_SECRET`) end to end.
- [ ] **13. Two-way email (Phase 1 + 2)** — inbound from an internal agent triggers the
  agent loop reply; inbound from an outside party drafts into `pending_email_replies`
  and briefs the agent; `approve_and_send_reply` / `schedule_reply` / the
  `/email/run-scheduled-replies` scan. Inbound threading itself is live; the auto-reply
  layer isn't.
- [ ] **14. Email delivery events (025) + Activity timeline (026)** — both migrations
  applied 2026-06-11 but not exercised: set up the SendGrid Event Webhook, force a
  bounce, confirm it records + nudges the agent; render the per-deal Activity timeline.
- [ ] **15. Per-agent style (1B)** — agent-profile style CRUD; confirm agent-specific
  rules merge over brokerage-wide and win on conflict in a real doc generation.

## Tier 2 — Production hardening before real client NPI

- [ ] **Unattended cron actually scheduled** — point a Render Cron Job at
  `POST /api/v1/cron/run-scans` with `X-Cron-Secret` (set `CRON_SECRET`). Without it,
  reminders + scheduled-reply resurfacing only run from the dashboard dev buttons.
- [ ] **Frontend custom domain** — currently `sloane-web.onrender.com`; move to
  `app.poweredbypenny.com` (and rebuild with `VITE_API_BASE_URL`).
- [ ] **NPI / data posture** — only HL6 interim retention exists (no SOC 2). Fine for
  design partners with test data; have the explicit conversation before real client PII
  at scale. See `BLOCKERS.md` HL6.
- [ ] **Multi-seat decision** — `require_admin` is a no-op; one admin login per
  brokerage. Confirm that's acceptable for testers (agents use WhatsApp/SMS, not logins)
  or scope real multi-seat.

## ⏸ Deferred — explicitly out of tester scope (behind seams)

- ⏸ DocuSign e-signature (Section 8) — seam reports "not connected."
- ⏸ MLS publishing — per-market write integration; no universal API.
- ⏸ Microsoft/Outlook calendar — columns + seam exist, not wired (Google is live).

---

## Already live-verified (reference — don't re-litigate)

Auth · signup · onboarding · contract extraction + transactions · WhatsApp text+voice
(sandbox) · **Google Calendar OAuth + full sync** · **SendGrid outbound (domain-authed,
From Penny)** · **SendGrid inbound reply threading** · **SMS inbound webhook on prod**
(delivery pending A2P) · **scheduling coordination** (type + coordinate-with-parties) ·
web chat "Ask Penny" · home/briefing/next-actions · backend on Render (api.poweredbypenny.com,
`/health` ok) · marketing site on Netlify (poweredbypenny.com) with SMS opt-in CTA.
