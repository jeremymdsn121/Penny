# Penny V2 — Blockers

Items here are **not engineering problems**. Each requires a business or legal
action, or external credentials/approval, before the corresponding code path can
do real work. The engineering seams are in place; only the seam bodies change
once a blocker is cleared. Do not attempt to engineer around these.

---

## HARD LIMIT 1 — State association forms / forms libraries

Dotloop and zipForm hold licensing agreements with NAR and state associations
(CAR, TAR, etc.) to distribute and pre-fill state-promulgated contract forms.
Penny cannot generate, pre-fill, or reproduce these forms without equivalent
licensing.

- **Penny can:** extract data from forms the agent already has, track them in the
  compliance file, send them for signature (once DocuSign is connected).
- **Requires a business deal:** distributing the actual forms.
- **Action:** if form distribution becomes a roadmap goal, engage NAR + the
  relevant state associations. A 6–18 month legal/business process.

## HARD LIMIT 2 — MLS write APIs

~580 independent MLSs in the US; each needs its own data-access agreement, API
credentials, and sometimes RESO Web API certification. The engineering seam
exists (`backend/app/services/mls_provider.py`); connecting any specific MLS is a
per-market BD process.

- **Action:** identify the 3–5 beachhead markets where initial broker-owner
  customers concentrate; pursue MLS data-access agreements for those only. Do not
  build a universal connector.

## HARD LIMIT 3 — Google / Microsoft calendar OAuth

Google's OAuth verification for calendar read/write scopes from external users
takes 4–12 weeks and may require a security assessment. Microsoft's Azure AD app
registration for delegated Graph permissions is faster but still reviewed. The
engineering seam exists (`backend/app/services/calendar_provider.py`).

- **Action:** submit the Google OAuth verification request now; it runs in
  parallel with all other engineering. Wire `calendar_provider` once testable.

## HARD LIMIT 4 — WhatsApp Business API production approval

The current implementation uses the Twilio WhatsApp Sandbox (each contact must
`join <word>` to opt in). Production needs a WhatsApp Business Account + approved
Business Profile via Twilio/META; real-estate bulk messaging has been delayed or
rejected before. **This is a wholly separate approval track from A2P 10DLC**
(Meta vs. US carriers / TCR) — neither clears the other.

- **Mitigation shipped:** the SMS fallback channel (Section 1C) is a
  production-ready channel (`TWILIO_SMS_FROM`) while approval is pending.

**Single-number decision (2026-06-04).** Penny will run WhatsApp and SMS on the
**same** number — `+14053636555` (a Twilio long code, confirmed **not** tied to
any consumer WhatsApp account, which is the one hard prerequisite). Twilio allows
one number to carry both an A2P 10DLC SMS registration and a production WhatsApp
sender; inbound traffic is routed by the `whatsapp:` address prefix, and the
WhatsApp sender's webhook and the number's SMS messaging webhook are configured
independently. Penny's two-endpoint design already supports this with **no code
change** — point the WhatsApp sender at `/api/v1/whatsapp/inbound` and the SMS
handler at `/api/v1/sms/inbound`; `TWILIO_WHATSAPP_FROM` and `TWILIO_SMS_FROM`
hold the same E.164 value (one carries the `whatsapp:` prefix). Rationale:
realtors save **one** "Penny" contact that works for WhatsApp and the SMS
fallback — the realtor experience is the product. (Refs: Twilio WhatsApp API
overview; inbound webhook request format; "Which Twilio numbers are compatible
with WhatsApp".)

**Onboarding action plan (Twilio-brokered Embedded Signup):**

1. **Start the long-lead items first** (these gate everything else):
   - Meta Business Manager account (business.facebook.com).
   - **Meta Business Verification** — legal name/address/website/domain must
     match; days-to-weeks. This is the usual bottleneck — kick it off immediately.
2. **Confirm the number is WhatsApp-clean** — `+14053636555` must not be
   registered on the consumer WhatsApp / WhatsApp Business app (confirmed clean
   as of 2026-06-04; re-verify at submission time).
3. **Create the WhatsApp sender** — Twilio Console → Messaging → Senders →
   WhatsApp senders → "Create new sender" → Meta Embedded Signup popup → attach
   `+14053636555` to the WABA → verify via OTP.
4. **Display name + business profile** — pick the display name (relate it to the
   brokerage brand; generic names get rejected), set category/description/logo.
5. **Point the sender's inbound webhook** at
   `https://api.poweredbypenny.com/api/v1/whatsapp/inbound` (POST).
6. **Message templates** — any send **outside** the 24h customer-service window
   must be a pre-approved template. Submit templates for Penny's proactive sends
   (deadline reminders, EMD nudges, review-queue pings) before go-live. Inbound
   and in-window replies need no templates.
7. **Cut over** — replace the sandbox `whatsapp:+14155238886` in
   `TWILIO_WHATSAPP_FROM` with `whatsapp:+14053636555`; drop the `join <word>` step.

## HARD LIMIT 5 — AI reliability in compliance review

The AI compliance *review* will occasionally misclassify an item. This is a
fundamental LLM property; it cannot be prompted away at this scale.

- **Product stance:** the human gate on compliance review is load-bearing and is
  **never** made autonomous (no setting or code path enables it). The separate
  **compliance file checklist** (Section 2A) is deterministic — it tracks whether
  documents are in the file, not an AI judgment.
- **Follow-ups — now built:** AI compliance findings carry a self-reported
  `confidence` (high/medium/low); low-confidence findings are surfaced distinctly
  in the UI ("low confidence — verify"). A broker correct/incorrect feedback log
  records to `compliance_feedback` (migration 021) for manual review — the model
  is **never** auto-tuned in production. UI states it's a checklist aid, not a
  legal determination.

## HARD LIMIT 6 — SOC 2 / NPI data handling

Broker-owners handling SSNs, bank statements, and income docs will ask about data
handling before signing an annual contract. Without SOC 2 Type II (or
equivalent), enterprise-adjacent brokerages won't sign.

- **Action:** begin a SOC 2 readiness assessment (6–12 months). Interim: publish a
  Privacy Policy + DPA; reference Supabase's existing SOC 2 / ISO 27001 as the
  infrastructure foundation.
- **Built:** configurable document retention in the brokerage admin panel (default
  7 years) — migration 022 + the "Document retention" card on Compliance Settings
  (policy value + an opt-in "enforce" flag). Automated purge of expired documents
  is a **separately-gated** follow-up; nothing is deleted blind. The policy math
  lives in `services/retention.py` (unit-tested), ready for the enforcement seam.
- **Still to do (business):** SOC 2 readiness, Privacy Policy + DPA.

---

## Section 8 — DocuSign integration (credential prerequisite)

Sending documents for e-signature is built behind a seam
(`backend/app/services/docusign_provider.py`; confirm-gated endpoints
`POST /transactions/{id}/docusign/send` and `/docusign/status`; a "Signatures"
card on the transaction page that shows "not connected"). The OAuth connect,
token storage, envelope creation, and Connect status webhook are **deliberately
not built blind** — they need:

- a DocuSign developer account + integration key (OAuth 2.0 Authorization Code),
- (for production) DocuSign partner review.

- **Action:** start the DocuSign developer account registration now (runs in
  parallel). When credentials exist and the flow is testable, implement the seam
  bodies + a `docusign_tokens` table and a `signed_contract_url` column; callers
  stay the same.
