-- Penny — MLS listing prep (PRD task `mls-entry`).
-- A `listings` table for the listing side: a property an agent is taking to
-- market. Distinct from `transactions` (purchase side). Penny extracts MLS-ready
-- fields from a listing packet into a draft listing the agent reviews; pushing
-- to an MLS is a deferred, per-market integration (see app/services/mls_provider.py).
-- Run this in the Supabase SQL Editor after 004_knowledge.sql.

create table if not exists listings (
  id                  uuid primary key default gen_random_uuid(),
  brokerage_id        uuid not null references brokerages(id) on delete cascade,
  agent_id            uuid references agents(id) on delete set null,
  transaction_id      uuid references transactions(id) on delete set null, -- linked once under contract
  status              text default 'draft',  -- draft | active | pending | sold | withdrawn
  address             text,
  city                text,
  state               text,
  zip                 text,
  property_type       text,   -- single_family | condo | townhouse | multi_family | land | other
  list_price          numeric,
  bedrooms            integer,
  bathrooms           numeric,
  square_footage      integer,
  lot_size_sqft       numeric,
  year_built          integer,
  stories             numeric,
  garage_spaces       numeric,
  hoa_fee             numeric,
  hoa_frequency       text,
  annual_taxes        numeric,
  parcel_number       text,
  mls_number          text,
  public_remarks      text,   -- the listing description / public remarks
  features            text[], -- interior/exterior features
  school_district     text,
  listing_agent_name  text,
  listing_agent_email text,
  seller_name         text,
  listing_packet_url  text,   -- storage object path of the uploaded packet
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create index if not exists idx_listings_brokerage on listings(brokerage_id);

-- updated_at trigger (set_updated_at() is defined in 001_init.sql)
drop trigger if exists set_updated_at on listings;
create trigger set_updated_at before update on listings
  for each row execute function set_updated_at();

-- Row-level security: a user sees/edits only its brokerage's listings.
alter table listings enable row level security;
drop policy if exists listings_by_brokerage on listings;
create policy listings_by_brokerage on listings
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
