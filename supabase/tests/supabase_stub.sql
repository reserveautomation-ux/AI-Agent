-- Minimal stand-in for the parts of a Supabase database our migrations rely on
-- (auth schema, auth.uid(), and the anon/authenticated/service_role roles).
-- Used ONLY for running tests against a plain Postgres. Never apply this to a
-- real Supabase project; it already has these objects.

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin bypassrls;
    end if;
end;
$$;

create schema if not exists auth;

create table if not exists auth.users (
    id                 uuid primary key,
    email              text,
    raw_user_meta_data jsonb default '{}'::jsonb,
    created_at         timestamptz default now()
);

create or replace function auth.uid() returns uuid
language sql stable as $$
    select coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    )::uuid
$$;

grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;

-- Supabase grants table privileges to these roles by default; RLS restricts them.
alter default privileges in schema public
    grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public
    grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public
    grant execute on functions to anon, authenticated, service_role;
