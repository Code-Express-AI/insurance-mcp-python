# Database specification

The detail behind decision 3 in [spec.md](spec.md). It says how the PostgreSQL database is built and, above all, how it's locked down. Locking the database down is the whole point of the project.

Everything here follows normal PostgreSQL conventions.

**Portable by design:** the same scripts must run unchanged on the local Docker database and on a hosted PostgreSQL service such as Neon (decision 14). So nothing may need a real superuser, the setup can't rely on Docker-only features, and the only difference between the two is the connection string.

**Signed off by Liam on 2026-11-05.** Every decision below is Agreed.

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

**What we can't lock down:** every role can read the system catalogs, which include table names, column names and the source code of every function. Revoking this breaks normal tools. Every role can also run PostgreSQL's built-in functions, such as `pg_sleep()`, and any extension's functions, such as pgvector's. Our revoke only covers functions our two owners create. Both only matter if someone can send raw SQL, which the MCP server never allows (layer 3). The docs say so plainly.

**Honest limit: every token sees every customer.** There's no "this client can't see these customers". PostgreSQL's row-level security (RLS) is the natural next step: a policy on each table filters rows for every query, so no function can forget to. A possible later extra would hide VIP customers from some clients, with a second reader role (`mcp_reader_vip`) for the clients allowed to see them. The policies would check `session_user`, not `current_user`, because inside our `SECURITY DEFINER` functions `current_user` is always `mcp_owner`. Not built in this project.

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
- **Read functions are marked `STABLE`.** This is a second guard, not just a hint to the planner: PostgreSQL refuses to run `INSERT`, `UPDATE` or `DELETE` inside a `STABLE` PL/pgSQL function.
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

**Periods**, worked out from the as-of date (31 December 2026), in whole calendar months:

| Period | Dates | Example |
|---|---|---|
| `last_month` | The calendar month before the as-of month | November 2026 |
| `last_3_months` | The as-of month and the 2 before it | October to December 2026 |
| `last_12_months` | The as-of month and the 11 before it | January to December 2026 |
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

**Free text** (claim descriptions and notes) is cleaned by a third helper, `insurance.redact_text()`, wherever an `mcp` function returns it (`get_claim` and the RAG functions). It uses `regexp_replace` to replace phone numbers and email addresses with `[phone]` and `[email]`. The model doesn't need contact details for any of our questions, and with a hosted model every tool result leaves the machine. **What it can't catch:** names, street addresses and injuries. Patterns are easy to match, meaning isn't, and the docs say so. The masking test (decision 13) also checks that no planted phone number or email comes back.

**Everything else** is simpler than masking: a column that no tool needs (street address, date of birth, phone) is just left out of every function's fixed columns (decision 7). Names, city, state and license plates are returned as they are, because the demo questions use them.

## 10. Audit log

**Status:** Agreed

Table `insurance.audit_log`: `id`, `occurred_at`, `caller` (the token's name, such as `claude-code`: see spec decision 4), `tool_name`, `arguments` (`jsonb`), `rows_returned`, `duration_ms`, `succeeded`, `error`, `previous_hash`, `row_hash`.

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
- **Whoever has the `mcp_reader` password can write audit rows directly.** `mcp.write_audit` must be granted to `mcp_reader`, because the server calls it. So anyone who connects as `mcp_reader` without going through the server can add rows with any caller name, or flood the table with rows that can never be deleted. Calling the data functions directly isn't audited at all, because the server writes the audit rows, not the functions. **The database limits *what* can be done; the server records *who* did it.** Keep the reader password long and secret (decision 12), and on a hosted database, restrict who can connect (decision 14).
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
  - `01_roles.sql`
  - `02_schema.sql`
  - `03_permissions.sql`
  - `04_functions.sql`
  - `05_audit.sql`
- **One small Python setup command runs the files in order**, connecting as the admin role through a connection string in `.env`. It's the same command for Docker and Neon. We don't use Docker's `/docker-entrypoint-initdb.d`, because it only exists in Docker. We don't use `psql` either, because many Windows users won't have it installed, and the project needs Python anyway.
- The `.sql` files are plain SQL with no `psql` commands, so any tool can run them.
- **The `mcp_reader` password** comes from `.env`. The setup command sets it after running the files, with the value passed safely by psycopg. No password is ever written in a committed file. **The setup refuses a password shorter than 24 characters**, so nobody uses `password123`, even locally.
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
- No function returns an unmasked email or driver's license number, or any street address, date of birth or phone number.
- `UPDATE`, `DELETE` and `TRUNCATE` on the audit log fail even as the admin role, while the trigger is enabled.
- The audit log is the only table with triggers. The test checks the system catalogs, so a trigger added anywhere else fails it.
- `verify_audit_log()` passes on a clean log and reports the right row after a deliberate edit (the test disables the trigger as the admin role to make the edit).
- A query that runs past the statement timeout is canceled.
- No `mcp` function returns an internal `bigint` id. The test checks every function's result columns in the system catalogs.
- `mcp_owner` has no `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` on any business table, and owns nothing in `insurance`. The test checks the system catalogs.
- A `STABLE` function that tries to write fails. The test creates one as `mcp_owner` to prove the guard holds.
- Every `mcp` function is `SECURITY DEFINER`, has `search_path` set, and is owned by `mcp_owner`. The test checks the system catalogs, so a function added later can't skip these rules.

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
