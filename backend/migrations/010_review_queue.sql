-- Sloane V2 — Broker review queue support (Section 2B).
-- Adds deadline resolution tracking and a transaction "last activity" timestamp
-- so the broker dashboard can surface stale and at-risk deals.
-- Run after 009_compliance_checklist.sql.

alter table deadlines add column if not exists resolved boolean default false;
alter table deadlines add column if not exists resolved_note text;

alter table transactions add column if not exists last_activity_at timestamptz default now();

-- Backfill so existing deals aren't all flagged stale on day one.
update transactions set last_activity_at = coalesce(updated_at, created_at)
  where last_activity_at is null;

-- Any direct edit to a transaction (incl. stage change, note) counts as activity.
create or replace function touch_tx_activity_self()
returns trigger language plpgsql as $$
begin
  new.last_activity_at = now();
  return new;
end;
$$;

drop trigger if exists set_last_activity on transactions;
create trigger set_last_activity before update on transactions
  for each row execute function touch_tx_activity_self();

-- Checklist and deadline changes bump the parent transaction's activity.
create or replace function touch_parent_tx_activity()
returns trigger language plpgsql as $$
begin
  update transactions set last_activity_at = now()
    where id = coalesce(NEW.transaction_id, OLD.transaction_id);
  return NEW;
end;
$$;

drop trigger if exists touch_tx_on_checklist on transaction_checklist_items;
create trigger touch_tx_on_checklist
  after insert or update on transaction_checklist_items
  for each row execute function touch_parent_tx_activity();

drop trigger if exists touch_tx_on_deadline on deadlines;
create trigger touch_tx_on_deadline
  after insert or update on deadlines
  for each row execute function touch_parent_tx_activity();
