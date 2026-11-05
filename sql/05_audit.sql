-- 05_audit.sql: the audit log, one row per tool call.
--
-- PostgreSQL has no built-in append-only tables, so the log is built from three parts:
--   1. Only mcp_owner can insert, and only through mcp.write_audit.
--      Nobody gets UPDATE or DELETE.
--   2. A trigger blocks UPDATE, DELETE and TRUNCATE for everyone.
--   3. A hash chain: each row stores a hash of its own data plus the previous
--      row's hash. insurance.verify_audit_log() finds the first row that doesn't match.
--
-- What it can't stop: the admin role can disable the trigger, change rows and
-- recompute the whole chain. No database can fully protect a log from its own admin.

set role insurance_owner;

create table insurance.audit_log (
    id            bigint generated always as identity primary key,
    occurred_at   timestamptz not null,   -- set by write_audit, never passed in
    caller        text not null,          -- the token's name, such as claude-code
    tool_name     text not null,
    arguments     jsonb not null,
    rows_returned integer,
    duration_ms   integer,
    succeeded     boolean not null,
    error         text,                   -- the short error only, never a stack trace
    previous_hash text,                   -- empty for the first row
    row_hash      text not null
);

-- The hash of one row, as 64 hex characters (SHA-256).
-- The fields go into a JSON array, in a fixed order, so nulls and commas can't
-- be confused. The time is written in UTC, so the session's time zone can't
-- change the hash. Used by write_audit and verify_audit_log, so both build
-- exactly the same text.
create function insurance.audit_row_hash(
    p_previous_hash text,
    p_occurred_at   timestamptz,
    p_caller        text,
    p_tool_name     text,
    p_arguments     jsonb,
    p_rows_returned integer,
    p_duration_ms   integer,
    p_succeeded     boolean,
    p_error         text
)
returns text
language sql
stable
set search_path = ''
as $$
    select encode(sha256(convert_to(jsonb_build_array(
        p_previous_hash,
        to_char(p_occurred_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        p_caller,
        p_tool_name,
        p_arguments,
        p_rows_returned,
        p_duration_ms,
        p_succeeded,
        p_error
    )::text, 'UTF8')), 'hex');
$$;

-- Blocks every change to an existing row. This is the only trigger in the database.
create function insurance.block_audit_changes()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    raise exception 'The audit log is append-only: % is not allowed.', tg_op;
end;
$$;

create trigger audit_log_no_update_or_delete
    before update or delete on insurance.audit_log
    for each row execute function insurance.block_audit_changes();

create trigger audit_log_no_truncate
    before truncate on insurance.audit_log
    for each statement execute function insurance.block_audit_changes();

-- Recomputes the chain from the first row. Returns the id of the first row
-- that doesn't match, or null if the whole log is intact.
-- Editing a row breaks its own hash. Deleting a row breaks the next row's
-- previous_hash. Deleting the newest rows can't be detected this way: that
-- needs a copy of the latest hash kept outside the database.
-- Run by the admin role. mcp_reader can't call it.
create function insurance.verify_audit_log()
returns bigint
language plpgsql
stable
set search_path = ''
as $$
declare
    v_row record;
    v_previous_hash text := null;
begin
    for v_row in select * from insurance.audit_log as a order by a.id loop
        if v_row.previous_hash is distinct from v_previous_hash
           or v_row.row_hash <> insurance.audit_row_hash(
                v_row.previous_hash, v_row.occurred_at, v_row.caller, v_row.tool_name,
                v_row.arguments, v_row.rows_returned, v_row.duration_ms,
                v_row.succeeded, v_row.error)
        then
            return v_row.id;
        end if;
        v_previous_hash := v_row.row_hash;
    end loop;
    return null;
end;
$$;

-- mcp_owner may add rows, and read only the two columns write_audit needs to
-- find the previous row's hash. It can't read who called what.
grant insert on insurance.audit_log to mcp_owner;
grant select (id, row_hash) on insurance.audit_log to mcp_owner;
grant execute on function insurance.audit_row_hash(
    text, timestamptz, text, text, jsonb, integer, integer, boolean, text
) to mcp_owner;

reset role;

-- The one write function ---------------------------------------------------------
-- The MCP server calls it after every tool call, including failed ones.
-- It returns nothing, so mcp_reader can add to the log but never read it.

set role mcp_owner;

create function mcp.write_audit(
    p_caller        text,
    p_tool_name     text,
    p_arguments     jsonb,
    p_rows_returned integer,
    p_duration_ms   integer,
    p_succeeded     boolean,
    p_error         text
)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_previous_hash text;
    v_occurred_at timestamptz;
    v_arguments jsonb := p_arguments;
begin
    -- Without this lock, two calls at the same moment could both chain to the
    -- same previous row. The number is arbitrary: only this function uses it.
    -- It's released when the transaction ends.
    perform pg_advisory_xact_lock(1001);

    select a.row_hash into v_previous_hash
    from insurance.audit_log as a
    order by a.id desc
    limit 1;

    -- Set here, after the lock, so times always go up with the id.
    v_occurred_at := clock_timestamp();

    -- Caps: the log is append-only, so junk can never be removed. These stop
    -- one call from adding a huge row.
    if length(v_arguments::text) > 4000 then
        v_arguments := jsonb_build_object('truncated', left(v_arguments::text, 4000));
    end if;

    insert into insurance.audit_log (
        occurred_at, caller, tool_name, arguments, rows_returned, duration_ms,
        succeeded, error, previous_hash, row_hash
    )
    values (
        v_occurred_at, left(p_caller, 100), left(p_tool_name, 100), v_arguments,
        p_rows_returned, p_duration_ms, p_succeeded, left(p_error, 500), v_previous_hash,
        insurance.audit_row_hash(
            v_previous_hash, v_occurred_at, left(p_caller, 100), left(p_tool_name, 100),
            v_arguments, p_rows_returned, p_duration_ms, p_succeeded, left(p_error, 500))
    );
end;
$$;
grant execute on function mcp.write_audit(
    text, text, jsonb, integer, integer, boolean, text
) to mcp_reader;

reset role;
