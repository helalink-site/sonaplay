-- Run once in the Supabase SQL editor.
-- 1) invite / share links set from the admin panel
alter table app_config add column if not exists invite_base text;
alter table app_config add column if not exists share_url text;
create or replace function public.admin_set_links(p_invite text, p_share text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if not exists (select 1 from app_config) then insert into app_config (premium_enabled) values (false); end if;
  update app_config set invite_base = nullif(p_invite,''), share_url = nullif(p_share,'') where true;
end $$;
revoke all on function admin_set_links(text,text) from public, anon;
grant execute on function admin_set_links(text,text) to authenticated;

-- 2) username chosen at signup is stored on the profile
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare un text := lower(new.raw_user_meta_data->>'username');
begin
  if un is null or un !~ '^[a-z0-9_]{3,20}$' or exists (select 1 from profiles where lower(username) = un) then un := null; end if;
  insert into profiles (id, display_name, region, username)
  values (new.id, coalesce(new.raw_user_meta_data->>'display_name', new.raw_user_meta_data->>'name', split_part(new.email,'@',1)),
          nullif(new.raw_user_meta_data->>'region',''), un)
  on conflict (id) do update set region = coalesce(profiles.region, excluded.region);
  insert into user_prefs (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;
