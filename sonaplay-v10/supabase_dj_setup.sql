-- Run this once in Supabase Dashboard -> SQL Editor -> New Query -> Run

-- Table for DJ-uploaded mixes
create table if not exists dj_mixes (
  id uuid primary key default gen_random_uuid(),
  dj_id uuid not null references auth.users(id),
  dj_name text not null,
  title text not null,
  youtube_url text not null,
  video_id text not null,
  thumbnail text,
  created_at timestamptz default now()
);

-- Anyone can view mixes (public DJ Mixes tab)
alter table dj_mixes enable row level security;
create policy "Anyone can view dj_mixes" on dj_mixes
  for select using (true);

-- Only the DJ who owns a mix can insert their own
create policy "DJs can insert their own mixes" on dj_mixes
  for insert with check (auth.uid() = dj_id);

-- Only the DJ who owns a mix can delete their own
create policy "DJs can delete their own mixes" on dj_mixes
  for delete using (auth.uid() = dj_id);

-- Add the DJ Mixes on/off switch to your existing app_config table
-- (same table Premium already uses - one row, flip this column when
-- you're ready to turn DJ Mixes on)
alter table app_config add column if not exists dj_mixes_enabled boolean default false;
