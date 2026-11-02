-- Run after 001 and 002. Adds: editable hero image, admin config saving, broadcast history.
alter table app_config add column if not exists hero_image_url text;
alter table app_config add column if not exists premium_enabled boolean default false;
alter table app_config add column if not exists dj_mixes_enabled boolean default false;

create or replace function public.admin_set_config(p_hero text, p_premium boolean, p_dj boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  if not exists (select 1 from app_config) then insert into app_config (premium_enabled) values (false); end if;
  update app_config set hero_image_url = nullif(p_hero,''), premium_enabled = p_premium, dj_mixes_enabled = p_dj where true;
end $$;
revoke all on function admin_set_config(text,boolean,boolean) from public, anon;
grant execute on function admin_set_config(text,boolean,boolean) to authenticated;

drop policy if exists "admin read broadcasts" on broadcasts;
create policy "admin read broadcasts" on broadcasts for select to authenticated using (is_admin());
grant select on broadcasts to authenticated;
