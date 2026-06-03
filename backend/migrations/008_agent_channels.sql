-- Penny V2 — Unified messaging channels (Section 1C: SMS fallback).
-- WhatsApp penetration among older US agents is low, so Penny also speaks plain
-- SMS. agent_channels is the single source of truth for "which phone numbers may
-- message Penny, and on which channel". A number can be registered on WhatsApp,
-- SMS, or both (one row per channel).
-- Existing whatsapp_contacts rows are copied in as channel='whatsapp'; the old
-- table is left in place (read-only) so nothing is lost.
-- Run after 007_agent_style.sql.

create table if not exists agent_channels (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  agent_id     uuid references agents(id) on delete set null,
  channel      text not null check (channel in ('whatsapp', 'sms')),
  phone_number text not null,           -- E.164, e.g. "+15551234567"
  display_name text,
  created_at   timestamptz not null default now(),
  unique (brokerage_id, phone_number, channel)
);

create index if not exists idx_agent_channels_brokerage on agent_channels(brokerage_id);
-- fast lookup by phone+channel on every inbound message
create index if not exists idx_agent_channels_lookup on agent_channels(phone_number, channel);

-- Migrate existing WhatsApp contacts (idempotent).
insert into agent_channels (brokerage_id, agent_id, channel, phone_number, display_name, created_at)
  select brokerage_id, agent_id, 'whatsapp', phone_number, display_name, created_at
  from whatsapp_contacts
  on conflict (brokerage_id, phone_number, channel) do nothing;

-- Row-level security: a user sees/edits only its brokerage's channels.
alter table agent_channels enable row level security;
drop policy if exists agent_channels_by_brokerage on agent_channels;
create policy agent_channels_by_brokerage on agent_channels
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
