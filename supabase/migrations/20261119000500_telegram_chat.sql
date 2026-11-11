-- Chat with your assistant from Telegram, through your own bot.
-- The owner links their Telegram chat once (t.me/<bot>?start=<code>); only that chat can talk
-- to the assistant. Telegram proves each webhook call with a secret header (stored hashed).
create table public.telegram_links (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    user_id         uuid not null references auth.users (id) on delete cascade,
    connection_id   uuid not null references public.tool_connections (id) on delete cascade,
    secret_hash     text not null,
    link_code       text,
    code_expires_at timestamptz,
    chat_id         bigint,
    conversation_id uuid references public.conversations (id) on delete set null,
    linked_at       timestamptz,
    created_at      timestamptz not null default now(),
    unique (user_id, workspace_id)
);

alter table public.telegram_links enable row level security;
revoke all on public.telegram_links from anon;
revoke insert, update, delete, truncate on public.telegram_links from authenticated;
create policy telegram_links_own_read on public.telegram_links
    for select to authenticated using (user_id = auth.uid());
