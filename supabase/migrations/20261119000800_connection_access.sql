-- Read-only vs can-act per connection: a read-only connection can be read (search mail,
-- check the calendar) but the workforce can't send, create or change anything with it.
alter table public.tool_connections
    add column can_act boolean not null default true;
