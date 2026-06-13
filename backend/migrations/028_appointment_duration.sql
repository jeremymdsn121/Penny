-- 028: real appointment duration.
--
-- Bookings carried an implied 30-minute length everywhere (calendar event end,
-- conflict checks, busy math). Persist the actual length so a 2-hour showing
-- blocks two hours for the next booking's conflict check, not thirty minutes.
-- Defaults to 30 so existing rows and any un-specified booking are unchanged.

alter table appointments
  add column if not exists duration_minutes integer default 30;
