-- Sloane V2 — Inbound email reply threading (Section 4).
-- Sloane sends intro emails and party notifications; when a lender or buyer
-- replies, that reply currently vanishes into someone's Gmail. transaction_emails
-- captures both directions so the broker has visibility and the transaction has a
-- record. Inbound replies arrive via SendGrid Inbound Parse to a per-transaction
-- Reply-To address (tx-{id}@<reply domain>).
-- Run after 011_workflow_tasks.sql.

create table if not exists transaction_emails (
  id                  uuid primary key default gen_random_uuid(),
  transaction_id      uuid not null references transactions(id) on delete cascade,
  direction           text not null check (direction in ('outbound', 'inbound')),
  sender_email        text,
  sender_name         text,
  recipient_emails    text[],
  subject             text,
  body_text           text,
  body_html           text,
  sendgrid_message_id text,
  read                boolean default false,
  read_at             timestamptz,
  read_by             uuid,
  received_at         timestamptz not null default now()
);

create index if not exists idx_transaction_emails_tx
  on transaction_emails(transaction_id, direction, read);

alter table transaction_emails enable row level security;
drop policy if exists transaction_emails_by_transaction on transaction_emails;
create policy transaction_emails_by_transaction on transaction_emails
  for all using (exists (
    select 1 from transactions tx
    where tx.id = transaction_emails.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ))
  with check (exists (
    select 1 from transactions tx
    where tx.id = transaction_emails.transaction_id and tx.brokerage_id = auth_brokerage_id()
  ));
