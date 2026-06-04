-- Penny — SMS double opt-in consent tracking (A2P 10DLC compliance).
--
-- US carriers require verifiable end-user consent for application-to-person SMS.
-- Penny's numbers are entered by a brokerage admin, so the agent who receives the
-- texts must confirm opt-in themselves. We track that consent on agent_channels:
--   pending    — registered, confirmation SMS sent, awaiting the agent's YES
--   active     — agent replied YES (or legacy/WhatsApp rows); messaging allowed
--   opted_out  — agent replied STOP; no further messages until they opt back in
--
-- Default is 'active' so every existing row (WhatsApp contacts, and any SMS
-- numbers added before this migration) keeps working unchanged. Only NEW SMS
-- registrations are inserted as 'pending' (see routes/sms.py). WhatsApp opt-in is
-- handled by the Business API / sandbox join, so WhatsApp rows stay 'active'.
-- Run after 008_agent_channels.sql.

alter table agent_channels
  add column if not exists consent_status text not null default 'active'
    check (consent_status in ('pending', 'active', 'opted_out')),
  add column if not exists consent_updated_at timestamptz;
