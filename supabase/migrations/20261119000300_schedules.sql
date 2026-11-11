-- Reminders and repeating jobs ("remind me at 6pm", "every Monday 9am summarise my inbox").
-- kind 'reminder': notify the person at that time. kind 'task': the workforce does the job.
create table public.schedules (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    user_id         uuid not null references auth.users (id) on delete cascade,
    conversation_id uuid references public.conversations (id) on delete set null,
    kind            text not null check (kind in ('reminder', 'task')),
    title           text not null check (length(title) between 1 and 120),
    what            text not null check (length(what) between 1 and 4000),
    repeat          text not null default 'none'
                    check (repeat in ('none', 'daily', 'weekdays', 'weekly', 'monthly')),
    timezone        text not null default 'Asia/Kolkata',
    local_time      text not null,  -- wall-clock HH:MM it should keep for repeats
    next_run_at     timestamptz,
    active          boolean not null default true,
    runs            integer not null default 0,
    last_run_at     timestamptz,
    created_at      timestamptz not null default now()
);

create index schedules_due_idx on public.schedules (next_run_at) where active;
create index schedules_user_idx on public.schedules (user_id, created_at desc);

alter table public.schedules enable row level security;
revoke all on public.schedules from anon;
revoke insert, update, delete, truncate on public.schedules from authenticated;
create policy schedules_own_read on public.schedules
    for select to authenticated using (user_id = auth.uid());
