-- 004 (run after 001, 002, 003). Safe to run again.
-- Adds: privacy/terms editor, usernames + invite tracking, top inviters, realtime for alerts.

-- Privacy Policy and Terms, edited in the admin panel
create table if not exists legal_docs (
  kind text primary key check (kind in ('privacy','terms')),
  content text not null default '',
  updated_at timestamptz default now());
alter table legal_docs enable row level security;
drop policy if exists "read legal" on legal_docs;
create policy "read legal" on legal_docs for select using (true);
grant select on legal_docs to anon, authenticated;

create or replace function public.admin_set_legal(p_kind text, p_content text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if p_kind not in ('privacy','terms') then raise exception 'bad kind'; end if;
  insert into legal_docs (kind, content, updated_at) values (p_kind, p_content, now())
  on conflict (kind) do update set content = excluded.content, updated_at = now();
end $$;

-- usernames (used in invite links) and who invited whom
alter table profiles add column if not exists username text;
alter table profiles add column if not exists referred_by uuid references auth.users(id) on delete set null;

create or replace function public.make_username(p_name text, p_id uuid) returns text
language plpgsql as $$
declare base text; cand text; n int := 0;
begin
  base := left(lower(regexp_replace(coalesce(p_name, ''), '[^a-zA-Z0-9]', '', 'g')), 20);
  if base = '' then base := 'user'; end if;
  cand := base;
  while exists (select 1 from profiles where lower(username) = cand and id <> p_id) loop
    n := n + 1; cand := base || n::text;
  end loop;
  return cand;
end $$;

update profiles set username = make_username(display_name, id) where username is null or username = '';
create unique index if not exists profiles_username_key on profiles (lower(username));

create or replace function public.profiles_set_username() returns trigger
language plpgsql as $$
begin
  if new.username is null or new.username = '' then new.username := make_username(new.display_name, new.id); end if;
  return new;
end $$;
drop trigger if exists profiles_username_trg on profiles;
create trigger profiles_username_trg before insert on profiles for each row execute function public.profiles_set_username();

-- a new user opens an invite link: record who invited them (only within 3 days of signing up, never yourself)
create or replace function public.claim_referral(p_username text) returns boolean
language plpgsql security definer set search_path = public as $$
declare rid uuid;
begin
  if auth.uid() is null then return false; end if;
  select id into rid from profiles where lower(username) = lower(p_username);
  if rid is null or rid = auth.uid() then return false; end if;
  update profiles set referred_by = rid
   where id = auth.uid() and referred_by is null and created_at > now() - interval '3 days';
  return found;
end $$;

create or replace function public.admin_top_inviters(p_limit int default 10)
returns table (username text, display_name text, invited bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select p.username, p.display_name, count(c.id)
    from profiles p join profiles c on c.referred_by = p.id
    group by p.id order by count(c.id) desc limit least(p_limit, 50);
end $$;

revoke all on function admin_set_legal(text, text), claim_referral(text), admin_top_inviters(int) from public, anon;
grant execute on function admin_set_legal(text, text), claim_referral(text), admin_top_inviters(int) to authenticated;

-- real-time alerts: make sure new rows in notifications are pushed to open apps
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'notifications') then
    alter publication supabase_realtime add table notifications;
  end if;
end $$;
