-- Connected accounts (Gmail first). OAuth tokens are encrypted by the backend
-- (AES-GCM, key held only by the API and worker) before they reach the
-- database; this table never sees a plaintext token.

create table public.connection_secrets (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    ciphertext   bytea not null,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

alter table public.connection_secrets enable row level security;
revoke all on public.connection_secrets from anon, authenticated;
-- No policies: browsers and apps can never read secrets, even encrypted.

alter table public.tool_connections
    add column display_name text,
    add column connected_by uuid references auth.users (id),
    add column last_used_at timestamptz,
    add column last_error   text,
    add column updated_at   timestamptz not null default now();

alter table public.tool_connections
    alter column secret_ref type uuid using nullif(secret_ref, '')::uuid,
    add constraint tool_connections_secret_fk
    foreign key (secret_ref) references public.connection_secrets (id) on delete set null;

-- Short-lived, single-use OAuth "state" (CSRF protection) + PKCE verifier.
create table public.oauth_states (
    state         text primary key,
    workspace_id  uuid not null references public.workspaces (id) on delete cascade,
    user_id       uuid not null references auth.users (id) on delete cascade,
    provider      text not null,
    code_verifier text not null,
    redirect_to   text not null,
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null default now() + interval '10 minutes'
);

alter table public.oauth_states enable row level security;
revoke all on public.oauth_states from anon, authenticated;
