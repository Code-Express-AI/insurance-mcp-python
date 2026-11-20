# Guide 2: SQL injection and prompt injection

This is the guide for [video 2 on YouTube](https://www.youtube.com/@CodeExpressAI).

## Attack 1: SQL injection

In 2025, researchers showed that the MCP project's own reference PostgreSQL server, which promised read-only access, could be made to run `COMMIT; DROP SCHEMA public CASCADE;`. That's **SQL injection**: the model wrote the SQL, and the database ran it.

- [Datadog Security Labs' report](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/) (August 2025)
- [The archived server on GitHub](https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres)

## Attack 2: prompt injection

In 2025, researchers showed that a support ticket written by an attacker could make a developer's AI assistant read secrets through Supabase's MCP server and post them back into the ticket. That's **prompt injection**: the model treated text it read as instructions, and its login could read every table.

Text the model reads is untrusted input: a support ticket here, and in RAG, every document it retrieves.

- [General Analysis's report](https://generalanalysis.com/blog/supabase-mcp-blog) (July 2025)

## The architecture: you know most of it already

| A web app you've built | This server |
|---|---|
| Front end | The AI assistant: Copilot or Claude Code |
| FastAPI | The MCP server: FastAPI, with the MCP SDK's `MCPServer` mounted at `/mcp` |
| An ORM: SQLAlchemy, Django's or SQLModel | No ORM: [psycopg](https://www.psycopg.org/psycopg3/) calls one PostgreSQL function per tool |
| PostgreSQL | PostgreSQL, where the server's login can only run those functions |

- **Seen `FastMCP` in tutorials?** Version 2 of the MCP SDK renamed it `MCPServer`, and the old import gives an error.
- **Why no ORM?** The login can only call functions, so there's nothing for an ORM to map. If your team uses SQLAlchemy, keep it: the security is in the database, not the Python.
- **The only permission the login gets** is to run each function, one grant per tool ([sql/080_mcp_functions.sql](../../sql/080_mcp_functions.sql)):

```sql
grant execute on function mcp.find_customers(text) to mcp_reader;
```

## See it for yourself

Run these from the repository folder, with the database running.

As `postgres`, the admin role: the query returns the records.

```bash
docker compose exec db psql -U postgres -d insurance -c "select first_name from insurance.customers limit 5;"
```

As `mcp_reader`, the login the MCP server uses: the same query gets permission denied on the `insurance` schema, so it can't reach the table.

```bash
docker compose exec db psql -U mcp_reader -d insurance -c "select first_name from insurance.customers limit 5;"
```

As `mcp_reader` again, calling the functions works, with the email and driver's license masked.

```bash
docker compose exec db psql -U mcp_reader -d insurance -x -c "select set_config('mcp.caller_key', 'local', false); select first_name, last_name, city, state, email, drivers_license_number from mcp.get_customer((select customer_id from mcp.find_customers('Eleanor Rutherford')));"
```

- `set_config` sets the caller, as the server does on every call. Leave it out and the server's login sees no customers, so you get `Unknown customer_id`.
- No password asked? The container trusts connections from inside itself. The MCP server connects from outside, and always needs one.

## Summary

The model never writes SQL, so SQL injection has nothing to get into. And the server's login can only run the functions, so a model fooled by prompt injection can only reach what those functions return. Prompt injection isn't solved, but if an attack gets through, the layers of security limit the damage.
