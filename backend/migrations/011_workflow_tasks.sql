-- Sloane V2 — Workflow task templates (Section 3).
-- A human TC's core value is knowing what needs to happen next without being
-- asked. These templates let Sloane generate the right tasks at the right time
-- (on stage entry, or N days before a deadline), so she's proactive, not just
-- reactive. Run after 010_review_queue.sql.

create table if not exists workflow_templates (
  id                uuid primary key default gen_random_uuid(),
  brokerage_id      uuid references brokerages(id) on delete cascade,  -- NULL = system default
  name              text not null,
  state             text,
  transaction_type  text check (
    transaction_type in ('buy_side', 'list_side', 'dual_agency', 'lease')
  ),
  is_system_default boolean default false,
  created_at        timestamptz not null default now()
);

create table if not exists workflow_steps (
  id                     uuid primary key default gen_random_uuid(),
  template_id            uuid not null references workflow_templates(id) on delete cascade,
  sort_order             integer not null default 0,
  label                  text not null,
  description            text,
  trigger_type           text not null check (
    trigger_type in ('stage_entry', 'days_before_deadline', 'days_after_stage', 'manual')
  ),
  trigger_stage          text,
  trigger_deadline_label text,
  trigger_days           integer,
  assigned_to_role       text check (
    assigned_to_role in ('agent', 'admin', 'buyer', 'seller', 'lender', 'title')
  ),
  due_offset_days        integer default 0,
  created_at             timestamptz not null default now()
);

create index if not exists idx_workflow_steps_template on workflow_steps(template_id);

create table if not exists transaction_tasks (
  id               uuid primary key default gen_random_uuid(),
  transaction_id   uuid not null references transactions(id) on delete cascade,
  step_id          uuid references workflow_steps(id),  -- NULL = manually created
  label            text not null,
  description      text,
  due_date         date,
  assigned_to_role text,
  status           text not null default 'pending'
    check (status in ('pending', 'complete', 'skipped')),
  completed_at     timestamptz,
  completed_by     uuid,
  skip_reason      text,
  created_at       timestamptz not null default now()
);

create index if not exists idx_transaction_tasks_tx on transaction_tasks(transaction_id, status);

-- --------------------------------------------------------------------------- --
-- Row-level security
-- --------------------------------------------------------------------------- --
alter table workflow_templates  enable row level security;
alter table workflow_steps      enable row level security;
alter table transaction_tasks   enable row level security;

drop policy if exists workflow_templates_read on workflow_templates;
create policy workflow_templates_read on workflow_templates
  for select using (brokerage_id is null or brokerage_id = auth_brokerage_id());
drop policy if exists workflow_templates_write on workflow_templates;
create policy workflow_templates_write on workflow_templates
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());

drop policy if exists workflow_steps_read on workflow_steps;
create policy workflow_steps_read on workflow_steps
  for select using (exists (
    select 1 from workflow_templates t
    where t.id = workflow_steps.template_id
      and (t.brokerage_id is null or t.brokerage_id = auth_brokerage_id())
  ));
drop policy if exists workflow_steps_write on workflow_steps;
create policy workflow_steps_write on workflow_steps
  for all using (exists (
    select 1 from workflow_templates t
    where t.id = workflow_steps.template_id and t.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from workflow_templates t
    where t.id = workflow_steps.template_id and t.brokerage_id = auth_brokerage_id()
  ));

drop policy if exists transaction_tasks_by_transaction on transaction_tasks;
create policy transaction_tasks_by_transaction on transaction_tasks
  for all using (exists (
    select 1 from transactions tx
    where tx.id = transaction_tasks.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from transactions tx
    where tx.id = transaction_tasks.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ));

-- --------------------------------------------------------------------------- --
-- Seed the system-default buy-side workflow (idempotent)
-- --------------------------------------------------------------------------- --
do $$
declare buy_id uuid;
begin
  if not exists (
    select 1 from workflow_templates where is_system_default and transaction_type = 'buy_side'
  ) then
    insert into workflow_templates (brokerage_id, transaction_type, name, is_system_default)
      values (null, 'buy_side', 'Buy-side workflow (default)', true)
      returning id into buy_id;

    insert into workflow_steps
      (template_id, sort_order, label, trigger_type, trigger_stage, trigger_deadline_label, trigger_days, assigned_to_role, due_offset_days)
    values
      -- Stage: under_contract
      (buy_id,  1, 'Send intro email to all parties',          'stage_entry', 'under_contract', null, null, 'agent', 0),
      (buy_id,  2, 'Confirm earnest money receipt date',       'stage_entry', 'under_contract', null, null, 'agent', 0),
      (buy_id,  3, 'Order home inspection',                    'stage_entry', 'under_contract', null, null, 'agent', 1),
      (buy_id,  4, 'Verify lender has application',            'stage_entry', 'under_contract', null, null, 'agent', 2),
      -- Inspection deadline approach
      (buy_id,  5, 'Confirm inspection is scheduled',          'days_before_deadline', null, 'inspection', 5, 'agent', 0),
      (buy_id,  6, 'Inspection objection deadline approaching — prepare response if needed', 'days_before_deadline', null, 'inspection', 2, 'agent', 0),
      -- Stage: pending
      (buy_id,  7, 'Order appraisal (if applicable)',          'stage_entry', 'pending', null, null, 'agent', 0),
      (buy_id,  8, 'Request title commitment from title company', 'stage_entry', 'pending', null, null, 'agent', 0),
      (buy_id,  9, 'Confirm appraisal is ordered',             'stage_entry', 'pending', null, null, 'agent', 3),
      -- Closing approach
      (buy_id, 10, 'Request final closing disclosure from lender', 'days_before_deadline', null, 'closing', 5, 'agent', 0),
      (buy_id, 11, 'Confirm final walkthrough is scheduled',   'days_before_deadline', null, 'closing', 5, 'agent', 0),
      (buy_id, 12, 'Prepare commission disbursement authorization', 'days_before_deadline', null, 'closing', 5, 'admin', 0),
      (buy_id, 13, 'Confirm wire instructions sent (and wire fraud advisory on file)', 'days_before_deadline', null, 'closing', 2, 'agent', 0),
      (buy_id, 14, 'Confirm closing time and location with all parties', 'days_before_deadline', null, 'closing', 2, 'agent', 0);
  end if;
end $$;
