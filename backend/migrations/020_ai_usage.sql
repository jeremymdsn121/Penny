-- 020: AI usage log for unit-economics tracking.
--
-- One row per Anthropic API call (agent run, contract extraction, etc.) so we
-- can measure tokens — and therefore cost — per brokerage and per feature.
-- Append-only; nothing reads it in the request path. brokerage_id is nullable
-- because some AI calls (e.g. inbound media before a contact is matched) have
-- no brokerage in scope.
--
-- Numbering note: 018/019 are the merged two-way-email feature. A separate
-- unmerged branch (claude/outstanding-items-review) also defines 018/019 for
-- other features; those must be renumbered to 021+ before that branch merges.

create table if not exists ai_usage (
  id uuid primary key default gen_random_uuid(),
  brokerage_id uuid references brokerages(id) on delete cascade,
  feature text not null,
  model text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cache_creation_input_tokens integer not null default 0,
  cache_read_input_tokens integer not null default 0,
  created_at timestamptz default now()
);

create index if not exists idx_ai_usage_brokerage on ai_usage(brokerage_id);
create index if not exists idx_ai_usage_created on ai_usage(created_at);

alter table ai_usage enable row level security;

do $$
begin
  create policy ai_usage_by_brokerage on ai_usage
    for all using (
      brokerage_id = (auth.jwt() -> 'app_metadata' ->> 'brokerage_id')::uuid
    );
exception when duplicate_object then null;
end $$;
