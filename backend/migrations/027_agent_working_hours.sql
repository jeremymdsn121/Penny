-- 027: per-agent working hours (override the brokerage default).
--
-- Each agent can keep their own scheduling window + buffer. NULL on any column
-- means "inherit the brokerage's work_start / work_end / buffer_minutes" (the
-- columns added in 002). Resolution is per-field — see
-- scheduling.resolve_working_hours — so an agent can override just the hours and
-- still inherit the brokerage buffer, or vice versa.
--
-- Agents already carry brokerage_id + RLS (001+), so no new policy is needed.

alter table agents
  add column if not exists work_start     text,
  add column if not exists work_end       text,
  add column if not exists buffer_minutes integer;
