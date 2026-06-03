-- Penny V2 — Broker reporting support (Section 7).
-- Records when a deal closed so production metrics (count, volume, days-to-close)
-- can be computed per period. closed_at is set on the stage transition to 'closed'.
-- Run after 014_party_consents.sql.

alter table transactions add column if not exists closed_at timestamptz;

-- Backfill: deals already in 'closed' get their last update as an approximate
-- close date so historical reporting isn't empty.
update transactions set closed_at = coalesce(updated_at, created_at)
  where stage = 'closed' and closed_at is null;
