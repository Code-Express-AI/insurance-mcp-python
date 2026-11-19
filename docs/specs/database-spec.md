# Database specification

The detail behind decision 3 in [spec.md](spec.md). It says how the PostgreSQL database is built and, above all, how it's locked down. Locking the database down is the whole point of the project.

Everything here follows normal PostgreSQL conventions.

**Portable by design:** the same scripts must run unchanged on the local Docker database and on a hosted PostgreSQL service such as Neon (decision 14). So nothing may need a real superuser, the setup can't rely on Docker-only features, and the only difference between the two is the connection string.

**Signed off by Liam on 2026-11-05.** Decisions marked Agreed are signed off. **Row-level security signed off by Liam on 2026-11-12:** a new decision 15, with small changes to decisions 6, 12 and 13. **Adding a table without a rebuild signed off by Liam on 2026-11-18:** a new decision 17, with the files renumbered in tens (decision 12).

**Status key:** Open (not discussed yet) · Proposed (Claude's suggestion, awaiting Liam) · Agreed (signed off by Liam)

## Decision summary

| # | Decision | Status |
|---|----------|--------|
| 1 | PostgreSQL version and Docker image | Agreed |
| 2 | Roles | Agreed |
| 3 | Schemas and naming | Agreed |
| 4 | Keys and identifiers | Agreed |
| 5 | Data types | Agreed |
| 6 | Permissions | Agreed |
| 7 | The `mcp` functions | Agreed |
| 8 | Errors | Agreed |
| 9 | Masking | Agreed |
| 10 | Audit log | Agreed |
| 11 | Resource limits | Agreed |
| 12 | Setup scripts | Agreed |
| 13 | Tests that prove the lockdown | Agreed |
| 14 | Hosting on Neon (optional) | Agreed |
| 15 | Row-level security: each caller sees only its own customers | Agreed |
| 16 | Reloading the functions without a rebuild: `update_db` | Agreed |
| 17 | Adding a table without a rebuild: `070_added_tables.sql` | Agreed |

## The lockdown at a glance

| Security idea | How | Decision |
|---|---|---|
| The server can only run approved queries | Functions in an `mcp` schema | 7 |
| A function can read tables its caller can't | `SECURITY DEFINER` functions | 7 |
| A buggy function still can't write | The functions' owner, `mcp_owner`, has only `SELECT` on the tables | 2 |
| No direct table access | Nothing granted, plus defaults removed from `PUBLIC` | 6 |
| An allow-list of functions | `GRANT EXECUTE` one by one, after revoking the default `EXECUTE` that every role gets | 6 |
| Internal ids never leave the database | `bigint` identity key plus a `uuid` public key | 4 |
| Hide personal data | Masking inside the functions | 9 |
| A tamper-evident audit log | A trigger that blocks changes, plus a hash chain | 10 |
| Errors only the database can spot reach the model | `RAISE EXCEPTION`, SQLSTATE `P0001` | 8 |
| No free-form SQL | No `EXECUTE` (dynamic SQL) in functions | 7 |
| Each caller sees only its own customers | Row-level security policies, keyed on a caller key the server sets | 15 |

## 1. PostgreSQL version and Docker image

**Status:** Agreed

- The `pgvector/pgvector` image from day one, as already agreed in spec decision 2, so the RAG extension doesn't need a rebuild.
- Pin the major version in the tag (for example `pgvector/pgvector:pg18`). Use the newest major that pgvector publishes an image for **and Neon supports** when we start building, then never change it.
- Docker Compose, with secrets in a git-ignored `.env`.
- **The port is published to this machine only:** `"127.0.0.1:5432:5432"`, not `"5432:5432"`. The short form listens on every network interface, so anyone on the same Wi-Fi could reach the database and try the admin password. On Linux, Docker's port publishing also bypasses the firewall (ufw), so the firewall wouldn't save you. The MCP server binds to `127.0.0.1` for the same reason (server decision 3).

## 2. Roles

**Status:** Agreed

PostgreSQL has roles, not separate logins and users. Four roles:

| Role | Can log in | Purpose |
|---|---|---|
| The admin role | Yes | Whatever admin role the host gives you: `postgres` in Docker (a real superuser), `neondb_owner` on Neon (not a real superuser). Used only to run the setup and load data. Never used by the MCP server. |
| `insurance_owner` | **No** | Owns the `insurance` schema, its tables and the helper functions. Nobody logs in as it. |
| `mcp_owner` | **No** | Owns the `mcp` schema and its functions. Has `SELECT` on the tables the functions read, `INSERT` on the audit log plus `SELECT` on two of its columns (decision 10), and nothing else. Nobody logs in as it. |
| `mcp_reader` | Yes | The only role the MCP server connects as. It may run the granted `mcp` functions and nothing else. |

The setup makes the admin role a member of both owner roles, so it can create objects owned by them.

**Why owners that can't log in:** a `SECURITY DEFINER` function runs with its owner's rights. If the owner were the admin role, a bug in one function would run with admin rights (superuser rights, in Docker). With `NOLOGIN`, only the admin role (through its membership) or a superuser can act as an owner.

**Why the functions don't belong to the table owner:** a function runs with all of its owner's rights, not just the ones it needs. If `insurance_owner` owned the functions, a bug in one would run with the rights to change, drop or truncate any table, and to disable the audit log's trigger (decision 10). `mcp_owner` can only read the tables and add audit rows, so the worst a buggy function can do is read. This is least privilege: give each role only what its job needs.

**It's also how you'd do it on a database you don't own.** In a real company, the data the MCP server reads usually belongs to someone else. You'd add the `mcp` schema, `mcp_owner` and `mcp_reader`, and get `SELECT` granted on the tables you need, without taking them over (spec decision 3).

The setup needs only what every host gives its admin role: permission to create roles (`CREATEROLE`) and to create schemas in the database. It never needs superuser.

## 3. Schemas and naming

**Status:** Agreed

- Two schemas:
  - `insurance`: the tables, which hold the business data plus the audit log.
  - `mcp`: the functions the server may call. This is the same idea as the well-known PostgREST pattern of a separate API schema.
- Nothing goes in `public`.
- Standard PostgreSQL naming: lowercase `snake_case` everywhere, plural table names (`claims`, `claim_notes`), singular column names, foreign keys named `<table singular>_id` (`policy_id`).
- Constraint and index names are left to PostgreSQL's defaults (`claims_pkey`, `claims_policy_id_fkey`) unless a name helps an error message.

## 4. Keys and identifiers

**Status:** Agreed

Every table has two keys, one for inside the database and one for outside it.

- **Internal key:** `id bigint generated always as identity primary key`. Foreign keys are `bigint` and point at `id`. Integers keep joins and indexes small and fast. **They never leave the database:** sequential numbers give away how many rows exist and let a caller guess other records by counting.
- **Public key:** `public_id uuid not null unique default gen_random_uuid()`, created when the row is inserted. This is the only key the API exposes, renamed to `<thing>_id` (decision 7). It's random (UUID version 4), so it says nothing about how many rows exist or what its neighbors are.
- **Why `bigint` everywhere, not `int` for small tables:** one rule is easier to follow, the extra 4 bytes don't matter, and a `bigint` can't run out.
- **Business numbers:** policy numbers (`AUT-104233`) and claim numbers are what people quote, so the tools accept them. The generator makes them **random and unique, not sequential**, so they don't give away volumes either.
- **Not version 7 UUIDs** (`uuidv7()`), even though PostgreSQL 18 has them. They start with a timestamp, which leaks when a row was created.

## 5. Data types

**Status:** Agreed

| Kind of value | Type | Note |
|---|---|---|
| Money (premium, deductible, reserve, payments) | `numeric(12,2)` | Never `float`, and never PostgreSQL's `money` type, which the PostgreSQL docs themselves advise against. |
| Dates (date of loss, policy start) | `date` | |
| Points in time (audit log, notes) | `timestamptz` | Stored in UTC. |
| Fixed lists (claim status, cover type) | `text` with a `CHECK` constraint | Easier to change than a PostgreSQL `enum` type, and easy to read. |
| Free text (descriptions, notes) | `text` | |
| Audit arguments | `jsonb` | |

All amounts are in US dollars. There's no currency column.

## 6. Permissions

**Status:** Agreed

In PostgreSQL, a role can do only what it, or `PUBLIC`, has been granted. There's no way to deny a right outright. `PUBLIC` is a built-in pseudo-role that every role belongs to, and it gets some rights by default. So locking down means two things: grant `mcp_reader` almost nothing, and take the defaults away from `PUBLIC`.

| Default for `PUBLIC` | What we do |
|---|---|
| `CONNECT` and `TEMPORARY` on every database | Revoke both from `PUBLIC`. Grant `CONNECT` to `mcp_reader` only. Without `TEMPORARY` it can't create temporary tables either. |
| `EXECUTE` on every new function | **The big PostgreSQL gotcha.** Revoke it from existing functions, and run `ALTER DEFAULT PRIVILEGES FOR ROLE insurance_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, and the same for `mcp_owner`, so new functions don't get it either. Otherwise every function we add would be callable by `mcp_reader` without anyone granting it. Default privileges only apply to objects created by the named role, so the setup creates every function as one of the two owners (decision 2). |
| `CREATE` on the `public` schema | Already off since PostgreSQL 15. Revoke anyway, so the script says it out loud. |

Then the grants, which are the whole list of what `mcp_reader` may do:

- `USAGE` on schema `mcp`, which lets it see the functions.
- `EXECUTE` on each `mcp` function, granted one by one, one line per function. A function without a grant line can't be called.
- **Nothing on schema `insurance`**, not even `USAGE`. The functions reach the tables through their owner's rights.

And for `mcp_owner`: `USAGE` on schema `insurance`, `SELECT` on each table its functions read, `EXECUTE` on the helper functions, and `INSERT` on `insurance.audit_log`, plus `SELECT` on just its `id` and `row_hash` columns (decision 10). No `UPDATE`, `DELETE`, `TRUNCATE` or ownership of anything in `insurance`. This is also a second lock: even if a function in `insurance` somehow had `EXECUTE`, `mcp_reader` couldn't call it without `USAGE` on the schema.

**What we can't lock down:** every role can read the system catalogs, which include table names, column names and the source code of every function. Revoking this breaks normal tools. Every role can also run PostgreSQL's built-in functions, such as `pg_sleep()`, and any extension's functions, such as pgvector's. Our revoke only covers functions our two owners create. Two more of the same kind: `mcp_reader` can connect to the server's other databases (`postgres`, `template1`), because the connect revoke in `030_permissions.sql` only covers our own database, and the setup may not own the others (on a hosted service it doesn't). And advisory lock numbers are shared by every role, so a direct `mcp_reader` session could hold lock 1001, the one `write_audit` waits for (decision 10), and every tool call would fail, because the audit fails closed. That's no worse than using up the 10 connections (decision 11). All of these only matter if someone can send raw SQL, which the MCP server never allows (layer 3). The docs say so plainly.

**Which rows each caller sees** is decided by row-level security (decision 15). The grants above decide what `mcp_reader` can do at all. Row-level security then decides which customers' rows the functions return for each caller.

## 7. The `mcp` functions

**Status:** Agreed

Each MCP tool calls exactly one `mcp` function. The rules below are agreed. The list of functions is at the end of this section.

Every function follows the same rules:

- **`SECURITY DEFINER`, owned by `mcp_owner`.** The function runs with the owner's rights, so it can read tables that `mcp_reader` can't, and nothing more. It's set explicitly on each function, so it's easy to see when reading the function.
- **`SET search_path = ''`, with every table name written in full** (`insurance.claims`). The `search_path` decides which schema PostgreSQL looks in for a name that has no schema. The PostgreSQL docs warn that a `SECURITY DEFINER` function must fix it, otherwise a caller could create a look-alike object and trick the function into using it. An empty path, with every name written in full, is the simplest way to be sure.
- **`RETURNS TABLE (...)` with fixed columns.** The model can't ask for other columns.
- **No `bigint` in any result.** Internal ids are `bigint`, so no result column is: counts are cast to `integer` (`count(*)::integer`). That keeps the catalog test (decision 13) a simple rule with no exceptions.
- **Public keys are renamed on the way out.** A table's `public_id` is returned as `<thing>_id` (`select c.public_id as customer_id`), and tool arguments use the same names. The model only ever sees `customer_id`, `policy_id` and so on, and those are always UUIDs. Inside the tables, `customer_id` is the internal `bigint` foreign key, so each function has a one-line comment explaining the rename. We avoid a `_key` suffix, because a model may mistake a "key" for a secret.
- **A `LIMIT` on every result.** Arguments like page size are clamped inside the function with `least()` and `greatest()`.
- **No dynamic SQL:** no `EXECUTE` and no `format()` used to build a query. Every query is written out in the function. Together with psycopg sending every value as a parameter, separate from the SQL text, this is what stops SQL injection. A value is only ever compared with data, never run as SQL.
- **Wildcards in searches are escaped.** This isn't SQL injection, but it's a related trick: a search for `%%` would match every customer and dump the whole table, up to the row limit. One helper, `insurance.escape_like(text)`, escapes `\` first, then `%` and `_`, using `replace()`. Every `ILIKE` search uses it. A search term must also have at least 2 characters after trimming spaces, otherwise the function returns no rows.
- **`LANGUAGE plpgsql` for all of them.** Plain `LANGUAGE sql` is shorter, but it can't raise an error, and many functions need to check their arguments. With one language, readers only ever see one shape: check the arguments, then `RETURN QUERY`.
- **Read functions are marked `STABLE`.** This is a second guard, not just a hint to the planner: PostgreSQL refuses to run `INSERT`, `UPDATE` or `DELETE` written in a `STABLE` PL/pgSQL function. It's a weak guard, though: it doesn't check the functions it calls, so a `STABLE` function that calls a `VOLATILE` one that writes succeeds (checked). The real guard is the grants: `mcp_owner` can't write to any business table.
- **Comments are written for readers**, explaining the security reason, not only what the code does.

The one write function is `mcp.write_audit(...)`. It inserts an audit row and returns nothing, so `mcp_reader` can add to the log but never read it.

### Naming inside a function

- **Arguments start with `p_`** (`p_customer_id`). In PL/pgSQL, an argument or output column with the same name as a table column makes a query ambiguous, and PostgreSQL stops with "column reference is ambiguous". The `p_` prefix is the usual PostgreSQL way to avoid it.
- **Every column in a query is written with its table alias** (`c.last_name`), because the `RETURNS TABLE` column names (`customer_id`, `status`) are variables too and would clash in the same way.

### Results with nested lists

Some tools return one thing with lists inside it: a claim with its payments and notes. A `RETURNS TABLE` function returns rows of one shape, so these functions return **one row, with the lists as `jsonb` columns** built with `jsonb_agg(jsonb_build_object(...))`. The keys are written out in the function, so they're as fixed as the columns. The tool still makes exactly one call, and the server passes the row on as a JSON object.

### Helper functions

In schema `insurance`, so `mcp_reader` can't call them (no `USAGE`, no `EXECUTE`). The `mcp` functions call them with their owner's rights.

| Helper | What it does |
|---|---|
| `insurance.as_of_date()` | The dataset's "today": `max(date_reported)` from `insurance.claims` (server decision 9). |
| `insurance.period_dates(p_period text, p_as_of date)` | Turns a period name into a start and end date (below). Raises an error for an unknown name. The `mcp` functions pass in `insurance.as_of_date()`. Taking the date as an argument keeps the helper a pure calculation that can be tested without any data. |
| `insurance.escape_like(text)` | Escapes `\`, `%` and `_` for `ILIKE` (above). |
| `insurance.mask_email(text)`, `insurance.mask_last4(text)`, `insurance.redact_text(text)` | Masking (decision 9). |

**Periods**, worked out from the as-of date (the day the data was set up), in whole calendar months. The examples are for an as-of date of 18 November 2026:

| Period | Dates | Example |
|---|---|---|
| `last_month` | The calendar month before the as-of month | October 2026 |
| `last_3_months` | The as-of month and the 2 before it | September to November 2026 |
| `last_12_months` | The as-of month and the 11 before it | December 2025 to November 2026 |
| `this_year` | 1 January of the as-of year to the as-of date | 2026 |
| `last_year` | The calendar year before | 2025 |

Whole months, so `count_claims_by_month` never shows a part month. A claim belongs to a period by its `date_reported`, the same date the as-of date comes from.

### The function list

One function per tool in [server-spec.md](server-spec.md), decision 10, with the same name. `mcp_reader` gets `EXECUTE` on these 10 plus `mcp.write_audit`: 11 grant lines in all.

| Function | Arguments | Returns | Limit |
|---|---|---|---|
| `mcp.get_dataset_info()` | None | One row: `as_of_date`, `first_date_reported`, `customer_count`, `policy_count`, `claim_count`, `open_claim_count` | 1 row |
| `mcp.find_customers` | `p_name text` | `customer_id`, `first_name`, `last_name`, `city`, `state`, `email` (masked), `policy_count`. Matches `p_name` anywhere in "first last", so "Rutherford" and "Maria Garcia" both work. Sorted by last name, then first name. | 25 rows |
| `mcp.get_customer` | `p_customer_id uuid` | One row: `customer_id`, `first_name`, `last_name`, `city`, `state`, `zip_code`, `email` (masked), `drivers_license_number` (masked), `claim_count`, and `policies` (`jsonb`: `policy_id`, `policy_number`, `coverage_level`, `status`, `start_date`, vehicle make, model, year and plate). Raises "Unknown customer_id" if not found. | 1 row |
| `mcp.get_policy` | `p_policy_number text` | One row: `policy_id`, `policy_number`, `customer_id`, `customer_name`, `coverage_level`, `premium`, `deductible`, `start_date`, `end_date`, `status`, `license_plate`, `make`, `model`, `model_year`, `vehicle_value`, and `drivers` (`jsonb`: name, relationship, age). Ages, not dates of birth. Raises "Unknown policy number" if not found. | 1 row |
| `mcp.search_claims` | `p_customer_id uuid`, `p_policy_id uuid`, `p_status text`, `p_claim_type text`, `p_min_reserve numeric`, `p_min_days_open int`, `p_period text`, `p_page int` | `claim_id`, `claim_number`, `policy_number`, `customer_name`, `claim_type`, `fault`, `status`, `date_of_loss`, `date_reported`, `reserve`, `days_open`, `total_count`. Every argument may be null, meaning "any". `p_min_days_open` only matches open claims, counting from `date_reported` to the as-of date. Newest first. `total_count` (all matching claims, from `count(*) over ()`) tells the model whether there are more pages. Pages stop at 20, so one set of filters returns at most 1,000 claims. | 50 rows per page, 20 pages |
| `mcp.get_claim` | `p_claim_number text` | One row: `claim_id`, `claim_number`, `policy_number`, `customer_name`, `driver_name`, `driver_age` (at the date of loss), `claim_type`, `fault`, `status`, the three dates, `reserve`, `total_paid`, `repair_shop_name`, `adjuster_name`, `description`, `payments` (`jsonb`), `note_count`, and `notes` (`jsonb`, newest first). Raises "Unknown claim number" if not found. | 20 notes |
| `mcp.count_claims_by_month` | `p_period text`, `p_claim_type text` | `month` (first day of the month), `claim_count`. Months with no claims are returned with 0 (`generate_series`), so a gap can't be misread. | 12 rows |
| `mcp.get_repair_shop_costs` | `p_period text`, `p_limit int` | `repair_shop_name`, `city`, `state`, `claim_count`, `average_repair_cost`, `total_repair_cost`. Repair payments only, on claims reported in the period. Shops with fewer than 5 claims in the period are left out, so one big claim can't put a shop on top. Most expensive first. `p_limit` is clamped to 1–20, default 10. | 20 rows |
| `mcp.get_adjuster_workload()` | None | `adjuster_name`, `open_claim_count`, `open_reserve_total`, `oldest_open_days`. Most open claims first. | 100 rows |
| `mcp.count_claims_by_driver_age` | `p_period text`, `p_fault text` | `age_band`, `claim_count`. Age at the date of loss. Always the four bands, `16-19`, `20-24`, `25-64`, `65+`, in that order, with 0 where there are none. | 4 rows |

The RAG part (spec decision 11) adds three more, with three more grant lines. Each takes the query as `p_embedding real[]` and turns it into a vector with a helper, `insurance.to_vector()`, which raises "The embedding must be a list of exactly 384 numbers." for anything else, a null included. Each raises "Run the embed command first." if there's nothing to search yet. `similarity` is 1 minus the cosine distance, to 3 decimal places. Every search is exact, with no vector index.

| Function | Arguments | Returns | Limit |
|---|---|---|---|
| `mcp.search_claim_text` | `p_embedding real[]`, `p_search_in text`, `p_claim_type text`, `p_status text`, `p_period text`, `p_min_reserve numeric`, `p_limit int` | `claim_id`, `claim_number`, `claim_type`, `status`, `date_reported`, `reserve`, `matched_text` (redacted), `similarity`. `p_search_in` is `descriptions` (the default) or `notes`, and anything else raises an error. For notes, each claim comes back once, with its closest note. Closest first. `p_limit` is clamped to 1–50, default 10. | 50 rows |
| `mcp.find_similar_claims` | `p_claim_number text`, the same four filters, `p_limit int` | `claim_id`, `claim_number`, `claim_type`, `status`, `date_reported`, `reserve`, `description` (redacted), `similarity`. Compares stored description embeddings, so the server needs no model. Leaves out the claim itself. Raises "Unknown claim number" if not found. | 50 rows |
| `mcp.search_policy_wording` | `p_embedding real[]`, `p_coverage_level text`, `p_limit int` | `coverage_level`, `heading`, `content`, `similarity`. `p_limit` is clamped to 1–50, default 5. | 50 rows |

**What the server checks and what the function checks.** The server rejects bad codes and out-of-range numbers before the call (decision 8). The functions still clamp limits and pages, and `insurance.period_dates()` still raises on an unknown period, so a bug in the server can't turn into a table dump.

## 8. Errors

**Status:** Agreed

The rule: **the caller gets a short, helpful message or a generic one, never database internals.** No stack traces, SQL text, table names or PostgreSQL error details ever go back to the model.

Who checks what:

| Problem | Checked by | What the model gets |
|---|---|---|
| Missing argument, wrong type, bad UUID format, out-of-range number, bad date | The MCP server, in Python, **before** calling the database (layer 3) | The MCP SDK's validation message, which names the argument and the rule it broke |
| A lookup by id or number finds nothing ("no policy AUT-104233") | The function: `RAISE EXCEPTION` | A message saying how to fix the call ("Unknown policy number. Use find_customers, then get_customer, to find it.") |
| A search finds nothing ("customers called Zzyzx") | Nobody: it isn't an error | An empty result |
| Anything else (a bug, the database is down, a timeout) | The MCP server | A generic message: "The database could not complete this request." |

Details:

- `RAISE EXCEPTION` uses its default SQLSTATE, `P0001`. Only our own functions raise it, so the server's rule is simple: `P0001` means "our message, safe to show".
- **For `P0001`, the server passes on the message text only.** A PostgreSQL error also carries a context line such as `PL/pgSQL function mcp.get_policy(text) line 5 at RAISE`, which reveals function names and code. That context is never passed on.
- **The full error is logged on the server, privately.** The model never sees it, but we do keep it, because without it nobody can fix a bug. This is the standard approach: details in your own logs, a generic message to the outside world. The audit log records only that the call failed and a short error, never a stack trace.

## 9. Masking

**Status:** Agreed. Kept deliberately small: two masked columns are enough to show the idea.

PostgreSQL has no built-in column masking. We mask **inside the functions**, with two small helper functions called in each `mcp` function's `SELECT`. It's simple, easy to see in the code, and needs no extension. (The alternative, the `postgresql_anonymizer` extension, isn't in the `pgvector/pgvector` image, so it would need our own Docker image. Too much for the course.)

**Being honest about this:** Built-in masking would apply whatever query reads a column. Here, masking only happens where a function remembers to do it. The safety net is a test (decision 13) that calls every function and checks no unmasked value comes back.

**Masked columns:**

| Column | Returned as | Example | Helper |
|---|---|---|---|
| `customers.email` | First letter plus domain | `j***@example.com` | `insurance.mask_email()` |
| `customers.drivers_license_number` | Last 4 characters only, the way US companies show "ending in 1234" | `*****1234` | `insurance.mask_last4()` |

**Free text** (claim descriptions and notes) is cleaned by a third helper, `insurance.redact_text()`, wherever an `mcp` function returns it (`get_claim` and the RAG functions). It uses `regexp_replace` to replace phone numbers and email addresses with `[phone]` and `[email]`. The model doesn't need contact details for any of our questions, and with a hosted model every tool result leaves the machine. **The customer's own street address** is replaced too, with `[address]`, before the pattern matching. Some notes write it out ("Visited Megan Jackson at home at 2087 Spring Street"), so a column that no tool returns would come straight back through the notes, and a RAG search for "the customer's home address" would collect them. The function knows whose claim it is, so it removes that exact address with `replace(n.note, cu.street_address, '[address]')`. The embed command embeds the same redacted text (spec decision 11). **What it can't catch:** names, injuries, and any other address: a witness's, or the customer's written differently ("2087 Spring St"). Patterns are easy to match, meaning isn't, and the docs say so. The masking test (decision 13) also checks that no planted phone number or email comes back.

**Everything else** is simpler than masking: a column that no tool needs (street address, date of birth, phone) is just left out of every function's fixed columns (decision 7). Names, city, state and license plates are returned as they are, because the demo questions use them.

## 10. Audit log

**Status:** Agreed

Table `insurance.audit_log`: `id`, `occurred_at`, `caller` (the token's name, such as `local` or `claude`: see spec decision 4), `tool_name`, `arguments` (`jsonb`), `rows_returned`, `duration_ms`, `succeeded`, `error`, `previous_hash`, `row_hash`.

PostgreSQL has no built-in append-only tables, so the log is built from three parts:

1. **Only `mcp_owner` can insert,** and only through `mcp.write_audit`. Nobody gets `UPDATE` or `DELETE`.
2. **A trigger blocks `UPDATE`, `DELETE` and `TRUNCATE`** for everyone, including the owner. Only the table's owner (`insurance_owner`, or a member of it), or a superuser, can disable the trigger. The owner can't log in, and the functions run as `mcp_owner`, which can't (decision 2), so in practice that's the admin role.
3. **A hash chain.** Each row stores a SHA-256 hash of its own data plus the previous row's hash. `insurance.verify_audit_log()` recomputes the chain and reports the first row that doesn't match. Editing or deleting a row in the middle breaks the chain.

**This is the only trigger in the database.** No other table gets one, not even the common `updated_at` triggers. Triggers run hidden logic that readers can't see in the query they're reading. The hash is calculated in `write_audit` itself, not in a trigger. The audit trigger is the one exception, because blocking changes can only be enforced in the database.

**What gets written:**

- One row per tool call, written by the server **after** the tool's function runs, as a separate statement outside the tool's transaction. A failed tool call is still recorded.
- `occurred_at` is set by the database, not passed in, so the caller can't fake it.
- `arguments` is capped at 4,000 characters and `error` at 500. Append-only means junk can never be removed, so caps stop the table growing without limit.
- `error` holds the short error only (decision 8). Stack traces go to the server log.
- **Requests that never reach a tool** (bad token, rate limited, malformed) go to the server's app log, not this table. Anyone on the internet can send a bad token, and an append-only table must not fill up with their junk.

**Fail closed:** if the audit row can't be written, the tool call fails with a generic error and the result isn't returned. No audit, no answer. There's no setting to turn this off. It costs almost nothing here: the audit log is in the same database as the data, so if it can't be written, the tool call would almost certainly have failed anyway.

**Who reads it:** no MCP tool reads the audit log. The admin role reads it directly and runs `verify_audit_log()`. Rows are never deleted. Re-running the setup is the only way to reset the log.

Two details to get right:

- `write_audit` reads the previous row's hash, so `mcp_owner` needs to read the audit log a little. It gets `SELECT` on just two columns, `id` and `row_hash` (a column-level grant), so a buggy `mcp` function still can't read who called what, or with which arguments.
- `write_audit` takes a lock before reading the last hash. Without it, two calls at the same moment would both chain to the same previous row. It uses a transaction-level advisory lock (`pg_advisory_xact_lock`), which needs no extra rights. Locking the table itself would need rights `mcp_owner` doesn't have.
- The hashed text is built in a fixed format (timestamps in UTC, a fixed order of fields). Otherwise session settings such as the time zone would change the hash.

**What PostgreSQL can't promise** (and the docs say so):

- The admin role can disable the trigger, change rows and recompute the whole chain. No database can fully protect a log from its own admin. The real fix is to copy the latest hash somewhere the database admin can't reach. We don't build it.
- **Whoever has the `mcp_reader` password can write audit rows directly.** `mcp.write_audit` must be granted to `mcp_reader`, because the server calls it. So anyone who connects as `mcp_reader` without going through the server can add rows with any caller name, or flood the table with rows that can never be deleted. Calling the data functions directly isn't audited at all, because the server writes the audit rows, not the functions. **Why the functions don't write their own row:** a PostgreSQL function can't commit separately from its caller's transaction, so `begin; select mcp.get_claim(...); rollback;` would return the data and erase the row. Closing that needs a second connection from inside the function (`dblink`), which isn't worth it for a protection that's easy to get around. Considered and dropped on 2026-11-12. **The database limits *what* can be done; the server records *who* did it.** Keep the reader password long and secret (decision 12), and on a hosted database, restrict who can connect (decision 14).
- **Personal data is kept forever.** `arguments` holds what was searched for, such as a customer's name, and an append-only table with a hash chain can't have it removed. Privacy laws such as the GDPR give people a right to have their data deleted. A real system would set a retention period and keep the hash chain in sections that can be archived and dropped together. We don't build it.
- **The trigger doesn't stop `DROP TABLE`.** An event trigger could block it, but it needs a real superuser (not available on Neon), it's a second trigger, and it would also block our own setup from resetting the database. We accept the gap.

## 11. Resource limits

**Status:** Agreed

PostgreSQL makes these one line each, and they stop a slow query or a flood of connections hurting the database:

- `ALTER ROLE mcp_reader SET statement_timeout = '5s'`
- `ALTER ROLE mcp_reader CONNECTION LIMIT 10`

The exact numbers are to be confirmed once the functions exist.

**What these are and aren't:** the connection limit holds whatever a session does. The timeout is only a default: any session can run `SET statement_timeout = 0`. The MCP server never does, so through the server it holds. Someone connecting directly as `mcp_reader` could turn it off, which is one more reason to keep that password secret.

## 12. Setup scripts

**Status:** Agreed

- Plain numbered `.sql` files in `sql/`, with no migration tool. This is a demo database that's rebuilt from scratch, not a live system that changes over time:
  - `010_roles.sql`
  - `020_schema.sql`
  - `030_permissions.sql`
  - `040_helpers.sql`: the helper functions in `insurance`
  - `050_audit.sql`: the audit log table, its triggers and hash chain
  - `060_row_security.sql`: the `caller_states` table, its rows and the row-level security policies (decision 15)
  - `070_added_tables.sql`: tables added after the first setup, written so they can be run again (decision 17)
  - `080_mcp_functions.sql`: the `mcp` schema and every `mcp` function, `write_audit` included. `update_db` reruns it, after `070` (decisions 16 and 17)
- **Numbered in tens,** so a file can go between two others without renaming the rest (decision 17).
- **One small Python setup command runs the files in order**, connecting as the admin role through a connection string in `.env`. It's the same command for Docker and Neon. We don't use Docker's `/docker-entrypoint-initdb.d`, because it only exists in Docker. We don't use `psql` either, because many Windows users won't have it installed, and the project needs Python anyway.
- The `.sql` files are plain SQL with no `psql` commands, so any tool can run them.
- **The `mcp_reader` password** comes from `.env`. The setup command sets it after running the files. It hashes the password first (SCRAM-SHA-256, as psql's `\password` does), so only the hash reaches the database: a database that logs its statements, as hosted ones often do, would otherwise write the password to its log. No password is ever written in a committed file. **The setup refuses a password shorter than 24 characters**, so nobody uses `password123`, even locally.
- **To start again:** the setup drops and recreates the `insurance` and `mcp` schemas and the three roles it creates (`insurance_owner`, `mcp_owner`, `mcp_reader`). That works on any host. No `docker compose down -v` is needed, though it still works locally.
- The setup command then runs the data generator by default ([data-generator-spec.md](data-generator-spec.md)), which also connects as the admin role. Nothing else uses the admin role.

## 13. Tests that prove the lockdown

**Status:** Agreed

**How they run:** with pytest and Testcontainers (spec decision 7). At the start of the test run, a throwaway `pgvector/pgvector` container is started, using the same image and version as decision 1. The setup command (decision 12) builds the database from empty, the tests run, and the container is deleted.

- **A separate container is necessary, not just tidy.** The tests deliberately do bad things: they create ungranted functions, disable the audit trigger and edit rows. A separate database inside your demo container wouldn't be enough either, because roles belong to the whole PostgreSQL server, not to one database.
- **Every test run also tests the setup**, because it builds the database from scratch.
- **No Docker, no failures:** if Docker isn't running, every integration test is skipped with one clear reason.
- **The tests build the database as a non-superuser admin,** a role that can create roles and owns the database, and nothing more, like a hosted database's admin. So every test run proves the setup never needs superuser rights (decision 2), not just the Docker path, where the admin is a superuser.
- The tests live in `tests/database/`, apart from the SQL in `sql/`.

Tests connect as `mcp_reader` unless a test says otherwise. Each one shows a security claim actually holds.

- It can't `SELECT`, `INSERT`, `UPDATE` or `DELETE` on any `insurance` table.
- It can't read the audit log.
- It can't create a table, a temporary table or a function in any schema.
- The setup refuses a reader password shorter than 24 characters.
- It can't call an `mcp` function that hasn't been granted. The test adds one to prove the default `EXECUTE` revoke works.
- Every granted function returns at most its row limit.
- A search for `%%`, `__` or `\` matches only names that really contain those characters, which means none.
- A lookup with an unknown number raises `P0001` with a helpful message.
- No function returns an unmasked email or driver's license number, or any street address, date of birth or phone number. That includes the free text: no note comes back with its own customer's street address, from `get_claim` or a notes search.
- `UPDATE`, `DELETE` and `TRUNCATE` on the audit log fail even as the admin role, while the trigger is enabled.
- The audit log is the only table with triggers. The test checks the system catalogs, so a trigger added anywhere else fails it.
- `verify_audit_log()` passes on a clean log and reports the right row after a deliberate edit (the test disables the trigger as the admin role to make the edit).
- A query that runs past the statement timeout is canceled.
- No `mcp` function returns an internal `bigint` id. The test checks every function's result columns in the system catalogs.
- `mcp_owner` has no `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` on any business table, and owns nothing in `insurance`. The test checks the system catalogs.
- A `STABLE` function that tries to write fails. The test creates one as `mcp_owner` to prove the guard holds.
- Every `mcp` function is `SECURITY DEFINER`, has `search_path` set, and is owned by `mcp_owner`. The test checks the system catalogs, so a function added later can't skip these rules.
- Every `mcp` function that takes a `real[]` query embedding passes it through `insurance.to_vector` (the 384-number check), and every `vector` column in `insurance` is `vector(384)`. Both read the system catalogs, so a search added later, by hand or by an AI without the skill, is checked without anyone adding it to a list (added 2026-11-18).
- **A snapshot of everything `mcp_reader` can do**, however it got the right: granted to it, to `PUBLIC` or to a role it belongs to. Any right the SQL files don't mean to give fails it, including one nobody thought to test for. Adding a function means adding it to the list.
- A search made of invisible characters (the byte-order mark, zero-width characters, the soft hyphen) matches nothing. Some databases ignore these when comparing text. PostgreSQL doesn't, so the server needn't filter them out.

Row-level security (decision 15). The tests' `mcp_reader` connection sets the `local` key for its whole session, so the tests above still check all the data. The tests below set their own keys.

- With no caller key, an empty one or an unknown one, every function returns nothing.
- Each named key sees only its own states, in every filtered table: a customer from Oklahoma is found by `claude` and `local`, but not by `copilot` or `inspector`. And the same for New Mexico (`copilot`) and Arizona (`inspector`).
- Maria Garcia and Rutherford are found by every key, so the demos work with any token.
- Another state's claim or policy number gets the same "Unknown..." message as a number that doesn't exist.
- The RAG functions return no claim or note from another state.
- The caller key is gone after the transaction, so a reused connection doesn't carry it to the next caller.
- RLS is on for exactly the seven customer-data tables. The test reads the list from the system catalogs and compares it to a fixed one, so whoever adds a table must decide whether it holds customer data.
- The admin still sees every row, so the data can be reloaded.
- `mcp_reader` can't read `caller_states` (the snapshot test covers this).

The tests use a throwaway container by default. Because nothing is Docker-specific, they could also be pointed at a Neon database with a connection string setting, which would prove that the hosted copy is locked down too. That setting is only added if hosting is.

## 14. Hosting on Neon (optional)

**Status:** Agreed. Local Docker is the main path. Hosting the database is an optional extra, not built yet. Until it is, the only requirement is that the design doesn't block it.

[Neon](https://neon.com) is hosted PostgreSQL with a free plan that needs no credit card, so it's the suggested example. It's a suggestion, not a dependency. Other hosted PostgreSQL services (AWS, Google Cloud, Supabase and others) also don't give you a real superuser, so a design that works on Neon works on them too. What Neon changes:

- **No real superuser.** The admin role (`neondb_owner`) can create roles and schemas but isn't a superuser. Decisions 2 and 12 are written so that's enough.
- **No Docker init scripts.** Handled by the Python setup command (decision 12).
- **The connection string uses TLS and checks the certificate** (`sslmode=verify-full`). `sslmode=require` encrypts the connection but doesn't check who's at the other end, so someone in between could pretend to be the database. Neon's own docs recommend `verify-full`. The server and tools read one connection string from `.env` and never build it from parts, so this is just a different value.
- **Use Neon's direct connection, not the pooled one.** The pooled connection goes through PgBouncer, which adds rules about session settings and prepared statements. At our traffic, the direct connection is simpler and enough.
- **The database is on the public internet.** Locally, only your machine can reach it. On Neon, anyone can try to connect, so the `mcp_reader` password must be long and random, and the docs say so. (Neon's IP allow-list may be a paid feature: check the current plans.)
- **Extensions:** pgvector is available on Neon. Anything else we use must be too.
- **Free plan storage:** check the current limit against our data volume, especially once the RAG extension adds embeddings. Each embedding is a few KB, and we'll have tens of thousands of notes. The embedding size (spec decision 11) may need to fit the free plan.
- **A bonus:** Neon keeps a history of the database for a short time (point-in-time restore). That's a second way to catch someone who edits the audit log, next to the hash chain.

## 15. Row-level security: each caller sees only its own customers

**Status:** Agreed (signed off by Liam on 2026-11-12). Checked in a throwaway container on `full` data before writing: every claim below marked "checked" was run, not assumed.

Until now, every token saw every customer (decision 6 listed this as an honest limit). Now each caller sees only the customers in the states it's given, along with their policies, vehicles, drivers, claims, payments and notes. Real insurers work like this: they're licensed state by state, and claims are handled by regional offices.

PostgreSQL's row-level security (RLS) does the filtering. A policy on a table adds a hidden condition to every query on it, so no `mcp` function can forget the check, and a new function gets it for free.

### Who's calling: the caller key

The database doesn't know about tokens, sign-in or identity providers. It only sees one string, the **caller key**, which the server puts in a setting at the start of every call:

```sql
select set_config('mcp.caller_key', 'copilot', true);   -- true: only until the end of this transaction
select * from mcp.find_customers('Garcia');
```

The policies read it back with `current_setting('mcp.caller_key', true)`. With named tokens, the key is the token's name. If the server is ever hosted with a sign-in provider such as Entra ID, Okta or Auth0, only the server changes: the key becomes the provider's stable user id, and the SQL stays the same ([server-spec.md](server-spec.md), decision 5).

This is the standard PostgreSQL pattern. PostgREST and Supabase do the same thing: the server sets the verified identity with `set_config(..., true)` on each transaction, and RLS policies read it.

- **It only lasts for one transaction.** A pooled connection can't carry one caller's key over to the next caller (checked: after the commit, the setting is empty). It also works through a transaction-mode pooler such as PgBouncer, which a hosted database might use.
- **No key, an empty key or an unknown key sees nothing.** The policies fail closed (checked: every count is 0).

### Which states each caller sees: `insurance.caller_states`

```sql
create table insurance.caller_states (
    caller_key text not null,
    state      text not null check (state ~ '^[A-Z]{2}$'),
    primary key (caller_key, state)
);
```

It's owned by `insurance_owner`. `mcp_owner` may read it, and `mcp_reader` gets nothing. A new file, `060_row_security.sql`, creates the table, the policies and these rows:

| Caller key | States | Why |
|---|---|---|
| `local` | All five (TX, OK, CO, NM, AZ) | The one token you start with. The quickstart and guides use it for Copilot, Claude Code and MCP Inspector alike. |
| `claude` | TX, CO, **OK** | Claude Code's own token, from the end of appendix A. |
| `copilot` | TX, CO, **NM** | GitHub Copilot's own token. |
| `inspector` | TX, CO, **AZ** | MCP Inspector's own token. |

**Two shared states, and one state each.** All three named tokens see TX and CO. The planted demo customers are in those two states (Maria Garcia in TX, Eleanor Rutherford in CO), so every demo question works with any token, and no new planted data is needed. Each named token also sees one state the other two can't. So a customer from Oklahoma turns up for `claude` and nobody else, which is the row-level security demo.

**Mapping states, not single customers,** keeps the table to 14 rows rather than one row per customer per caller. It's also easy to show on screen, and it reads like a real business rule.

**The rows are set up as part of the SQL, not the generated data.** The data generator never touches `caller_states`, just as it never touches the audit log, so reloading the data keeps the mapping. The setup command rebuilds it with everything else.

### The policies

RLS is turned on for the seven tables that hold customer data. Each policy is `for select to mcp_owner`, because the `mcp` functions run as `mcp_owner` (`SECURITY DEFINER`). Each one follows the table's foreign key up to the customer:

| Table | A row is visible if |
|---|---|
| `customers` | its `state` is in `caller_states` for the caller key |
| `policies` | its customer is visible |
| `vehicles`, `drivers`, `claims` | their policy is visible |
| `claim_payments`, `claim_notes` | their claim is visible |

Each policy only asks "is the parent visible?", and the parent's own policy applies inside that check, so the rule is written once, on `customers`. For example:

```sql
create policy visible_customer on insurance.policies for select to mcp_owner
    using (exists (select from insurance.customers as c where c.id = customer_id));
```

**Not filtered:** `repair_shops`, `adjusters` and `policy_document_chunks` hold no customer data. The audit log isn't filtered either, because `mcp_owner` can only add to it. The tools that add up claims, such as `get_repair_shop_costs` and `get_adjuster_workload`, still only count the caller's claims, because they read `claims`.

**The RAG tools are covered too.** `search_claim_text` and `find_similar_claims` read `claims` and `claim_notes`, so a search by meaning can't surface another state's claim.

### What it means for callers

- **A hidden record is "unknown".** `get_claim` with another state's claim number gets the same "Unknown claim number" message as a number that doesn't exist (checked), so the error doesn't confirm the record is there.
- **`get_dataset_info` counts only what the caller can see.** `local` sees all 12,000 customers, and each named token fewer.
- **A token whose name isn't in `caller_states` sees nothing.** Every answer is empty, not an error. The guides say so, and appendix A shows the `insert` that gives a new token its states.

### What isn't filtered

- **The admin sees every row.** The tables belong to `insurance_owner`, and table owners skip RLS, including an admin acting through membership of that role (checked). So loading, reloading and deleting the data work as before. We don't use `FORCE ROW LEVEL SECURITY`, which would filter the owner too. It would also break the data load: PostgreSQL refuses `COPY FROM` into a table whose row-level security applies to the user (found in the build, when a test switched `FORCE` on).
- **`mcp_reader` can't read any table anyway** (decision 6). RLS is a second lock on what the functions return, not a replacement for the first.

### Speed

The policies add a check per row. Checked on `full` data, the slowest call is `get_dataset_info`, which counts every table: it went from about 4 ms to about 0.3 s. A scan of all 76,000 notes takes about 0.2 s. Both are well inside the 5-second statement timeout (decision 11), and small next to the time a model takes to answer. No new index is needed.

### Honest limit: the database trusts the server

`mcp_reader` can run `set_config` itself, so anyone with its password can claim to be any caller (checked). PostgreSQL has no read-only session setting. The MCP server sets the key from the token, and a model can't change it, because no tool runs raw SQL. So the `mcp_reader` password must be kept as secret as the tokens. Making the database check each user itself would mean a database login per person, which isn't how web apps normally connect. The docs say so.

This replaces the `session_user` idea in decision 6: one reader role plus a caller key covers any number of callers, where a second reader role covered only one extra group.

## 16. Reloading the functions without a rebuild: `update_db`

**Status:** Agreed (Liam, 2026-11-18)

**The problem:** adding or changing a tool (video 3, the add-an-insurance-tool skill) means changing an `mcp` function. Today the only way to load it is `setup_db`, which rebuilds everything: the data is generated again, the audit log is emptied and the embeddings are removed. That's slow on camera, and it throws away the audit rows the video wants to show.

**The command:** `uv run python -m insurance_database.update_db`. It connects as the admin role (`ADMIN_DATABASE_URL`, as `setup_db` does), runs one SQL file in one transaction, and prints what it did. It changes only the `mcp` schema. The data, the embeddings, the audit log, `caller_states`, the roles and the `mcp_reader` password are left as they are. If anything fails, nothing changes. If the database hasn't been set up yet, it says to run `setup_db` first.

**The file it runs: a new `080_mcp_functions.sql`.** It starts with

```sql
drop schema if exists mcp cascade;
create schema mcp authorization mcp_owner;
grant usage on schema mcp to mcp_reader;
```

and then creates every `mcp` function, each followed by its grant. Dropping the schema, rather than `create or replace function`, is the point:

- **A removed or renamed function goes, along with its grant.** With `create or replace`, the old one would stay behind and `mcp_reader` could still call it. And changing a function's arguments would add a second function with the same name.
- **A function's columns can change.** PostgreSQL refuses `create or replace` when the returned columns change, which is likely while a tool's columns are being decided.
- **No leftovers:** what's in the file is exactly what's in the schema.

That's safe because nothing else lives in `mcp`: the tables, the helpers and the audit log are all in `insurance`.

**The files move to make that work:**

| File | Before | After |
|------|--------|-------|
| `020_schema.sql` | creates both schemas | creates `insurance` only |
| `030_permissions.sql` | grants `usage on schema mcp` | moves to `080` |
| `04_functions.sql` | the helpers and the `mcp` functions | renamed `040_helpers.sql`: the helpers only |
| `050_audit.sql` | the audit log and `mcp.write_audit` | the audit log only. `write_audit` moves to `080`, because dropping the schema drops it |
| `080_mcp_functions.sql` | (new) | the schema, `write_audit` and every `mcp` function, with their grants |

`setup_db` still runs every file in order. `010_roles.sql` still drops both schemas first, so a full rebuild is unchanged. The "What can `mcp_reader` do at this point?" notes at the end of each file, and the `mcp-reader-permissions` guide, follow the new order: `mcp_reader` can run nothing until `080`.

**What it doesn't do:** change tables or helpers. A new table, a new column or a changed helper still needs `setup_db`. Adding a table without a rebuild is decision 17.

**The server can stay running** while it runs. Calls made during the reload wait until it finishes, which takes a moment. Restart the server afterwards to pick up a new or changed Python tool, as the skill already says. *Check during the build:* the server's pooled connections keep working after the functions are recreated, because psycopg prepares a statement after it's been used five times.

**Tests** (`tests/database/test_update_db.py`, on `small` data):

- The data, the embeddings and the audit log are the same afterwards, and `verify_audit_log()` still finds no broken row.
- A function created by hand in `mcp` is gone afterwards.
- The permissions are exactly the same as after `setup_db` (the existing permissions snapshot).
- A file with an error leaves every function as it was. `update_db` takes the file's path as an argument, defaulting to `080_mcp_functions.sql`, so this test can pass it a broken copy.

**Docs that change:** decision 12's file list, the add-an-insurance-tool skill (functions go in `080_mcp_functions.sql`, and step 9 runs `update_db` unless a table was added) and its spec, appendix B's setup output, the `mcp-reader-permissions` guide, guide 2 and the "Using this with your own data" page (file names), and the troubleshooting page if it lists the commands.

## 17. Adding a table without a rebuild: `070_added_tables.sql`

**Status:** Agreed (Liam, 2026-11-18)

**The problem:** video 5 adds a table (the adjusters' manual, searched by meaning) on camera. Until now a new table went in `020_schema.sql` and needed `setup_db`, which makes the data again, empties the audit log and removes the embeddings. Liam's bar: "create a new table, load some data, add a function: then we're done", not a migration tool.

**The fix: one more file, run by both commands.**

- **New tables go in `sql/070_added_tables.sql`,** never in `020_schema.sql`. On `main` it holds only comments: the rules and an example. Each table brings its own `grant select` to `mcp_owner` and, if it holds customer data, its own row-level security, so the file stands alone.
- **`update_db` runs `070` and then `080`, in one transaction.** If anything fails, nothing changes, as before. `setup_db` runs it in order with the others, so a fresh setup builds the same database.
- **Everything in `070` is safe to run twice:** `create table if not exists`, `insert ... on conflict do nothing` for a short fixed list, `drop policy if exists` before `create policy`. Grants are safe to repeat already.
- **The data:** text searched by meaning is loaded by the embed command, which skips what's already loaded, so `embed --booklets-only` loads a new table's text in seconds. A short fixed list loads with the file. Rows from the data generator still need `setup_db`.
- **The files are renumbered in tens** (`010_roles.sql` to `080_mcp_functions.sql`), so `070` fits before the functions. The functions must come after the tables they read: `setup_db` runs the files in name order, and PostgreSQL checks a `language sql` function's tables when it's created. Nothing had been recorded yet, so this was the cheapest time to rename.

**What it doesn't do:** change a table that's already there. `create table if not exists` leaves it as it is, so a changed table needs `setup_db`. No `alter table` in `070`: that's where a migration tool starts.

**Tests** (`tests/database/test_update_db.py`): a table added to a copy of `070` loads through `update_db`, keeps its rows when the update runs again, and `mcp_reader` still can't read it. The existing setup tests run the real `070` as part of every setup.
