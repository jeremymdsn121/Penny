-- Penny — Recurring status updates (Autonomy task `status-updates`).
-- A transaction coordinator's most-cited routine: a regular "here's where we
-- stand" update to the parties on a deal (done / upcoming / awaiting). Penny
-- now sends these on a weekly cadence from an idempotent scan, mirroring the
-- deadline-reminder + scheduled-reply pattern. Run after 028.
--
-- Two pieces, both brokerage-scoped:
--   transactions.last_status_update_at — cadence anchor + idempotency claim. The
--     scan only sends/queues for a deal whose last update is >= the cadence ago,
--     and stamps this column when it handles the deal so a re-run can't repeat.
--   pending_status_updates — the one-click send queue. When status-updates
--     autonomy is OFF, the drafted update lands here for the deal's agent to
--     approve (confirm-gated send) instead of going out blind. When autonomy is
--     ON, the send happens in the scan and is logged here as status='sent' for
--     the audit trail.

alter table transactions
  add column if not exists last_status_update_at timestamptz;

create table if not exists pending_status_updates (
  id               uuid primary key default gen_random_uuid(),
  brokerage_id     uuid not null references brokerages(id) on delete cascade,
  transaction_id   uuid not null references transactions(id) on delete cascade,
  subject          text not null,
  body_text        text not null,
  body_html        text,
  recipient_emails text[] not null default '{}',
  status           text not null default 'pending'
                     check (status in ('pending', 'sent', 'dismissed')),
  resolved_at      timestamptz,
  resolved_by      uuid,
  created_at       timestamptz default now()
);

create index if not exists idx_pending_status_updates_brokerage
  on pending_status_updates(brokerage_id);
create index if not exists idx_pending_status_updates_transaction
  on pending_status_updates(transaction_id);
-- At most one open (pending) status update per deal at a time, so repeated scans
-- before the agent acts can't pile up duplicate drafts. Sent/dismissed rows are
-- excluded so the next cadence cycle can queue a fresh one.
create unique index if not exists uq_pending_status_updates_open
  on pending_status_updates(transaction_id)
  where status = 'pending';

alter table pending_status_updates enable row level security;

do $$
begin
  create policy pending_status_updates_by_brokerage on pending_status_updates
    for all using (
      brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
    );
end $$;
