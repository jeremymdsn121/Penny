# WhatsApp Business API — Verification & Setup Walkthrough

Clearing `BLOCKERS.md` Hard Limit 4: moving Penny off the Twilio WhatsApp
**sandbox** (where every contact has to text `join <word>`) onto a **production
WhatsApp sender**. Start this now — Meta business verification and template review
take real calendar time, and real-estate messaging has been delayed/rejected
before, so the earlier the better. The **SMS fallback** (`TWILIO_SMS_FROM`) keeps
Penny working the whole time, so nothing is blocked while this runs.

Penny uses **Twilio as the BSP** (Business Solution Provider), so you do this
through Twilio + Meta, not Meta directly. Most of it is phone/browser-doable.

---

## 0. Timeline & expectations

| Stage | Typical time | Who |
|-------|-------------|-----|
| Meta Business verification | a few days to ~2 weeks (longer if docs bounce) | you + Meta |
| Register the Twilio WhatsApp sender | minutes to a day | you |
| Display-name review | hours to a few days | Meta |
| Message-template approval | minutes to ~1 day each | Meta |

The long pole is **business verification**. Submit it first; everything else
queues behind it.

---

## 1. Have these ready before you start

- [ ] **Twilio account** with billing enabled (you already use it for SMS/sandbox).
- [ ] **A phone number for the WhatsApp sender** that is **not** currently
      registered on any WhatsApp / WhatsApp Business app. A new Twilio number or a
      dedicated business line works. (You cannot reuse a number that's on personal
      WhatsApp.)
- [ ] **Meta Business Manager account** (business.facebook.com). Create one if you
      don't have it.
- [ ] **Business legal details:** legal name, address, website
      (poweredbypenny.com or the brokerage's site), business email/phone.
- [ ] **Business verification documents** (Meta asks for these): business
      registration / incorporation doc, a utility bill or bank statement showing
      the business name + address, and possibly a domain you control.
- [ ] **Display name** for the sender (e.g. "Penny" or "<Brokerage> Coordinator").
      Meta has display-name rules — it should reflect the business, not be
      misleading.

---

## 2. Verify your business in Meta

1. Go to **business.facebook.com → Settings (gear) → Business Settings**.
2. **Security Center → Business Verification → Start verification.**
3. Enter the legal business details, then upload the registration + address
   documents when prompted.
4. Submit. You'll get an email when Meta approves (or asks for more). **This is
   the gate** — do it first.

> Tip: the business name on your documents must match what you enter exactly.
> Mismatches are the #1 reason verification bounces.

---

## 3. Register the WhatsApp sender in Twilio

Once business verification is in flight (you can start this in parallel, but
final approval depends on Meta):

1. **Twilio Console → Messaging → Senders → WhatsApp senders → Create new sender.**
2. Connect / select your **Meta Business Manager (WhatsApp Business Account /
   WABA)**. Twilio will walk you through an embedded Meta signup that links your
   WABA to Twilio as the BSP.
3. Choose the **phone number** for the sender (the unused one from §1) and verify
   it via the OTP Twilio/Meta sends.
4. Set the **display name** and business profile (logo, description, website,
   category — pick a non-marketing category like "Professional Services" / "Real
   Estate").
5. Submit the display name for review.

When approved, Twilio gives you the production sender address in the form
`whatsapp:+1XXXXXXXXXX` — **this replaces the sandbox `whatsapp:+14155238886`.**

---

## 4. Message templates (important for Penny)

WhatsApp splits messages into two kinds:

- **Session messages** — free-form replies sent within **24 hours** of the
  contact's last inbound message. Penny's *replies* to an agent's text fall here;
  no template needed.
- **Business-initiated messages** — anything Penny sends **outside** that 24-hour
  window must use a **pre-approved template**. For Penny this includes the
  **proactive deadline reminders** and **doc-routing nudges** — they go out on a
  schedule, often cold, so they need templates.

To set them up:

1. **Twilio Console → Messaging → Content Template Builder** (or Senders →
   Templates) → create a template.
2. Use a **utility / notification** category (not marketing). Example:
   > "Reminder from Penny: the {{1}} deadline on {{2}} is {{3}}. Reply here and I
   > can notify the parties."
3. Submit for Meta approval. Approved templates get a content SID you reference
   when sending.

> Engineering note: today Penny sends WhatsApp nudges as free-form text
> (`twilio_client.send_whatsapp_message`). On production WhatsApp, the *proactive*
> nudges (reminder scan, doc-routing) will need to send via an **approved template**
> when outside a 24h session. That's a follow-up wiring change in
> `twilio_client` / the reminder + doc-routing senders — flag it when you switch
> `TWILIO_WHATSAPP_FROM` to the production sender. Inbound replies and in-session
> replies are unaffected.

---

## 5. Opt-in (don't skip — this is what gets accounts flagged)

WhatsApp requires **documented opt-in** before you message someone. For Penny:
capture consent when an agent/party registers their number (a checkbox + stored
timestamp), and keep messaging **transactional** (deadline/status notifications
they asked for), never marketing blasts. Real-estate bulk/cold messaging is
exactly what Meta scrutinizes — frame Penny as transactional notifications with
explicit opt-in.

---

## 6. Wire it into Penny (once the sender is approved)

- [ ] Set `TWILIO_WHATSAPP_FROM` = the production sender (`whatsapp:+1XXXXXXXXXX`),
      replacing the sandbox number.
- [ ] Point the sender's inbound webhook (Twilio Console → the WhatsApp sender →
      Messaging config) at `https://<api-host>/api/v1/whatsapp/inbound` (POST) —
      same handler the sandbox uses.
- [ ] Set `TWILIO_SKIP_VALIDATION=false` in production (signed webhooks; never skip
      in prod).
- [ ] Switch the proactive senders (reminder scan, doc-routing) to approved
      templates per §4.
- [ ] Send a real test message to a number that opted in; confirm the round-trip.

---

## 7. Quality rating & limits (after launch)

New WhatsApp senders start with a **messaging limit tier** (e.g. 250 → 1K → 10K
business-initiated conversations/day) that scales up automatically as your
**quality rating** stays green. Keep templates relevant and opt-in clean and the
limit grows on its own. A flood of blocks/reports drops the rating and the limit —
another reason to keep it transactional.

---

### Summary of what to do today, from your phone
1. Start **Meta Business Verification** (§2) — the long pole.
2. While that's pending, create the **WhatsApp sender in Twilio** (§3) and draft
   your **templates** (§4).
3. SMS keeps Penny fully functional until this clears — no rush on the wiring in
   §6 until you have an approved sender.
