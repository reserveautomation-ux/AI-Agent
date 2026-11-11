-- Important-email alerts: remember, per connected inbox, the newest mail already seen,
-- so the owner is alerted once per new important email (never for the old backlog).
create table public.inbox_watch (
    connection_id uuid primary key references public.tool_connections (id) on delete cascade,
    workspace_id  uuid not null references public.workspaces (id) on delete cascade,
    enabled       boolean not null default true,
    last_seen_ms  bigint not null,
    checked_at    timestamptz not null default now()
);

alter table public.inbox_watch enable row level security;
revoke all on public.inbox_watch from anon;
revoke insert, update, delete, truncate on public.inbox_watch from authenticated;
create policy inbox_watch_member_read on public.inbox_watch
    for select to authenticated using (public.is_workspace_member(workspace_id));
