-- 04_functions.sql: the helper functions and the mcp functions.
--
-- Rules for every function:
--   SET search_path = ''  and every name written in full (insurance.claims).
--                         A SECURITY DEFINER function must fix its search_path,
--                         or a caller could create a look-alike object and
--                         trick the function into using it.
--   Arguments start with p_, so they can't clash with column names.
--
-- Extra rules for the mcp functions (the only ones mcp_reader can call):
--   SECURITY DEFINER     runs with mcp_owner's rights: it can read the tables,
--                        and nothing more.
--   STABLE               PostgreSQL refuses INSERT, UPDATE or DELETE inside it.
--   RETURNS TABLE        fixed columns, and a LIMIT on every result.
--   public keys only     a table's public_id is returned as <thing>_id.
--   no dynamic SQL       no EXECUTE, no format(): every query is written out.

-- Helper functions ---------------------------------------------------------------
-- In schema insurance, owned by insurance_owner. mcp_reader can't call them
-- (no USAGE on the schema, no EXECUTE). The mcp functions call them as mcp_owner.

set role insurance_owner;

-- The dataset's "today": the latest date a claim was reported (31 December 2026).
create function insurance.as_of_date()
returns date
language sql
stable
set search_path = ''
as $$
    select max(c.date_reported) from insurance.claims as c;
$$;

-- Turns a period name into a start and end date, in whole calendar months,
-- counted from the as-of date. Raises an error for an unknown name, so a bug
-- in the server can never turn into "no date filter at all".
create function insurance.period_dates(p_period text, p_as_of date)
returns table (start_date date, end_date date)
language plpgsql
immutable
set search_path = ''
as $$
declare
    -- First day of the as-of month.
    v_month date := date_trunc('month', p_as_of)::date;
    -- First day of the as-of year.
    v_year date := date_trunc('year', p_as_of)::date;
begin
    case p_period
        when 'last_month' then
            return query select (v_month - interval '1 month')::date, v_month - 1;
        when 'last_3_months' then
            return query select (v_month - interval '2 months')::date, p_as_of;
        when 'last_12_months' then
            return query select (v_month - interval '11 months')::date, p_as_of;
        when 'this_year' then
            return query select v_year, p_as_of;
        when 'last_year' then
            return query select (v_year - interval '1 year')::date, v_year - 1;
        else
            raise exception 'Unknown period "%". Use last_month, last_3_months, last_12_months, this_year or last_year.', p_period;
    end case;
end;
$$;

-- Escapes the characters ILIKE treats as wildcards, so a search for "%%"
-- matches only names that really contain "%%", not every row.
-- The backslash goes first, so the backslashes added for % and _ aren't doubled.
create function insurance.escape_like(p_text text)
returns text
language sql
immutable
set search_path = ''
as $$
    select replace(replace(replace(p_text, '\', '\\'), '%', '\%'), '_', '\_');
$$;

-- maria.garcia@example.com -> m***@example.com
create function insurance.mask_email(p_email text)
returns text
language sql
immutable
set search_path = ''
as $$
    select left(p_email, 1) || '***@' || split_part(p_email, '@', 2);
$$;

-- D1234567 -> *****4567. Always five stars, so the length isn't given away.
create function insurance.mask_last4(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select '*****' || right(p_value, 4);
$$;

-- Replaces US phone numbers and email addresses in free text (claim
-- descriptions and notes) with [phone] and [email].
-- It can't catch names, street addresses or injuries: patterns are easy to
-- match, meaning isn't.
create function insurance.redact_text(p_text text)
returns text
language sql
immutable
set search_path = ''
as $$
    select regexp_replace(
        regexp_replace(p_text, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[email]', 'g'),
        '\(?\m[0-9]{3}\)?[-. ]?[0-9]{3}[-. ][0-9]{4}\M', '[phone]', 'g'
    );
$$;

-- mcp_owner runs the mcp functions, which call these helpers.
grant execute on function insurance.as_of_date() to mcp_owner;
grant execute on function insurance.period_dates(text, date) to mcp_owner;
grant execute on function insurance.escape_like(text) to mcp_owner;
grant execute on function insurance.mask_email(text) to mcp_owner;
grant execute on function insurance.mask_last4(text) to mcp_owner;
grant execute on function insurance.redact_text(text) to mcp_owner;

reset role;

-- The mcp functions ----------------------------------------------------------------
-- One per MCP tool, with the same name. Each one is granted to mcp_reader on
-- the line after it. A function without a grant line can't be called.

set role mcp_owner;

-- The data's date range and size. The tool's description tells the model to
-- call it first for any question with a relative date ("last month").
-- Counts are cast to integer: no mcp function returns a bigint, so a test can
-- check that no internal id (always bigint) ever leaves the database.
create function mcp.get_dataset_info()
returns table (
    as_of_date          date,
    first_date_reported date,
    customer_count      integer,
    policy_count        integer,
    claim_count         integer,
    open_claim_count    integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return query
    select
        insurance.as_of_date(),
        (select min(c.date_reported) from insurance.claims as c),
        (select count(*)::integer from insurance.customers),
        (select count(*)::integer from insurance.policies),
        (select count(*)::integer from insurance.claims),
        (select count(*)::integer from insurance.claims as c where c.status = 'open');
end;
$$;
grant execute on function mcp.get_dataset_info() to mcp_reader;

reset role;
