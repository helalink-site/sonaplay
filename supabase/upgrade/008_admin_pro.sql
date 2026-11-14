-- Run once in the Supabase SQL editor. Adds the data the new admin panel shows.
create or replace function public.admin_top_songs(p_days int default 30, p_limit int default 10)
returns table (video_id text, title text, artist text, plays bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select h.video_id, max(coalesce(h.track->>'title', h.track->>'t'))::text, max(coalesce(h.track->>'artist', h.track->>'a'))::text, count(*)
    from history h where h.played_at > now() - make_interval(days => least(p_days, 365))
    group by h.video_id order by 4 desc limit least(p_limit, 50);
end $$;
create or replace function public.admin_top_artists(p_days int default 30, p_limit int default 10)
returns table (artist text, plays bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select a::text, count(*) from (select coalesce(h.track->>'artist', h.track->>'a') a from history h
      where h.played_at > now() - make_interval(days => least(p_days, 365))) x
    where a is not null and a <> '' group by a order by 2 desc limit least(p_limit, 50);
end $$;
create or replace function public.admin_plays_by_day(p_days int default 30)
returns table (bucket date, users bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select h.played_at::date, count(*) from history h
    where h.played_at >= now() - make_interval(days => least(p_days, 120)) group by 1 order by 1;
end $$;
create or replace function public.admin_genre_split()
returns table (genre text, users bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select g::text, count(*) from user_prefs, unnest(genres) g group by 1 order by 2 desc limit 12;
end $$;
create or replace function public.admin_top_followed(p_limit int default 10)
returns table (artist text, followers bigint)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select f.artist_name::text, count(*) from follows f group by 1 order by 2 desc limit least(p_limit, 50);
end $$;
create or replace function public.admin_comments(p_limit int default 30)
returns table (id uuid, thread text, name text, body text, created_at timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  return query select c.id, c.thread, c.name, c.body, c.created_at from notif_comments c order by c.created_at desc limit least(p_limit, 100);
end $$;
create or replace function public.admin_delete_comment(p_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  delete from notif_comments where id = p_id;
end $$;
create or replace function public.admin_set_api(p_url text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if not exists (select 1 from app_config) then insert into app_config (premium_enabled) values (false); end if;
  update app_config set api_url = nullif(p_url, '') where true;
end $$;
revoke all on function admin_top_songs(int,int), admin_top_artists(int,int), admin_plays_by_day(int), admin_genre_split(), admin_top_followed(int),
  admin_comments(int), admin_delete_comment(uuid), admin_set_api(text) from public, anon;
grant execute on function admin_top_songs(int,int), admin_top_artists(int,int), admin_plays_by_day(int), admin_genre_split(), admin_top_followed(int),
  admin_comments(int), admin_delete_comment(uuid), admin_set_api(text) to authenticated;
