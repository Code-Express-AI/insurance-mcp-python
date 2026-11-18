-- 06_row_security.sql: each caller sees only the customers in its own states.
--
-- Row-level security (RLS) adds a hidden condition to every query on a table,
-- so no mcp function can forget the check, and a new one gets it for free.
--
-- Who's calling: before every call, the MCP server runs
--     select set_config('mcp.caller_key', '<token name>', true);
-- and the policies read it back with current_setting('mcp.caller_key', true).
-- true means the setting ends with the transaction, so a pooled connection
-- can't hand one caller's key to the next. No key, an empty key or a key with
-- no rows below sees nothing.
--
-- Honest limit: mcp_reader can run set_config itself, so anyone with its
-- password can claim to be any caller. The database trusts the server.

-- Create the table as its owner, so insurance_owner owns it.
set role insurance_owner;

-- Which states each caller key may see. The data generator never touches this
-- table, so reloading the data keeps it.
create table insurance.caller_states (
    caller_key text not null,
    state      text not null check (state ~ '^[A-Z]{2}$'),
    primary key (caller_key, state)
);

insert into insurance.caller_states (caller_key, state) values
    -- The one token you start with (the quickstart): every state.
    ('local', 'TX'), ('local', 'OK'), ('local', 'CO'), ('local', 'NM'), ('local', 'AZ'),
    -- One token per client (end of guide 3): TX and CO, where the demo
    -- customers live, plus one state the other two can't see.
    ('claude', 'TX'), ('claude', 'CO'), ('claude', 'OK'),
    ('copilot', 'TX'), ('copilot', 'CO'), ('copilot', 'NM'),
    ('inspector', 'TX'), ('inspector', 'CO'), ('inspector', 'AZ');

grant select on insurance.caller_states to mcp_owner;

-- The policies ----------------------------------------------------------------
-- Turned on for the seven tables that hold customer data. Each policy is for
-- mcp_owner, the role the mcp functions run as (SECURITY DEFINER).
--
-- The tables belong to insurance_owner, and table owners skip RLS, so the admin
-- (who acts as insurance_owner) still sees every row and can reload the data.
--
-- Only customers checks the state. Every other policy asks "is my parent row
-- visible?", and the parent's own policy applies inside that check, so the
-- rule is written once.

alter table insurance.customers enable row level security;
alter table insurance.policies enable row level security;
alter table insurance.vehicles enable row level security;
alter table insurance.drivers enable row level security;
alter table insurance.claims enable row level security;
alter table insurance.claim_payments enable row level security;
alter table insurance.claim_notes enable row level security;

create policy callers_states on insurance.customers for select to mcp_owner
    using (customers.state in (
        select cs.state from insurance.caller_states as cs
        where cs.caller_key = current_setting('mcp.caller_key', true)
    ));

create policy visible_customer on insurance.policies for select to mcp_owner
    using (exists (select from insurance.customers as c where c.id = policies.customer_id));

create policy visible_policy on insurance.vehicles for select to mcp_owner
    using (exists (select from insurance.policies as p where p.id = vehicles.policy_id));

create policy visible_policy on insurance.drivers for select to mcp_owner
    using (exists (select from insurance.policies as p where p.id = drivers.policy_id));

create policy visible_policy on insurance.claims for select to mcp_owner
    using (exists (select from insurance.policies as p where p.id = claims.policy_id));

create policy visible_claim on insurance.claim_payments for select to mcp_owner
    using (exists (select from insurance.claims as c where c.id = claim_payments.claim_id));

create policy visible_claim on insurance.claim_notes for select to mcp_owner
    using (exists (select from insurance.claims as c where c.id = claim_notes.claim_id));

reset role;

-- What can mcp_reader do at this point?
-- Still nothing: the mcp functions come next, in 07_mcp_functions.sql. From
-- then on, each one returns only rows for customers in the states linked to the
-- caller key the server set. No key means no rows. mcp_reader can set the key
-- itself with set_config, so the database trusts the server.
