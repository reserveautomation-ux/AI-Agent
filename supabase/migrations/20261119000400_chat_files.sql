-- Photos and PDFs people attach in chat, so the assistant can read them.
create table public.chat_files (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    name         text not null check (length(name) between 1 and 200),
    media_type   text not null check (media_type in
                   ('image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf')),
    size_bytes   integer not null check (size_bytes between 1 and 10485760),
    content      bytea not null,
    created_at   timestamptz not null default now()
);

create index chat_files_user_idx on public.chat_files (user_id, created_at desc);

alter table public.chat_files enable row level security;
revoke all on public.chat_files from anon;
revoke insert, update, delete, truncate on public.chat_files from authenticated;
create policy chat_files_own_read on public.chat_files
    for select to authenticated using (user_id = auth.uid());
