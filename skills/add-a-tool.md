# Add a tool

How to add a new read-only tool to this MCP server, and a new table for it if it needs one. Follow the steps in order, and don't skip any.

Every tool has the same four parts:

1. **A PostgreSQL function** in the `mcp` schema. It's the only thing that reads the data.
2. **One grant**, so the server's database login (`mcp_reader`) can call that function and nothing more.
3. **A Python tool** in the server. It checks the arguments and calls the function.
4. **Tests** that prove the security still holds.

A new table adds three more: the table, where its data comes from, and who may read it.

## Never

If the request needs any of these, stop and explain why to the human. Don't find a way round it.

- A tool that changes data (insert, update or delete), or that runs SQL it's given.
- A grant on a table to `mcp_reader`. It may only execute `mcp` functions.
- Insert, update or delete rights for `mcp_owner`.
- Changing an existing tool, function, role or grant, unless the human asks for that change.
- Real data about real people. All data is made up.
- Fixing a red test by weakening the test.

## Step 1: plan, then wait

Before writing any code, tell the human:

- The tool's name (`snake_case`, a verb first, such as `get_...`, `find_...`, `count_...`).
- Its arguments, and the limits on each.
- The columns it returns, and the most rows it can return.
- Whether it needs a new table. If so, the table's columns and where its data comes from (step 2).
- The existing function in `sql/080_mcp_functions.sql` closest to it, to copy its shape.

Then wait for the human to agree.

## Step 2: a new table (skip if the tool reads tables that exist)

**The table.** Add it to `sql/070_added_tables.sql`, never to `sql/020_schema.sql`. `update_db` runs that file again every time, so it loads a new table without a rebuild. Everything in it must be safe to run twice, as the comment at the top of the file says. Inside `set role insurance_owner;` ... `reset role;`, write `create table if not exists`, and follow the rules of the other tables:

- `id bigint generated always as identity primary key` for joins. It never leaves the database.
- `public_id uuid not null unique default gen_random_uuid()` if a tool will look a row up by key. It's returned as `<thing>_id`.
- A foreign key to its parent's `id`, and an index on that column (PostgreSQL doesn't add one by itself).
- Lowercase `snake_case` names, a plural table name, `text` codes with a `check` for fixed lists, `numeric(12,2)` for money.
- `check` constraints for formats, with `[0-9]`, never `\d`.

**Who may read it.** In the same file, after `reset role;`: `grant select on insurance.<table> to mcp_owner;`. Select only.

**Customer data?** If the table holds anything about a customer, or hangs off a table that does, add row-level security in the same file: enable it, then `drop policy if exists` and one `for select to mcp_owner` policy that asks "is my parent row visible?", like the policies in `sql/060_row_security.sql`. Then add the table to `FILTERED_TABLES` in `tests/database/test_row_security.py`. If it holds no customer data, leave it out of both.

**Where the data comes from.** Pick one:

| The data is | Load it with | Where |
|---|---|---|
| A short fixed list (a few dozen rows at most) | `insert ... values ... on conflict do nothing` straight after `create table`, with a `unique` column so a second run adds nothing | `sql/070_added_tables.sql` |
| Many rows linked to customers, policies or claims | The data generator | `database/src/insurance_database/generate/` |
| Text to search by meaning (RAG) | A markdown file, loaded and embedded by the embed command | See step 3 |

For the data generator: add a record class in `records.py`, make the rows in `random_data.py` with the generator's `rng` (never `random` directly, so the data is the same for everyone), load them in `database.py` with `copy_rows`, and add the table to `BUSINESS_TABLES` there so a reload empties it. Make the new rows at the end of `build_dataset` in `__init__.py`. Making them earlier changes every row after them.

**What data to load.** Made up, and believable for a US auto insurer:

- US places, ZIP codes and dollars. Phone numbers only in the fictional `555-01xx` range, and emails only `@example.com`.
- No real people, companies or vehicles' owners. Common brand names (car makes, stores) are fine.
- Enough rows for the tool to be worth trying, and no more. Most tools need tens or hundreds, not thousands.

## Step 3: text to search by meaning (skip unless the tool searches by meaning)

- **The column:** `embedding public.vector(384)`. The model, `all-MiniLM-L6-v2`, makes 384 numbers. No index on it: every search is exact, which is fast enough at this size.
- **The text:** a markdown file in `database/src/insurance_database/`. If the human names a file that's already there, use it as it is. Never put it in `booklets/`: the embed command loads every file there as a coverage level. Split it into sections at its `## ` headings with `split_booklet` in `embed.py`. Each section is about one topic and is one row.
- **Short sections:** the model reads at most 256 word pieces and silently ignores the rest, which is roughly 150 words. Add the new file to `test_every_text_fits_in_what_the_model_reads` in `tests/rag/test_embedding_model.py`.
- **Loading:** add a function to `embed.py`, copying how the booklets are loaded: skip if the table already has rows, embed `heading + "\n" + content` with `model.passage_embed`, insert, commit. Call it from `embed_everything` straight after the booklets, so `--booklets-only` loads it too. In `tests/rag/test_embedding_model.py`, delete its rows wherever the booklets' rows are deleted: the `embedded` fixture's clean-up and the `--booklets-only` test.
- **The search function** (step 4) takes `p_embedding real[]` and turns it into a vector with `insurance.to_vector(p_embedding)`, which raises an error unless it's exactly 384 numbers. If the table is empty, it raises `'Run the embed command first.'`. It orders by `embedding operator(public.<=>) v_query` and returns a `similarity` of `round((1 - distance)::numeric, 3)`. Copy an existing search function in `sql/080_mcp_functions.sql`.

## Step 4: the SQL function

Add it to `sql/080_mcp_functions.sql`, after the other `mcp` functions, with a one-line comment above it saying what it returns. Copy the shape of the closest one (step 1). Every rule below is already followed by the functions in that file.

- `language plpgsql` (or `sql`), `stable`, `security definer`, `set search_path = ''`.
- Every name written in full: `insurance.claims`, `insurance.mask_email(...)`.
- `returns table (...)` with fixed columns. Never `select *`, `returns setof`, `execute` or `format()`.
- **Names can't clash.** In a plpgsql `returns table` function, every output column is also a variable. So: start every argument with `p_`, give every table an alias and put it in front of every column (`c.status`), and order by position (`order by 2`, with a comment saying which column) when ordering by an output column.
- **Public ids only.** Return `public_id` as `<thing>_id`. Never the `id` column, and nothing of type `bigint`: cast counts with `::integer`.
- **No personal data the question doesn't need.** Never a street address, phone number or date of birth (return an age instead). Emails go through `insurance.mask_email()`, license numbers through `insurance.mask_last4()`, and free text written by people through `insurance.redact_text()`.
- **A row limit on every result.** A fixed `limit`, or a `p_limit` / `p_page` clamped with `least(greatest(coalesce(p_limit, <default>), 1), <max>)`. The Python tool checks it too. The function checks it again, so a bug in the server can't return the whole table.
- **A parent with its children is one row**, with the children as a `jsonb` list: `coalesce(jsonb_agg(jsonb_build_object(...) order by ...), '[]')`. Not two functions, and not put together in Python.
- **Counts by month or by band return every month or band**, zeros included. Use `generate_series` and a left join, so a gap can't be misread as "no data".
- **Dates come as a period name**, never as raw dates from the model. Use `insurance.period_dates(p_period, insurance.as_of_date())`, which raises an error for an unknown name. It uses the data's own "today", not the real one.
- **Text searches** with `like` or `ilike` pass the argument through `insurance.escape_like()`, or a search for `%%` matches every row.
- **Not found.** For a lookup by id or number, after `return query`: `if not found then raise exception 'Unknown <thing>. Use <tool> to find it.'; end if;`. The same message whether the row is missing or the caller may not see it.
- Row-level security needs no code. The policies on the tables filter every query.

## Step 5: the grant

Straight after the function:

```sql
grant execute on function mcp.<name>(<argument types>) to mcp_reader;
```

List the argument types in order, such as `(text, integer)`. Then add the function's name to the "What can mcp_reader do at this point?" comment at the end of the file.

## Step 6: the Python tool

In `server/src/insurance_mcp/tools.py`:

- An `async def <name>(ctx: Context, ...)` with the same name as the SQL function, placed with the others (the search tools go with the RAG tools).
- **The docstring is what the model reads.** First line: what it returns. Then anything the model needs to use it well, and when to use it rather than a similar tool. Explain any insurance word.
- **Every argument has a type with limits and a `Field(description=...)`.** Reuse the argument types at the top of the file (`SearchText`, `QueryText`, `Period`, `ClaimType`, the number patterns, ...). Add a new type only for a new kind of value: a `Literal` for a fixed list, a pattern with `[0-9]` for a number format, and `ge` / `le` on every `int`.
- **Exactly one database call:** `return await run(ctx, "<name>", <argument>=<argument>, ...)`. The keyword names are the SQL argument names without `p_`. A tool that returns one row returns `rows[0]`.
- **A search by meaning** embeds the question first with `embedding = await embed(query)`, and passes `audit_as=` with the question and filters, so the audit log records the question, not 384 numbers. Copy an existing RAG tool.
- **Add it to `TOOLS`.** That registers it, marks it read-only and puts it through the unknown-argument check. No other code is needed.

## Step 7: the tests

Two tests turn red until the tool is added on purpose:

- `tests/database/test_reader_permissions.py`: add `("function mcp.<name>", "EXECUTE")` to `expected` in `test_reader_holds_only_the_rights_the_sql_files_give`, in alphabetical order.
- `tests/server/test_tools.py`: add one call to `TOOL_CALLS`, with the arguments a model would send. For a search by meaning, add it to `RAG_TOOLS` there and to `RAG_TOOL_CALLS` in `tests/server/test_rag_tools.py` instead.

For a search by meaning, the database tests use hand-made embeddings, not the model. In the `fake_embeddings` fixture in `tests/conftest.py`, insert a few dozen rows into the new table with `make_unit_vector(3)`, and delete them at the end, like the booklet rows there.

Then add tests in `tests/database/test_mcp_functions.py` (or `test_rag_functions.py` for a search by meaning), next to the ones like them:

- It returns at most its row limit.
- An unknown id or number raises the "Unknown ..." message, if it looks one up.
- An unknown period raises an error, if it takes one.
- A search by meaning: add its name to `function` in `test_anything_but_384_numbers_is_rejected`, and add a "Run the embed command first" test next to the others at the top of the file (before any test that uses `fake_embeddings`).
- Its result goes into `everything_about_maria_garcia`, if it returns anything about a customer. Then the existing test checks it returns none of her personal data.

`test_function_rules.py` and the table permission tests already check every function and table. Leave them as they are.

## Step 8: check

Run each of these, and fix anything that fails:

```bash
uv run ruff check
uv run ruff format --check
uv run pytest
```

The tests start their own database in Docker, so Docker must be running. They don't touch the human's database. Don't run the setup, update or embed commands yourself: they change the human's database (step 9).

## Step 9: hand over to the human

Show the new SQL function and its grant in full, then this list:

**Check it** (the AI wrote the function and the tests, so they can share a mistake):

- [ ] Every column returned is needed for the question. Nothing personal that isn't masked.
- [ ] There's a row limit.
- [ ] It's `security definer` with `set search_path = ''`.
- [ ] One `grant execute` to `mcp_reader`, on this function only. No grant on a table to `mcp_reader`.
- [ ] A new table: `select` only for `mcp_owner`, and row-level security if it holds customer data.
- [ ] `git diff --stat` shows no file changed that this guide doesn't name.

**Run it**, in a terminal in the repository folder:

1. Stop the MCP server (`Ctrl+C`).
2. Load the new function, and the new table if there is one. This keeps the data, the embeddings and the audit log:
   ```bash
   uv run python -m insurance_database.update_db
   ```
   Only if the new table's rows come from the data generator, rebuild the database instead, which runs every SQL file and makes the data again:
   ```bash
   uv run python -m insurance_database.setup_db
   ```
   That starts the database again from scratch: the audit log is emptied, and the embeddings are removed.
3. If the new tool searches by meaning, or after a rebuild, load the embeddings. This loads the new text and the booklets in seconds, and skips anything already loaded:
   ```bash
   uv run python -m insurance_database.embed --booklets-only
   ```
   Leave out `--booklets-only` to embed the claims too, which takes a few minutes.
4. Start the server again:
   ```bash
   uv run python -m insurance_mcp.main
   ```
5. Make the assistant see the new tool. In Copilot, run **MCP: List Servers**, choose `insurance`, then **Restart Server**. In Claude Code, run `/mcp` and reconnect `insurance`. Then ask a question the new tool answers.
