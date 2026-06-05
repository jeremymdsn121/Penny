# Parallel approvals — setup checklists

Two deferred integrations gate on external developer-app registration + review
(BLOCKERS.md Hard Limits 3 and Section 8). Kick these off during the WhatsApp /
A2P wait so their review clocks run in parallel.

**Each is two phases:**
1. **Register the dev app now** → get credentials, works against test/demo
   environments immediately. *(This doc.)*
2. **Formal review** (Google OAuth verification / DocuSign go-live) → needs a
   working integration + demo, so it follows after the seam is wired.

The redirect URIs and scopes below are the values the seams will use — register
them now so the app config and code agree when the seam lands. Tokens for calendar
go in the existing `brokerages.google_calendar_token` / `microsoft_token` jsonb
columns; DocuSign will need a new `docusign_tokens` table + `signed_contract_url`
column (built when the seam is wired).

---

## 1. Google Calendar OAuth (Hard Limit 3) — the long pole (4–12 wk verification)

Seam: `app/services/calendar_provider.py` (`status`/`get_busy`/`create_event`).
Env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

**Do now (Google Cloud Console):**
1. Create/select a project (e.g. "Penny").
2. **Enable the Google Calendar API** (APIs & Services → Library).
3. **OAuth consent screen:**
   - User type: **External** (brokerage users sign in with their own Google accounts).
   - App name, support email, app logo, **app homepage**, **privacy policy URL**,
     authorized domain. (Privacy/terms are already served at
     `https://api.poweredbypenny.com/api/v1/privacy` + `/terms` — confirm Google
     accepts that domain, or host them on the public marketing domain.)
   - **Scopes** (these are *sensitive*, not *restricted* — verification required
     but lighter than Gmail/Drive, no CASA security assessment):
     - `https://www.googleapis.com/auth/calendar.events` — create/manage events
     - `https://www.googleapis.com/auth/calendar.freebusy` — free/busy reads
       (fall back to `calendar.readonly` if freebusy alone is insufficient)
   - Add yourself + the dev brokerage as **test users** (lets the flow work before
     verification completes).
4. **Credentials → Create OAuth client ID → Web application:**
   - Authorized redirect URI: `https://api.poweredbypenny.com/api/v1/calendar/google/callback`
   - Save → this gives `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`.

**Follows the seam build:** record the OAuth-flow demo video + submit the consent
screen **for verification** (the 4–12 wk clock). Verification wants the working
flow, so submit after the seam is wired and testable with test users.

### 1b. Microsoft / Outlook calendar (the faster sibling)

The seam already supports `outlook`. Azure AD app registration has **no
Google-style verification**, so it's quick.
Env vars: `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`.

**Do now (Azure Portal → App registrations → New registration):**
1. Supported account types: accounts in any org directory + personal (multi-tenant).
2. Redirect URI (Web): `https://api.poweredbypenny.com/api/v1/calendar/outlook/callback`
3. **API permissions → Microsoft Graph → Delegated:** `Calendars.ReadWrite`,
   `offline_access` (refresh tokens). Grant.
4. **Certificates & secrets → New client secret** → gives
   `MICROSOFT_CLIENT_ID` (Application/client ID) + `MICROSOFT_CLIENT_SECRET`.

---

## 2. DocuSign developer account (V2 Section 8)

Seam: `app/services/docusign_provider.py` (`status`/`send_envelope`).
Env vars: `DOCUSIGN_CLIENT_ID`, `DOCUSIGN_CLIENT_SECRET` (likely also
`DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_BASE_URI` when wired).

**Do now (developers.docusign.com — free demo account):**
1. Create a developer account (demo / sandbox environment).
2. **Settings → Apps and Keys → Add App and Integration Key:**
   - Auth: **Authorization Code Grant**.
   - Redirect URI: `https://api.poweredbypenny.com/api/v1/docusign/callback`
   - **Add a secret key** → gives `DOCUSIGN_CLIENT_ID` (integration key) +
     `DOCUSIGN_CLIENT_SECRET`.
   - Scopes: `signature extended` (extended = refresh tokens).
3. Note the **demo base URI** (`account-d.docusign.com` for OAuth,
   `demo.docusign.net` for the API) — all build/testing happens here, free.

**Follows the seam build:** DocuSign **go-live review** promotes the integration
from demo to production. It requires a set of successful demo API calls + their
review — so it comes after the seam is wired and exercised in demo.

**Scoping guardrail (BLOCKERS Hard Limit 1):** DocuSign only sends documents Penny
already has (extracted contracts, generated correspondence). It is **not** a forms
library — no state-association form distribution.

---

## After registration

Hand me the **client IDs/secrets** (or just confirm the apps exist with the
redirect URIs above) and I'll wire the calendar + DocuSign OAuth seams against the
test-user / demo environments — real, testable engineering that fills the wait and
produces exactly what the formal reviews need. Set the env vars on Render where
each is being exercised; never commit secret values.
