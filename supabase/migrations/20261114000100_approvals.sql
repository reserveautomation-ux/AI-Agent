-- Approval centre: owner edits, expiry, and handing decided tasks back to workers.

alter table public.approval_events
    drop constraint approval_events_decision_check,
    add constraint approval_events_decision_check
        check (decision in ('approved', 'rejected', 'expired', 'invalidated', 'edited'));

-- Expire unanswered approvals and wake tasks that have nothing left waiting.
-- Called by workers on every poll and by the API before listing approvals.
create function public.expire_approvals() returns integer
language plpgsql as $$
declare
    n integer;
begin
    with expired as (
        update public.approval_requests
        set status = 'expired', decided_at = now()
        where status = 'pending' and expires_at <= now()
        returning id, workspace_id
    ), logged as (
        insert into public.approval_events (workspace_id, approval_id, decision, reason)
        select workspace_id, id, 'expired', 'no answer before it expired' from expired
        returning 1
    )
    select count(*) into n from logged;

    perform set_config('app.actor_type', 'system', true);
    perform set_config('app.reason', 'approvals answered or expired', true);
    update public.tasks t
    set status = 'running', run_after = now()
    where t.status = 'waiting_for_approval'
      and not exists (
          select 1 from public.approval_requests a
          where a.task_id = t.id and a.status = 'pending'
      );
    return n;
end;
$$;
