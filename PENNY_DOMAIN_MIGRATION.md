# Penny domain migration — heysloane.io → poweredbypenny.com

**Status: cutover essentially complete.** DNS (SendGrid CNAMEs + reply MX + api
CNAME) is live and verified; SendGrid domain is authenticated with Inbound Parse on
`reply.poweredbypenny.com`; Render has the new env vars and `api.poweredbypenny.com`
serves prod over HTTPS (`/health` returns 200); the live `backend/.env` is on the
new domain. Remaining: a real outbound→reply email round-trip and a WhatsApp message
test after the latest deploy, then optionally decommission heysloane.io.

This doc is kept as the record of what was done. Original plan/ordering below.

## Naming decided

| Thing | Value |
|-------|-------|
| Brand / marketing site | `poweredbypenny.com` |
| Outbound email sender (`SENDGRID_FROM_EMAIL`) | `hello@poweredbypenny.com` |
| Reply subdomain (`REPLY_EMAIL_DOMAIN`) | `reply.poweredbypenny.com` |
| Backend API host (`PUBLIC_BASE_URL`) | `api.poweredbypenny.com` *(recommended — custom domain on the existing Render service)* |
| Frontend host (future, when deployed) | `app.poweredbypenny.com` |

**One decision to make first — backend host:**
- **(Recommended) Add a custom domain** `api.poweredbypenny.com` to the existing
  Render service. No URL churn → Twilio/SendGrid webhooks that already point at
  `sloane-api.onrender.com` keep working during the transition.
- **(Alternative) Rename the Render service** `sloane-api` → `penny-api`. Cleaner
  name, but the `*.onrender.com` URL changes → every webhook (Twilio inbound x2,
  SendGrid Inbound Parse) must be repointed at the new URL the same day.

---

## ✅ Done
- [x] All code symbols, copy, filenames reverted Sloane → Penny
- [x] All in-repo domain references heysloane.io → poweredbypenny.com (config
      defaults, `.env.example`, comments, docs)
- [x] Frontend typecheck + backend import both pass
- [x] DNS in Porkbun: 3 SendGrid CNAMEs, `MX reply → mx.sendgrid.net`,
      `CNAME api → sloane-api.onrender.com`; wildcard parking CNAME removed
- [x] SendGrid: domain authenticated (green) + Inbound Parse on `reply.poweredbypenny.com`
- [x] Render: custom domain `api.poweredbypenny.com` (cert issued) + env vars updated
- [x] Live `backend/.env` flipped to the new domain (gitignored)
- [x] Twilio signature fix for Render's TLS proxy (honour `X-Forwarded-Proto`)

### Still to verify after deploy
- [ ] Outbound email arrives From `hello@poweredbypenny.com` (not spam)
- [ ] Reply round-trips through `/api/v1/email/inbound` and threads
- [ ] WhatsApp inbound → Penny replies (the signature fix must be deployed first)

---

## A. DNS — at the poweredbypenny.com registrar  *(long lead, do first)*
- [ ] **SendGrid domain authentication CNAMEs** — add the ~3 CNAME records SendGrid
      generates (step B1) for `poweredbypenny.com`. Wait for propagation + SendGrid
      "Verified".
- [ ] **Reply MX:** add `MX` for host `reply.poweredbypenny.com` → `mx.sendgrid.net`
      (priority 10).
- [ ] **(Recommended) Backend CNAME:** `api.poweredbypenny.com` → the Render
      service host (`<service>.onrender.com`). Then attach it in Render (step C).
- [ ] *(Later)* `app.poweredbypenny.com` → frontend host, when the frontend deploys.

## B. SendGrid dashboard
- [ ] **Settings → Sender Authentication → Authenticate Your Domain** →
      `poweredbypenny.com` → copy CNAMEs into DNS (A1) → **Verify**.
      (Domain auth covers every `@poweredbypenny.com` sender — no separate single-sender step.)
- [ ] **Settings → Inbound Parse → Add Host & URL:**
      host `reply.poweredbypenny.com`, destination
      `https://<api-host>/api/v1/email/inbound?key=<SENDGRID_WEBHOOK_KEY>`.
      Keep the old `reply.heysloane.io` entry during transition; remove later.

## C. Render
- [ ] Pick the host strategy above. If custom domain: **Settings → Custom Domains →
      Add** `api.poweredbypenny.com`, follow the verification.
- [ ] **Environment tab — update vars and redeploy:**
  - [ ] `SENDGRID_FROM_EMAIL=hello@poweredbypenny.com`
  - [ ] `REPLY_EMAIL_DOMAIN=reply.poweredbypenny.com`
  - [ ] `PUBLIC_BASE_URL=https://api.poweredbypenny.com` *(or new onrender URL if you renamed)*

## D. Local `backend/.env`  *(flip AFTER B verifies — one word and I'll do it)*
- [ ] `SENDGRID_FROM_EMAIL=hello@poweredbypenny.com`
- [ ] `REPLY_EMAIL_DOMAIN=reply.poweredbypenny.com`
- [ ] `PUBLIC_BASE_URL` stays `http://localhost:8000` for local dev (only Render's is public)

## E. Twilio  *(only if the backend URL changed — i.e. you renamed the Render service)*
- [ ] WhatsApp number webhook → `https://<new-host>/api/v1/whatsapp/inbound`
- [ ] SMS number webhook → `https://<new-host>/api/v1/sms/inbound`
- [ ] *(If you added a custom domain and kept the onrender URL live, no change needed.)*

## F. Supabase  *(no action yet)*
- [ ] When the frontend gets a public domain: **Auth → URL Configuration** → add
      `https://app.poweredbypenny.com` to Site URL + redirect allowlist. Currently
      localhost-only, so nothing to do until then.

## G. Verify cutover
- [ ] `GET https://api.poweredbypenny.com/health` → 200
- [ ] Send a test outbound email → arrives, **From `hello@poweredbypenny.com`**, not spam
- [ ] Reply to it → `/api/v1/email/inbound` logs the thread + nudges the deal's agent
- [ ] WhatsApp + SMS inbound still round-trip

## H. Decommission heysloane.io  *(later, optional)*
- [ ] After a clean transition window, remove the old SendGrid Inbound Parse entry
      and let heysloane.io lapse (or 301 it). Keep it live during transition so any
      in-flight reply threads still route.

## Optional cosmetic — local repo folder
- [ ] Rename `C:\Users\Jeremy\sloane` → `...\penny` if you want the path to match.
      Would also need `.claude/launch.json` path + `.venv` recreation (the venv
      shims embed the abs path). Purely cosmetic; not required for the migration.
