-- Identity and tenancy: workspaces, members, and first-login bootstrap.
-- Every business record in later migrations is scoped to a workspace,
-- even though v1 is a single-owner private system.

create extension if not exists pgcrypto;

create table public.workspaces (
    id            uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users (id) on delete restrict,
    name          text not null,
    timezone      text not null default 'UTC',
    plan          text not null default 'private',
    status        text not null default 'active'
                  check (status in ('active', 'suspended', 'closed')),
    kill_switch   boolean not null default false,  -- emergency stop for all agent activity
    created_at    timestamptz not null default now()
);

create table public.workspace_members (
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    role         text not null default 'member'
                 check (role in ('owner', 'admin', 'member', 'viewer')),
    status       text not null default 'active'
                 check (status in ('active', 'disabled')),
    created_at   timestamptz not null default now(),
    primary key (workspace_id, user_id)
);

create index workspace_members_user_idx on public.workspace_members (user_id);

-- Policies are versioned; approvals bind to a specific policy version.
create table public.policies (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    name         text not null,
    version      integer not null default 1 check (version > 0),
    rules        jsonb not null,
    created_at   timestamptz not null default now(),
    unique (workspace_id, name, version)
);

-- Default risk-tier rules (see docs/ARCHITECTURE.md, "Risk tiers").
create function public.default_policy_rules() returns jsonb
language sql immutable as $$
    select jsonb_build_object(
        'tiers', jsonb_build_object(
            '0', 'allow',                   -- read
            '1', 'allow',                   -- reversible internal write
            '2', 'require_approval',        -- external communication / commitment
            '3', 'require_owner_approval',  -- financial / high impact
            '4', 'deny'                     -- security / destructive
        ),
        'approval_ttl_seconds', 86400,
        'max_task_budget_usd', 5
    )
$$;

-- On first sign-up, give the user a personal workspace, owner membership and
-- the default policy. Disable public sign-ups in Supabase Auth settings so only
-- the owner (and people they invite) can get in.
create function public.handle_new_auth_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare
    ws_id uuid;
begin
    insert into public.workspaces (owner_user_id, name)
    values (new.id, coalesce(new.email, 'My') || ' workspace')
    returning id into ws_id;

    insert into public.workspace_members (workspace_id, user_id, role)
    values (ws_id, new.id, 'owner');

    insert into public.policies (workspace_id, name, version, rules)
    values (ws_id, 'default', 1, public.default_policy_rules());

    return new;
end;
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_auth_user();

-- RLS helpers. SECURITY DEFINER so policies can consult membership without
-- recursing into workspace_members' own policies.
create function public.is_workspace_member(ws uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (
        select 1 from public.workspace_members m
        where m.workspace_id = ws and m.user_id = auth.uid() and m.status = 'active'
    )
$$;

create function public.is_workspace_admin(ws uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (
        select 1 from public.workspace_members m
        where m.workspace_id = ws and m.user_id = auth.uid() and m.status = 'active'
          and m.role in ('owner', 'admin')
    )
$$;
