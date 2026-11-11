-- Row-level security.
--
-- The browser holds the public anon key, so anything reachable through the
-- Supabase Data API must be locked down here. Model:
--   * anon: no access to anything.
--   * authenticated: read-only access to rows in workspaces they belong to.
--   * All writes go through the FastAPI backend, which enforces the task state
--     machine, policy checks and audit logging.

do $$
declare
    t text;
begin
    foreach t in array array[
        'workspaces', 'workspace_members', 'policies', 'agents', 'departments',
        'agent_versions', 'agent_evaluations', 'tool_definitions', 'tool_connections',
        'tasks', 'task_events', 'task_steps', 'workflow_runs', 'tool_invocations',
        'approval_requests', 'approval_events', 'artifacts', 'memories', 'budgets',
        'llm_calls', 'notifications', 'audit_events', 'task_status_transitions'
    ] loop
        execute format('alter table public.%I enable row level security', t);
        execute format('revoke all on public.%I from anon', t);
        execute format('revoke insert, update, delete, truncate on public.%I from authenticated', t);
    end loop;
end;
$$;

-- Read access for workspace members on workspace-scoped tables.
do $$
declare
    t text;
begin
    foreach t in array array[
        'policies', 'agents', 'departments', 'agent_evaluations', 'tasks',
        'task_events', 'task_steps', 'workflow_runs', 'tool_invocations',
        'approval_requests', 'approval_events', 'artifacts', 'memories', 'budgets',
        'llm_calls'
    ] loop
        execute format(
            'create policy %I on public.%I for select to authenticated
             using (public.is_workspace_member(workspace_id))',
            t || '_member_read', t
        );
    end loop;
end;
$$;

create policy workspaces_member_read on public.workspaces
    for select to authenticated using (public.is_workspace_member(id));

create policy workspace_members_member_read on public.workspace_members
    for select to authenticated using (public.is_workspace_member(workspace_id));

create policy agent_versions_member_read on public.agent_versions
    for select to authenticated using (
        exists (select 1 from public.agents a
                where a.id = agent_id and public.is_workspace_member(a.workspace_id))
    );

-- Sensitive tables: owners/admins only.
create policy tool_connections_admin_read on public.tool_connections
    for select to authenticated using (public.is_workspace_admin(workspace_id));

create policy audit_events_admin_read on public.audit_events
    for select to authenticated using (public.is_workspace_admin(workspace_id));

-- Users see only their own notifications.
create policy notifications_own_read on public.notifications
    for select to authenticated
    using (user_id = auth.uid() and public.is_workspace_member(workspace_id));

-- Global reference data.
create policy tool_definitions_read on public.tool_definitions
    for select to authenticated using (true);

create policy task_status_transitions_read on public.task_status_transitions
    for select to authenticated using (true);
