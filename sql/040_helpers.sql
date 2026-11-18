-- 040_helpers.sql: the helper functions the mcp functions call.
--
-- Rules for every function, here and in 080_mcp_functions.sql:
--   SET search_path = ''  and every name written in full (insurance.claims).
--                         A SECURITY DEFINER function must fix its search_path,
--                         or a caller could create a look-alike object and
--                         trick the function into using it.
--   Arguments start with p_, so they can't clash with column names.

-- Helper functions ---------------------------------------------------------------
-- In schema insurance, owned by insurance_owner. mcp_reader can't call them
-- (no USAGE on the schema, no EXECUTE). The mcp functions call them as mcp_owner.

set role insurance_owner;

-- The dataset's "today": the latest date a claim was reported (the day the data was set up).
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
-- match, meaning isn't. The one address we can catch is the customer's own:
-- the notes branches below replace it exactly, before calling this.
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

-- Checks a query embedding from the server and turns it into a vector.
-- The server sends a plain array of numbers (real[]), so mcp_reader needs
-- nothing from pgvector. pgvector checks the length too, but its message is
-- written for developers, and a null would give rows with no score instead of
-- an error. So we check it ourselves first.
create function insurance.to_vector(p_embedding real[])
returns public.vector
language plpgsql
immutable
set search_path = ''
as $$
begin
    if p_embedding is null
       or array_ndims(p_embedding) <> 1
       or cardinality(p_embedding) <> 384
       or array_position(p_embedding, null) is not null then
        raise exception 'The embedding must be a list of exactly 384 numbers.';
    end if;
    return p_embedding::public.vector(384);
end;
$$;

-- mcp_owner runs the mcp functions, which call these helpers.
grant execute on function insurance.as_of_date() to mcp_owner;
grant execute on function insurance.period_dates(text, date) to mcp_owner;
grant execute on function insurance.escape_like(text) to mcp_owner;
grant execute on function insurance.mask_email(text) to mcp_owner;
grant execute on function insurance.mask_last4(text) to mcp_owner;
grant execute on function insurance.redact_text(text) to mcp_owner;
grant execute on function insurance.to_vector(real[]) to mcp_owner;

reset role;

-- What can mcp_reader do at this point?
-- The same as after 030_permissions.sql. The helpers are granted to mcp_owner
-- only, and mcp_reader has no USAGE on the insurance schema.
