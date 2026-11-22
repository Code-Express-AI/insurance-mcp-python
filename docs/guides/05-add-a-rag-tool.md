# Guide 5: add a RAG tool

This is the guide for [video 5 on YouTube](https://www.youtube.com/@CodeExpressAI).

The policy booklets say what a customer is covered for. They don't say how staff should handle a claim. The [adjusters' manual](../../database/src/insurance_database/adjusters_manual.md) does: it's already in the repo, but nothing searches it yet. You'll add a tool that searches it by meaning, with the same skill as [guide 3](03-add-a-tool.md). This time the skill also adds a table, and loads the manual into it with its embeddings. Carry on in the same copy as video 3: your `get_customer_with_policies` tool stays.

## Before you begin: if you get stuck

Your code will look a bit different from the video: the AI writes it fresh each time. If you get stuck, compare with the [`video-5-done`](https://github.com/Code-Express-AI/insurance-mcp-python/tree/video-5-done) branch, which has the finished table, function and tool, and passes every test. It's built on `video-3-done`, so it has video 3's tool too, and you lose nothing by switching. Or switch to it and carry on from there. `git stash -u` puts your own changes aside first, new files included, so the switch doesn't refuse. `git pull` gets the latest copy of the branch:

```bash
git fetch
git stash -u
git switch video-5-done
git pull
uv run python -m insurance_database.update_db
uv run python -m insurance_database.embed --booklets-only
```

Then restart the server, and reconnect your assistant (see [load it](#load-it)). If the database still seems wrong, rebuild it with `uv run python -m insurance_database.setup_db`, then run the embed command again. If you forked the repository, your fork may not have the branch: GitHub copies only `main` unless you untick that box when you fork.

## Part 1: with GitHub Copilot

The skill comes with the repo, so there's nothing to install. It's the same one as in guide 3, and its step 3 covers text to search by meaning. You can [read it here](../../skills/add-an-insurance-tool.md).

1. Open the repository folder in VS Code. Open the Chat view, and choose **Agent** mode.
2. Ask:
   > Use the add-an-insurance-tool skill to add a new tool called search_adjuster_manual. It should search the adjusters' manual in database/src/insurance_database/adjusters_manual.md by meaning, from a new table called adjuster_manual_chunks that the embed command loads, and return the closest sections with their headings. Copy how search_policy_wording works. Its description should tell the model to use it for how staff handle a claim, and search_policy_wording for what a customer is covered for.

   **Why so precise?** As in guide 3: name what you need and the code to copy. The last sentence matters most here. The two search tools look alike to the model, so the description is all it has to choose between them.
3. It shows its plan first, and waits. Read it, then tell it to go ahead.
4. It writes the table, the code that loads the manual, the function, the grant, the Python tool and the tests, then runs the checks. Allow the commands when it asks.
5. It ends with the new SQL function, its grant, and a list to check. Read them: the AI wrote the function and the tests, so they can share a mistake.
6. [Load it](#load-it), then [try it yourself](#try-it-yourself).

## Part 2: with Claude Code

Claude Code loads the same skill, so there's nothing to install here either.

1. In a terminal in the repository folder, start Claude Code with `claude`.
2. Ask the same thing:
   > Use the add-an-insurance-tool skill to add a new tool called search_adjuster_manual. It should search the adjusters' manual in database/src/insurance_database/adjusters_manual.md by meaning, from a new table called adjuster_manual_chunks that the embed command loads, and return the closest sections with their headings. Copy how search_policy_wording works. Its description should tell the model to use it for how staff handle a claim, and search_policy_wording for what a customer is covered for.

   Or type `/add-an-insurance-tool` followed by the request.
3. It shows its plan first, and waits. Read it, then tell it to go ahead.
4. It writes the table, the code that loads the manual, the function, the grant, the Python tool and the tests, then runs the checks. Allow the commands when it asks.
5. It ends with the new SQL function, its grant, and a list to check. Read them.
6. [Load it](#load-it), then [try it yourself](#try-it-yourself).

Tested with Claude Code on November 22, 2026, with Opus 5.5 at medium effort, in the same copy as video 3. The code passed every test, including the ones that use the real model, and worked first time.

## Part 3: the code

There's no typing guide this time. To see the code, or to check what your assistant wrote, compare your copy with the [`video-5-done`](https://github.com/Code-Express-AI/insurance-mcp-python/tree/video-5-done) branch:

```bash
git fetch
git diff origin/video-5-done --stat
```

The list includes any differences in your video 3 tool too, since your assistant wrote its own version of that as well.

The files to look at, and what to check in each:

| File | What's added | Check |
|---|---|---|
| `sql/070_added_tables.sql` | The table, with an `embedding vector(384)` column, and `grant select` to `mcp_owner` | No grant on the table to `mcp_reader`. No row-level security: the manual holds no customer data |
| `database/src/insurance_database/embed.py` | Splits the manual at its `## ` headings, embeds each section and loads it, straight after the booklets | It's called from `embed_everything`, so `--booklets-only` loads it too |
| `sql/080_mcp_functions.sql` | `mcp.search_adjuster_manual`, and one `grant execute` to `mcp_reader` | `security definer`, `set search_path = ''`, the query through `insurance.to_vector` (exactly 384 numbers), a row limit |
| `server/src/insurance_mcp/tools.py` | The tool, added to `TOOLS` | The docstring tells it apart from `search_policy_wording` |
| `tests/` | The new grant and tool in the lists, test rows in `fake_embeddings`, and a test or two for the function | The existing tests weren't weakened |

[Guide 4](04-rag.md) explains how the embeddings are made and searched.

## Load it

In a terminal in the repository folder:

1. Stop the MCP server (`Ctrl+C`).
2. Load the new table and function. This keeps the data, the embeddings and the audit log. It runs in one transaction, so if the SQL has a mistake, it tells you and nothing changes.
   ```bash
   uv run python -m insurance_database.update_db
   ```
3. Load the manual. This embeds its sections in a second or two, and skips the booklets if they're already loaded:
   ```bash
   uv run python -m insurance_database.embed --booklets-only
   ```
4. Start the server again:
   ```bash
   uv run python -m insurance_mcp.main
   ```
5. Make the assistant see the new tool. In Copilot, run **MCP: List Servers**, choose `insurance`, then **Restart Server**. In Claude Code, run `/mcp` and reconnect `insurance`.

## Try it yourself

**Ask a question.** In a new chat:

> A customer reports a hit-and-run. What should I do?

The assistant should call `search_adjuster_manual`, and answer from its "Hit-and-run claims" section: a police report within 24 hours, store camera footage, photos of the damage, and a check of the booklet for collision coverage. It may search the booklets with `search_policy_wording` too, because the manual says to check them: that's right.

**Ask one that needs three tools:**

> Maria Garcia has a chip in her windshield. How should I handle her claim?

The manual says how to handle a glass claim, but sends you to the booklet for what she'll pay. So the assistant should look up her policy (Full coverage, a $500 deductible), search the manual, and search the booklets. A chip repair costs her nothing; a new windshield costs her the $500. Check the audit log too: an assistant may search the booklets for a coverage level before it has looked hers up. If it guessed wrong, the answer quotes the wrong booklet.

**Check the server's login can't read the table.** Like every other table, only the function can:

```bash
docker compose exec db psql -U mcp_reader -d insurance -c "select heading from insurance.adjuster_manual_chunks limit 5;"
```

You should get permission denied. If you get headings instead, the assistant granted the table to `mcp_reader`, and `uv run pytest` fails too.

**Check the audit log.** It records the question, not 384 numbers:

```bash
docker compose exec db psql -U postgres -d insurance -c "select occurred_at, tool_name, arguments, rows_returned from insurance.audit_log order by id desc limit 5"
```

## If something goes wrong

| What you see | Why, and the fix |
|---|---|
| The assistant says "Run the embed command first." | The table is empty. Run [load it](#load-it), step 3. If it still says so, the loader isn't called from `embed_everything`. |
| "The database could not complete this request." | The real error is in the server's terminal, after `The database call for search_adjuster_manual failed`. `permission denied for function`: the grant is missing, or its argument types don't match the function's. `does not exist`: `update_db` hasn't run since you added it. |
| `update_db` says `... has an error, so nothing changed` | A typo in the SQL. The message below it names the problem. |
| The assistant uses `search_policy_wording` for the hit-and-run question | The server wasn't restarted or reconnected ([load it](#load-it)), or the new tool's description doesn't say when to use it. Start a new chat too. |
| `Unknown tool: search_adjuster_manual` | The tool isn't in `TOOLS`, or the server is still running the old code. Restart it. |

More problems and their fixes are in [guide 1](01-quickstart-help.md).
