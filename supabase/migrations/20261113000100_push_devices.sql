-- Phones that receive push notifications (Expo push tokens).

create table public.push_devices (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    token        text not null unique check (length(token) between 10 and 300),
    platform     text not null check (platform in ('ios', 'android', 'web')),
    device_name  text,
    created_at   timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    disabled_at  timestamptz          -- set when Expo reports the token is no longer valid
);

create index push_devices_user_idx on public.push_devices (user_id) where disabled_at is null;

alter table public.push_devices enable row level security;
revoke all on public.push_devices from anon;
revoke insert, update, delete, truncate on public.push_devices from authenticated;

create policy push_devices_own_read on public.push_devices
    for select to authenticated using (user_id = auth.uid());

-- One notification per task event (prevents duplicates when work is resumed).
alter table public.notifications
    add column event_key text;

create unique index notifications_event_key_idx
    on public.notifications (user_id, event_key) where event_key is not null;
