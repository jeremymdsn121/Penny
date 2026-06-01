-- Sloane V2 — Pending WhatsApp transactions (Section 1A).
-- Stores in-flight contract extractions triggered by a media upload from WhatsApp.
-- One row per contact (UNIQUE on brokerage_id + phone_number); upsert replaces
-- any prior extraction so the agent can re-send without manual cleanup.
-- Rows expire after 2 hours and can be pruned by a scheduled job.
-- Run after 005_listings.sql.

CREATE TABLE IF NOT EXISTS pending_whatsapp_transactions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  brokerage_id     uuid NOT NULL REFERENCES brokerages(id) ON DELETE CASCADE,
  phone_number     text NOT NULL,            -- E.164, matches whatsapp_contacts.phone_number
  extracted_fields jsonb NOT NULL DEFAULT '{}',
  pdf_storage_url  text,                     -- path in the contracts bucket (PDF uploads only)
  expires_at       timestamptz NOT NULL DEFAULT (now() + INTERVAL '2 hours'),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brokerage_id, phone_number)
);

CREATE INDEX IF NOT EXISTS idx_pending_wt_lookup
  ON pending_whatsapp_transactions(brokerage_id, phone_number);

CREATE INDEX IF NOT EXISTS idx_pending_wt_expires
  ON pending_whatsapp_transactions(expires_at);

ALTER TABLE pending_whatsapp_transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS pending_wt_by_brokerage ON pending_whatsapp_transactions;
CREATE POLICY pending_wt_by_brokerage ON pending_whatsapp_transactions
  FOR ALL
  USING  (brokerage_id = auth_brokerage_id())
  WITH CHECK (brokerage_id = auth_brokerage_id());
