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
-- 002: region at sign-up, admin role, analytics for the admin panel, admin broadcasts.
-- Run AFTER 001_schema.sql. Safe to re-run.
alter table profiles add column if not exists region text;
alter table profiles add column if not exists last_seen_at timestamptz;
create index if not exists profiles_region_idx on profiles (region);
create index if not exists profiles_created_idx on profiles (created_at);
grant update (region) on profiles to authenticated;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (id, display_name, region)
  values (new.id, coalesce(new.raw_user_meta_data->>'display_name', new.raw_user_meta_data->>'name', split_part(new.email,'@',1)),
          nullif(new.raw_user_meta_data->>'region',''))
  on conflict (id) do update set region = coalesce(profiles.region, excluded.region);
  insert into user_prefs (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;

-- admins: add yourself once:  insert into admins (user_id) select id from auth.users where email = 'you@email.com';
create table if not exists admins (user_id uuid primary key references auth.users(id) on delete cascade, created_at timestamptz default now());
alter table admins enable row level security;   -- no policies: not readable from the browser
create or replace function public.is_admin() returns boolean language sql stable security definer set search_path = public as
$$ select exists (select 1 from admins where user_id = auth.uid()) $$;

-- daily activity (one row per user per day)
create table if not exists user_activity (
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null default ((now() at time zone 'utc')::date), primary key (user_id, day));
alter table user_activity enable row level security;
create or replace function public.touch_activity() returns void language sql security definer set search_path = public as
$$ insert into user_activity (user_id) values (auth.uid()) on conflict do nothing;
   update profiles set last_seen_at = now() where id = auth.uid(); $$;

-- notifications can now also be admin broadcasts (no song attached)
alter table notifications alter column video_id drop not null;
alter table notifications add column if not exists kind text default 'release';
alter table notifications add column if not exists body text;
alter table notifications add column if not exists pushed boolean default false;
create table if not exists broadcasts (
  id uuid primary key default gen_random_uuid(), sent_by uuid references auth.users(id) on delete set null,
  title text not null, body text, region text, recipients int default 0, created_at timestamptz default now());
alter table broadcasts enable row level security;

create or replace function public.admin_send_broadcast(p_title text, p_body text, p_region text default null) returns int
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  insert into notifications (user_id, artist, title, body, kind)
    select id, 'Sona Play', p_title, p_body, 'broadcast' from profiles where p_region is null or region = p_region;
  get diagnostics n = row_count;
  insert into broadcasts (sent_by, title, body, region, recipients) values (auth.uid(), p_title, p_body, p_region, n);
  return n;
end $$;

create or replace function public.admin_overview() returns json language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return json_build_object(
    'total_users', (select count(*) from profiles),
    'new_today', (select count(*) from profiles where created_at >= date_trunc('day', now())),
    'active_today', (select count(*) from user_activity where day = (now() at time zone 'utc')::date),
    'active_7d', (select count(distinct user_id) from user_activity where day > (now() at time zone 'utc')::date - 7),
    'active_30d', (select count(distinct user_id) from user_activity where day > (now() at time zone 'utc')::date - 30),
    'no_region', (select count(*) from profiles where region is null));
end $$;

-- p_period: 'day' | 'week' | 'month'; returns the last p_count buckets
create or replace function public.admin_signups(p_period text, p_count int default 30) returns table (bucket date, users bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if p_period not in ('day','week','month') then raise exception 'bad period'; end if;
  return query select date_trunc(p_period, created_at)::date, count(*) from profiles
    where created_at >= date_trunc(p_period, now()) - ((least(p_count,120) - 1) * ('1 ' || p_period)::interval)
    group by 1 order by 1;
end $$;

create or replace function public.admin_active(p_period text, p_count int default 30) returns table (bucket date, users bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if p_period not in ('day','week','month') then raise exception 'bad period'; end if;
  return query select date_trunc(p_period, day::timestamp)::date, count(distinct user_id) from user_activity
    where day::timestamp >= date_trunc(p_period, now()) - ((least(p_count,120) - 1) * ('1 ' || p_period)::interval)
    group by 1 order by 1;
end $$;

create or replace function public.admin_by_region() returns table (region text, users bigint, active_30d bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select coalesce(p.region, 'Not set'), count(*),
    count(*) filter (where p.last_seen_at > now() - interval '30 days') from profiles p group by 1 order by 2 desc;
end $$;

create or replace function public.admin_list_users(p_search text default '', p_limit int default 50, p_offset int default 0)
returns table (id uuid, email text, display_name text, region text, created_at timestamptz, last_seen_at timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select p.id, u.email::text, p.display_name, p.region, p.created_at, p.last_seen_at
    from profiles p join auth.users u on u.id = p.id
    where p_search = '' or u.email ilike '%' || p_search || '%' or p.display_name ilike '%' || p_search || '%'
    order by p.created_at desc limit least(p_limit, 200) offset p_offset;
end $$;

-- only signed-in users may call these (the admin ones also check is_admin() inside)
revoke all on function touch_activity(), is_admin(), admin_send_broadcast(text,text,text), admin_overview(),
  admin_signups(text,int), admin_active(text,int), admin_by_region(), admin_list_users(text,int,int) from public, anon;
grant execute on function touch_activity(), is_admin(), admin_send_broadcast(text,text,text), admin_overview(),
  admin_signups(text,int), admin_active(text,int), admin_by_region(), admin_list_users(text,int,int) to authenticated;

-- realtime for the notification bell
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'notifications') then
    alter publication supabase_realtime add table notifications;
  end if;
end $$;
