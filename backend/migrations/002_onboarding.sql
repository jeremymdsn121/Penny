-- Penny — onboarding support.
-- Adds the columns the setup wizard captures that aren't already in 001:
--   * onboarding_completed — whether a brokerage finished the wizard
--   * calendar/scheduling preferences (provider, working hours, buffer, showing method)
-- (email_mode and monitor_email already exist from 001_init.sql.)
-- Run this in the Supabase SQL Editor after 001_init.sql.

alter table brokerages
  add column if not exists onboarding_completed boolean not null default false,
  add column if not exists calendar_provider text,            -- 'google' | 'outlook' | null
  add column if not exists work_start text default '09:00',   -- working hours start, HH:MM
  add column if not exists work_end   text default '17:00',   -- working hours end, HH:MM
  add column if not exists buffer_minutes integer default 15,  -- gap between appointments
  add column if not exists showing_method text default 'email'; -- 'email' | 'showingtime'
