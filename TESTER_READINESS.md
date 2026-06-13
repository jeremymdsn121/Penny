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

**Verification bar:** driving the real API/HTTP path on a throwaway tenant (deleted
after) counts as verified — manual browser click-throughs are not required. Accepted
tradeoff: this won't catch a purely visual render bug; typecheck + correct API
responses cover most of it, and the real UI is spot-checked in normal use.

- [x] **1. Core deal flow, fresh brokerage** — VERIFIED 2026-06-11 via the real HTTP
  path on a throwaway tenant (since deleted): signup → JWT carries `brokerage_id` →
  onboarding completes (all tasks default non-autonomous) → extract on a 10-page
  contract returned clean fields with `not_found` correctly empty (no hallucination) →
  transaction created + scoped to the new brokerage; listing under its token returned
  only its own deal (tenant isolation holds). Run with SendGrid/Twilio keys blanked —
  zero outbound. (Browser wizard click-through waived per the verification bar above.)
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
- [x] **4. Deadline reminders firing live** — VERIFIED 2026-06-11 (API, throwaway tenant,
  Twilio blanked). Seeded deadlines at +5/+2/today: one scan fired the correct mark each
  (5day/2day/day) and silently consumed passed marks (flags `(5,2,day)` =
  `(T,F,F)`/`(T,T,F)`/`(T,T,T)`); a second scan processed 0 (**idempotent**). With
  `deadline-reminders` non-autonomous, the party email was held as `pending_confirm` (no
  auto-send). Confirm-gated `notify-parties` rejected `confirmed=false` (400) and sent on
  `confirmed=true` to the operator's inbox. **Not exercised:** the internal WhatsApp nudge
  send (no registered contact; scan no-ops gracefully — needs Twilio + a real number).
- [x] **5. Compliance review (AI pass) + checklist (2A)** — VERIFIED 2026-06-11 (API,
  throwaway tenant). On a deal with the contract on file: the 2A checklist auto-
  instantiated **16 buy-side items** and an item PATCH → `complete` set `completed_at`;
  `compliance-review` ran the **AI contract pass** (`contract_reviewed`) and surfaced 3
  findings (incl. structural "closing date passed, not marked closed" + AI disclosure
  checks), a `suggested_status`, an annotated checklist, and the legal disclaimer; the
  confirm-gated `compliance-decision` rejected `confirmed=false` (400) and recorded on
  `confirmed=true`. (Review is surface-only — it suggests; the human decision sets it.)
- [x] **6. Review queue (2B)** — VERIFIED 2026-06-11 (API, throwaway tenant). Seeded one
  deal per bucket; `GET /broker/review-queue` (admin-gated, `require_admin` accepts
  `broker_in_charge`) sorted **all six** correctly with accurate reasons:
  compliance_attention, past_closing_not_closed ("Closed 1 day ago…"), closing_soon_incomplete
  ("Closing in 3 days, file 0% complete"), overdue_deadlines, emd_overdue, stale_transactions
  ("No activity in 9 days"). **Gotcha learned:** migration 010's `set_last_activity` is a
  `BEFORE UPDATE` trigger that bumps `last_activity_at = now()` on *any* write, so a stale
  deal can't be seeded by an UPDATE — seed it with a **direct INSERT** carrying an old
  `last_activity_at` (no update trigger fires). In production deals go stale naturally
  (nothing writes to them for 7+ days).
- [x] **7. Workflow tasks (3)** — VERIFIED 2026-06-11 (API, throwaway tenant). All three
  triggers fired from the buy-side seed: **create** → 4 `under_contract` stage-entry tasks;
  **stage→pending** → 3 more (appraisal / title commitment); an **inspection deadline @+5
  + reminder scan** → "Confirm inspection is scheduled" (days_before_deadline).
  `get_pending_tasks` bucketed every pending task correctly by due date (overdue / today /
  this week / upcoming).
- [x] **8. EMD receipt tracking (5)** — VERIFIED 2026-06-11 (API, throwaway tenant). EMD
  scalars (amount $5,000 / due date / held_by / notes) set via the generic PATCH; receipt
  uploaded to the `compliance-docs` bucket (`emd_receipt_document_url` set); `mark-received`
  rejected `confirmed=false` (400) and on `confirmed=true` set `emd_received=true` +
  `emd_received_date`, receipt still on file. Receipt-tracking only — no calculations or
  disbursements (hard rule).
- [x] **9. Comparable sales + property record (Rentcast)** — VERIFIED 2026-06-11 against
  live Rentcast: `comps` returned an estimate ($224k) + 6 comparables; `property-record`
  returned the full public profile (year built, sqft, beds/baths, last sale, and
  tax-assessment / property-tax history). Note: Rentcast returned no value range for this
  address (estimate + comps only) — data variance, not a bug.
- [x] **10. MLS listing prep** — VERIFIED 2026-06-11 (API, throwaway tenant).
  `listings/extract` AI-pulled MLS-ready fields from a packet (address, city/state/zip,
  property_type, list_price, parcel/legal, listing agent, seller) with MLS-only fields
  correctly in `not_found`; saved via `listings` POST (status `draft`, scoped); the
  confirm-gated `push` rejected `confirmed=false` (400) and on `confirmed=true` returned
  the no-op seam ("Direct MLS publishing isn't connected… per-market write integration is
  a planned add-on").
- [x] **11. Broker reporting (7)** — VERIFIED 2026-06-11 (API, throwaway tenant). Seeded
  3 active + 2 closed deals: `broker-summary` returned correct pipeline (active=3, volume,
  by_stage, closing_this_month), production (closed_count=2, closed_volume $900k,
  avg_days_to_close, agent_breakdown), compliance, and at_risk; month/quarter/ytd all 200;
  `transactions-export` returned a valid CSV of closed deals. **Observation:**
  avg_days_to_close is measured from `created_at` (deal entered into Penny), not
  `contract_date` (contract-to-close) — under-reports if deals are entered late; switch to
  `contract_date` for the conventional metric if desired.
- [x] **12. AI disclosure + consent (6)** — VERIFIED 2026-06-11 (API, throwaway tenant).
  Disclosure footer toggles via `PUT /compliance-settings` — `disclosure_text` returns the
  brokerage text when enabled and `None` when disabled (the append path is already live via
  #3's send). HMAC consent link: a valid signed link recorded the acknowledgment (method
  `email_link`, listed via `/transactions/{id}/consents`); a forged token was rejected
  ("invalid"). `CONSENT_SECRET` set.
- [x] **13. Two-way email (Phase 1 + 2)** — VERIFIED 2026-06-11 (API, crafted inbound
  payloads; all email to the operator's own inbox). Outside-party inbound → `outside_drafted`:
  Penny summarized + drafted a non-committal reply into `pending_email_replies` and briefed
  the agent; the send is confirm-gated (400 on `confirmed=false`); dismiss works. Internal-
  agent inbound (SPF-authenticated, matches an `agents.email`) → `agent_replied` (ran the
  agent loop, replied in-thread). `/email/run-scheduled-replies` idempotent. Loop guard:
  `no-reply@` sender → `skipped`. (Inbound-threading logging was already live.)
- [x] **14. Email delivery events (025) + Activity timeline (026)** — VERIFIED 2026-06-11
  (API, throwaway tenant). `POST /email/events` recorded a bounce and was idempotent on
  re-delivery (`processed:0` the 2nd time); `delivery-events` listed it with reason; the
  bounce nudge fired (no-op with Twilio blanked). `GET /{id}/activity` merged the audit
  trail newest-first: delivery_problem, emd_received, compliance_decision, stage_change,
  created. Migrations 025 + 026 confirmed working.
- [x] **15. Per-agent style (1B)** — VERIFIED 2026-06-11 (API, throwaway tenant). With a
  brokerage-wide `tone` (formal) + `signoff` and an agent-specific `tone` (casual),
  `get_confirmed_knowledge_rules(brk, agent)` merged them so the **agent's tone won** on
  conflict (formal suppressed) while the non-conflicting brokerage `signoff` was retained;
  brokerage-only resolution returned just the brokerage rules. A `draft-document` with the
  agent flowed the merged style through — the body opened in the agent's casual first-name
  tone.

## Tier 2 — Production hardening before real client NPI

- [x] **Unattended cron actually scheduled** — DONE + VERIFIED LIVE 2026-06-13. The
  `penny-cron-scans` Render Cron Job (every 15 min, `backend/scripts/run_cron_scans.py`
  → `POST /api/v1/cron/run-scans`) pulls `CRON_SECRET` from `penny-api` via `fromService`
  so the generated value matches on both sides. **Verified** in the Render logs: back-to-
  back scheduled runs (08:15 / 08:30) each returned `200` with
  `{"ok":true,"brokerages":4,...,"errors":[]}` and finished successfully — confirms the
  schedule, the secret wiring, the per-brokerage loop, and idempotency. Reminders +
  scheduled-reply resurfacing no longer depend on the dashboard dev buttons.
- [x] **Frontend custom domain** — DONE 2026-06-13. Browser app live on
  `app.poweredbypenny.com` (Render custom domain + cert; CNAME at Porkbun; penny-web
  redeployed). `render.yaml` declares the domain on `penny-web` and pins the public URLs
  (`VITE_API_BASE_URL`, plus `penny-api`'s `EXTRA_CORS_ORIGINS` / `FRONTEND_BASE_URL` →
  the app origin); Supabase Auth Site URL set to the new host. **Verified live** in the
  browser: dashboard loaded, `transactions` + `review-queue` XHRs hit
  `api.poweredbypenny.com/api/v1` and returned 200 (CORS + baked `VITE_API_BASE_URL` +
  auth all good); only console noise was a browser-extension message, nothing app-side.
  Runbook in `DEPLOYMENT.md` § 4c.
- [ ] **NPI / data posture** — only HL6 interim retention exists (no SOC 2). Fine for
  design partners with test data; have the explicit conversation before real client PII
  at scale. **Decision write-up (question / options / recommendation) in
  `TIER2_DECISIONS.md` § 1** — recommends onboarding pilots under a written DPA +
  Privacy Policy, test/redacted data only. See also `BLOCKERS.md` HL6.
- [ ] **Multi-seat decision** — `require_admin` is a no-op; one admin login per
  brokerage. Confirm that's acceptable for testers (agents use WhatsApp/SMS, not logins)
  or scope real multi-seat. **Decision write-up in `TIER2_DECISIONS.md` § 2** —
  recommends keeping single-admin for the pilot (the gate is already wired).

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
