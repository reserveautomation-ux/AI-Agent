-- Long-term memory for the workspace and for each agent.
--
-- scope 'workspace': shared by every agent (your preferences, contacts, facts).
-- scope 'agent':     one agent's own learnings ("Swiggy search works best with...").
--
-- Search uses Postgres full-text ('simple' config, so it works for Hindi and
-- other Indian languages without English stemming) plus trigram similarity for
-- typos and partial words. No external embedding service needed.
--
-- Prompt-injection guard: an agent can only write *untrusted* memories; only
-- you can create 'instruction' memories (standing orders agents must follow).

create extension if not exists pg_trgm;

alter table public.memories
    drop constraint if exists memories_sensitivity_check;

alter table public.memories
    add column agent_id     uuid references public.agents (id),
    add column source_type  text not null default 'user'
                            check (source_type in ('user', 'agent', 'system')),
    add column source_ref   text,          -- e.g. task id the memory came from
    add column trusted      boolean not null default false,
    add column importance   smallint not null default 3 check (importance between 1 and 5),
    add column pinned       boolean not null default false,
    add column use_count    integer not null default 0,
    add column last_used_at timestamptz,
    add column updated_at   timestamptz not null default now(),
    add column search       tsvector
        generated always as (to_tsvector('simple', coalesce(content, ''))) stored;

alter table public.memories
    alter column content set not null,
    add constraint memories_content_length check (length(content) between 1 and 4000),
    add constraint memories_scope_check check (
        (owner_scope = 'workspace' and agent_id is null)
        or (owner_scope = 'agent' and agent_id is not null)
    ),
    add constraint memories_type_check check (
        memory_type in ('preference', 'fact', 'contact', 'instruction', 'learning', 'episode')
    ),
    add constraint memories_sensitivity_check check (sensitivity in ('normal', 'private')),
    add constraint memories_instruction_from_user check (
        memory_type <> 'instruction' or source_type = 'user'
    ),
    add constraint memories_agent_untrusted check (source_type <> 'agent' or not trusted);

create index memories_search_idx on public.memories using gin (search);
create index memories_trgm_idx on public.memories using gin (content gin_trgm_ops);
create index memories_workspace_scope_idx on public.memories (workspace_id, owner_scope, agent_id);

create trigger memories_touch_updated_at
    before update on public.memories
    for each row execute function public.touch_updated_at();

-- Ranked recall: text match + fuzzy match, boosted by importance, pinning and
-- recency of use. Returns workspace memories plus the given agent's own.
create function public.recall_memories(
    p_workspace uuid,
    p_query text,
    p_agent uuid default null,
    p_limit integer default 10,
    p_include_pinned boolean default true  -- agents always see pinned memories
) returns table (
    id uuid, owner_scope text, agent_id uuid, memory_type text, content text,
    trusted boolean, importance smallint, pinned boolean, created_at timestamptz,
    score real
)
language sql stable as $$
    with q as (select websearch_to_tsquery('simple', coalesce(p_query, '')) as tsq)
    select m.id, m.owner_scope, m.agent_id, m.memory_type, m.content, m.trusted,
           m.importance, m.pinned, m.created_at,
           (
               ts_rank(m.search, q.tsq) * 2
               + similarity(m.content, coalesce(p_query, ''))
               + m.importance * 0.05
               + case when m.pinned then 0.5 else 0 end
               + case when m.last_used_at > now() - interval '30 days' then 0.1 else 0 end
           )::real as score
    from public.memories m, q
    where m.workspace_id = p_workspace
      and (m.expires_at is null or m.expires_at > now())
      and (m.owner_scope = 'workspace' or m.agent_id = p_agent)
      and (
          coalesce(p_query, '') = ''
          or m.search @@ q.tsq
          or similarity(m.content, p_query) > 0.15
          or (p_include_pinned and m.pinned)
      )
    order by score desc, m.created_at desc
    limit greatest(1, least(p_limit, 50))
$$;
