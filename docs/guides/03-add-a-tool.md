# Guide 3: add a tool

This is the guide for [video 3 on YouTube](https://www.youtube.com/@CodeExpressAI).

## Before you begin: if you get stuck

Your code will look a bit different from the video: the AI writes it fresh each time. If you get stuck, compare with the [`video-3-done`](https://github.com/Code-Express-AI/insurance-mcp-python/tree/video-3-done) branch, which has the finished tool and passes every test. Or switch to it and carry on from there. `git stash -u` puts your own changes aside first, new files included, so the switch doesn't refuse. `git pull` gets the latest copy of the branch:

```bash
git fetch
git stash -u
git switch video-3-done
git pull
uv run python -m insurance_database.update_db
```

Then restart the server, and reconnect your assistant (see [load it](#load-it)). If the database still seems wrong, rebuild it with `uv run python -m insurance_database.setup_db`. If you forked the repository, your fork may not have the branch: GitHub copies only `main` unless you untick that box when you fork.

## Part 1: with GitHub Copilot

### Install the skill

There's nothing to install: the skill comes with the repo, and Copilot loads it automatically when you ask Copilot to use it. The skill is in plain English, and you can [read it here](../../skills/add-an-insurance-tool.md).

### Use it

1. Open the repository folder in VS Code. Open the Chat view, and choose **Agent** mode.
2. Ask:
   > Use the add-an-insurance-tool skill to add a new tool called get_customer_with_policies. It should return one customer with all their policies, including each policy's vehicle and drivers.

   **Why name the vehicle and drivers?** Policies, vehicles and drivers are in separate tables. Ask only for the policies, and you'll likely get the policy table's columns and nothing more. The more you know about the business and the database underneath, the better the code the assistant writes.
3. It shows its plan first, and waits. Read it, then tell it to go ahead.
4. It writes the function, the grant, the Python tool and the tests, then runs the checks. Allow the commands when it asks.
5. It ends with the new SQL function, its grant, and a list to check. Read them: the AI wrote the function and the tests, so they can share a mistake.
6. [Load it](#load-it), then [try it yourself](#try-it-yourself).

Tested on Copilot's free plan on November 19, 2026. Copilot chose gpt6-luna as the model, and the code was clean, passed every test and worked first time.

## Part 2: with Claude Code

### Install the skill

There's nothing to install here either: Claude Code loads the same skill automatically when you ask Claude Code to use it. You can [read it here](../../skills/add-an-insurance-tool.md).

### Use it

1. In a terminal in the repository folder, start Claude Code with `claude`.
2. Ask the same thing:
   > Use the add-an-insurance-tool skill to add a new tool called get_customer_with_policies. It should return one customer with all their policies, including each policy's vehicle and drivers.

   Or type `/add-an-insurance-tool` followed by the request.

   **Why name the vehicle and drivers?** Policies, vehicles and drivers are in separate tables. Ask only for the policies, and you'll likely get the policy table's columns and nothing more. The more you know about the business and the database underneath, the better the code the assistant writes.
3. It shows its plan first, and waits. Read it, then tell it to go ahead.
4. It writes the function, the grant, the Python tool and the tests, then runs the checks. Allow the commands when it asks.
5. It ends with the new SQL function, its grant, and a list to check. Read them: the AI wrote the function and the tests, so they can share a mistake.
6. [Load it](#load-it), then [try it yourself](#try-it-yourself).

## Part 3: by hand

The same steps, typed in yourself. Each step says what the code is for, so it's also a good way to check what the assistant wrote in parts 1 and 2.

### Step 1: the SQL function

Open [`sql/080_mcp_functions.sql`](../../sql/080_mcp_functions.sql). Near the end, find the line `reset role;`, just above the comment "What can mcp_reader do at this point?". Paste this above that line:

```sql
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
```

It's `get_customer` and `get_policy` put together, so most of it will look familiar. What each part is for:

- **`security definer` and `set search_path = ''`.** The function runs as its owner, `mcp_owner`, which may read the tables. `mcp_reader` can't. The empty `search_path` means every name is written out in full (`insurance.customers`), so nobody can slip in a table of their own with the same name.
- **Fixed columns.** `returns table (...)` lists exactly what comes back. No `select *`, so a column added to the table later doesn't leak out through this function.
- **Public ids only.** `cu.public_id` goes out as `customer_id`. The `id` column, used for joins, never leaves the database.
- **No personal data the question doesn't need.** No street address, phone number or date of birth. The email and the driver's license number are masked, and drivers get an age instead of a birthday.
- **One row, with the policies as a list.** `jsonb_agg` builds the list of policies in the database, each with its list of drivers. One function call means one audit row.
- **A row limit.** It returns one customer at most, found by their id. A customer has only a few policies, so the list stays short.
- **Not found.** A made-up id gets the same message as a customer this caller isn't allowed to see. So the message doesn't confirm who exists.
- **Row-level security** needs no code. Each caller sees only its own states' customers, because the rule is on the tables.

**Why the prefixes and aliases?** In a plpgsql function that `returns table`, every output column is also a variable. A bare `state` would be ambiguous: the output column or the table's column? So the argument starts with `p_`, every table has an alias, and every column has its table's alias in front (`cu.state`).

### Step 2: the grant

Straight after the function, add:

```sql
grant execute on function mcp.get_customer_with_policies(uuid) to mcp_reader;
```

That's the whole permission change. `mcp_reader` can now call this one function. It still can't read a single table.

Optionally, add `get_customer_with_policies` to the list in the "What can mcp_reader do at this point?" comment at the end of the file, so the comment stays true.

### Step 3: the Python tool

Open [`server/src/insurance_mcp/tools.py`](../../server/src/insurance_mcp/tools.py). Find `get_policy`, and add this after it:

```python
async def get_customer_with_policies(
    ctx: Context,
    customer_id: Annotated[UUID, Field(description="From find_customers.")],
) -> dict[str, Any]:
    """Return one customer with every policy in full: coverage level, yearly premium,
    deductible, dates, status, vehicle and listed drivers.

    Use this instead of get_customer followed by get_policy for each policy.
    coverage_level: liability (damage to others only), liability_collision (plus the
    customer's own car in a crash) or full (plus theft, fire, vandalism, weather and glass).
    deductible: what the customer pays on each claim before the insurer pays.
    """
    rows = await run(ctx, "get_customer_with_policies", customer_id=customer_id)
    return rows[0]
```

Then add it to the `TOOLS` list further down, after `get_policy`:

```python
TOOLS = [
    get_dataset_info,
    find_customers,
    get_customer,
    get_policy,
    get_customer_with_policies,
    search_claims,
    ...
]
```

That's all the Python. Being in `TOOLS` registers the tool, marks it read-only and puts it through the unknown-argument check. What each part is for:

- **The docstring is what the model reads.** It says what comes back, explains the insurance words, and says when to pick this tool over `get_customer`. With two similar tools, the docstring is how the model chooses.
- **The argument has a type.** `UUID` means anything that isn't one is rejected before the database is called, with a message the model can act on.
- **One database call.** `run` calls `mcp.get_customer_with_policies` as `mcp_reader` and writes the audit row. The keyword name is the SQL argument's name without `p_`.

### Step 4: the tests

Two tests list every grant and every tool exactly, so nothing can be added without anyone noticing. A new one turns them red until you add it on purpose. Two small changes:

**The grant.** In [`tests/database/test_reader_permissions.py`](../../tests/database/test_reader_permissions.py), add the new function to `expected`, after `get_customer` (the list is in alphabetical order):

```python
        ("function mcp.get_customer", "EXECUTE"),
        ("function mcp.get_customer_with_policies", "EXECUTE"),
```

**The tool.** In [`tests/server/test_tools.py`](../../tests/server/test_tools.py), change `test_every_tool_has_an_end_to_end_test` to:

```python
def test_every_tool_has_an_end_to_end_test():
    not_in_tool_calls = {"get_customer", "get_customer_with_policies"}
    assert {name for name, _ in TOOL_CALLS} | not_in_tool_calls | RAG_TOOLS == set(TOOL_ARGUMENTS)
```

Now run the checks. Docker must be running: the tests start their own throwaway database, and don't touch yours.

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

Every test should pass. The security checks need nothing new: `test_function_rules.py` already checks that every `mcp` function is `security definer` with a fixed `search_path`, and the permission tests check that `mcp_reader` still can't read a single table. You test the tool itself when you [try it yourself](#try-it-yourself).

## Load it

In a terminal in the repository folder:

1. Stop the MCP server (`Ctrl+C`).
2. Reload the functions. This keeps the data, the embeddings and the audit log. It runs in one transaction, so if your SQL has a mistake, it tells you and nothing changes.
   ```bash
   uv run python -m insurance_database.update_db
   ```
3. Start the server again:
   ```bash
   uv run python -m insurance_mcp.main
   ```
4. Make the assistant see the new tool. In Copilot, run **MCP: List Servers**, choose `insurance`, then **Restart Server**. In Claude Code, run `/mcp` and reconnect `insurance`.

## Try it yourself

**Ask a question.** In a new chat:

> Show me Eleanor Rutherford and all her policies, with the deductibles.

The assistant should call `find_customers`, then `get_customer_with_policies`, with no `get_policy` calls. She has two policies: a 2022 Subaru Outback with full coverage and a $1,000 deductible, and a 2015 Ford F-150 with liability and collision and a $500 deductible. If it calls `get_customer` and `get_policy` instead, it hasn't seen the new tool: go back to [load it](#load-it), part 4.

**Check the audit log.** Every call is recorded. Look at the latest rows:

```bash
docker compose exec db psql -U postgres -d insurance -c "select occurred_at, caller, tool_name, rows_returned, succeeded from insurance.audit_log order by id desc limit 5"
```

You should see one `get_customer_with_policies` row, just after a `find_customers` row.

**Check what it refuses.** Ask for a customer that doesn't exist, such as "Use get_customer_with_policies with customer_id 00000000-0000-0000-0000-000000000000". The tool returns "Unknown customer_id. Use find_customers to find it.", and the audit log records the failed call.

**Optional: MCP Inspector.** To call the tool without a model in the way, connect [MCP Inspector](appendix-a-server-security.md#optional-call-a-tool-from-mcp-inspector), open the tool list, and you'll see `get_customer_with_policies` with its description: exactly what the model reads. Call `find_customers` with `Rutherford`, then the new tool with the `customer_id` it returns.

## If something goes wrong

**"The database could not complete this request."** That's all the assistant gets when the function fails, on purpose: a database error can give away table and column names. The real error is in the terminal where the server runs, just after `The database call for get_customer_with_policies failed`. The last line of that error tells you which of these it is:

| The server's terminal says | Why, and the fix |
|---|---|
| `column reference "..." is ambiguous` | A column without its table's alias in front, such as `state` instead of `cu.state`. See the end of step 1. PostgreSQL only checks this when the function first runs, so `update_db` doesn't catch it. |
| `permission denied for function get_customer_with_policies` | The grant is missing, or its argument types aren't `(uuid)`. |
| `function mcp.get_customer_with_policies(...) does not exist` | `update_db` hasn't run since you added the function, or it stopped with an error. |

Other problems:

| What you see | Why, and the fix |
|---|---|
| `update_db` says `080_mcp_functions.sql has an error, so nothing changed` | A typo in the SQL. The message below it names the problem. Your old functions are still there. |
| `Unknown tool: get_customer_with_policies` | The Python tool isn't in `TOOLS`, or the server is still running the old code. Restart it. |
| The assistant doesn't use the new tool | The server wasn't restarted, or the assistant wasn't reconnected ([load it](#load-it)). Start a new chat too. |

More problems and their fixes are in [guide 1](01-quickstart-help.md).
