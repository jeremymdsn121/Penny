# Penny — Pre-deploy Security Review

Scope: a focused pass over the surfaces that matter most before a real broker's
transactions (real NPI — SSNs, financials) land in the system. This is an
engineering review of the codebase, not a compliance audit (SOC 2 is `BLOCKERS.md`
Hard Limit 6). Reviewed on branch `claude/outstanding-items-review-MjanO`.

**Headline:** no high-severity code vulnerabilities found. The tenant-isolation
model is sound but discipline-dependent (see Finding 1). One low-severity
hardening was fixed in this pass (constant-time webhook key compare). The rest is
deployment configuration that must be set correctly — captured as a checklist at
the end.

---

## How the security model works (so the findings make sense)

- **AuthN:** Supabase issues the JWT; the backend validates it by asking Supabase
  who it belongs to (`core/security.py`). `app_metadata.brokerage_id` from the
  token drives all scoping.
- **AuthZ / tenancy:** the backend talks to Postgres with the **service-role key**,
  which **bypasses RLS**. So isolation rests on two things: every query manually
  filtering by `brokerage_id`, and child resources (deadlines, appointments,
  checklist items, EMD, …) verifying ownership through their parent transaction in
  the route before acting. RLS policies also exist on the tables (defense-in-depth,
  but not what the service-role path relies on).

---

## Findings

### 1. Tenant isolation is correct but depends on scope-in-caller — Medium (process)
Because the service-role key bypasses RLS, a single query that forgets its
`brokerage_id` filter, or a route that mutates a child record by bare id without
first checking the parent belongs to the caller, is a cross-tenant leak. Spot
checks were clean: `get_transaction`, agent/checklist/deadline reads scope by
`brokerage_id`; child-resource routes verify parent ownership; the only bare-id
mutators (`pending_whatsapp_transactions`) operate on an internal 2-hour holding
record keyed off a brokerage-scoped phone lookup, not an attacker-supplied id.
**Recommendations:** (a) keep table RLS enabled as a backstop; (b) treat "every
new list/get takes `brokerage_id`, every child mutation checks parent ownership"
as a review rule for new routes; (c) consider a thin integration test that asserts
cross-brokerage reads return empty once a staging DB exists.

### 2. SendGrid inbound webhook key compared non-constant-time — Low — **fixed**
`routes/email.py` compared the `?key=` shared secret with `!=`, a (minor) timing
side channel. Changed to `hmac.compare_digest`. Note the webhook is **unauthenticated
when `SENDGRID_WEBHOOK_KEY` is unset** — it must be set in production, since inbound
email bodies are PII attributed to a transaction.

### 3. Unattended reminder cron endpoint — reviewed, acceptable
`POST /deadlines/run-reminders-all` (added this branch) is JWT-less and guarded by
`REMINDER_CRON_SECRET` via the `X-Cron-Secret` header: constant-time compare, 503
when unset, and it returns only brokerage ids + processed counts to the secret
holder. The scan is idempotent (sent-flags), so a leaked secret can't be used to
spam-resend reminders — limited blast radius. **Recommendations:** use a long random
secret, make it rotatable, and (if your scheduler has a stable egress IP)
optionally add an IP allowlist at the edge.

### 4. CORS — fine, minor tightening optional — Low
`main.py` uses an explicit origin allowlist (`CORS_ORIGINS` + `EXTRA_CORS_ORIGINS`),
never `*`, which is correct alongside `allow_credentials=True`. Auth is Bearer-token
(not cookies), so credentialed CORS isn't strictly needed. `allow_methods=["*"]` /
`allow_headers=["*"]` is broad but low-risk; tighten to the methods/headers actually
used if you want defense-in-depth.

### 5. Secrets handling — clean
Service-role key is server-only; `.env` is gitignored; `render.yaml` marks every
secret `sync: false` (or `generateValue: true`) so nothing sensitive is committed.
A grep for logging/printing of keys, tokens, secrets, or auth headers found
nothing. Keep the project rule of never echoing `.env` values.

### 6. PostgREST query construction — Low
Filters are built as `eq.{value}` and passed as httpx `params` (URL-encoded values,
parsed as literals by PostgREST). `brokerage_id` comes from the trusted JWT. The one
user-supplied filter (address search, `ilike.*{q}*`) only broadens matching within
the caller's own brokerage — not an injection vector. No raw SQL is constructed.

### 7. Confirmation gates intact
The hard-rule confirm-gated actions (email/document send, compliance decision,
appointment booking, listing push, deadline party notification, EMD mark-received,
DocuSign send) remain gated; compliance review is never autonomous. The new cron
endpoint introduces no bypass.

### 8. Data handling / retention — known gap
No SOC 2 and no document-retention controls yet (`BLOCKERS.md` Hard Limit 6 lists
configurable retention as a follow-up). Acceptable for one design partner under a
written agreement; revisit before broader rollout.

---

## Pre-deploy security checklist

- [ ] `TWILIO_SKIP_VALIDATION=false` in production (signed Twilio webhooks).
- [ ] `SENDGRID_WEBHOOK_KEY` set (inbound parse webhook is open without it).
- [ ] `REMINDER_CRON_SECRET` set to a long random value; matching repo secret on
      the cron; rotate if leaked.
- [ ] `SECRET_KEY` / `CONSENT_SECRET` set to strong values (Render `generateValue`
      handles this).
- [ ] Supabase **RLS stays enabled** on all tables (backstop behind the
      service-role path).
- [ ] CORS (`EXTRA_CORS_ORIGINS`) lists only the real frontend origin.
- [ ] HTTPS only (Render terminates TLS by default).
- [ ] Design partner under an NDA / pilot agreement; Privacy Policy linked;
      AI-disclosure footer enabled.
