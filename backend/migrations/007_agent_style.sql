-- Penny V2 — Per-agent style profiles (Section 1B).
-- Brokerage-wide style rules are the floor; an individual agent can layer their
-- own style on top. A rule with agent_id NULL is brokerage-wide; a rule with
-- agent_id set applies only to that agent's generated documents and takes
-- precedence over the brokerage rule in the same category.
-- The agents table already exists (001_init.sql); we only add the link columns.
-- Run after 006_pending_whatsapp_transactions.sql.

-- knowledge_rules: optional agent scope (NULL = brokerage-wide).
alter table knowledge_rules
  add column if not exists agent_id uuid references agents(id) on delete cascade;

create index if not exists idx_knowledge_rules_agent
  on knowledge_rules(brokerage_id, agent_id);

-- knowledge_documents: tag agent-uploaded style references so the brokerage
-- knowledge page can keep brokerage-wide and per-agent uploads separate.
alter table knowledge_documents
  add column if not exists agent_id uuid references agents(id) on delete cascade;

create index if not exists idx_knowledge_documents_agent
  on knowledge_documents(brokerage_id, agent_id);

-- whatsapp_contacts: optionally link a registered number to an agent so the
-- WhatsApp document-drafting path can apply that agent's style preferences.
alter table whatsapp_contacts
  add column if not exists agent_id uuid references agents(id) on delete set null;

-- The agents table predates RLS-by-policy convenience helpers but already has a
-- brokerage_id policy from 001_init.sql, so no new policy is required here.
