-- Core data model (blueprint section 8) plus the gaps identified in review:
-- tool registry, task_events, idempotency keys, approval binding fields,
-- llm_calls for cost-per-successful-task.

-- ---------------------------------------------------------------------------
-- Task state machine
-- ---------------------------------------------------------------------------
create type public.task_status as enum (
    'draft', 'planned', 'queued', 'running',
    'waiting_for_tool', 'waiting_for_approval', 'verifying', 'completed',
    'blocked', 'failed', 'cancelled', 'expired'
);

-- Allowed transitions. Mirrored in packages/core/src/workforce_core/task_states.py;
-- a test asserts both definitions are identical.
create table public.task_status_transitions (
    from_status public.task_status not null,
    to_status   public.task_status not null,
    primary key (from_status, to_status)
);

insert into public.task_status_transitions (from_status, to_status) values
    ('draft', 'planned'), ('draft', 'failed'), ('draft', 'cancelled'),
    ('planned', 'queued'), ('planned', 'blocked'), ('planned', 'failed'), ('planned', 'cancelled'),
    ('queued', 'running'), ('queued', 'cancelled'), ('queued', 'expired'),
    ('running', 'waiting_for_tool'), ('running', 'waiting_for_approval'), ('running', 'verifying'),
    ('running', 'blocked'), ('running', 'failed'), ('running', 'cancelled'),
    ('waiting_for_tool', 'running'), ('waiting_for_tool', 'failed'),
    ('waiting_for_tool', 'cancelled'), ('waiting_for_tool', 'expired'),
    ('waiting_for_approval', 'running'), ('waiting_for_approval', 'failed'),
    ('waiting_for_approval', 'cancelled'), ('waiting_for_approval', 'expired'),
    ('verifying', 'completed'), ('verifying', 'running'), ('verifying', 'failed'),
    ('blocked', 'planned'), ('blocked', 'queued'), ('blocked', 'running'),
    ('blocked', 'failed'), ('blocked', 'cancelled'),
    ('failed', 'queued');  -- safe replay from dead-letter

-- ---------------------------------------------------------------------------
-- Agents and departments
-- ---------------------------------------------------------------------------
create table public.agents (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    department_id   uuid,
    parent_agent_id uuid references public.agents (id),
    name            text not null,
    role            text not null,
    status          text not null default 'sandbox'
                    check (status in ('sandbox', 'active', 'suspended', 'retired')),
    version         integer not null default 1,
    config_json     jsonb not null default '{}'::jsonb,
    model_profile   text not null default 'default',
    max_concurrency integer not null default 1 check (max_concurrency > 0),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table public.departments (
    id               uuid primary key default gen_random_uuid(),
    workspace_id     uuid not null references public.workspaces (id) on delete cascade,
    name             text not null,
    manager_agent_id uuid references public.agents (id),
    policy_id        uuid references public.policies (id),
    created_at       timestamptz not null default now(),
    unique (workspace_id, name)
);

alter table public.agents
    add constraint agents_department_fk
    foreign key (department_id) references public.departments (id);

create table public.agent_versions (
    id                 uuid primary key default gen_random_uuid(),
    agent_id           uuid not null references public.agents (id) on delete cascade,
    version            integer not null,
    config_snapshot    jsonb not null,
    evaluation_summary jsonb,
    created_at         timestamptz not null default now(),
    unique (agent_id, version)
);

create table public.agent_evaluations (
    id                uuid primary key default gen_random_uuid(),
    workspace_id      uuid not null references public.workspaces (id) on delete cascade,
    agent_id          uuid not null references public.agents (id) on delete cascade,
    agent_version     integer not null,
    evaluation_window tstzrange not null,
    success_rate      numeric(5, 4),
    quality_score     numeric(5, 4),
    cost_usd          numeric(12, 6),
    p50_latency_ms    integer,
    sample_size       integer not null,
    created_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Tool registry (global; defined in code, synced by the backend)
-- ---------------------------------------------------------------------------
create table public.tool_definitions (
    name         text primary key,
    version      integer not null default 1,
    category     text not null,
    description  text not null,
    risk_tier    smallint not null check (risk_tier between 0 and 4),
    input_schema jsonb not null,
    enabled      boolean not null default true,
    updated_at   timestamptz not null default now()
);

create table public.tool_connections (
    id                uuid primary key default gen_random_uuid(),
    workspace_id      uuid not null references public.workspaces (id) on delete cascade,
    provider          text not null,
    account_ref       text not null,
    scopes            text[] not null default '{}',
    secret_ref        text,  -- reference into a secrets manager, never the secret itself
    connection_status text not null default 'active'
                      check (connection_status in ('active', 'expired', 'revoked', 'error')),
    created_at        timestamptz not null default now(),
    unique (workspace_id, provider, account_ref)
);

-- ---------------------------------------------------------------------------
-- Tasks
-- ---------------------------------------------------------------------------
create table public.tasks (
    id                uuid primary key default gen_random_uuid(),
    workspace_id      uuid not null references public.workspaces (id) on delete cascade,
    parent_task_id    uuid references public.tasks (id),
    title             text not null check (length(title) between 1 and 200),
    objective         text not null check (length(objective) between 1 and 10000),
    status            public.task_status not null default 'draft',
    priority          smallint not null default 2 check (priority between 0 and 4),
    deadline          timestamptz,
    budget_limit_usd  numeric(12, 4) check (budget_limit_usd is null or budget_limit_usd >= 0),
    success_criteria  jsonb,
    result_summary    text,
    created_by        uuid not null references auth.users (id),
    assigned_agent_id uuid references public.agents (id),
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    completed_at      timestamptz
);

create index tasks_workspace_created_idx on public.tasks (workspace_id, created_at desc);
create index tasks_workspace_status_idx on public.tasks (workspace_id, status);

create table public.task_events (
    id           bigint generated always as identity primary key,
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    task_id      uuid not null references public.tasks (id) on delete cascade,
    from_status  public.task_status,
    to_status    public.task_status not null,
    actor_type   text not null,
    actor_id     text,
    reason       text,
    created_at   timestamptz not null default now()
);

create index task_events_task_idx on public.task_events (task_id, id);

create table public.task_steps (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    task_id      uuid not null references public.tasks (id) on delete cascade,
    sequence     integer not null,
    step_type    text not null,
    description  text,
    input_json   jsonb,
    output_json  jsonb,
    status       text not null default 'pending'
                 check (status in ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    retry_count  integer not null default 0,
    started_at   timestamptz,
    completed_at timestamptz,
    unique (task_id, sequence)
);

create table public.workflow_runs (
    id             uuid primary key default gen_random_uuid(),
    workspace_id   uuid not null references public.workspaces (id) on delete cascade,
    task_id        uuid not null references public.tasks (id) on delete cascade,
    workflow_id    text not null,
    run_id         text,
    run_status     text not null,
    checkpoint_ref text,
    started_at     timestamptz not null default now(),
    completed_at   timestamptz
);

create table public.tool_invocations (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    task_id         uuid not null references public.tasks (id) on delete cascade,
    step_id         uuid references public.task_steps (id),
    agent_id        uuid references public.agents (id),
    tool_name       text not null references public.tool_definitions (name),
    risk_tier       smallint not null check (risk_tier between 0 and 4),
    idempotency_key text not null,
    arguments_hash  text not null,
    arguments_json  jsonb,
    result_ref      text,
    status          text not null default 'pending'
                    check (status in ('pending', 'denied', 'awaiting_approval', 'running',
                                      'succeeded', 'failed')),
    error           text,
    started_at      timestamptz not null default now(),
    completed_at    timestamptz,
    unique (workspace_id, idempotency_key)  -- a retried action cannot run twice
);

-- ---------------------------------------------------------------------------
-- Approvals: bound to the exact action (blueprint section 6)
-- ---------------------------------------------------------------------------
create type public.approval_status as enum (
    'pending', 'approved', 'rejected', 'expired', 'consumed', 'invalidated'
);

create table public.approval_requests (
    id                 uuid primary key default gen_random_uuid(),
    workspace_id       uuid not null references public.workspaces (id) on delete cascade,
    task_id            uuid not null references public.tasks (id) on delete cascade,
    tool_invocation_id uuid references public.tool_invocations (id),
    action             text not null,
    action_payload     jsonb not null,
    action_hash        text not null,  -- sha256 of canonical binding; re-checked at execution
    amount             numeric(14, 4),
    currency           text,
    recipient          text,
    item               text,
    account_ref        text,
    policy_id          uuid not null references public.policies (id),
    policy_version     integer not null,
    risk_tier          smallint not null check (risk_tier between 0 and 4),
    status             public.approval_status not null default 'pending',
    expires_at         timestamptz not null,
    created_at         timestamptz not null default now(),
    decided_at         timestamptz
);

create index approval_requests_pending_idx
    on public.approval_requests (workspace_id, status) where status = 'pending';

create table public.approval_events (
    id            bigint generated always as identity primary key,
    workspace_id  uuid not null references public.workspaces (id) on delete cascade,
    approval_id   uuid not null references public.approval_requests (id) on delete cascade,
    actor_user_id uuid references auth.users (id),
    decision      text not null check (decision in ('approved', 'rejected', 'expired', 'invalidated')),
    reason        text,
    created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Outputs, memory, cost, notifications
-- ---------------------------------------------------------------------------
create table public.artifacts (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    task_id         uuid not null references public.tasks (id) on delete cascade,
    name            text not null,
    storage_uri     text not null,
    file_type       text not null,
    checksum_sha256 text not null,
    size_bytes      bigint not null,
    created_at      timestamptz not null default now()
);

create table public.memories (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    owner_scope  text not null,
    memory_type  text not null,
    content      text,
    content_ref  text,
    sensitivity  text not null default 'normal'
                 check (sensitivity in ('normal', 'private', 'secret_ref')),
    expires_at   timestamptz,
    created_at   timestamptz not null default now()
);

create table public.budgets (
    id               uuid primary key default gen_random_uuid(),
    workspace_id     uuid not null references public.workspaces (id) on delete cascade,
    agent_id         uuid references public.agents (id),
    task_id          uuid references public.tasks (id) on delete cascade,
    spend_limit      numeric(12, 4) not null,
    spent_amount     numeric(12, 4) not null default 0,
    currency         text not null default 'USD',
    created_at       timestamptz not null default now()
);

create table public.llm_calls (
    id                 bigint generated always as identity primary key,
    workspace_id       uuid not null references public.workspaces (id) on delete cascade,
    task_id            uuid references public.tasks (id) on delete cascade,
    agent_id           uuid references public.agents (id),
    model              text not null,
    purpose            text not null,
    input_tokens       integer not null default 0,
    output_tokens      integer not null default 0,
    cache_read_tokens  integer not null default 0,
    cache_write_tokens integer not null default 0,
    cost_usd           numeric(12, 6) not null default 0,
    latency_ms         integer,
    stop_reason        text,
    created_at         timestamptz not null default now()
);

create index llm_calls_task_idx on public.llm_calls (task_id);

create table public.notifications (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    task_id      uuid references public.tasks (id) on delete cascade,
    channel      text not null check (channel in ('in_app', 'email', 'push')),
    status       text not null default 'pending'
                 check (status in ('pending', 'sent', 'failed', 'read')),
    payload      jsonb not null,
    created_at   timestamptz not null default now(),
    sent_at      timestamptz
);
