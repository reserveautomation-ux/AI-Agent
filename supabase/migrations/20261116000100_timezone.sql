-- Calendar events and "next Friday" need the owner's time zone. Default to India
-- time; owners elsewhere change it in Settings.
alter table public.workspaces alter column timezone set default 'Asia/Kolkata';
update public.workspaces set timezone = 'Asia/Kolkata' where timezone = 'UTC';
