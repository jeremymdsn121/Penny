-- 016: Optional forwarding of inbound email replies to the deal's agent.
--
-- When a party replies to a Penny-sent email, the reply is captured via
-- Inbound Parse (Section 4) and logged on the transaction. This flag lets a
-- brokerage also forward each reply to the responsible agent's email inbox.
-- Off by default — Penny stays the hub; this is purely an opt-in convenience.

alter table brokerages
  add column if not exists forward_replies_to_agent boolean not null default false;
