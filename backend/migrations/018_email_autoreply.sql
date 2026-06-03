-- 018: Email as a two-way channel (Phase 1 — agents converse with Penny by email).
--
-- Until now Penny never replied to inbound email (Section 4 logged + nudged
-- only). Realtors answer in the medium a message arrives in, so forcing them to
-- switch to WhatsApp/the dashboard to act on an emailed reply is friction. This
-- opens email as an input channel, with two deliberately-scoped toggles:
--
--   email_agent_autoreply_enabled  — when an INTERNAL agent (sender matches an
--     agents.email row) emails Penny on a deal, run her normal agent loop and
--     reply by email. Low risk (the agent is the brokerage's own person), so it
--     defaults ON. This is the opt-in exception to the "never auto-reply" rule.
--   email_outside_draft_enabled    — when an OUTSIDE party emails, Penny never
--     auto-sends; she drafts a suggested reply into pending_email_replies for the
--     agent to review and confirm-send. Defaults ON (drafting is harmless; the
--     send stays human-gated).
--
-- pending_email_replies is the outside-party approval queue, mirroring the
-- pending_doc_routes pattern. Run after 017.

alter table brokerages
  add column if not exists email_agent_autoreply_enabled boolean not null default true;
alter table brokerages
  add column if not exists email_outside_draft_enabled boolean not null default true;

create table if not exists pending_email_replies (
  id               uuid primary key default gen_random_uuid(),
  brokerage_id     uuid not null references brokerages(id) on delete cascade,
  transaction_id   uuid not null references transactions(id) on delete cascade,
  -- The inbound message we're suggesting a reply to (for thread context / dedupe).
  inbound_email_id uuid references transaction_emails(id) on delete set null,
  to_email         text not null,
  to_name          text,
  subject          text not null default '',
  draft_body       text not null default '',
  status           text not null default 'pending'
                     check (status in ('pending', 'sent', 'dismissed')),
  resolved_at      timestamptz,
  resolved_by      uuid,
  created_at       timestamptz default now()
);

create index if not exists idx_pending_email_replies_brokerage
  on pending_email_replies(brokerage_id);
create index if not exists idx_pending_email_replies_transaction
  on pending_email_replies(transaction_id);
-- At most one open suggestion per inbound message so a retried Inbound Parse
-- delivery can't queue duplicates. Resolved rows are excluded.
create unique index if not exists uq_pending_email_replies_inbound
  on pending_email_replies(inbound_email_id)
  where status = 'pending';

alter table pending_email_replies enable row level security;

do $$
begin
  create policy pending_email_replies_by_brokerage on pending_email_replies
    for all using (
      brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
    );
end $$;
