# Implementation plan

The order we build the project in. What to build is decided in [spec.md](spec.md), [database-spec.md](database-spec.md), [server-spec.md](server-spec.md) and [data-generator-spec.md](data-generator-spec.md), all signed off. This plan only decides the order, what "done" means for each stage, and how we work.

**Status:** Agreed

## Build order

Each stage ends with something that runs, has passing tests, and has its guide written while the details are fresh.

| # | Stage | Done when |
|---|-------|-----------|
| 0 | **Check the MCP SDK:** a throwaway test with one tool, mounted in FastAPI. Not committed. See "Checks to make during the build". | We know the SDK can do what [server-spec.md](server-spec.md) needs, or we've updated the spec |
| 1 | **Project skeleton:** `pyproject.toml`, `.python-version`, `.env.example`, `docker-compose.yml`, ruff, pytest, GitHub Actions, Dependabot | `uv run pytest` runs (with no tests yet), PostgreSQL starts in Docker, and CI is green |
| 2 | **Database:** the `sql/` scripts, the setup command, and the lockdown tests ([database-spec.md](database-spec.md)) | The setup command builds the database from scratch, and every lockdown test passes |
| 3 | **Data generator,** with its `small` and `full` sizes, and its tests ([data-generator-spec.md](data-generator-spec.md)). **Guide 1** (database). | The setup command loads the same data for everyone, and the planted demo facts hold on `full` data in CI |
| 4a | **One tool through the whole request path:** settings, database access, audit, tokens, host checks, rate limiting and input limits, all proven with `get_dataset_info` ([server-spec.md](server-spec.md)). **Guide 2** (server). | Every server test passes, and MCP Inspector can call the tool |
| 4b | **The other tools** and the server instructions | Every tool has its tests, and MCP Inspector can call each one |
| 5 | **Guide 3** (connect an AI assistant), the "Using this with your own data" page, and the README ([spec.md](spec.md), decision 8) | Someone new can follow guides 1 to 3 on a clean machine and ask the demo questions in GitHub Copilot |
| 6 | **RAG extension** ([spec.md](spec.md), decision 11) | The embeddings load with the local model, the RAG tools work, and the RAG security tests pass |
| 7 | **Optional: hosted database guide** ([database-spec.md](database-spec.md), decision 14) | The same setup command works against a hosted database |

The MCP part (stages 0 to 5) is complete on its own. RAG comes after it.

**Nice to have, not planned:** hiding VIP customers from some clients with row-level security ([database-spec.md](database-spec.md), decision 6).

## How we work

- **One stage at a time.** Claude builds a stage, Liam reviews and commits it, and only then does the next stage start.
- **Tests during a stage:** Claude runs only the tests for the code being changed, on `small` data. Before handing a stage over, one full run of the test suite, which takes under a minute. Where a test proves a security claim, it's shown failing first, then passing.
- **CI does the rest** on every push: ruff, the full test suite on `small` data, and the planted demo facts on `full` data ([spec.md](spec.md), decision 7). A CI failure gets a quick fix commit.

## Keep the code easy to follow

The spec has grown heavy. The security audit added about 20 items on top of the 14 server decisions. Each one is defensible, but this is teaching material, and the question is whether a reader can follow the code.

So at each stage review, we check the audit fixes in that stage. If a fix needs more explaining than it's worth, it doesn't go into the code. Instead it becomes a short honest limit on the "Using this with your own data" page, and the spec is updated to match.

## Checks to make during the build

The specs leave these details to be confirmed against the real libraries:

- **MCP Python SDK (stage 0):** how to mount it in FastAPI, its host-check settings, the status code for a rejected host (403 or 421), how to reject unknown arguments, how it handles JSON-RPC batches, tool annotations, and its test client.
- **pgvector under `search_path = ''` (stage 6):** which schema the extension goes in, and whether the `<=>` operator needs writing as `OPERATOR(schema.<=>)`.
- **RAG functions take `real[]` (stage 6)** and cast it to a vector inside the function, so `mcp_reader` needs no access to the vector type.
- **Embedding time (stage 6):** how long the local model (fastembed) takes to embed the `full` data, about 90,000 texts.
