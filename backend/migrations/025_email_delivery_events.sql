-- Email delivery feedback (post-V2). Penny emails outside parties, but
-- send_email only knows "SendGrid accepted it" — not "it arrived". When a
-- buyer's address was extracted with a typo, every notice silently vanishes
-- and the broker believes the parties were informed. The SendGrid Event
-- Webhook posts bounce / dropped / spamreport events to
-- POST /api/v1/email/events; this table records them per transaction so the
-- Communications tab can show delivery problems (the deal's agent is also
-- WhatsApp-nudged at receipt time).
-- Run after 024_agent_calendar.sql.

create table if not exists email_delivery_events (
  id             uuid primary key default gen_random_uuid(),
  brokerage_id   uuid not null references brokerages(id) on delete cascade,
  transaction_id uuid references transactions(id) on delete cascade,
  email          text not null,
  event          text not null check (event in ('bounce', 'dropped', 'spamreport')),
  reason         text,
  sg_event_id    text,
  created_at     timestamptz not null default now()
);

-- SendGrid retries webhook batches and can deliver an event more than once;
-- the unique sg_event_id makes recording idempotent (inserts 409 and are skipped).
create unique index if not exists idx_email_delivery_events_sg_event
  on email_delivery_events(sg_event_id) where sg_event_id is not null;
create index if not exists idx_email_delivery_events_tx
  on email_delivery_events(transaction_id);

alter table email_delivery_events enable row level security;
drop policy if exists email_delivery_events_by_brokerage on email_delivery_events;
create policy email_delivery_events_by_brokerage on email_delivery_events
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
