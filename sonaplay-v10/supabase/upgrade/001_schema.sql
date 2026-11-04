-- Sona Play schema. Safe to re-run. New project: run as is. Existing project: it only adds what is missing.
-- Dashboard > SQL Editor > New query > paste > Run.

create table if not exists app_config (premium_enabled boolean default false);
alter table app_config add column if not exists dj_mixes_enabled boolean default false;
insert into app_config (premium_enabled) select false where not exists (select 1 from app_config);

create table if not exists dj_mixes (
  id uuid primary key default gen_random_uuid(),
  dj_id uuid not null references auth.users(id) on delete cascade,
  dj_name text not null, title text not null, youtube_url text not null, video_id text not null,
  thumbnail text, created_at timestamptz default now());

create table if not exists playlists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null, created_at timestamptz default now());
create table if not exists playlist_tracks (
  id uuid primary key default gen_random_uuid(),
  playlist_id uuid not null references playlists(id) on delete cascade,
  track jsonb not null, position int default 0, created_at timestamptz default now());

create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text, avatar_url text, created_at timestamptz default now());
create table if not exists user_prefs (
  user_id uuid primary key references auth.users(id) on delete cascade,
  genres text[] default '{}', notify_new_songs boolean default true,
  audio_quality text default 'high', updated_at timestamptz default now());
create table if not exists follows (
  user_id uuid not null references auth.users(id) on delete cascade,
  artist_name text not null, channel_id text, kind text default 'artist' check (kind in ('artist','dj')),
  created_at timestamptz default now(), primary key (user_id, artist_name));
create table if not exists liked_songs (
  user_id uuid not null references auth.users(id) on delete cascade,
  video_id text not null, track jsonb, created_at timestamptz default now(), primary key (user_id, video_id));
create table if not exists history (
  id bigserial primary key, user_id uuid not null references auth.users(id) on delete cascade,
  video_id text not null, track jsonb, played_at timestamptz default now());
create table if not exists push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null unique, p256dh text not null, auth text not null, created_at timestamptz default now());
create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  artist text, video_id text not null, title text, thumbnail text,
  read boolean default false, created_at timestamptz default now());
-- used only by the release-check job (service role); no policies = invisible to app users
create table if not exists artist_state (
  artist_name text primary key, channel_id text, last_seen_video_id text, checked_at timestamptz default now());

create index if not exists follows_artist_idx on follows (artist_name);
create index if not exists notif_user_idx on notifications (user_id, created_at desc);
create index if not exists history_user_idx on history (user_id, played_at desc);

-- profile row on sign-up
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, display_name) values (new.id, coalesce(new.raw_user_meta_data->>'name', split_part(new.email,'@',1))) on conflict do nothing;
  insert into user_prefs (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

-- Row level security: every user only touches their own rows
do $$ declare t text; begin
  foreach t in array array['app_config','dj_mixes','playlists','playlist_tracks','profiles','user_prefs','follows','liked_songs','history','push_subscriptions','notifications','artist_state'] loop
    execute format('alter table %I enable row level security', t); end loop;
  foreach t in array array['playlists','user_prefs','follows','liked_songs','history','push_subscriptions'] loop
    execute format('drop policy if exists "own rows" on %I', t);
    execute format('create policy "own rows" on %I for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id)', t); end loop;
end $$;

drop policy if exists "own tracks" on playlist_tracks;
create policy "own tracks" on playlist_tracks for all to authenticated
  using (exists (select 1 from playlists p where p.id = playlist_id and p.user_id = auth.uid()))
  with check (exists (select 1 from playlists p where p.id = playlist_id and p.user_id = auth.uid()));
drop policy if exists "own profile read" on profiles;   create policy "own profile read" on profiles for select to authenticated using (auth.uid() = id);
drop policy if exists "own profile update" on profiles; create policy "own profile update" on profiles for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);
drop policy if exists "own notifications read" on notifications;   create policy "own notifications read" on notifications for select to authenticated using (auth.uid() = user_id);
drop policy if exists "own notifications update" on notifications; create policy "own notifications update" on notifications for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "own notifications delete" on notifications; create policy "own notifications delete" on notifications for delete to authenticated using (auth.uid() = user_id);
drop policy if exists "Anyone can view dj_mixes" on dj_mixes;           create policy "Anyone can view dj_mixes" on dj_mixes for select using (true);
drop policy if exists "DJs can insert their own mixes" on dj_mixes;     create policy "DJs can insert their own mixes" on dj_mixes for insert to authenticated with check (auth.uid() = dj_id);
drop policy if exists "DJs can delete their own mixes" on dj_mixes;     create policy "DJs can delete their own mixes" on dj_mixes for delete to authenticated using (auth.uid() = dj_id);
drop policy if exists "read config" on app_config; create policy "read config" on app_config for select using (true);

-- Least privilege: the browser (anon/authenticated) gets only what the app needs
revoke all on all tables in schema public from anon, authenticated;
grant select on app_config, dj_mixes to anon, authenticated;
grant insert, delete on dj_mixes to authenticated;
grant select, insert, update, delete on playlists, playlist_tracks, follows, liked_songs, history, push_subscriptions to authenticated;
grant select, insert, update on user_prefs to authenticated;
grant select, update (display_name, avatar_url) on profiles to authenticated;
grant select, delete on notifications to authenticated;
grant update (read) on notifications to authenticated;
grant usage, select on all sequences in schema public to authenticated;
