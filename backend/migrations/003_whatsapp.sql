-- Penny — WhatsApp messaging tables (Task 17).
-- Creates:
--   whatsapp_contacts  — maps realtor phone numbers to a brokerage
--   whatsapp_messages  — conversation history (last N messages fed to Claude)
-- Also adds a notes column to transactions so Penny can annotate deals.
-- Run this in the Supabase SQL Editor after 002_onboarding.sql.

-- --------------------------------------------------------------------------- --
-- transactions: freeform notes field
-- --------------------------------------------------------------------------- --
alter table transactions
  add column if not exists notes text;

-- --------------------------------------------------------------------------- --
-- whatsapp_contacts
-- --------------------------------------------------------------------------- --
create table if not exists whatsapp_contacts (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  phone_number text not null,   -- E.164 format, e.g. "+15551234567"
  display_name text,            -- friendly label, e.g. "Sarah (listing agent)"
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (brokerage_id, phone_number)
);

create index if not exists idx_whatsapp_contacts_brokerage
  on whatsapp_contacts(brokerage_id);

-- fast lookup by phone number (used on every inbound message)
create index if not exists idx_whatsapp_contacts_phone
  on whatsapp_contacts(phone_number);

-- --------------------------------------------------------------------------- --
-- whatsapp_messages
-- --------------------------------------------------------------------------- --
create table if not exists whatsapp_messages (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  phone_number text not null,          -- the realtor's E.164 number
  direction    text not null,          -- 'inbound' | 'outbound'
  body         text,                   -- message text (transcript for audio)
  media_url    text,                   -- original Twilio media URL (nullable)
  content_type text not null default 'text',  -- 'text' | 'audio' | 'image'
  created_at   timestamptz not null default now()
);

create index if not exists idx_whatsapp_messages_brokerage
  on whatsapp_messages(brokerage_id);

create index if not exists idx_whatsapp_messages_thread
  on whatsapp_messages(brokerage_id, phone_number, created_at desc);

-- --------------------------------------------------------------------------- --
-- updated_at trigger for whatsapp_contacts
-- --------------------------------------------------------------------------- --
drop trigger if exists set_updated_at on whatsapp_contacts;
create trigger set_updated_at before update on whatsapp_contacts
  for each row execute function set_updated_at();

-- --------------------------------------------------------------------------- --
-- Row-level security
-- --------------------------------------------------------------------------- --
alter table whatsapp_contacts enable row level security;
alter table whatsapp_messages  enable row level security;

drop policy if exists whatsapp_contacts_by_brokerage on whatsapp_contacts;
create policy whatsapp_contacts_by_brokerage on whatsapp_contacts
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());

drop policy if exists whatsapp_messages_by_brokerage on whatsapp_messages;
create policy whatsapp_messages_by_brokerage on whatsapp_messages
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
