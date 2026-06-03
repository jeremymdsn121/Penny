-- Penny V2 — AI disclosure & party consent (Section 6).
-- Several states have or are passing AI-disclosure requirements for real estate
-- communications. Penny appends a disclosure footer to outbound email (on by
-- default) and can optionally collect explicit acknowledgment from parties.
-- Run after 013_emd_tracking.sql.

create table if not exists party_consents (
  id             uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references transactions(id) on delete cascade,
  party_role     text not null,  -- buyer | seller | buyer_agent | listing_agent | lender | title
  email          text not null,
  consented_at   timestamptz,
  ip_address     text,
  user_agent     text,
  consent_method text default 'email_link'
);

create index if not exists idx_party_consents_tx on party_consents(transaction_id);

-- Brokerage-level disclosure settings.
alter table brokerages add column if not exists ai_disclosure_enabled boolean default true;
alter table brokerages add column if not exists ai_disclosure_text text default
  'Communications from this office may be drafted or assisted by artificial intelligence. All communications are reviewed and authorized by a licensed real estate professional before sending.';
alter table brokerages add column if not exists request_ai_consent boolean default false;

alter table party_consents enable row level security;
drop policy if exists party_consents_by_transaction on party_consents;
create policy party_consents_by_transaction on party_consents
  for all using (exists (
    select 1 from transactions tx
    where tx.id = party_consents.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from transactions tx
    where tx.id = party_consents.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ));
