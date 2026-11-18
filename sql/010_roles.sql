-- 010_roles.sql: start again, then create the three roles.
--
-- Run by the setup command as the admin role: postgres in Docker, or the
-- owner role a hosted service gives you. Nothing here needs a superuser.

-- Start again -----------------------------------------------------------------
-- Dropping the schemas removes every table, function and grant inside them.

drop schema if exists mcp cascade;
drop schema if exists insurance cascade;

-- Roles belong to the whole PostgreSQL server, not to one database, so they
-- survive the schemas being dropped. Drop them too, if they exist.
do $$
begin
    if exists (select from pg_roles where rolname = 'mcp_reader') then
        -- The one grant left after the schemas are gone: CONNECT on this database.
        execute format('revoke connect on database %I from mcp_reader', current_database());
        drop role mcp_reader;
    end if;

    if exists (select from pg_roles where rolname = 'mcp_owner') then
        -- DROP OWNED also removes the role's default privileges (see 030_permissions.sql).
        drop owned by mcp_owner;
        drop role mcp_owner;
    end if;

    if exists (select from pg_roles where rolname = 'insurance_owner') then
        drop owned by insurance_owner;
        drop role insurance_owner;
    end if;
end
$$;

-- The roles -------------------------------------------------------------------

-- Owns the insurance schema: the tables, the helper functions and the audit log.
-- NOLOGIN: nobody can connect as it.
create role insurance_owner nologin;

-- Owns the mcp schema and its functions. Its functions run with its rights
-- (SECURITY DEFINER), so it gets only what they need: SELECT on the tables
-- and INSERT on the audit log. A bug in a function can read, but never change data.
create role mcp_owner nologin;

-- The only role the MCP server connects as. It can run the granted mcp
-- functions and nothing else. Its password is set by the setup command, from
-- .env, so it's never written in a file.
create role mcp_reader login;

-- Limits, set on the role so the server can't forget them.
-- A slow query is canceled after 5 seconds. Any session could switch this off
-- with SET, but the MCP server never does.
alter role mcp_reader set statement_timeout = '5s';
-- At most 10 connections at once, whatever a session does.
alter role mcp_reader connection limit 10;

-- Let the admin role act as the two owners, so it can create objects that
-- belong to them (and drop them next time). The owners still can't log in.
grant insurance_owner, mcp_owner to current_user;

-- What can mcp_reader do at this point?
-- It can log in and connect, because PUBLIC still has its default CONNECT and
-- TEMPORARY rights (030_permissions.sql takes those away). It can run plain SQL,
-- read the system catalogs and create temporary tables, but there's no data
-- to see: the insurance and mcp schemas don't exist yet.
-- New sessions get a 5-second statement timeout, and at most 10 connections.
