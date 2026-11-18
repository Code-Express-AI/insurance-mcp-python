# How mcp_reader is locked down, step by step

This guide follows the SQL setup scripts in order. It shows how the MCP server reads business data through a few approved functions, while its database role, `mcp_reader`, can't touch the tables at all.

For the hands-on version, see [guide 4: database security](./04-database-security.md).

## 1. Create separate roles

[`01_roles.sql`](../../sql/01_roles.sql) creates three PostgreSQL roles, one per job:

```sql
create role insurance_owner nologin;
create role mcp_owner nologin;
create role mcp_reader login;
```

- `insurance_owner` owns the business tables and the audit log.
- `mcp_owner` owns the MCP functions.
- `mcp_reader` is the role the MCP server logs in as. It owns nothing.

`NOLOGIN` means nobody can connect as the two owners. The script also limits `mcp_reader` to 10 connections and gives it a 5-second statement timeout.

At this point `mcp_reader` can already connect to the database and create temporary tables. It hasn't been granted either right: it gets them from `PUBLIC`, a built-in group that every role belongs to. Step 3 takes them away.

## 2. Make insurance_owner own the tables

[`02_schema.sql`](../../sql/02_schema.sql) creates the `insurance` schema for `insurance_owner`, then switches to that role before creating the tables:

```sql
create schema insurance authorization insurance_owner;
set role insurance_owner;
```

Everything created after `set role insurance_owner` belongs to `insurance_owner`, not to `mcp_owner` or `mcp_reader`.

## 3. Take away the defaults, and let mcp_owner read the tables

[`03_permissions.sql`](../../sql/03_permissions.sql) starts by removing `PUBLIC`'s defaults. It revokes `CONNECT` and `TEMPORARY` on the database from `PUBLIC`, then grants `CONNECT` back to `mcp_reader` by name. It also stops `PUBLIC` creating objects in the `public` schema.

The big gotcha: by default, `PUBLIC` can run every new function. The script turns that off for functions created by the two owners:

```sql
alter default privileges for role insurance_owner
    revoke execute on functions from public;
alter default privileges for role mcp_owner
    revoke execute on functions from public;
```

So a new function isn't callable by `mcp_reader` until someone grants it.

Next, `mcp_owner` gets `USAGE` on `insurance` and `SELECT` on each business table. For example:

```sql
grant select on insurance.customers to mcp_owner;
```

`mcp_owner` gets no `INSERT`, `UPDATE` or `DELETE` on the business tables. The audit log is different, and comes in step 4.

`mcp_reader` gets nothing on `insurance`, not even `USAGE`. It can connect, but there's nothing it can run yet.

[`04_helpers.sql`](../../sql/04_helpers.sql) adds small helper functions in `insurance`, such as the masking ones. They're granted to `mcp_owner` only, so `mcp_reader` still can't run anything.

## 4. Let mcp_owner add to the audit log, and nothing more

[`05_audit.sql`](../../sql/05_audit.sql) creates the audit log as `insurance_owner`. Unlike the business tables, `mcp_owner` must write to it, to add a row after each tool call. It gets `INSERT` on the table, and `SELECT` on just two columns, `id` and `row_hash`, to find the previous row's hash:

```sql
grant insert on insurance.audit_log to mcp_owner;
grant select (id, row_hash) on insurance.audit_log to mcp_owner;
```

Triggers block any update, delete or truncate of the log. `mcp_reader` gets nothing here: it adds rows through a function, `mcp.write_audit`, in step 6.

## 5. Filter which rows the functions will see

[`06_row_security.sql`](../../sql/06_row_security.sql) turns on row-level security for the tables that hold customer data, with policies for `mcp_owner`. The functions run as `mcp_owner`, so the policies filter what they return.

Before each call, the server sets a session value that says who's calling. Each caller sees only the customers in its own states. With no value set, the functions return no rows, which is why [guide 4](./04-database-security.md) gets counts of 0 at first.

The database trusts the server to set that value. Anyone with the `mcp_reader` password can set it themselves, so row-level security filters rows, but it doesn't prove who the caller is.

## 6. Create the MCP functions as mcp_owner

[`07_mcp_functions.sql`](../../sql/07_mcp_functions.sql) creates the `mcp` schema for `mcp_owner`, and gives `mcp_reader` `USAGE` on it. Then it switches to `mcp_owner` before creating the functions, so `mcp_owner` owns them:

```sql
create schema mcp authorization mcp_owner;
grant usage on schema mcp to mcp_reader;
set role mcp_owner;
```

Every function is marked `SECURITY DEFINER`. For example, `mcp.get_dataset_info` includes:

```sql
security definer
set search_path = ''
```

`SECURITY DEFINER` runs the function with its owner's rights, not the caller's. So when `mcp_reader` calls one, the function's queries run as `mcp_owner`, which can read the business tables but not change them. Those rights stay inside the function: `mcp_reader` doesn't gain them.

Each function is granted to `mcp_reader` on its own, on the line after it:

```sql
grant execute on function mcp.get_dataset_info() to mcp_reader;
```

`mcp_reader` can only run the functions granted this way. The read functions return fixed columns and a limited number of rows. The one write function, `mcp.write_audit`, adds a row to the audit log and returns nothing, so `mcp_reader` can add to the log but can't read or change it.

The empty `search_path` matters too. Every function writes each name in full, such as `insurance.claims`, so a caller can't create a look-alike table and trick the function into reading it.

This file comes last, and it starts by dropping the `mcp` schema, so it can run again on its own: `uv run python -m insurance_database.update_db` reloads the functions without touching the data or the audit log.

## What the permissions don't stop

Permissions don't stop a role from sending SQL. `mcp_reader` can run `select 1`, or set the session value from step 5. What they stop is reading the tables or changing data directly: the data is only reachable through the granted functions.

The MCP server only offers those functions, as named tools. It has no raw-SQL tool. Someone who connects as `mcp_reader` directly can still send SQL, but PostgreSQL refuses anything it hasn't been granted.

`mcp_reader` can also read the system catalogs, as every PostgreSQL role can. Connect with a database tool such as DBeaver and it lists the `insurance` schema with every table and column, and shows the source code of every function, even without `USAGE` on the schema. It sees the names but not the data: opening a table gives "permission denied". PostgreSQL doesn't support hiding the catalogs, and clients rely on them, so the setup doesn't try.

For the decisions behind these permissions, see [database-spec.md](../specs/database-spec.md).

## In short

`mcp_reader` can run a short list of functions, and the functions do the reading as `mcp_owner`. That only stays safe while `mcp_owner` has the bare minimum of rights and each function does only its one job.
