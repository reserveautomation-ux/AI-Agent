-- Connect-when-needed: a task can pause until the owner connects a service,
-- then resume automatically.

alter table public.tasks
    add column waiting_for_connection text[] not null default '{}';

create index tasks_waiting_connection_idx on public.tasks using gin (waiting_for_connection)
    where status = 'blocked';

-- Called right after a service is connected: resume tasks waiting for it.
create function public.wake_tasks_for_connection(p_workspace uuid, p_connector text)
returns integer
language plpgsql as $$
declare
    n integer;
begin
    perform set_config('app.actor_type', 'system', true);
    perform set_config('app.reason', p_connector || ' connected', true);
    update public.tasks
    set status = 'running',
        waiting_for_connection = array_remove(waiting_for_connection, p_connector),
        run_after = now(), lease_owner = null, lease_expires_at = null
    where workspace_id = p_workspace
      and status = 'blocked'
      and p_connector = any(waiting_for_connection);
    get diagnostics n = row_count;
    return n;
end;
$$;
