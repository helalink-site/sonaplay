-- Run once in the Supabase SQL editor: player backgrounds that the admin uploads.
insert into storage.buckets (id, name, public) values ('backgrounds', 'backgrounds', true) on conflict (id) do nothing;
create table if not exists backgrounds (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 40),
  path text not null,
  active boolean not null default true,
  sort int not null default 0,
  created_at timestamptz not null default now()
);
alter table backgrounds enable row level security;
drop policy if exists "bg read" on backgrounds;   create policy "bg read"  on backgrounds for select to anon, authenticated using (active or is_admin());
drop policy if exists "bg admin" on backgrounds;  create policy "bg admin" on backgrounds for all to authenticated using (is_admin()) with check (is_admin());
grant select on backgrounds to anon, authenticated;
grant insert, update, delete on backgrounds to authenticated;
drop policy if exists "bg files read" on storage.objects;  create policy "bg files read"  on storage.objects for select using (bucket_id = 'backgrounds');
drop policy if exists "bg files add" on storage.objects;   create policy "bg files add"   on storage.objects for insert to authenticated with check (bucket_id = 'backgrounds' and is_admin());
drop policy if exists "bg files drop" on storage.objects;  create policy "bg files drop"  on storage.objects for delete to authenticated using (bucket_id = 'backgrounds' and is_admin());
