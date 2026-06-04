-- 021: Compliance review feedback log (BLOCKERS Hard Limit 5).
--
-- The AI compliance review will occasionally misclassify an item — a fundamental
-- LLM property. We never auto-tune the model in production; instead the broker can
-- mark a finding correct/incorrect, building an audit log we can review by hand to
-- spot systematic errors. This is a record only — it changes no behavior.

create table if not exists compliance_feedback (
  id             uuid primary key default gen_random_uuid(),
  brokerage_id   uuid not null references brokerages(id) on delete cascade,
  transaction_id uuid not null references transactions(id) on delete cascade,
  rule_id        text not null,
  ai_status      text,        -- satisfied | missing | unclear (what the model said)
  ai_confidence  text,        -- high | medium | low
  human_verdict  text not null check (human_verdict in ('correct', 'incorrect')),
  note           text,
  created_by     uuid,
  created_at     timestamptz default now()
);

create index if not exists idx_compliance_feedback_brokerage
  on compliance_feedback(brokerage_id);
create index if not exists idx_compliance_feedback_transaction
  on compliance_feedback(transaction_id);

alter table compliance_feedback enable row level security;

-- Idempotent policy (re-runnable): drop then create, so re-pasting can't error.
drop policy if exists compliance_feedback_by_brokerage on compliance_feedback;
create policy compliance_feedback_by_brokerage on compliance_feedback
  for all using (
    brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
  );
