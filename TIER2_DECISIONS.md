# Tier-2 go-live decisions

The two remaining Tier-2 items in `TESTER_READINESS.md` are **business decisions, not
engineering work**. Both are framed below — question, current state, options, and a
recommendation. The engineering groundwork for the recommended path already exists in
each case, so "decide and proceed" is the intent, not "build first."

Last updated: 2026-06-13.

---

## 1. NPI / data posture before real client data

**Question.** What data may a design-partner brokerage put into Penny, and what do we
owe them in writing, before we have SOC 2?

**Current state.**
- Penny ingests contract PDFs that can carry **NPI** — SSNs, bank statements, income
  docs. Files live in **private** Supabase Storage buckets; every query is scoped by
  `brokerage_id` and enforced by Postgres **RLS**; the `service_role` key is server-only.
- **Infra floor:** Supabase carries SOC 2 Type II / ISO 27001 — that's our hosting
  foundation, not our own attestation.
- **Built (HL6 interim):** configurable document retention (migration 022, default 7yr,
  opt-in "enforce" flag, policy math in `services/retention.py`). Automated purge is a
  separately-gated follow-up — **nothing is deleted blind**.
- **Owed (business):** a published **Privacy Policy + DPA**, and the start of a **SOC 2
  readiness** assessment (6–12 months). We are **not** SOC 2 attested today.

**Options.**
- **A. (Recommended) Design partners under a written DPA + Privacy Policy, test /
  low-sensitivity data only.** Onboard pilots now; have each sign a DPA that names
  Supabase as the subprocessor and states the no-SOC-2-yet posture; ask them to avoid
  loading documents with live SSNs / full financials during the pilot (or redact). Begin
  SOC 2 readiness on the business track in parallel.
- **B. Hold all real brokerages until SOC 2 readiness is underway + DPA signed.** Safest,
  but stalls the pilot for months and forfeits the design-partner feedback loop.
- **C. Onboard with no paperwork.** Not acceptable — a broker-owner handling NPI will ask
  about data handling before an annual contract, and "nothing in writing" fails that
  conversation (and exposes us).

**Recommendation: A.** It matches BLOCKERS HL6 and unblocks the pilot without taking on
NPI-at-scale risk. Concrete next steps (business, not code): (1) publish a Privacy Policy
+ DPA — the marketing site already serves privacy/terms HTML; a DPA is a separate
document; (2) add a one-line data-handling note to the onboarding/tester guide setting
the "test or redacted data during pilot" expectation; (3) kick off the SOC 2 readiness
assessment. Defer real NPI-at-scale (and the retention **enforcement** seam) until that
readiness work is moving.

---

## 2. Multi-seat (one admin login per brokerage)

**Question.** Is a single web login per brokerage acceptable for the pilot, or do we need
real multi-seat (multiple logins, agent web access, role separation) before onboarding?

**Current state.**
- Signup creates **one** auth user per brokerage and stamps
  `app_metadata.role = 'broker_in_charge'` + `brokerage_id` (rides in the JWT, drives
  scoping + RLS).
- **Agents have no logins.** They interact entirely over **WhatsApp / SMS**; the web app
  is the broker-in-charge's cockpit.
- `security.require_admin` already gates the admin routers (`broker`, `reports`,
  `autonomy`). It's a **no-op today** (the only login *is* the admin) but it's wired, so
  multi-seat is a flip, not a refactor. Per-agent plumbing already exists too: the
  `agents` table, `agent_channels`, per-agent style, per-agent calendar.

**Options.**
- **A. (Recommended) Keep single-admin for the pilot.** Agents are designed around the
  messaging channels; the broker uses the web app. Zero work now. Revisit only if a
  design partner explicitly needs agents *logging into the web UI*.
- **B. Build real multi-seat now.** Multiple logins per brokerage, an invite flow,
  agent-level web login, frontend role-based route gating, and agent-scoped web views.
  Meaningful work (auth invites + RBAC on the frontend + scoped queries) for a need no
  tester has voiced yet.

**Recommendation: A.** The product model is "broker logs in, agents are on
WhatsApp/SMS," and the code already reflects that with the admin gate in place. Hold
multi-seat until a partner asks for agent web logins; the existing `agents` /
`agent_channels` / role-stamp groundwork makes it an incremental add when that day comes.

**Confirm for the pilot:** every test brokerage is fine with a single broker-in-charge
login, and agents acting only through WhatsApp/SMS. If yes, this item is closed.
