-- 02_schema.sql: the two schemas and the business tables.
--
-- Every table has two keys:
--   id         bigint, for joins inside the database. Never leaves it.
--   public_id  a random UUID, the only key the mcp functions return.
-- Fixed lists are lowercase text codes with a CHECK constraint.
-- Money is numeric(12,2), in US dollars.

-- pgvector, for the RAG part: a vector column type and distance operators.
-- It goes in schema public, where extensions go by default, and stays there when
-- the setup runs again. Only a superuser can install it (it isn't a "trusted"
-- extension): locally the admin is postgres, and hosted services let their
-- admin role install it.
create extension if not exists vector;

create schema insurance authorization insurance_owner;
create schema mcp authorization mcp_owner;

-- Create the tables as their owner, so insurance_owner owns them.
set role insurance_owner;

create table insurance.customers (
    id                     bigint generated always as identity primary key,
    public_id              uuid not null unique default gen_random_uuid(),
    first_name             text not null,
    last_name              text not null,
    date_of_birth          date not null,
    street_address         text not null,
    city                   text not null,
    state                  text not null check (state ~ '^[A-Z]{2}$'),
    zip_code               text not null check (zip_code ~ '^[0-9]{5}$'),
    email                  text not null,
    phone                  text not null,
    drivers_license_number text not null
);

create table insurance.policies (
    id             bigint generated always as identity primary key,
    public_id      uuid not null unique default gen_random_uuid(),
    policy_number  text not null unique check (policy_number ~ '^AUT-[0-9]{6}$'),
    customer_id    bigint not null references insurance.customers (id),
    coverage_level text not null check (coverage_level in ('liability', 'liability_collision', 'full')),
    premium        numeric(12,2) not null check (premium > 0),   -- per year
    deductible     numeric(12,2) not null check (deductible >= 0),
    start_date     date not null,
    end_date       date,                                          -- set only when canceled
    status         text not null check (status in ('active', 'canceled')),
    check ((status = 'canceled') = (end_date is not null)),
    check (end_date >= start_date)
);

create table insurance.vehicles (
    id            bigint generated always as identity primary key,
    public_id     uuid not null unique default gen_random_uuid(),
    policy_id     bigint not null unique references insurance.policies (id),  -- one per policy
    license_plate text not null,
    make          text not null,
    model         text not null,
    model_year    integer not null check (model_year between 1980 and 2027),
    value         numeric(12,2) not null check (value >= 0)
);

create table insurance.drivers (
    id            bigint generated always as identity primary key,
    public_id     uuid not null unique default gen_random_uuid(),
    policy_id     bigint not null references insurance.policies (id),
    first_name    text not null,
    last_name     text not null,
    date_of_birth date not null,
    relationship  text not null check (relationship in ('policyholder', 'spouse', 'child', 'other'))
);

create table insurance.repair_shops (
    id        bigint generated always as identity primary key,
    public_id uuid not null unique default gen_random_uuid(),
    name      text not null,
    city      text not null,
    state     text not null check (state ~ '^[A-Z]{2}$')
);

create table insurance.adjusters (
    id         bigint generated always as identity primary key,
    public_id  uuid not null unique default gen_random_uuid(),
    first_name text not null,
    last_name  text not null
);

create table insurance.claims (
    id             bigint generated always as identity primary key,
    public_id      uuid not null unique default gen_random_uuid(),
    claim_number   text not null unique check (claim_number ~ '^CLM-[0-9]{7}$'),
    policy_id      bigint not null references insurance.policies (id),
    driver_id      bigint not null references insurance.drivers (id),  -- who was at the wheel
    adjuster_id    bigint not null references insurance.adjusters (id),
    repair_shop_id bigint references insurance.repair_shops (id),      -- empty if no shop was used
    claim_type     text not null check (claim_type in ('collision', 'theft', 'glass', 'fire', 'vandalism', 'weather')),
    fault          text not null check (fault in ('at_fault', 'not_at_fault', 'shared')),
    status         text not null check (status in ('open', 'settled', 'denied', 'withdrawn')),
    date_of_loss   date not null,
    date_reported  date not null,
    date_closed    date,                                                -- empty while open
    reserve        numeric(12,2) not null check (reserve >= 0),        -- expected total cost
    description    text not null,
    embedding      public.vector(384),                                  -- of the description, for RAG
    check (date_reported >= date_of_loss),
    check ((status = 'open') = (date_closed is null)),
    check (date_closed >= date_reported)
);

create table insurance.claim_payments (
    id           bigint generated always as identity primary key,
    public_id    uuid not null unique default gen_random_uuid(),
    claim_id     bigint not null references insurance.claims (id),
    payment_type text not null check (payment_type in ('repair', 'rental_car', 'injury', 'total_loss')),
    amount       numeric(12,2) not null check (amount > 0),
    payment_date date not null
);

create table insurance.claim_notes (
    id          bigint generated always as identity primary key,
    public_id   uuid not null unique default gen_random_uuid(),
    claim_id    bigint not null references insurance.claims (id),
    adjuster_id bigint not null references insurance.adjusters (id),
    created_at  timestamptz not null,
    note        text not null,
    embedding   public.vector(384)  -- of the note, for RAG
);

-- The policy booklets, one row per section, for RAG. The embed command loads them.
-- No public_id: no tool looks a section up by key. A section is named by its
-- coverage level and heading.
create table insurance.policy_document_chunks (
    id             bigint generated always as identity primary key,
    coverage_level text not null check (coverage_level in ('liability', 'liability_collision', 'full')),
    heading        text not null,
    content        text not null,
    embedding      public.vector(384) not null,
    unique (coverage_level, heading)
);

-- The embedding columns stay empty until the embed command fills them, and
-- they have no index: every search is exact. pgvector's HNSW index is
-- approximate, and it applies SQL filters after picking its nearest candidates,
-- so a strict filter can leave no rows at all. At our size, exact search takes
-- well under a second.

-- PostgreSQL doesn't index foreign keys by itself. These keep joins fast.
create index on insurance.policies (customer_id);
create index on insurance.drivers (policy_id);
create index on insurance.claims (policy_id);
create index on insurance.claims (driver_id);
create index on insurance.claims (adjuster_id);
create index on insurance.claims (repair_shop_id);
create index on insurance.claims (date_reported);
create index on insurance.claim_payments (claim_id);
create index on insurance.claim_notes (claim_id);

reset role;
