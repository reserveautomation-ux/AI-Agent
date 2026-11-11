-- Chat with your personal assistant.
--
-- Each person has private conversations. The assistant answers quick things
-- itself and hands real work (sending, building, booking, research) to the
-- workforce as tasks; when a task finishes, needs approval or waits for a
-- connection, a message about it appears in the conversation that started it.

create table public.conversations (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    title        text not null default 'New chat' check (length(title) between 1 and 120),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    archived_at  timestamptz
);

create index conversations_user_idx
    on public.conversations (user_id, updated_at desc) where archived_at is null;

create table public.chat_messages (
    id              uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations (id) on delete cascade,
    workspace_id    uuid not null references public.workspaces (id) on delete cascade,
    role            text not null check (role in ('user', 'assistant')),
    content         text not null check (length(content) <= 40000),
    via             text not null default 'text' check (via in ('text', 'voice')),
    -- kind: 'reply' | 'task_update'; task_id/status for task updates; tasks/memories started by a reply
    meta            jsonb not null default '{}',
    created_at      timestamptz not null default now()
);

create index chat_messages_conversation_idx on public.chat_messages (conversation_id, created_at);
create index chat_messages_rate_idx on public.chat_messages (workspace_id, created_at desc)
    where role = 'user';

alter table public.tasks
    add column conversation_id uuid references public.conversations (id) on delete set null;

create index tasks_conversation_idx on public.tasks (conversation_id)
    where conversation_id is not null;

alter table public.conversations enable row level security;
alter table public.chat_messages enable row level security;
revoke all on public.conversations, public.chat_messages from anon;
revoke insert, update, delete, truncate on public.conversations, public.chat_messages
    from authenticated;

create policy conversations_own_read on public.conversations
    for select to authenticated using (user_id = auth.uid());

create policy chat_messages_own_read on public.chat_messages
    for select to authenticated using (
        exists (select 1 from public.conversations c
                where c.id = conversation_id and c.user_id = auth.uid())
    );

-- Post task progress into the conversation that started the task.
create function public.chat_task_update() returns trigger
language plpgsql security definer set search_path = public as $$
declare
    v_text text;
    v_pending integer;
begin
    if new.conversation_id is null or new.status is not distinct from old.status then
        return new;
    end if;
    if new.status = 'completed' then
        v_text := coalesce(nullif(new.result_summary, ''), 'Done.');
    elsif new.status = 'failed' then
        v_text := 'I couldn''t finish "' || new.title || '". '
                  || coalesce(nullif(new.result_summary, ''), new.last_error, '');
    elsif new.status = 'waiting_for_approval' then
        select count(*) into v_pending from public.approval_requests
         where task_id = new.id and status = 'pending';
        v_text := '"' || new.title || '" is ready for your approval ('
                  || v_pending || case when v_pending = 1 then ' item' else ' items' end
                  || '). Nothing is sent, booked or paid until you approve.';
    elsif new.status = 'blocked' then
        v_text := coalesce(nullif(new.result_summary, ''), '"' || new.title || '" needs your input.');
    else
        return new;
    end if;

    insert into public.chat_messages (conversation_id, workspace_id, role, content, meta)
    values (new.conversation_id, new.workspace_id, 'assistant', left(trim(v_text), 40000),
            jsonb_build_object('kind', 'task_update', 'task_id', new.id, 'status', new.status,
                               'waiting_for_connection', to_jsonb(new.waiting_for_connection)));
    update public.conversations set updated_at = now() where id = new.conversation_id;
    return new;
end;
$$;

create trigger tasks_chat_update
    after update of status on public.tasks
    for each row execute function public.chat_task_update();
