-- 022: Configurable document retention policy (BLOCKERS Hard Limit 6, interim).
--
-- Broker-owners handling SSNs / income docs ask about data handling before they
-- sign. This lets a brokerage state its retention policy (default 7 years, a
-- common real-estate record-keeping requirement). The setting is surfaced in the
-- admin panel; actual enforcement (purging expired documents) is a deliberate,
-- separately-gated follow-up — we do not auto-delete client documents blind.

alter table brokerages
  add column if not exists document_retention_years integer not null default 7;

-- Off by default: turning this on is an explicit opt-in to (future) enforcement.
alter table brokerages
  add column if not exists document_retention_enabled boolean not null default false;
