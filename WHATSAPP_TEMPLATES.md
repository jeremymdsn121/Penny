# WhatsApp Message Templates (Penny)

Proactive, business-initiated WhatsApp messages must be **pre-approved templates**
when sent **outside the 24-hour customer-service window**. Penny's normal agent
back-and-forth (a realtor texts Penny, she replies) is *inside* the window and
needs no template. Only the cron/event-driven nudges below do.

All of these are **Utility** category (they're tied to a specific transaction
event or account action, not promotional), language **English (US) / `en_US`**.
Utility templates approve quickly and are the cheapest tier.

## How to submit

Use Twilio's **Content Template Builder** (Twilio Console → Messaging → Content
Template Builder), not Meta's Template Manager directly — Twilio submits to Meta
for approval *and* hands back a `ContentSid` (`HX...`) that the backend needs to
actually send the template. Pick category **Utility**, language **en_US**, paste
the body, fill the sample values, submit. Approval is usually minutes to a day.

> **Code wiring (built, config-gated).** All five proactive send sites
> (`deadline_reminders.py`, `doc_routing.py`, `routes/email.py`,
> `email_autoreply.py`, `email_scheduler.py`) route through
> `twilio_client.send_whatsapp_template(to, template_key, variables,
> fallback_body)`. With no config it sends the freeform fallback — today's
> sandbox behavior, unchanged. Once a template is approved, set the
> **`TWILIO_CONTENT_SIDS`** env var to a JSON object mapping the template keys
> below to their `HX...` ContentSids, e.g.
> `{"deadline_reminder": "HX…", "document_ready_to_send": "HX…"}` — that send
> site immediately switches to the Content API (ContentSid + positional
> ContentVariables). Keys can be added one at a time as approvals land; unmapped
> keys keep falling back. Verify each template against the WABA test number
> before adding its SID in production.

Meta body rules these are written to satisfy: don't start or end the body with a
variable, don't place two variables adjacent, keep it clearly transactional.

---

## 1. `deadline_reminder`

Source: `deadline_reminders.py` (`build_agent_nudge`). Fires from the reminder
scan at the 5-day / 2-day / day-of marks.

**Category:** Utility · **Language:** en_US

**Body:**
```
⏰ Penny reminder: {{1}} for {{2}} is {{3}}. Reply here and I'll help you line up the next step.
```

| Var | Meaning | Sample |
|-----|---------|--------|
| {{1}} | deadline label | Inspection contingency |
| {{2}} | property address | 11313 Bluff Creek Dr |
| {{3}} | due description | due tomorrow (Jun 6) |

*Code note:* `{{3}}` maps to the existing `_timing()` phrase, lightly reworded to
drop the leading "is" (so "is due tomorrow" becomes "due tomorrow"). The optional
"notify responsible parties" line stays a separate in-window/dashboard action.

---

## 2. `document_ready_to_send`

Source: `doc_routing.py`. Fires when a deal enters a stage with a routing rule and
a contract is ready to send.

**Category:** Utility · **Language:** en_US

**Body:**
```
📄 Update on {{1}}: the deal entered {{2}}, and I have the contract ready to send to {{3}}. Approve the send in your Penny dashboard under Document routing.
```

| Var | Meaning | Sample |
|-----|---------|--------|
| {{1}} | property address | 11313 Bluff Creek Dr |
| {{2}} | stage entered | Pending |
| {{3}} | recipient roles | the buyer and listing agent |

---

## 3. `email_reply_received`

Source: `routes/email.py` (generic targeted nudge). Fires when an inbound email
reply lands on a transaction.

**Category:** Utility · **Language:** en_US

**Body:**
```
📨 New reply on {{1}} from {{2}}: "{{3}}". Open your Penny dashboard to read the full message and respond.
```

| Var | Meaning | Sample |
|-----|---------|--------|
| {{1}} | property address | 11313 Bluff Creek Dr |
| {{2}} | sender name | Gary Cochran |
| {{3}} | message preview | Can we move the walkthrough to Friday? |

---

## 4. `draft_reply_ready`

Source: `email_autoreply.py`. Fires when an outside party replies and Penny has
drafted a suggested reply for the agent to review.

**Category:** Utility · **Language:** en_US

**Body:**
```
📨 Heads-up from Penny: {{1}} replied on {{2}}. {{3}} I've drafted a suggested reply for you. Review and send it from your dashboard.
```

| Var | Meaning | Sample |
|-----|---------|--------|
| {{1}} | sender name | Gary Cochran |
| {{2}} | property address | 11313 Bluff Creek Dr |
| {{3}} | recommendation / summary | They're asking to push closing two days. |

---

## 5. `agent_action_needed` (catch-all, optional)

Source: `email_scheduler.py` `_notify_agent` WhatsApp fallback (and any future
proactive nudge). The body there is dynamic, so a flexible utility template covers
it. Optional — submit only if you want the scheduled-reply WhatsApp fallback to
work outside the window.

**Category:** Utility · **Language:** en_US

**Body:**
```
📋 Penny update on {{1}}: {{2}} Reply here or open your dashboard to take the next step.
```

| Var | Meaning | Sample |
|-----|---------|--------|
| {{1}} | property address | 11313 Bluff Creek Dr |
| {{2}} | what's needed | A deferred reply to the buyer's agent is due to send. |

---

## Not templated (intentionally)

- **The agent ↔ Penny conversation** — inside the 24h window, freeform, no template.
- **SMS opt-in / STOP / HELP** (`routes/sms.py`) — that's the A2P 10DLC channel,
  not WhatsApp; it uses standard SMS, not WhatsApp templates.
- **EMD nudges** — EMD-overdue is surfaced in the review queue (dashboard), not a
  proactive WhatsApp push, so there's nothing to template today. Add one here if a
  push is introduced later.

## Testing before the real number is live

The WABA's free **Test Number** (`+1 555-667-0303`) can send approved templates to
up to 5 added recipients — useful to sanity-check rendering before `+14053636555`
is verified.
