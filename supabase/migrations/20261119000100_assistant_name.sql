-- Each person names their own assistant ("Maya", "Jarvis"...). Voices are chosen per device.
alter table public.workspace_members
    add column assistant_name text not null default 'AI Assistant'
        check (length(trim(assistant_name)) between 1 and 40);
