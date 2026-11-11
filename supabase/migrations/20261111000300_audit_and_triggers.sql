-- Append-only audit log and task-state enforcement.
--
-- Actor context: the backend sets these transaction-local settings before
-- writing, so database triggers can attribute changes:
--   select set_config('app.actor_type', 'user', true);
--   select set_config('app.actor_id',   '<uuid>', true);
--   select set_config('app.reason',     'optional text', true);

create table public.audit_events (
    id           bigint generated always as identity primary key,
    workspace_id uuid not null references public.workspaces (id) on delete restrict,
    actor_type   text not null check (actor_type in ('user', 'agent', 'worker', 'system')),
    actor_id     text,
    action       text not null,
    target_type  text,
    target_id    text,
    event_json   jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null default now()
);

create index audit_events_workspace_idx on public.audit_events (workspace_id, id desc);
create index audit_events_target_idx on public.audit_events (target_type, target_id);

create function public.reject_mutation() returns trigger
language plpgsql as $$
begin
    raise exception '% is append-only: % is not allowed', tg_table_name, tg_op
        using errcode = 'insufficient_privilege';
end;
$$;

-- Applies to every role, including the backend's own connection.
create trigger audit_events_append_only
    before update or delete on public.audit_events
    for each row execute function public.reject_mutation();

create trigger task_events_append_only
    before update or delete on public.task_events
    for each row execute function public.reject_mutation();

create trigger approval_events_append_only
    before update or delete on public.approval_events
    for each row execute function public.reject_mutation();

-- Truncate bypasses row triggers; block it too.
create trigger audit_events_no_truncate
    before truncate on public.audit_events
    for each statement execute function public.reject_mutation();

-- ---------------------------------------------------------------------------
-- Task status: validate transitions and record every one in task_events.
-- ---------------------------------------------------------------------------
create function public.task_status_guard() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        if new.status <> 'draft' then
            raise exception 'tasks must be created in draft status, got %', new.status
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    new.updated_at := now();

    if new.status is distinct from old.status then
        if not exists (
            select 1 from public.task_status_transitions t
            where t.from_status = old.status and t.to_status = new.status
        ) then
            raise exception 'invalid task status transition % -> %', old.status, new.status
                using errcode = 'check_violation';
        end if;

        if new.status = 'completed' then
            new.completed_at := now();
        end if;
    end if;

    return new;
end;
$$;

create trigger tasks_status_guard
    before insert or update on public.tasks
    for each row execute function public.task_status_guard();

create function public.task_status_log() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' or new.status is distinct from old.status then
        insert into public.task_events
            (workspace_id, task_id, from_status, to_status, actor_type, actor_id, reason)
        values (
            new.workspace_id,
            new.id,
            case when tg_op = 'UPDATE' then old.status end,
            new.status,
            coalesce(nullif(current_setting('app.actor_type', true), ''), 'system'),
            nullif(current_setting('app.actor_id', true), ''),
            nullif(current_setting('app.reason', true), '')
        );
    end if;
    return null;
end;
$$;

create trigger tasks_status_log
    after insert or update of status on public.tasks
    for each row execute function public.task_status_log();

-- Agents can never be deleted (retire them instead) so history stays intact.
create trigger agents_no_delete
    before delete on public.agents
    for each row execute function public.reject_mutation();

create function public.touch_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger agents_touch_updated_at
    before update on public.agents
    for each row execute function public.touch_updated_at();
