-- Run once in the Supabase SQL editor: likes, loves and replies on notifications.
create table if not exists notif_reactions (
  thread text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('like','love')),
  primary key (thread, user_id)
);
create table if not exists notif_comments (
  id uuid primary key default gen_random_uuid(),
  thread text not null,
  parent_id uuid references notif_comments(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text,
  body text not null check (char_length(body) between 1 and 500),
  created_at timestamptz not null default now()
);
create index if not exists notif_comments_thread_idx on notif_comments (thread, created_at);
alter table notif_reactions enable row level security;
alter table notif_comments enable row level security;
drop policy if exists "react read" on notif_reactions;   create policy "react read"   on notif_reactions for select to authenticated using (true);
drop policy if exists "react write" on notif_reactions;  create policy "react write"  on notif_reactions for insert to authenticated with check (user_id = auth.uid());
drop policy if exists "react change" on notif_reactions; create policy "react change" on notif_reactions for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "react delete" on notif_reactions; create policy "react delete" on notif_reactions for delete to authenticated using (user_id = auth.uid());
drop policy if exists "comment read" on notif_comments;   create policy "comment read"   on notif_comments for select to authenticated using (true);
drop policy if exists "comment write" on notif_comments;  create policy "comment write"  on notif_comments for insert to authenticated with check (user_id = auth.uid());
drop policy if exists "comment delete" on notif_comments; create policy "comment delete" on notif_comments for delete to authenticated using (user_id = auth.uid());
grant select, insert, update, delete on notif_reactions to authenticated;
grant select, insert, delete on notif_comments to authenticated;
