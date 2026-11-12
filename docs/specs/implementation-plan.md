# Implementation plan

The order we build the project in. What to build is decided in [spec.md](spec.md), [database-spec.md](database-spec.md), [server-spec.md](server-spec.md) and [data-generator-spec.md](data-generator-spec.md), all signed off. This plan only decides the order, what "done" means for each stage, and how we work.

**Status:** Agreed

## Build order

Each stage ends with something that runs, has passing tests, and has its guide written while the details are fresh.

| # | Stage | Done when |
|---|-------|-----------|
| 0 | **Check the MCP SDK:** a throwaway test with one tool, mounted in FastAPI. Not committed. See "Checks to make during the build". | We know the SDK can do what [server-spec.md](server-spec.md) needs, or we've updated the spec |
| 1 | **Project skeleton:** `pyproject.toml`, `.python-version`, `.env.example`, `docker-compose.yml`, ruff, pytest, GitHub Actions, Dependabot | `uv run pytest` runs (with no tests yet), PostgreSQL starts in Docker, and CI is green |
| 2 | **Database:** the `sql/` scripts, the setup command, and the lockdown tests that need no data ([database-spec.md](database-spec.md)). The roles, tables, permissions, helper functions, audit log and the first `mcp` function, `get_dataset_info`. | The setup command builds the database from scratch, and every lockdown test passes |
| 3 | **Data generator,** with its `small` and `full` sizes, and its tests ([data-generator-spec.md](data-generator-spec.md)). **Guide 1** (database). | The setup command loads the same data for everyone, and the planted demo facts hold on `full` data in CI |
| 4a | **One tool through the whole request path:** settings, database access, audit, tokens, host checks, rate limiting and input limits, all proven with `get_dataset_info` ([server-spec.md](server-spec.md)). **Guide 2** (server). | Every server test passes, and MCP Inspector can call the tool |
| 4b | **The other tools,** each with its `mcp` function and that function's lockdown tests (row limits, masking, wildcard escaping, unknown numbers), on `small` data. The planted-fact tests from stage 3 switch from plain SQL to these functions. And the server instructions. | Every tool and function has its tests, and MCP Inspector can call each one |
| 5 | **Guide 3** (connect an AI assistant), the "Using this with your own data" page, and the README ([spec.md](spec.md), decision 8) | Someone new can follow guides 1 to 3 on a clean machine and ask the demo questions in GitHub Copilot |
| 6 | **RAG extension** ([spec.md](spec.md), decision 11) | The embeddings load with the local model, the RAG tools work, and the RAG security tests pass |
| 7 | **Optional: hosted database guide** ([database-spec.md](database-spec.md), decision 14) | The same setup command works against a hosted database |
| 8 | **Row-level security** ([database-spec.md](database-spec.md), decision 15): `06_row_security.sql`, the caller key on every call, the tests, and the step-by-step SQL section in guide 1, and "Give each client its own token" at the end of guide 3. Guides 1 to 3 switch to one `local` token, and the per-client tokens are `claude`, `copilot` and `inspector` (they were `claude-code` and `copilot`). The README's security layers, the "Using this with your own data" page and the specs' honest limits updated to match. Signed off 2026-11-12. Built before stage 7, which is on hold. | Each named token sees only its own states in every tool, the RAG tools included, the demos work with every token, and the guides' walkthroughs work as written |

The MCP part (stages 0 to 5) is complete on its own. RAG comes after it.

**Nothing is written before it can be tested.** Each `mcp` function arrives with its tool, so its results are checked against real data as soon as it exists. The lockdown tests that check the system catalogs (every function is `SECURITY DEFINER`, sets `search_path`, returns no internal ids) pick up each new function without changes.

## How we work

- **One stage at a time.** Claude builds a stage, Liam reviews and commits it, and only then does the next stage start.
- **Tests during a stage:** Claude runs only the tests for the code being changed, on `small` data. Before handing a stage over, one full run of the test suite, which takes under a minute. Where a test proves a security claim, it's shown failing first, then passing.
- **CI does the rest** on every push: ruff, the full test suite on `small` data, and the planted demo facts on `full` data ([spec.md](spec.md), decision 7). A CI failure gets a quick fix commit.

## Keep the code easy to follow

The spec has grown heavy. The security audit added about 20 items on top of the 14 server decisions. Each one is defensible, but this is teaching material, and the question is whether a reader can follow the code.

So at each stage review, we check the audit fixes in that stage. If a fix needs more explaining than it's worth, it doesn't go into the code. Instead it becomes a short honest limit on the "Using this with your own data" page, and the spec is updated to match.

## Checks to make during the build

The specs leave these details to be confirmed against the real libraries:

- **MCP Python SDK (stage 0): done.** Checked against `mcp` 2.3.0, and [server-spec.md](server-spec.md) updated to match (decisions 1, 6, 7, 9, 13 and 14).
- **Row-level security (stage 8): done** (2026-11-12, throwaway container, `full` data). The admin skips RLS through its membership of the owner role. Policies `to mcp_owner` filter the `SECURITY DEFINER` functions. No key or an unknown key sees nothing. `set_config(..., true)` is gone after the commit. A hidden claim gets "Unknown claim number". The slowest call takes about 0.3 s. `mcp_reader` can set the key itself (an honest limit). The SDK's `TokenVerifier` runs inside the `/mcp` mount, after our rate limiter, so we keep our own `caller_for` ([server-spec.md](server-spec.md), decision 5).
- **pgvector, `real[]` and embedding time (stage 6): done.** Checked against pgvector 0.8.7 and fastembed 0.9.1, and [spec.md](spec.md) decision 11 updated to match: pgvector goes in `public` and needs a superuser to install, the operator is written `OPERATOR(public.<=>)`, the `real[]` cast works, and exact search replaces the HNSW index. Testing the demo questions on `full` data then changed the model to `all-MiniLM-L6-v2` (better matches, and `full` data embeds in about 3.5 minutes on a fast laptop) and split `search_claim_text` into descriptions or notes.
