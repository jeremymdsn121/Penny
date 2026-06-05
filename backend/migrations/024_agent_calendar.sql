-- Penny — per-agent calendar connections.
--
-- Calendar sync (PRD task `scheduling`) routes a deal's showings/inspections to
-- the *agent's* own calendar when connected, falling back to the brokerage's
-- shared calendar. The brokerage-level columns already exist on `brokerages`
-- (google_calendar_token / microsoft_token / calendar_provider, from 001+002);
-- this adds the same per-agent columns so each agent can connect their own
-- Google account. Agents have no web login, so connection is admin-initiated via
-- a signed OAuth state (see services/calendar_provider.py + routes/calendar.py).
--
-- `agents` is already brokerage-scoped under RLS (001_init.sql), so no new policy
-- is needed. Run any time after 001.

alter table agents
  add column if not exists google_calendar_token jsonb,
  add column if not exists microsoft_token       jsonb,
  add column if not exists calendar_provider      text;  -- 'google' | 'outlook' | null
