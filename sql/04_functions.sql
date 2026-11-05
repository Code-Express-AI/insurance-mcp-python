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

-- Customers whose name contains the search text, anywhere in "first last", so
-- "Rutherford" and "Maria Garcia" both work.
-- escape_like: a search for "%%" matches names that contain "%%", not everyone.
-- Fewer than 2 characters returns nothing, so one letter can't list the table.
create function mcp.find_customers(p_name text)
returns table (
    customer_id  uuid,
    first_name   text,
    last_name    text,
    city         text,
    state        text,
    email        text,
    policy_count integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if length(trim(p_name)) < 2 then
        return;
    end if;

    return query
    select
        cu.public_id,  -- the public key, returned as customer_id
        cu.first_name,
        cu.last_name,
        cu.city,
        cu.state,
        insurance.mask_email(cu.email),
        (select count(*)::integer from insurance.policies as p where p.customer_id = cu.id)
    from insurance.customers as cu
    where cu.first_name || ' ' || cu.last_name
          ilike '%' || insurance.escape_like(trim(p_name)) || '%'
    order by cu.last_name, cu.first_name
    limit 25;
end;
$$;
grant execute on function mcp.find_customers(text) to mcp_reader;

-- One customer, their policies (as a jsonb list) and how many claims they have.
-- Street address, date of birth and phone aren't returned at all: no tool needs them.
create function mcp.get_customer(p_customer_id uuid)
returns table (
    customer_id            uuid,
    first_name             text,
    last_name              text,
    city                   text,
    state                  text,
    zip_code               text,
    email                  text,
    drivers_license_number text,
    claim_count            integer,
    policies               jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return query
    select
        cu.public_id,  -- the public key, returned as customer_id
        cu.first_name,
        cu.last_name,
        cu.city,
        cu.state,
        cu.zip_code,
        insurance.mask_email(cu.email),
        insurance.mask_last4(cu.drivers_license_number),
        (select count(*)::integer
         from insurance.claims as c
         join insurance.policies as p on p.id = c.policy_id
         where p.customer_id = cu.id),
        (select coalesce(jsonb_agg(jsonb_build_object(
                    'policy_id', p.public_id,
                    'policy_number', p.policy_number,
                    'coverage_level', p.coverage_level,
                    'status', p.status,
                    'start_date', p.start_date,
                    'make', v.make,
                    'model', v.model,
                    'model_year', v.model_year,
                    'license_plate', v.license_plate
                ) order by p.start_date), '[]')
         from insurance.policies as p
         join insurance.vehicles as v on v.policy_id = p.id
         where p.customer_id = cu.id)
    from insurance.customers as cu
    where cu.public_id = p_customer_id;

    if not found then
        raise exception 'Unknown customer_id. Use find_customers to find it.';
    end if;
end;
$$;
grant execute on function mcp.get_customer(uuid) to mcp_reader;

-- One policy: what it covers, its vehicle, and its listed drivers.
-- Drivers' ages, not their dates of birth.
create function mcp.get_policy(p_policy_number text)
returns table (
    policy_id      uuid,
    policy_number  text,
    customer_id    uuid,
    customer_name  text,
    coverage_level text,
    premium        numeric,
    deductible     numeric,
    start_date     date,
    end_date       date,
    status         text,
    license_plate  text,
    make           text,
    model          text,
    model_year     integer,
    vehicle_value  numeric,
    drivers        jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return query
    select
        p.public_id,   -- the public key, returned as policy_id
        p.policy_number,
        cu.public_id,  -- returned as customer_id
        cu.first_name || ' ' || cu.last_name,
        p.coverage_level,
        p.premium,
        p.deductible,
        p.start_date,
        p.end_date,
        p.status,
        v.license_plate,
        v.make,
        v.model,
        v.model_year,
        v.value,
        (select jsonb_agg(jsonb_build_object(
                    'name', d.first_name || ' ' || d.last_name,
                    'relationship', d.relationship,
                    'age', extract(year from age(insurance.as_of_date(), d.date_of_birth))::integer
                ) order by d.id)
         from insurance.drivers as d
         where d.policy_id = p.id)
    from insurance.policies as p
    join insurance.customers as cu on cu.id = p.customer_id
    join insurance.vehicles as v on v.policy_id = p.id
    where p.policy_number = p_policy_number;

    if not found then
        raise exception 'Unknown policy number. Use find_customers, then get_customer, to find it.';
    end if;
end;
$$;
grant execute on function mcp.get_policy(text) to mcp_reader;

-- Claims matching every filter given. A null filter means "any".
-- 50 per page, newest first, and at most 20 pages, so one set of filters can
-- return at most 1,000 claims. total_count says how many match in all.
-- days_open is only set for open claims: the days since the claim was reported.
create function mcp.search_claims(
    p_customer_id   uuid    default null,
    p_policy_id     uuid    default null,
    p_status        text    default null,
    p_claim_type    text    default null,
    p_min_reserve   numeric default null,
    p_min_days_open integer default null,
    p_period        text    default null,
    p_page          integer default 1
)
returns table (
    claim_id      uuid,
    claim_number  text,
    policy_number text,
    customer_name text,
    claim_type    text,
    fault         text,
    status        text,
    date_of_loss  date,
    date_reported date,
    reserve       numeric,
    days_open     integer,
    total_count   integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_as_of date := insurance.as_of_date();
    v_start date;
    v_end   date;
    -- The page is clamped here too, so a bug in the server can't page further.
    v_page  integer := least(greatest(coalesce(p_page, 1), 1), 20);
begin
    if p_period is not null then
        select pd.start_date, pd.end_date into v_start, v_end
        from insurance.period_dates(p_period, v_as_of) as pd;
    end if;

    return query
    select
        c.public_id,  -- the public key, returned as claim_id
        c.claim_number,
        p.policy_number,
        cu.first_name || ' ' || cu.last_name,
        c.claim_type,
        c.fault,
        c.status,
        c.date_of_loss,
        c.date_reported,
        c.reserve,
        case when c.status = 'open' then v_as_of - c.date_reported end,
        (count(*) over ())::integer
    from insurance.claims as c
    join insurance.policies as p on p.id = c.policy_id
    join insurance.customers as cu on cu.id = p.customer_id
    where (p_customer_id is null or cu.public_id = p_customer_id)
      and (p_policy_id is null or p.public_id = p_policy_id)
      and (p_status is null or c.status = p_status)
      and (p_claim_type is null or c.claim_type = p_claim_type)
      and (p_min_reserve is null or c.reserve >= p_min_reserve)
      and (p_min_days_open is null
           or (c.status = 'open' and v_as_of - c.date_reported >= p_min_days_open))
      and (p_period is null or c.date_reported between v_start and v_end)
    order by c.date_reported desc, c.claim_number desc
    limit 50
    offset (v_page - 1) * 50;
end;
$$;
grant execute on function mcp.search_claims(uuid, uuid, text, text, numeric, integer, text, integer) to mcp_reader;

-- One claim with its payments and its latest 20 notes.
-- Descriptions and notes are free text, so phone numbers and emails in them
-- are replaced with [phone] and [email] (insurance.redact_text).
create function mcp.get_claim(p_claim_number text)
returns table (
    claim_id         uuid,
    claim_number     text,
    policy_number    text,
    customer_name    text,
    driver_name      text,
    driver_age       integer,
    claim_type       text,
    fault            text,
    status           text,
    date_of_loss     date,
    date_reported    date,
    date_closed      date,
    reserve          numeric,
    total_paid       numeric,
    repair_shop_name text,
    adjuster_name    text,
    description      text,
    payments         jsonb,
    note_count       integer,
    notes            jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return query
    select
        c.public_id,  -- the public key, returned as claim_id
        c.claim_number,
        p.policy_number,
        cu.first_name || ' ' || cu.last_name,
        d.first_name || ' ' || d.last_name,
        -- The driver's age on the day of the accident.
        extract(year from age(c.date_of_loss, d.date_of_birth))::integer,
        c.claim_type,
        c.fault,
        c.status,
        c.date_of_loss,
        c.date_reported,
        c.date_closed,
        c.reserve,
        (select coalesce(sum(cp.amount), 0)
         from insurance.claim_payments as cp
         where cp.claim_id = c.id),
        s.name,
        a.first_name || ' ' || a.last_name,
        insurance.redact_text(c.description),
        (select coalesce(jsonb_agg(jsonb_build_object(
                    'payment_type', cp.payment_type,
                    'amount', cp.amount,
                    'payment_date', cp.payment_date
                ) order by cp.payment_date, cp.id), '[]')
         from insurance.claim_payments as cp
         where cp.claim_id = c.id),
        (select count(*)::integer from insurance.claim_notes as n where n.claim_id = c.id),
        (select coalesce(jsonb_agg(jsonb_build_object(
                    'created_at', latest.created_at,
                    'adjuster_name', latest.adjuster_name,
                    'note', latest.note
                ) order by latest.created_at desc), '[]')
         from (
             select
                 n.created_at,
                 na.first_name || ' ' || na.last_name as adjuster_name,
                 insurance.redact_text(n.note) as note
             from insurance.claim_notes as n
             join insurance.adjusters as na on na.id = n.adjuster_id
             where n.claim_id = c.id
             order by n.created_at desc
             limit 20
         ) as latest)
    from insurance.claims as c
    join insurance.policies as p on p.id = c.policy_id
    join insurance.customers as cu on cu.id = p.customer_id
    join insurance.drivers as d on d.id = c.driver_id
    join insurance.adjusters as a on a.id = c.adjuster_id
    left join insurance.repair_shops as s on s.id = c.repair_shop_id  -- no shop for a stolen car
    where c.claim_number = p_claim_number;

    if not found then
        raise exception 'Unknown claim number. Use search_claims to find it.';
    end if;
end;
$$;
grant execute on function mcp.get_claim(text) to mcp_reader;

-- Claims reported per month in the period, optionally of one type.
-- Every month in the period is returned, with 0 where there were no claims
-- (generate_series), so a gap can't be misread as a missing month.
create function mcp.count_claims_by_month(p_period text, p_claim_type text default null)
returns table (
    month       date,
    claim_count integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_start date;
    v_end   date;
begin
    -- Raises an error for an unknown period, including a missing one.
    select pd.start_date, pd.end_date into v_start, v_end
    from insurance.period_dates(p_period, insurance.as_of_date()) as pd;

    return query
    select
        m.month::date,
        count(c.id)::integer
    from generate_series(v_start::timestamp, v_end::timestamp, interval '1 month') as m(month)
    left join insurance.claims as c
        on date_trunc('month', c.date_reported::timestamp) = m.month
       and (p_claim_type is null or c.claim_type = p_claim_type)
    group by m.month
    order by m.month
    limit 12;
end;
$$;
grant execute on function mcp.count_claims_by_month(text, text) to mcp_reader;

-- Repair shops ranked by their average repair cost per claim, on claims
-- reported in the period. Repair payments only.
-- Shops with fewer than 5 claims are left out, so one big claim can't put a
-- small shop on top.
create function mcp.get_repair_shop_costs(p_period text, p_limit integer default 10)
returns table (
    repair_shop_name    text,
    city                text,
    state               text,
    claim_count         integer,
    average_repair_cost numeric,
    total_repair_cost   numeric
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_start date;
    v_end   date;
begin
    select pd.start_date, pd.end_date into v_start, v_end
    from insurance.period_dates(p_period, insurance.as_of_date()) as pd;

    return query
    select
        s.name,
        s.city,
        s.state,
        count(distinct c.id)::integer,
        round(sum(cp.amount) / count(distinct c.id), 2),
        sum(cp.amount)
    from insurance.claims as c
    join insurance.repair_shops as s on s.id = c.repair_shop_id
    join insurance.claim_payments as cp on cp.claim_id = c.id and cp.payment_type = 'repair'
    where c.date_reported between v_start and v_end
    group by s.id
    having count(distinct c.id) >= 5
    -- By position (5 is average_repair_cost): written by name, it would clash
    -- with the output column of the same name, which is a variable in PL/pgSQL.
    order by 5 desc, s.name
    -- Clamped to 1-20 here too, so a bug in the server can't list more.
    limit least(greatest(coalesce(p_limit, 10), 1), 20);
end;
$$;
grant execute on function mcp.get_repair_shop_costs(text, integer) to mcp_reader;

-- Open claims per adjuster: how many, their total reserve, and how long the
-- oldest has been open. Most open claims first.
create function mcp.get_adjuster_workload()
returns table (
    adjuster_name      text,
    open_claim_count   integer,
    open_reserve_total numeric,
    oldest_open_days   integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    return query
    select
        a.first_name || ' ' || a.last_name,
        count(*)::integer,
        sum(c.reserve),
        insurance.as_of_date() - min(c.date_reported)
    from insurance.claims as c
    join insurance.adjusters as a on a.id = c.adjuster_id
    where c.status = 'open'
    group by a.id
    -- By position (2 is open_claim_count, 1 adjuster_name), as in get_repair_shop_costs.
    order by 2 desc, 1
    limit 100;
end;
$$;
grant execute on function mcp.get_adjuster_workload() to mcp_reader;

-- Claims reported in the period, by the age of the driver on the day of the
-- accident, optionally only for one fault. Always the four bands, in order,
-- with 0 where there are none.
create function mcp.count_claims_by_driver_age(p_period text, p_fault text default null)
returns table (
    age_band    text,
    claim_count integer
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_start date;
    v_end   date;
begin
    select pd.start_date, pd.end_date into v_start, v_end
    from insurance.period_dates(p_period, insurance.as_of_date()) as pd;

    return query
    with claim_ages as (
        select extract(year from age(c.date_of_loss, d.date_of_birth)) as driver_age
        from insurance.claims as c
        join insurance.drivers as d on d.id = c.driver_id
        where c.date_reported between v_start and v_end
          and (p_fault is null or c.fault = p_fault)
    )
    select
        b.label,
        count(ca.driver_age)::integer
    from (values
        (1, '16-19', 16, 19),
        (2, '20-24', 20, 24),
        (3, '25-64', 25, 64),
        (4, '65+',   65, 200)
    ) as b(sort_order, label, min_age, max_age)
    left join claim_ages as ca on ca.driver_age between b.min_age and b.max_age
    group by b.sort_order, b.label
    order by b.sort_order
    limit 4;
end;
$$;
grant execute on function mcp.count_claims_by_driver_age(text, text) to mcp_reader;

reset role;
