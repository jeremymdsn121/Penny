-- Penny V2 — Earnest money deposit receipt tracking (Section 5).
-- Brokers are personally liable for trust-account handling in many states. If EMD
-- isn't received by the deadline and no one noticed, that's a legal problem.
-- This tracks *receipt only* — no calculations, no disbursements, no trust math.
-- Run after 012_transaction_emails.sql.

alter table transactions add column if not exists emd_amount numeric;
alter table transactions add column if not exists emd_due_date date;
alter table transactions add column if not exists emd_received boolean default false;
alter table transactions add column if not exists emd_received_date date;
alter table transactions add column if not exists emd_receipt_document_url text;
alter table transactions add column if not exists emd_held_by text
  check (emd_held_by in ('title', 'brokerage', 'escrow', 'other'));
alter table transactions add column if not exists emd_notes text;
