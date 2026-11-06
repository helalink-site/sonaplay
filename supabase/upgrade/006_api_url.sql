-- Run once in the Supabase SQL editor.
-- The phone server publishes its current address here; the app reads it at start.
alter table app_config add column if not exists api_url text;
