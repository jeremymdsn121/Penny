-- Penny — knowledge base / brand & style ingestion.
-- Creates:
--   knowledge_documents — uploaded style references (letterheads, sample
--                         letters, templates) stored in the private
--                         "knowledge-docs" bucket, with processing status.
-- Also links knowledge_rules back to the document they were extracted from.
--
-- Flow: a brokerage admin uploads a document → Penny reads it and proposes
-- style rules into knowledge_rules (confirmed=false) → the admin confirms →
-- confirmed rules are injected into Penny's AI prompts.
--
-- Run this in the Supabase SQL Editor after 003_whatsapp.sql.

-- --------------------------------------------------------------------------- --
-- knowledge_documents
-- --------------------------------------------------------------------------- --
create table if not exists knowledge_documents (
  id           uuid primary key default gen_random_uuid(),
  brokerage_id uuid not null references brokerages(id) on delete cascade,
  filename     text not null,                        -- original upload name
  storage_path text not null,                        -- path within the bucket
  content_type text,                                 -- MIME type as uploaded
  file_size    integer,                              -- bytes
  status       text not null default 'processing',   -- 'processing'|'processed'|'failed'
  error        text,                                 -- failure detail, if any
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists idx_knowledge_documents_brokerage
  on knowledge_documents(brokerage_id);

-- --------------------------------------------------------------------------- --
-- knowledge_rules: trace each proposed rule back to its source document
-- --------------------------------------------------------------------------- --
alter table knowledge_rules
  add column if not exists document_id uuid
    references knowledge_documents(id) on delete set null;

create index if not exists idx_knowledge_rules_document
  on knowledge_rules(document_id);

-- --------------------------------------------------------------------------- --
-- updated_at trigger for knowledge_documents
-- --------------------------------------------------------------------------- --
drop trigger if exists set_updated_at on knowledge_documents;
create trigger set_updated_at before update on knowledge_documents
  for each row execute function set_updated_at();

-- --------------------------------------------------------------------------- --
-- Row-level security
-- --------------------------------------------------------------------------- --
alter table knowledge_documents enable row level security;

drop policy if exists knowledge_documents_by_brokerage on knowledge_documents;
create policy knowledge_documents_by_brokerage on knowledge_documents
  for all using (brokerage_id = auth_brokerage_id())
  with check (brokerage_id = auth_brokerage_id());
