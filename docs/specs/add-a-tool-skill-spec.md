# Add-a-tool skill specification

The skill that tells an AI assistant (GitHub Copilot or Claude Code) how to add a new read-only tool to this server, and a new table for it if it needs one. It follows the rules in [database-spec.md](database-spec.md) and [server-spec.md](server-spec.md) and adds none of its own. The steps themselves are in the skill, [skills/add-a-tool.md](../../skills/add-a-tool.md). This spec records the decisions behind it.

**Status key:** Open (not discussed yet) · Proposed (Claude's suggestion, awaiting Liam) · Agreed (signed off by Liam)

## Decision summary

| # | Decision | Status |
|---|----------|--------|
| 1 | Where the files go | Agreed |
| 2 | What the skill covers | Agreed |
| 3 | Generic, not tied to the existing tools | Agreed |
| 4 | The human agrees the plan, runs the commands, and signs it off | Proposed |
| 5 | Docs it doesn't touch | Proposed |
| 6 | How we know it works | Proposed |

## 1. Where the files go (Agreed)

One copy of the skill, and a short stub for each assistant that points to it:

```
skills/add-a-tool.md                  the skill itself
.github/skills/add-a-tool/SKILL.md    stub for GitHub Copilot
.claude/skills/add-a-tool/SKILL.md    stub for Claude Code
```

Each assistant reads only its own folder: Copilot reads `.github/skills/`, Claude Code reads `.claude/skills/`. Both read the `name` and `description` at the top of every `SKILL.md`, and load the rest only when a request matches the description. The two stubs are the same. Only their `description` would need changing in two places, and it rarely changes. Both are committed, so nobody following the videos has to create anything.

No extra pointers go in `.github/copilot-instructions.md` or a committed `CLAUDE.md`. If rehearsals show an assistant not picking up the skill, we add them then.

**Switching it off** (video 5's run without the skill): a `video-5-without-skill` branch, which is `main` without `skills/`, the two stubs and `docs/`. The code and its comments, the tests and the README stay, like most codebases. Switch with `git switch video-5-without-skill` and back with `git switch main`: the same on every OS, and nothing is lost. Merge `main` into it before each rehearsal or recording, so both runs start from the same code. Round 2 runs on `main`, with the skill and the specs, as viewers have it. The README section on this is still to write.

## 2. What the skill covers (Agreed)

Everything from the request to a working tool:

- **A new table**, if needed: its SQL, `select` for `mcp_owner`, and row-level security if it holds customer data.
- **Its data:** a short fixed list in the SQL file, many generated rows in the data generator, or text to search by meaning, loaded and embedded by the embed command. It also covers what the data may contain (made up, US, the fictional phone range, `example.com`).
- **Embeddings:** the column, the section length the model reads, the loader, and the search function's checks.
- **The function, the grant, the Python tool and the tests.**
- **What the human runs** to see it working: the setup command, the embed command, a server restart, and reconnecting the assistant.
- **What it refuses:** writes, raw SQL, table grants to `mcp_reader`, changes to what exists, real data, and weakening a test.

## 3. Generic, not tied to the existing tools (Agreed)

Liam, 2026-11-18: the skill names no existing tool or function. It names the files, the shared helpers (`insurance.mask_email()`, `insurance.period_dates()`, ...), the argument types and the tests to change. Where a pattern helps, it says "copy the closest function in `sql/04_functions.sql`", and the assistant picks that function in step 1.

Two reasons. The skill stays true when tools are added or changed. And it doesn't lead the assistant towards a tool that already exists when it builds video 3's tool.

## 4. The human agrees the plan, runs the commands, and signs it off (Proposed)

- **Step 1 stops for agreement**: the tool's name, its arguments and limits, its columns, its row limit, any new table and its data. Video 3 asks for the SQL first, and a wrong plan is cheapest to fix here.
- **The assistant never runs the setup or embed commands.** They rebuild the human's database, emptying the audit log and removing the embeddings. It runs only ruff and pytest, which use their own database in Docker.
- **It ends with a review list**, because the assistant wrote both the function and its tests, so they can share a mistake. The rule tests catch a missing grant or a missing `security definer`. They don't catch a column the question doesn't need.

## 5. Docs it doesn't touch (Proposed)

The skill doesn't update the tool tables in `server-spec.md`, `database-spec.md` or the guides. They describe the tools the repo ships with. The `video-3-done` and `video-5-done` branches update them by hand.

## 6. How we know it works (Proposed)

There's no automated test for a skill. It's tested by use:

- **Rehearse from a fresh clone, more than once, on each assistant**, with video 3's and video 5's requests, including on Copilot's free plan. Check both fit inside the free plan's monthly limit.
- **Each run must:** stop after the plan, follow the steps in order, finish with `uv run pytest` green, and end on the review list.
- **Write down what went wrong** in each run, and fix the skill, not the tests.

## Known limits

- **The run commands rebuild everything.** Until `update_db` exists, seeing a new tool means running the setup command again: the audit log is emptied and the embeddings are removed. When `update_db` exists, step 9 changes to use it for a new function.
- **The functions are in one file,** `sql/04_functions.sql`. If `update_db` moves them, steps 3 to 5 name the new files.
- **"Returns a column it shouldn't"** is only partly tested: the test with one customer's personal data catches personal data, not every unneeded column. The review list covers the rest.
