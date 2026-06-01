# Sloane V2 — Blockers

Items here are **not engineering problems**. Each requires a business or legal
action, or external credentials/approval, before the corresponding code path can
do real work. The engineering seams are in place; only the seam bodies change
once a blocker is cleared. Do not attempt to engineer around these.

---

## HARD LIMIT 1 — State association forms / forms libraries

Dotloop and zipForm hold licensing agreements with NAR and state associations
(CAR, TAR, etc.) to distribute and pre-fill state-promulgated contract forms.
Sloane cannot generate, pre-fill, or reproduce these forms without equivalent
licensing.

- **Sloane can:** extract data from forms the agent already has, track them in the
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
rejected before.

- **Mitigation shipped:** the SMS fallback channel (Section 1C) is a
  production-ready channel (`TWILIO_SMS_FROM`) while approval is pending.
- **Action:** begin the Twilio/META WhatsApp Business API application now.

## HARD LIMIT 5 — AI reliability in compliance review

The AI compliance *review* will occasionally misclassify an item. This is a
fundamental LLM property; it cannot be prompted away at this scale.

- **Product stance:** the human gate on compliance review is load-bearing and is
  **never** made autonomous (no setting or code path enables it). The separate
  **compliance file checklist** (Section 2A) is deterministic — it tracks whether
  documents are in the file, not an AI judgment.
- **Follow-ups (engineering, when prioritized):** add a self-reported
  `confidence` (high/medium/low) to AI findings and surface low-confidence ones
  with a distinct treatment; add an admin correct/incorrect feedback log (do not
  auto-tune the model in production). UI already states it's a checklist aid, not
  a legal determination.

## HARD LIMIT 6 — SOC 2 / NPI data handling

Broker-owners handling SSNs, bank statements, and income docs will ask about data
handling before signing an annual contract. Without SOC 2 Type II (or
equivalent), enterprise-adjacent brokerages won't sign.

- **Action:** begin a SOC 2 readiness assessment (6–12 months). Interim: publish a
  Privacy Policy + DPA; reference Supabase's existing SOC 2 / ISO 27001 as the
  infrastructure foundation; add configurable document retention to the brokerage
  admin panel (default 7 years) — *not yet built; tracked as a follow-up.*

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
