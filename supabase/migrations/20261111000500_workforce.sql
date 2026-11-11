-- Workforce hierarchy support: template keys, clone lineage, per-agent tool allowlists.

alter table public.departments
    add column key text;

create unique index departments_workspace_key_idx
    on public.departments (workspace_id, key) where key is not null;

alter table public.agents
    add column template_key  text,
    add column lineage_id    uuid,          -- the original agent a clone family descends from
    add column cloned_from   uuid references public.agents (id),
    add column allowed_tools text[] not null default '{}',
    add column retired_at    timestamptz;

create index agents_workspace_lineage_idx on public.agents (workspace_id, lineage_id);

-- Root agents are their own lineage.
create function public.agents_set_lineage() returns trigger
language plpgsql as $$
begin
    if new.lineage_id is null then
        new.lineage_id := new.id;
    end if;
    return new;
end;
$$;

create trigger agents_set_lineage
    before insert on public.agents
    for each row execute function public.agents_set_lineage();

-- Retired is final: a retired agent can never be reactivated, and clones may
-- never widen the tool allowlist they inherited.
create function public.agents_lifecycle_guard() returns trigger
language plpgsql as $$
begin
    if old.status = 'retired' and new.status <> 'retired' then
        raise exception 'retired agents cannot be reactivated' using errcode = 'check_violation';
    end if;
    if new.status = 'retired' and old.status <> 'retired' then
        new.retired_at := now();
    end if;
    if not (new.allowed_tools <@ old.allowed_tools) then
        raise exception 'agent tool permissions cannot be widened in place; create a new version'
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger agents_lifecycle_guard
    before update on public.agents
    for each row execute function public.agents_lifecycle_guard();

create function public.agents_clone_guard() returns trigger
language plpgsql as $$
declare
    parent_tools text[];
begin
    if new.cloned_from is not null then
        select allowed_tools into parent_tools from public.agents where id = new.cloned_from;
        if not (new.allowed_tools <@ parent_tools) then
            raise exception 'a clone cannot have more tools than its source'
                using errcode = 'check_violation';
        end if;
        if new.status <> 'sandbox' then
            raise exception 'clones must start in sandbox' using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

create trigger agents_clone_guard
    before insert on public.agents
    for each row execute function public.agents_clone_guard();
