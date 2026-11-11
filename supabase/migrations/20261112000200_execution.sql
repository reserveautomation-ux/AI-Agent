-- Phase 2: durable background execution.
--
-- Workers claim tasks with a time-limited lease (FOR UPDATE SKIP LOCKED). A
-- worker that crashes simply stops renewing its lease; another worker picks the
-- task up and resumes from the last checkpointed step. All progress lives in
-- Postgres, so closing the app, restarting workers or redeploying loses nothing.

alter table public.tasks
    add column lease_owner      text,
    add column lease_expires_at timestamptz,
    add column run_after        timestamptz not null default now(),
    add column attempts         integer not null default 0,
    add column plan             jsonb,
    add column verification     jsonb,
    add column reply_language   text,
    add column rework_count     integer not null default 0,
    add column cost_usd         numeric(12, 6) not null default 0,
    add column last_error       text;

create index tasks_claimable_idx on public.tasks (run_after, priority, created_at)
    where status in ('draft', 'planned', 'queued', 'running', 'verifying');

-- Verified work that needs your approval before an external action runs.
insert into public.task_status_transitions (from_status, to_status)
values ('verifying', 'waiting_for_approval')
on conflict do nothing;

alter table public.task_steps
    add column agent_id uuid references public.agents (id),
    add column title    text,
    add column error    text;

-- Small artifacts are stored inline for now; large files move to Supabase
-- Storage later (storage_uri then points there and content stays null).
alter table public.artifacts
    add column step_id uuid references public.task_steps (id),
    add column content bytea,
    add column preview text;

alter table public.tool_invocations
    add column result_json jsonb;
