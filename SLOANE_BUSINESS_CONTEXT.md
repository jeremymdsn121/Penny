# Sloane — Business Context

A self-contained brief for discussing the business side of Sloane with an AI assistant. Last updated 2026-06-01.

---

## What Sloane is

**Sloane** is a B2B SaaS virtual transaction coordinator (TC) for real estate brokerages. She's a conversational AI assistant — accessible over WhatsApp, SMS, and a web chat interface — that helps agents and brokers manage deals from contract to close.

**What she does:**
- Extracts fields from contracts (PDF AI extraction)
- Tracks transaction stages, deadlines, and the compliance file checklist
- Sends intro emails introducing all parties on a deal
- Drafts and sends correspondence in the brokerage's voice and style
- Provides comparable sales (Rentcast AVM)
- Schedules showings / appointments
- Manages a workflow task list that advances as deals move through stages
- Surfaces a broker review queue (compliance flags, overdue deadlines, stale deals, EMD issues)
- Handles inbound email threading (replies log to the deal's thread)
- Provides broker reporting (pipeline, production, compliance health)
- Routes documents to relevant parties on stage transitions

**What she doesn't do:**
- Distribute state association contract forms (requires NAR/state licensing — a 6–18 month legal process)
- Connect to MLSs for publishing (each MLS requires its own data-access agreement)
- Run compliance review autonomously — always surfaces findings to a human
- Auto-reply to emails, auto-approve, or take money actions

**One instance per brokerage.** Multi-tenant SaaS where the brokerage is the customer; individual agents are the users.

---

## Product status

The build is essentially complete for V1 + V2 features. A working dev instance runs against a live Supabase backend; code is in source control but not yet deployed to production. No external customers yet.

Key capabilities built and verified in the dev environment:
- Full WhatsApp + SMS + web chat agent loop
- Contract extraction, transactions, deadlines, scheduling, doc generation, comps, MLS listing prep
- Compliance checklist + broker review queue
- Workflow tasks, EMD tracking, inbound email threading
- Broker reporting, autonomy settings, document routing
- Per-agent style profiles, AI disclosure / party consent

Capabilities built but pending live end-to-end testing (need keys / migrations applied):
- Per-agent style, SMS fallback, compliance checklist, review queue, workflow tasks, inbound email threading, EMD tracking, AI disclosure/consent, broker reporting

Hard blockers still behind seams (engineering in place; external approval required):
- WhatsApp Business API production approval (currently on Twilio sandbox — see below)
- Google / Microsoft calendar OAuth (4–12 weeks for Google review)
- DocuSign production partner review
- SOC 2 / NPI data handling (6–12 months — needed before enterprise-adjacent brokerages sign)

---

## Pricing model (decided)

- **All features included** — no feature tiers, no crippleware. Every customer gets everything.
- **Per-seat recurring subscription** + a small platform base fee.
  - Per-seat: justified by fairness and COGS (Sloane's costs scale with usage — AI calls, WhatsApp, email — so seats proxy ability-to-pay)
  - Base fee: ensures even a 1–2 person brokerage generates a revenue floor in slow months
  - Recurring over per-transaction: Sloane's value is "always-on standby"; per-transaction creates usage-anxiety and earns too little from seasonal brokerages
- **Not yet decided:** actual numbers (base $ + per-seat $), seat definition (likely a registered agent), billing cadence (monthly vs annual), free-trial length, seat true-up cadence

---

## Go-to-market plan (designed, not yet started)

**Phase 1 — design-partner motion:**
- Beachhead states: TX, FL, CA, NY, SC (states with deep compliance rulesets where Sloane's AI review adds the most value)
- Warm-network entry: Jeremy's connections include a realtor family member, friends in real estate, and 1–2 brokerages he's connected to. Treat the personal network as an advisor/intro engine; the connected brokerages are the actual design-partner targets.
- Goal: 1–2 arm's-length references for external credibility alongside the warm network
- Run as a partnership: free or discounted + founder pricing in exchange for feedback + named case studies
- White-glove onboarding to the activation milestone (first contract extracted + first WhatsApp exchange + first intro email sent)

**Billing approach (planned, not built):**
- Stripe Billing — one Customer per brokerage, one subscription with a base price component + a per-seat price component (quantity = active seats, monthly true-up)
- Hosted Checkout + Customer Portal, webhooks → mirror subscription status locally
- Stripe as source of truth, not a custom billing ledger

---

## Known go-live gates

### 1. WhatsApp Business API production approval (most pressing)
Currently on the **Twilio WhatsApp Sandbox** — every contact must send `join <word>` to opt in. Production requires:

- **Meta Business Verification** — multi-week review of legal entity, address, website, and business documents. This is the slow, blocking step.
- A dedicated phone number (not the sandbox number, not registered on consumer WhatsApp)
- A display name ("Sloane") approved separately by Meta
- Pre-approved **message templates** for any business-initiated messages (deadline reminders, nudges to agents) — only free-form replies within a 24h window after a contact messages first are unrestricted
- Recipient **opt-in** required before Sloane can initiate messages

**Mitigation already shipped:** SMS fallback channel is production-ready and available while WhatsApp approval is pending.

**Framing for Meta review:** position as transactional/conversational coordination between known parties on a real estate deal — not bulk or marketing outreach. Real estate bulk messaging has been delayed or rejected before.

**Architecture decision pending:** does the WhatsApp sender live under a single company WABA (Jeremy/Sloane manages approval once) or does each brokerage register their own number? This choice affects onboarding scalability and who owns verification.

**Entity:** plan is to submit Meta Business Verification under Jeremy's existing registered LLC.

### 2. DNS — reply.heysloane.io
`reply.heysloane.io` needs an MX record pointing to `mx.sendgrid.net`. This is the gating step for inbound email threading (Section 4) and the reply-forwarding feature. DNS itself is quick to configure; propagation is the lag.

### 3. Google / Microsoft calendar OAuth
Google's OAuth verification for calendar scopes from external users takes 4–12 weeks and may require a security assessment. Calendar sync is built behind a seam (`calendar_provider.py`) and doesn't block the rest of the product; start the Google OAuth verification request as soon as there's a website + privacy policy to submit.

### 4. SOC 2 (longer-term)
Enterprise-adjacent brokerages handling SSNs, bank statements, and income docs will ask before signing an annual contract. SOC 2 Type II readiness is a 6–12 month process. Interim: publish a Privacy Policy + DPA; reference Supabase's existing SOC 2 / ISO 27001 as the infrastructure foundation.

---

## Hard limits (business / legal — not engineering problems)

1. **State association forms** — Sloane cannot generate or distribute NAR/state-promulgated contract forms without licensing agreements (6–18 month process). Sloane can *extract data from* forms agents already have.
2. **MLS write APIs** — ~580 independent MLSs each require their own data-access agreement. The publishing seam is built; each market is a separate BD engagement.
3. **AI compliance review** — the human gate is load-bearing and is never made autonomous. LLMs will occasionally misclassify; the product stance is surface-only + human decision, always.

---

## Tech stack (for context)
FastAPI (Python) backend on Supabase; React 18 + TypeScript frontend. Anthropic Claude for AI (contract extraction, agent loop, compliance review, doc generation, style extraction). Twilio for WhatsApp + SMS. SendGrid for email. Rentcast for comparable sales. No custom billing built yet.
