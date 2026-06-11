-- Per-deal activity timeline (post-V2). A broker buying an AI that touches
-- client communication will ask "show me everything that happened on this deal,
-- and what did Penny do on her own." Most actions are already timestamped in
-- their own tables (emails, delivery events, appointments), but stage changes,
-- compliance decisions, EMD receipt, and autonomous sends had no history — only
-- the current value was persisted. This table is the append-only audit trail
-- for those actions; the timeline endpoint merges it with the existing logs.
-- Append-only by convention (no update/delete paths in the app).
-- Run after 025_email_delivery_events.sql.

create table if not exists transaction_events (
  id             uuid primary key default gen_random_uuid(),
  brokerage_id   uuid not null references brokerages(id) on delete cascade,
  transaction_id uuid not null references transactions(id) on delete cascade,
  kind           text not null,           -- e.g. stage_change, compliance_decision, emd_received
  title          text not null,           -- one-line human summary
  detail         text,                    -- optional longer line
  actor          text not null default 'Penny',  -- 'Penny' | 'You' | a person's name
  via            text not null default 'system', -- web | whatsapp | sms | email | system
  metadata       jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now()
);

create index if not exists idx_transaction_events_tx
  on transaction_events(transaction_id, created_at desc);

alter table transaction_events enable row level security;
drop policy if exists transaction_events_by_brokerage on transaction_events;
create policy transaction_events_by_brokerage on transaction_events
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
