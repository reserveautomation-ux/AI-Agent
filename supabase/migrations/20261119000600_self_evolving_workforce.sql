-- Self-evolving workforce: every night the worker scores agents on real outcomes, clones
-- strong ones (clones inherit lessons and must pass a supervised trial), suspends then
-- retires weak ones, and tells the owner what changed. The owner can switch it off.
alter table public.workspaces
    add column auto_workforce boolean not null default true,
    add column evolved_at     timestamptz;
