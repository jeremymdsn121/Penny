-- Sloane V2 — Compliance checklist engine (Section 2A).
-- Distinct from the AI compliance review (which reads the contract for issues):
-- this tracks whether the required documents are *in the file* — agency
-- disclosure, lead-based paint, wire fraud advisory, etc. — with completed-by
-- and timestamp tracking, so the broker-of-record has an audit-ready closed file.
-- Run after 008_agent_channels.sql.

-- transactions carry a type so we can pick the right checklist/workflow template.
alter table transactions
  add column if not exists transaction_type text default 'buy_side';

-- Template library: system defaults (brokerage_id NULL) + brokerage customizations.
create table if not exists compliance_templates (
  id                uuid primary key default gen_random_uuid(),
  brokerage_id      uuid references brokerages(id) on delete cascade,  -- NULL = system default
  state             text,
  transaction_type  text not null check (
    transaction_type in ('buy_side', 'list_side', 'dual_agency', 'lease')
  ),
  name              text not null,
  is_system_default boolean default false,
  created_at        timestamptz not null default now()
);

create index if not exists idx_compliance_templates_lookup
  on compliance_templates(transaction_type, brokerage_id);

create table if not exists compliance_template_items (
  id                uuid primary key default gen_random_uuid(),
  template_id       uuid not null references compliance_templates(id) on delete cascade,
  sort_order        integer not null default 0,
  label             text not null,
  description       text,
  required          boolean default true,
  document_required boolean default false,
  notes             text,
  created_at        timestamptz not null default now()
);

create index if not exists idx_compliance_template_items_template
  on compliance_template_items(template_id);

-- Per-transaction checklist (instantiated from a template on transaction creation).
create table if not exists transaction_checklist_items (
  id               uuid primary key default gen_random_uuid(),
  transaction_id   uuid not null references transactions(id) on delete cascade,
  template_item_id uuid references compliance_template_items(id),  -- NULL = manually added
  label            text not null,
  required         boolean default true,
  document_required boolean default false,
  status           text not null default 'pending'
    check (status in ('pending', 'complete', 'waived', 'not_applicable')),
  completed_at     timestamptz,
  completed_by     uuid,
  document_url     text,
  waiver_note      text,
  sort_order       integer default 0,
  created_at       timestamptz not null default now()
);

create index if not exists idx_transaction_checklist_items_tx
  on transaction_checklist_items(transaction_id);

-- --------------------------------------------------------------------------- --
-- Row-level security
-- --------------------------------------------------------------------------- --
alter table compliance_templates       enable row level security;
alter table compliance_template_items  enable row level security;
alter table transaction_checklist_items enable row level security;

-- Templates: system defaults are readable by everyone; brokerage templates only
-- by their owner. Writes only on brokerage-owned templates.
drop policy if exists compliance_templates_read on compliance_templates;
create policy compliance_templates_read on compliance_templates
  for select using (brokerage_id is null or brokerage_id = auth_brokerage_id());
drop policy if exists compliance_templates_write on compliance_templates;
create policy compliance_templates_write on compliance_templates
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());

drop policy if exists compliance_template_items_read on compliance_template_items;
create policy compliance_template_items_read on compliance_template_items
  for select using (exists (
    select 1 from compliance_templates t
    where t.id = compliance_template_items.template_id
      and (t.brokerage_id is null or t.brokerage_id = auth_brokerage_id())
  ));
drop policy if exists compliance_template_items_write on compliance_template_items;
create policy compliance_template_items_write on compliance_template_items
  for all using (exists (
    select 1 from compliance_templates t
    where t.id = compliance_template_items.template_id
      and t.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from compliance_templates t
    where t.id = compliance_template_items.template_id
      and t.brokerage_id = auth_brokerage_id()
  ));

drop policy if exists transaction_checklist_by_transaction on transaction_checklist_items;
create policy transaction_checklist_by_transaction on transaction_checklist_items
  for all using (exists (
    select 1 from transactions tx
    where tx.id = transaction_checklist_items.transaction_id
      and tx.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from transactions tx
    where tx.id = transaction_checklist_items.transaction_id
      and tx.brokerage_id = auth_brokerage_id()
  ));

-- --------------------------------------------------------------------------- --
-- Seed system default templates (idempotent on name + is_system_default)
-- --------------------------------------------------------------------------- --
do $$
declare buy_id uuid; list_id uuid;
begin
  if not exists (
    select 1 from compliance_templates
    where is_system_default and transaction_type = 'buy_side'
  ) then
    insert into compliance_templates (brokerage_id, state, transaction_type, name, is_system_default)
      values (null, null, 'buy_side', 'Buy-side closing file (default)', true)
      returning id into buy_id;
    insert into compliance_template_items (template_id, sort_order, label, required, document_required) values
      (buy_id,  1, 'Buyer representation agreement (signed)',                 true,  true),
      (buy_id,  2, 'Agency disclosure (signed by buyer)',                     true,  true),
      (buy_id,  3, 'Wire fraud advisory (signed by buyer)',                   true,  true),
      (buy_id,  4, 'Purchase contract — fully executed copy',                 true,  true),
      (buy_id,  5, 'Earnest money receipt',                                   true,  true),
      (buy_id,  6, 'Inspection report (received)',                            true,  true),
      (buy_id,  7, 'Inspection objection / resolution addendum (if applicable)', false, true),
      (buy_id,  8, 'Financing commitment letter',                            true,  true),
      (buy_id,  9, 'Appraisal report (if applicable)',                        false, true),
      (buy_id, 10, 'Title commitment / preliminary title report',            true,  true),
      (buy_id, 11, 'HOA documents (if applicable)',                           false, true),
      (buy_id, 12, 'Lead-based paint disclosure (pre-1978 properties)',       false, true),
      (buy_id, 13, 'Final walkthrough confirmation',                          true,  true),
      (buy_id, 14, 'Closing disclosure (reviewed)',                           true,  true),
      (buy_id, 15, 'Settlement statement / ALTA',                             true,  true),
      (buy_id, 16, 'Commission disbursement authorization (CDA)',             true,  true);
  end if;

  if not exists (
    select 1 from compliance_templates
    where is_system_default and transaction_type = 'list_side'
  ) then
    insert into compliance_templates (brokerage_id, state, transaction_type, name, is_system_default)
      values (null, null, 'list_side', 'List-side closing file (default)', true)
      returning id into list_id;
    insert into compliance_template_items (template_id, sort_order, label, required, document_required) values
      (list_id,  1, 'Listing agreement — fully executed',                    true,  true),
      (list_id,  2, 'Seller''s property disclosure statement',               true,  true),
      (list_id,  3, 'Agency disclosure (signed by seller)',                  true,  true),
      (list_id,  4, 'Wire fraud advisory (signed by seller)',                true,  true),
      (list_id,  5, 'Lead-based paint disclosure (pre-1978 properties)',     false, true),
      (list_id,  6, 'HOA addendum and documents (if applicable)',            false, true),
      (list_id,  7, 'MLS input sheet / listing data verification',           true,  true),
      (list_id,  8, 'Professional photos received',                          true,  false),
      (list_id,  9, 'Purchase contract — fully executed copy',               true,  true),
      (list_id, 10, 'Earnest money receipt',                                 true,  true),
      (list_id, 11, 'Inspection report (received by seller''s side)',        true,  true),
      (list_id, 12, 'Repair request and resolution addendum (if applicable)', false, true),
      (list_id, 13, 'Appraisal report (if applicable)',                       false, true),
      (list_id, 14, 'Title commitment',                                       true,  true),
      (list_id, 15, 'Settlement statement / ALTA',                            true,  true),
      (list_id, 16, 'Commission disbursement authorization (CDA)',            true,  true);
  end if;
end $$;
