-- 019: Deferred / scheduled replies to outside parties (two-way email, Phase 2).
--
-- Builds on 018's pending_email_replies queue. When an outside party replies,
-- Penny now also writes a plain-language SUMMARY of what they said and a
-- RECOMMENDATION for the agent ("the seller's agent wants to discuss closing
-- costs — I can respond if you'd like"), notifies the deal's agent in-channel,
-- and lets the agent approve OR defer the send until a trigger. Nothing is ever
-- auto-sent to an outside party — every deferral re-surfaces for a fresh confirm:
--   trigger_type = 'time'   → at scheduled_send_at, re-surface for a final confirm
--   trigger_type = 'event'  → re-surface for a final confirm when trigger_event
--                             becomes true on the transaction
--   trigger_type = 'manual' → free-form hold (hold_note); Penny only reminds
--   trigger_type = 'none'   → awaiting the agent's decision (status 'pending')
--
-- A scheduled job hits POST /email/run-scheduled-replies to re-surface due time
-- triggers and met event triggers, and nudge on held drafts (same cron pattern as
-- deadline reminders). Run after 018.

alter table pending_email_replies
  add column if not exists summary text;
alter table pending_email_replies
  add column if not exists recommendation text;
alter table pending_email_replies
  add column if not exists trigger_type text not null default 'none';
alter table pending_email_replies
  add column if not exists scheduled_send_at timestamptz;
alter table pending_email_replies
  add column if not exists trigger_event text;
alter table pending_email_replies
  add column if not exists hold_note text;
alter table pending_email_replies
  add column if not exists last_reminder_at timestamptz;

-- Expand the status domain. The 018 inline check is named
-- pending_email_replies_status_check; replace it. 'awaiting_event' = parked on an
-- event trigger; 'scheduled' = time trigger armed; 'held' = free-form manual hold.
alter table pending_email_replies
  drop constraint if exists pending_email_replies_status_check;
alter table pending_email_replies
  add constraint pending_email_replies_status_check
  check (status in ('pending', 'scheduled', 'awaiting_event', 'held', 'sent', 'dismissed'));

alter table pending_email_replies
  drop constraint if exists pending_email_replies_trigger_type_check;
alter table pending_email_replies
  add constraint pending_email_replies_trigger_type_check
  check (trigger_type in ('none', 'time', 'event', 'manual'));

-- The scan looks up armed/held rows by status across brokerages-of-interest.
create index if not exists idx_pending_email_replies_status
  on pending_email_replies(status);
create index if not exists idx_pending_email_replies_scheduled
  on pending_email_replies(scheduled_send_at)
  where status = 'scheduled';
