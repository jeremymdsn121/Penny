-- Penny — Document routing (Autonomy task `doc-routing`).
-- Routes the contract to selected parties (e.g. title, lender) when a deal
-- enters a chosen stage. Two tables, both brokerage-scoped:
--   doc_routing_rules  — per-brokerage config: which stage fires, which roles
--                        receive, which document source. The "configurable" part.
--   pending_doc_routes — the one-click send queue. When doc-routing autonomy is
--                        OFF, a fired rule lands here for the deal's agent to
--                        approve (confirm-gated send), instead of sending blind.
-- When doc-routing autonomy is ON, the send happens immediately and is logged
-- here with status='sent' for the audit trail. Run after 016.

create table if not exists doc_routing_rules (
  id              uuid primary key default gen_random_uuid(),
  brokerage_id    uuid not null references brokerages(id) on delete cascade,
  trigger_stage   text not null,
  document_source text not null default 'contract',
  recipient_roles text[] not null default '{}',
  enabled         boolean not null default true,
  created_at      timestamptz default now()
);

create table if not exists pending_doc_routes (
  id               uuid primary key default gen_random_uuid(),
  brokerage_id     uuid not null references brokerages(id) on delete cascade,
  transaction_id   uuid not null references transactions(id) on delete cascade,
  rule_id          uuid references doc_routing_rules(id) on delete set null,
  trigger_stage    text not null,
  document_source  text not null default 'contract',
  document_url     text,
  recipient_roles  text[] not null default '{}',
  recipient_emails text[] not null default '{}',
  status           text not null default 'pending'
                     check (status in ('pending', 'sent', 'dismissed')),
  resolved_at      timestamptz,
  resolved_by      uuid,
  created_at       timestamptz default now()
);

create index if not exists idx_doc_routing_rules_brokerage
  on doc_routing_rules(brokerage_id);
create index if not exists idx_pending_doc_routes_brokerage
  on pending_doc_routes(brokerage_id);
create index if not exists idx_pending_doc_routes_transaction
  on pending_doc_routes(transaction_id);
-- One queued/sent row per (transaction, rule) so re-entering a stage can't
-- double-route. Dismissed rows are excluded so an agent who dismisses can be
-- re-prompted if the rule fires again later.
create unique index if not exists uq_pending_doc_routes_tx_rule
  on pending_doc_routes(transaction_id, rule_id)
  where status in ('pending', 'sent');

alter table doc_routing_rules enable row level security;
alter table pending_doc_routes enable row level security;

do $$
begin
  create policy doc_routing_rules_by_brokerage on doc_routing_rules
    for all using (
      brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
    );
  create policy pending_doc_routes_by_brokerage on pending_doc_routes
    for all using (
      brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
    );
end $$;
