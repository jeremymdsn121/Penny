-- Sloane — initial schema (PRD Section 4) + row-level security.
-- Run this once in the Supabase SQL Editor.
--
-- Isolation model: every row is scoped to a brokerage. The authenticated user
-- carries its brokerage id in the JWT under app_metadata.brokerage_id (set by
-- the backend at signup). RLS policies compare against auth_brokerage_id().
-- The backend uses the service-role key, which bypasses RLS; these policies
-- protect any direct client access with a user JWT.

create extension if not exists pgcrypto;

-- --------------------------------------------------------------------------- --
-- updated_at trigger
-- --------------------------------------------------------------------------- --
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- brokerage id from the current JWT's app_metadata claim
create or replace function auth_brokerage_id()
returns uuid language sql stable as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'brokerage_id', '')::uuid;
$$;

-- --------------------------------------------------------------------------- --
-- Tables
-- --------------------------------------------------------------------------- --
create table if not exists brokerages (
  id                    uuid primary key default gen_random_uuid(),
  name                  text not null,
  assistant_name        text default 'Sloane',
  state                 text,
  email                 text,
  phone                 text,
  sendgrid_api_key      text,
  rentcast_api_key      text,
  google_calendar_token jsonb,
  microsoft_token       jsonb,
  email_mode            text,
  monitor_email         text,
  brand_colors          jsonb,
  subscription_tier     text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table if not exists agents (
  id             uuid primary key default gen_random_uuid(),
  brokerage_id   uuid not null references brokerages(id) on delete cascade,
  name           text,
  email          text,
  phone          text,
  license_number text,
  role           text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists transactions (
  id                  uuid primary key default gen_random_uuid(),
  brokerage_id        uuid not null references brokerages(id) on delete cascade,
  agent_id            uuid references agents(id) on delete set null,
  address             text,
  city                text,
  state               text,
  zip                 text,
  buyer_name          text,
  buyer_email         text,
  buyer_phone         text,
  seller_name         text,
  seller_email        text,
  seller_phone        text,
  list_price          numeric,
  sale_price          numeric,
  financing           text,
  contract_date       date,
  closing_date        date,
  stage               text,
  listing_agent_name  text,
  listing_agent_email text,
  selling_agent_name  text,
  selling_agent_email text,
  lender_name         text,
  lender_email        text,
  title_company       text,
  title_email         text,
  tc_name             text,
  tc_email            text,
  mls_number          text,
  compliance_status   text,
  docs_sent_to_title  boolean default false,
  docs_sent_to_lender boolean default false,
  intro_email_sent    boolean default false,
  contract_pdf_url    text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table if not exists deadlines (
  id                  uuid primary key default gen_random_uuid(),
  transaction_id      uuid not null references transactions(id) on delete cascade,
  label               text,
  due_date            date,
  responsible_parties text[],
  status              text,
  reminder_5day_sent  boolean default false,
  reminder_2day_sent  boolean default false,
  reminder_day_sent   boolean default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table if not exists appointments (
  id               uuid primary key default gen_random_uuid(),
  transaction_id   uuid not null references transactions(id) on delete cascade,
  type             text,
  showing_method   text,
  scheduled_at     timestamptz,
  confirmed        boolean default false,
  calendar_event_id text,
  attendees        text[],
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table if not exists doc_rules (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  trigger      text,
  docs         text,
  recipient    text,
  active       boolean default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table if not exists knowledge_rules (
  id              uuid primary key default gen_random_uuid(),
  brokerage_id    uuid not null references brokerages(id) on delete cascade,
  category        text,
  rule            text,
  source_document text,
  confirmed       boolean default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists task_autonomy (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  task_id      text,
  autonomous   boolean default false,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- helpful indexes for brokerage-scoped lookups
create index if not exists idx_agents_brokerage         on agents(brokerage_id);
create index if not exists idx_transactions_brokerage   on transactions(brokerage_id);
create index if not exists idx_deadlines_transaction     on deadlines(transaction_id);
create index if not exists idx_appointments_transaction  on appointments(transaction_id);
create index if not exists idx_doc_rules_brokerage       on doc_rules(brokerage_id);
create index if not exists idx_knowledge_rules_brokerage on knowledge_rules(brokerage_id);
create index if not exists idx_task_autonomy_brokerage   on task_autonomy(brokerage_id);

-- --------------------------------------------------------------------------- --
-- updated_at triggers
-- --------------------------------------------------------------------------- --
do $$
declare t text;
begin
  foreach t in array array[
    'brokerages','agents','transactions','deadlines',
    'appointments','doc_rules','knowledge_rules','task_autonomy'
  ] loop
    execute format(
      'drop trigger if exists set_updated_at on %1$I;
       create trigger set_updated_at before update on %1$I
         for each row execute function set_updated_at();', t);
  end loop;
end $$;

-- --------------------------------------------------------------------------- --
-- Row-level security
-- --------------------------------------------------------------------------- --
alter table brokerages     enable row level security;
alter table agents         enable row level security;
alter table transactions   enable row level security;
alter table deadlines      enable row level security;
alter table appointments   enable row level security;
alter table doc_rules      enable row level security;
alter table knowledge_rules enable row level security;
alter table task_autonomy  enable row level security;

-- brokerages: a user sees/edits only its own brokerage row
drop policy if exists brokerages_self on brokerages;
create policy brokerages_self on brokerages
  for all using (id = auth_brokerage_id())
  with check (id = auth_brokerage_id());

-- tables with a direct brokerage_id column
do $$
declare t text;
begin
  foreach t in array array[
    'agents','transactions','doc_rules','knowledge_rules','task_autonomy'
  ] loop
    execute format('drop policy if exists %1$s_by_brokerage on %1$I;', t);
    execute format(
      'create policy %1$s_by_brokerage on %1$I
         for all using (brokerage_id = auth_brokerage_id())
         with check (brokerage_id = auth_brokerage_id());', t);
  end loop;
end $$;

-- deadlines / appointments: scoped through their parent transaction
drop policy if exists deadlines_by_transaction on deadlines;
create policy deadlines_by_transaction on deadlines
  for all using (
    exists (select 1 from transactions tx
            where tx.id = deadlines.transaction_id
              and tx.brokerage_id = auth_brokerage_id())
  )
  with check (
    exists (select 1 from transactions tx
            where tx.id = deadlines.transaction_id
              and tx.brokerage_id = auth_brokerage_id())
  );

drop policy if exists appointments_by_transaction on appointments;
create policy appointments_by_transaction on appointments
  for all using (
    exists (select 1 from transactions tx
            where tx.id = appointments.transaction_id
              and tx.brokerage_id = auth_brokerage_id())
  )
  with check (
    exists (select 1 from transactions tx
            where tx.id = appointments.transaction_id
              and tx.brokerage_id = auth_brokerage_id())
  );
