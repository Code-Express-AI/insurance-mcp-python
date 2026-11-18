-- 080_mcp_functions.sql: the mcp schema and every function mcp_reader can call.
--
-- update_db runs this file after 070_added_tables.sql, so a changed function
-- can be loaded without rebuilding the data
-- (uv run python -m insurance_database.update_db).
-- It drops the mcp schema and creates it again, so the schema holds exactly
-- what's in this file: a function removed here is gone, with its grant.
-- Nothing else lives in mcp: the tables, helpers and audit log are in insurance.
--
-- Rules for every function (the helpers in 040_helpers.sql follow the first two):
--   SET search_path = ''  and every name written in full (insurance.claims).
--                         A SECURITY DEFINER function must fix its search_path,
--                         or a caller could create a look-alike object and
--                         trick the function into using it.
--   Arguments start with p_, so they can't clash with column names.
--
-- Extra rules for the mcp functions (the only ones mcp_reader can call):
--   SECURITY DEFINER     runs with mcp_owner's rights: it can read the tables,
--                        and nothing more.
--   STABLE               PostgreSQL refuses INSERT, UPDATE or DELETE written in
--                        the function. It doesn't check the functions it calls:
--                        what really stops writes is that mcp_owner has no
--                        write rights on the business tables.
--   RETURNS TABLE        fixed columns, and a LIMIT on every result.
--   public keys only     a table's public_id is returned as <thing>_id.
--   no dynamic SQL       no EXECUTE, no format(): every query is written out.

drop schema if exists mcp cascade;
create schema mcp authorization mcp_owner;

-- mcp_reader may look in the schema. Which functions it may run is granted one
-- by one below.
grant usage on schema mcp to mcp_reader;

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

-- The read-only functions ---------------------------------------------------------
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
-- are replaced with [phone] and [email] (insurance.redact_text). Some notes
-- also write out the customer's street address, which no tool returns, so
-- it's replaced with [address].
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
                 insurance.redact_text(replace(n.note, cu.street_address, '[address]')) as note
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

-- RAG: search by meaning -------------------------------------------------------------
-- The server turns the question into an embedding (384 numbers) with the same
-- model that embedded the text, and passes it in as p_embedding. "Close" is
-- cosine distance, pgvector's <=> operator. With search_path = '', even the
-- operator is written with its schema: OPERATOR(public.<=>).
-- similarity is 1 minus the distance: 1 means the same meaning, lower is weaker.
-- Every search is exact (no vector index), so the filters never lose matches.

-- Claims whose accident descriptions, or whose notes, are closest in meaning
-- to the question. One or the other, not both: the notes are mostly the same
-- few paperwork sentences, and mixed in, they crowd out the descriptions.
-- p_search_in: 'descriptions' (what happened) or 'notes' (how the claim was
-- handled). Each claim once, with its best-matching text. A null filter means "any".
create function mcp.search_claim_text(
    p_embedding   real[],
    p_search_in   text    default 'descriptions',
    p_claim_type  text    default null,
    p_status      text    default null,
    p_period      text    default null,
    p_min_reserve numeric default null,
    p_limit       integer default 10
)
returns table (
    claim_id      uuid,
    claim_number  text,
    claim_type    text,
    status        text,
    date_reported date,
    reserve       numeric,
    matched_text  text,
    similarity    numeric
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_query public.vector := insurance.to_vector(p_embedding);
    -- Clamped to 1-50 here too, so a bug in the server can't list more.
    v_limit integer := least(greatest(coalesce(p_limit, 10), 1), 50);
    v_start date;
    v_end   date;
begin
    if not exists (select from insurance.claims as c where c.embedding is not null) then
        raise exception 'Run the embed command first.';
    end if;

    if p_period is not null then
        select pd.start_date, pd.end_date into v_start, v_end
        from insurance.period_dates(p_period, insurance.as_of_date()) as pd;
    end if;

    if p_search_in = 'descriptions' then
        return query
        select
            c.public_id,  -- the public key, returned as claim_id
            c.claim_number,
            c.claim_type,
            c.status,
            c.date_reported,
            c.reserve,
            insurance.redact_text(c.description),
            round((1 - (c.embedding operator(public.<=>) v_query))::numeric, 3)
        from insurance.claims as c
        where c.embedding is not null
          and (p_claim_type is null or c.claim_type = p_claim_type)
          and (p_status is null or c.status = p_status)
          and (p_min_reserve is null or c.reserve >= p_min_reserve)
          and (p_period is null or c.date_reported between v_start and v_end)
        order by c.embedding operator(public.<=>) v_query, c.claim_number
        limit v_limit;

    elsif p_search_in = 'notes' then
        return query
        with best as (
            -- Each claim once, with its closest note.
            select distinct on (n.claim_id)
                n.claim_id as claim_ref,
                n.note,
                n.embedding operator(public.<=>) v_query as distance
            from insurance.claim_notes as n
            where n.embedding is not null
            order by n.claim_id, n.embedding operator(public.<=>) v_query
        )
        select
            c.public_id,  -- the public key, returned as claim_id
            c.claim_number,
            c.claim_type,
            c.status,
            c.date_reported,
            c.reserve,
            -- The customer's street address too, as in get_claim. Without it,
            -- a search for "the customer's home address" collects them.
            insurance.redact_text(replace(b.note, cu.street_address, '[address]')),
            round((1 - b.distance)::numeric, 3)
        from best as b
        join insurance.claims as c on c.id = b.claim_ref
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        where (p_claim_type is null or c.claim_type = p_claim_type)
          and (p_status is null or c.status = p_status)
          and (p_min_reserve is null or c.reserve >= p_min_reserve)
          and (p_period is null or c.date_reported between v_start and v_end)
        order by b.distance, c.claim_number
        limit v_limit;

    else
        raise exception 'Unknown search_in "%". Use descriptions or notes.', p_search_in;
    end if;
end;
$$;
grant execute on function mcp.search_claim_text(real[], text, text, text, text, numeric, integer) to mcp_reader;

-- Claims whose accident descriptions are closest to one claim's description.
-- It compares the stored embeddings with each other, so it needs no model.
create function mcp.find_similar_claims(
    p_claim_number text,
    p_claim_type   text    default null,
    p_status       text    default null,
    p_period       text    default null,
    p_min_reserve  numeric default null,
    p_limit        integer default 10
)
returns table (
    claim_id      uuid,
    claim_number  text,
    claim_type    text,
    status        text,
    date_reported date,
    reserve       numeric,
    description   text,
    similarity    numeric
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_claim_ref bigint;  -- the internal id: used here, never returned
    v_query     public.vector;
    v_start     date;
    v_end       date;
begin
    select c.id, c.embedding into v_claim_ref, v_query
    from insurance.claims as c
    where c.claim_number = p_claim_number;

    if not found then
        raise exception 'Unknown claim number. Use search_claims to find it.';
    end if;
    if v_query is null then
        raise exception 'Run the embed command first.';
    end if;

    if p_period is not null then
        select pd.start_date, pd.end_date into v_start, v_end
        from insurance.period_dates(p_period, insurance.as_of_date()) as pd;
    end if;

    return query
    select
        c.public_id,  -- the public key, returned as claim_id
        c.claim_number,
        c.claim_type,
        c.status,
        c.date_reported,
        c.reserve,
        insurance.redact_text(c.description),
        round((1 - (c.embedding operator(public.<=>) v_query))::numeric, 3)
    from insurance.claims as c
    where c.embedding is not null
      and c.id <> v_claim_ref  -- not the claim itself
      and (p_claim_type is null or c.claim_type = p_claim_type)
      and (p_status is null or c.status = p_status)
      and (p_min_reserve is null or c.reserve >= p_min_reserve)
      and (p_period is null or c.date_reported between v_start and v_end)
    order by c.embedding operator(public.<=>) v_query, c.claim_number
    limit least(greatest(coalesce(p_limit, 10), 1), 50);
end;
$$;
grant execute on function mcp.find_similar_claims(text, text, text, text, numeric, integer) to mcp_reader;

-- Sections of the policy booklets closest in meaning to the question,
-- optionally for one coverage level.
create function mcp.search_policy_wording(
    p_embedding      real[],
    p_coverage_level text    default null,
    p_limit          integer default 5
)
returns table (
    coverage_level text,
    heading        text,
    content        text,
    similarity     numeric
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_query public.vector := insurance.to_vector(p_embedding);
begin
    if not exists (select from insurance.policy_document_chunks) then
        raise exception 'Run the embed command first.';
    end if;

    return query
    select
        d.coverage_level,
        d.heading,
        d.content,
        round((1 - (d.embedding operator(public.<=>) v_query))::numeric, 3)
    from insurance.policy_document_chunks as d
    where p_coverage_level is null or d.coverage_level = p_coverage_level
    order by d.embedding operator(public.<=>) v_query, d.coverage_level, d.heading
    limit least(greatest(coalesce(p_limit, 5), 1), 50);
end;
$$;
grant execute on function mcp.search_policy_wording(real[], text, integer) to mcp_reader;

-- One customer with every policy in full: coverage, premium, deductible, vehicle
-- and drivers. What get_customer and get_policy return, in one call.
create function mcp.get_customer_with_policies(p_customer_id uuid)
returns table (
    customer_id            uuid,
    first_name             text,
    last_name              text,
    city                   text,
    state                  text,
    zip_code               text,
    email                  text,
    drivers_license_number text,
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
        (select coalesce(jsonb_agg(jsonb_build_object(
                    'policy_number', p.policy_number,
                    'coverage_level', p.coverage_level,
                    'premium', p.premium,
                    'deductible', p.deductible,
                    'start_date', p.start_date,
                    'end_date', p.end_date,
                    'status', p.status,
                    'license_plate', v.license_plate,
                    'make', v.make,
                    'model', v.model,
                    'model_year', v.model_year,
                    'vehicle_value', v.value,
                    'drivers', (select jsonb_agg(jsonb_build_object(
                                        'name', d.first_name || ' ' || d.last_name,
                                        'relationship', d.relationship,
                                        'age', extract(year from age(insurance.as_of_date(), d.date_of_birth))::integer
                                    ) order by d.id)
                                from insurance.drivers as d
                                where d.policy_id = p.id)
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
grant execute on function mcp.get_customer_with_policies(uuid) to mcp_reader;

reset role;

-- What can mcp_reader do at this point?
-- It can call write_audit, get_dataset_info, find_customers, get_customer,
-- get_policy, get_customer_with_policies, search_claims, get_claim, count_claims_by_month, get_repair_shop_costs,
-- get_adjuster_workload, count_claims_by_driver_age, search_claim_text,
-- find_similar_claims and search_policy_wording. The read-only ones return fixed
-- columns and limited rows, and can't change data. It still can't reach the
-- insurance tables directly, and it can't call the insurance helper functions,
-- which are granted to mcp_owner only. Row-level security (060_row_security.sql)
-- limits each caller to its own states' customers.
