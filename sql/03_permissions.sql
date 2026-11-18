-- 03_permissions.sql: take away PostgreSQL's defaults, then grant the minimum.
--
-- PostgreSQL has no DENY. A role can do what it, or PUBLIC, has been granted.
-- PUBLIC is a built-in group every role belongs to, and it gets some rights by
-- default. So locking down means two things: remove the defaults from PUBLIC,
-- and grant mcp_reader almost nothing.

-- The defaults ------------------------------------------------------------------

-- Every role may connect to every database and create temporary tables in it.
-- GRANT ... ON DATABASE needs the database's name, which differs between hosts
-- (insurance locally, neondb on Neon), so we look it up.
do $$
begin
    execute format('revoke connect, temporary on database %I from public', current_database());
    execute format('grant connect on database %I to mcp_reader', current_database());
end
$$;

-- Already off since PostgreSQL 15. Revoked anyway, so the script says it out loud.
revoke create on schema public from public;

-- The big gotcha: every new function is callable by PUBLIC, unless you say otherwise.
-- Without these two lines, any function we add would be callable by mcp_reader
-- without anyone granting it. They only cover functions created by these two
-- roles, so the setup creates every function as one of them.
alter default privileges for role insurance_owner revoke execute on functions from public;
alter default privileges for role mcp_owner revoke execute on functions from public;

-- What mcp_owner may do ----------------------------------------------------------
-- Read the business tables, and nothing else. No INSERT, UPDATE or DELETE, and
-- it owns nothing in insurance. The audit log grants are in 05_audit.sql.

grant usage on schema insurance to mcp_owner;

grant select on insurance.customers to mcp_owner;
grant select on insurance.policies to mcp_owner;
grant select on insurance.vehicles to mcp_owner;
grant select on insurance.drivers to mcp_owner;
grant select on insurance.repair_shops to mcp_owner;
grant select on insurance.adjusters to mcp_owner;
grant select on insurance.claims to mcp_owner;
grant select on insurance.claim_payments to mcp_owner;
grant select on insurance.claim_notes to mcp_owner;
grant select on insurance.policy_document_chunks to mcp_owner;

-- What mcp_reader may do ----------------------------------------------------------
-- Nothing at all on schema insurance, not even USAGE: the mcp functions reach
-- the tables with their owner's rights. Its rights on the mcp schema and each
-- function are granted in 07_mcp_functions.sql.

-- What can mcp_reader do at this point?
-- It can connect, because CONNECT is now granted to it by name rather than
-- through PUBLIC. It can no longer create temporary tables. It has no access to the insurance
-- schema, so it can't read or change any business data. It can still
-- see table and column names in the system catalogs, as every role can.
