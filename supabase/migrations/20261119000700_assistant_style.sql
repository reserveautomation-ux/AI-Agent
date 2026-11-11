-- How each person's assistant talks: its personality and how long its replies are.
alter table public.workspace_members
    add column assistant_style text not null default 'friendly'
        check (assistant_style in ('friendly', 'professional', 'hinglish', 'playful')),
    add column reply_length text not null default 'short'
        check (reply_length in ('short', 'detailed'));
