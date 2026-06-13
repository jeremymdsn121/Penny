# Penny — Tester Onboarding Checklist

A practical guide for bringing the first testers onto Penny. Two parts: what the
**admin** (you) does to prep + onboard each tester, and a **quick-start** you can
hand each tester. Plus what works today vs. what's still pending, so expectations
are set up front.

Last reviewed: 2026-06-13.

---

## Channels at a glance

| Channel | Status | Tester uses |
|---|---|---|
| **Web app** | Live | `https://app.poweredbypenny.com` |
| **WhatsApp** | Live (production number) | Text/voice Penny at **+1 405-363-6555** |
| **Email (outbound + inbound threading)** | Configured; needs one live test | Penny emails from the brokerage sender; replies thread back to the deal |
| **SMS** | **Blocked** — waiting on A2P 10DLC approval | (not yet) |

> Start testers on **WhatsApp + web app + email**. Hold SMS until A2P clears.

---

## A. Admin prep (one-time, before inviting anyone)

- [ ] Confirm you can log in to the web app at `https://app.poweredbypenny.com`.
- [ ] Onboarding completed for the brokerage (5-step wizard: brokerage details,
      brand/style, autonomy toggles, etc.).
- [ ] At least one **real transaction** loaded (upload a contract PDF → Penny
      extracts the fields) so testers have something to act on.
- [ ] Brand & Style: upload a letterhead / sample letter so generated documents
      and emails come out in your voice (optional but makes the demo land).
- [ ] Decide **autonomy** posture for testing (Settings → Autonomy). Recommended
      for a first cohort: leave the confirm-gates **on** (intro-email,
      doc-routing, deadline party-notify, etc.) so nothing goes out unattended.
      Compliance is always human-confirmed and can't be made autonomous.
- [ ] Run the two **smoke tests** in Section D before kickoff.

---

## B. Per-tester onboarding (do this for each tester)

- [ ] Get the tester's **mobile number** (the one they'll text Penny from) and,
      if they'll use the web app, an **email** for their login.
- [ ] **Register their WhatsApp number** so Penny recognizes them (Messaging
      settings → add contact). An unknown sender is asked to register first, so
      pre-registering avoids that friction.
- [ ] (Optional) **Link the number to an agent record** and **assign deals to
      that agent** — this is what makes targeted nudges (email-reply alerts,
      doc-routing) reach the right person instead of the whole brokerage.
- [ ] Tell them the WhatsApp number to save: **+1 405-363-6555** (save as
      "Penny").
- [ ] Hand them the Section C quick-start.

---

## C. Quick-start to hand each tester

**Meet Penny — your transaction coordinator.**

1. **Save this contact:** Penny — **+1 405-363-6555** (WhatsApp).
2. **Say hi on WhatsApp.** Text "Hey Penny, what's on my plate?" She'll brief you
   on active deals, what needs review, and what's closing soon.
3. **Things to try over WhatsApp:**
   - "What's missing on 123 Main St?" (checklist gaps)
   - "What's overdue?" / "What should I do first?" (she proposes the next action)
   - "Draft a status update for the buyer on 123 Main"
   - "Propose showing times for Friday afternoon"
   - Send a **photo or PDF of a contract** — she'll extract it and ask you to
     confirm.
   - Send a **voice memo** — she transcribes and acts on it.
4. **Or use the web app:** `https://app.poweredbypenny.com` — same Penny in a
   chat bar on the home page, plus the full dashboard (deals, deadlines,
   compliance, comps, reports).
5. **What Penny won't do:** give legal/tax/financial advice (she'll point you to
   your attorney/CPA/broker), and she never sends anything to an outside party
   without your explicit OK.

---

## D. Smoke tests to run before kickoff

### 1. Proactive WhatsApp nudge (approved template, outside the 24h window)
Proactive nudges (deadline reminders, etc.) must go out as approved templates
when it's been >24h since the tester last messaged Penny. `TWILIO_CONTENT_SIDS`
is set in production, so this should work — verify it once:

- [ ] Use a WhatsApp number that **hasn't** messaged Penny in the last 24h
      (a second phone, or wait out the window).
- [ ] Ensure that number is a registered contact and there's a deal with a
      **deadline at the 5-day / 2-day / day-of mark**.
- [ ] Trigger **Dashboard → "Run reminders."**
- [ ] **Pass:** the reminder arrives looking like the "⏰ Penny reminder: …"
      template. **Fail:** nothing arrives → re-check the `TWILIO_CONTENT_SIDS`
      JSON on Render for stray/smart quotes, redeploy, retry.

### 2. Inbound email reply threading
- [ ] Find an email Penny sent on a deal (its `Reply-To` is
      `tx-{transaction_id}@reply.poweredbypenny.com`).
- [ ] **Reply** to it from any inbox.
- [ ] Open that deal's **Communications tab.**
- [ ] **Pass:** your reply appears in the thread and the deal's agent gets a
      nudge. **Fail:** confirm the SendGrid Inbound Parse `?key=` matches
      `SENDGRID_WEBHOOK_KEY` on Render.

---

## E. What works today vs. pending

**Works today (exercise freely):**
- Ask Penny — web chat + WhatsApp (text, voice memo, photo/PDF intake).
- Contract extraction → transactions; deadlines + reminders; workflow tasks.
- Compliance review (surface-only, human-confirmed — *not legal advice*).
- Comparable sales + property record (Rentcast); EMD **receipt** tracking.
- Document generation + intro email (confirm-then-send); broker review queue;
  reports; checklist tracking; scheduling (working-hours slots + local booking).
- Proactive next-action suggestions / briefing.

**Pending / deferred (tell testers, so it's not a surprise):**
- **SMS** — blocked on A2P 10DLC approval.
- **Live calendar sync** (Google/Microsoft) — built behind a seam; connect flow
  needs OAuth credentials before free/busy + event creation work for real.
- **MLS publishing** and **DocuSign** — deferred seams; they report "not
  connected" by design.
- **Inbound email auto-reply to outside parties** — Penny only *drafts* a
  suggested reply for an outside party; a human confirm-sends. She replies
  directly only to your own agents (if that toggle is on).

---

## F. Capture feedback
- [ ] Decide where testers send feedback (shared doc / channel / email).
- [ ] Ask them to flag: anything Penny got **wrong** (especially extracted
      fields or compliance findings), anything that **felt slow**, and the
      single thing they'd want her to do next.
