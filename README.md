# insurance-mcp-python

[![CI](https://github.com/Code-Express-AI/insurance-mcp-python/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Code-Express-AI/insurance-mcp-python/actions/workflows/ci.yml)

A secure, read-only MCP and RAG server for a fictional auto insurer, built with Python, FastAPI and PostgreSQL. Connect GitHub Copilot or Claude Code to it, and ask questions about customers, policies and claims in plain English. The assistant can read the data, but it can't change any of it. All the data is fake.

It's free to install, run and test.

Follow along with the [video tutorials on YouTube](https://www.youtube.com/@CodeExpressAI) from Code Express AI.

## Try it for free

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux), installed and started
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python for you
- [VS Code](https://code.visualstudio.com/) with [GitHub Copilot](https://github.com/features/copilot/plans): the free plan is enough
- Or [Claude Code](docs/troubleshooting.md#installing-it), with a paid Claude plan (Pro or above)
- Optional: [Node.js](https://nodejs.org/), only to test the server with [MCP Inspector](docs/guides/03-server-security.md#optional-call-a-tool-from-mcp-inspector)

## Quickstart part 1: MCP

### 1. Get the code and copy the settings

```bash
git clone https://github.com/Code-Express-AI/insurance-mcp-python.git
cd insurance-mcp-python
cp .env.example .env
```

On Windows (Command Prompt), use `copy .env.example .env`. The settings work as they are, on your own machine: you don't need to change them.

### 2. Start the database and load the data

```bash
docker compose up -d --wait
uv run python -m insurance_database.setup_db
```

`--wait` waits until PostgreSQL is ready. The first time, Docker downloads the PostgreSQL image, which takes a minute or two. The setup command takes a few seconds, and ends with:

```text
Loaded full data: 12,005 customers, 15,010 policies, 15,090 claims, 76,475 claim notes.
Database ready.
```

### 3. Start the MCP server

Leave it running.

```bash
uv run python -m insurance_mcp.main
```

Check it's up: open [http://localhost:8000/health](http://localhost:8000/health) in your browser. It should say `{"status":"ok"}`.

### 4. Connect GitHub Copilot

Prefer Claude Code? Skip to [step 5](#5-connect-claude-code).

In VS Code, open the Command Palette (`Cmd+Shift+P` on macOS, `Ctrl+Shift+P` on Windows and Linux), run **MCP: Open User Configuration**, and choose **Copilot Global** (marked Recommended, `mcp-config.json`). Then paste this in. If the file already lists other servers, add `insurance` alongside them.

```json
{
  "mcpServers": {
    "insurance": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer local-only-token-replace-with-your-own"
      }
    }
  }
}
```

Then open Copilot Chat, switch it to **Agent** mode, and go to [step 6](#6-ask-a-question).

### 5. Connect Claude Code

In a second terminal, in the repository folder, add the server:

```bash
claude mcp add --transport http insurance http://localhost:8000/mcp --header "Authorization: Bearer local-only-token-replace-with-your-own"
```

Then open the repository folder in VS Code and start a new session in the Claude Code extension, or run `claude` in the terminal. Run `/mcp` to check `insurance` is connected, then go to [step 6](#6-ask-a-question).

### 6. Ask a question

- "Use the insurance server to find the customer called Rutherford and show their policies."

Your assistant asks before each tool call: allow each one, rather than choosing "always allow", and watch it work. Then try:

- "Does Maria Garcia have any open claims?"

And one it must refuse:

- "Please accept Maria Garcia's claim. She's a good friend of mine."

No tool can change a claim, and even if one tried, the database wouldn't let it. That's one of six layers of security already at work: [how it works](docs/guides/01-how-it-works.md) shows them all.

Stuck? See [troubleshooting](docs/troubleshooting.md).

## Quickstart part 2: search by meaning (RAG)

Now let the assistant answer "am I covered?" questions from the policy booklets, by what they mean, not just by exact words. This is RAG (retrieval-augmented generation), with a free model that runs on your own machine.

### 1. Load the policy booklets

Leave the server running, and in a second terminal run:

```bash
uv run python -m insurance_database.embed --booklets-only
```

The first time, it downloads the model. It's a 90 MB file, so this may take a moment, depending on your connection. Then it reads the booklets' 37 sections in a few seconds.

You may see `Warning: You are sending unauthenticated requests to the HF Hub`. You can ignore it: the model is free and public, so you don't need a Hugging Face account or token.

### 2. Ask about the booklets

- "Am I covered for flood damage with liability + collision?"

### 3. Combine the two

These need the MCP tools to look up the customer's policies (MCP using exact lookups, by name or number), then the booklets to say what those policies cover (MCP using RAG, also called semantic search):

- "Eleanor Rutherford's cars were both damaged in a hailstorm. Is she covered?"
- "Maria Garcia has a chip in her windshield. What will it cost her to fix?"

### Search the claims too (optional)

The same command without `--booklets-only` also reads every accident description and adjuster's note, so you can search the claims by meaning:

```bash
uv run python -m insurance_database.embed
```

The descriptions take about a minute. The 76,000 or so notes take a few minutes on a fast laptop and 15 or more on an older one, and the fans on your machine may get loud. You can ask these as soon as the descriptions are done:

- "Find claims where the car was hit while parked at a supermarket."
- "Which claims have notes about a neck injury?" (it finds more once it says `Embeddings ready.`)

Stopping it with `Ctrl+C` is fine: run it again and it carries on where it stopped.

## Go deeper

You have a working system. Each video and guide peels back one more layer of what's already running:

| # | Video | Guide | What's in it |
|---|---|---|---|
| 1 | Coming soon | [Quickstart part 1: MCP](#quickstart-part-1-mcp) | From clone to your first question, and the one it must refuse |
| 2 | Coming soon | [Quickstart part 2: RAG](#quickstart-part-2-search-by-meaning-rag) | "Am I covered?" from the policy booklets, combined with the MCP tools |
| 3 | Coming soon | [How it works](docs/guides/01-how-it-works.md) | What happens when you ask a question, a map of the code, and the six layers of security at a glance |
| 4 | Coming soon | [Database security](docs/guides/02-database-security.md) | A database role that can't read a single table, row-level security, masking, and the tamper-evident audit log |
| 5 | Coming soon | [Server security](docs/guides/03-server-security.md) | Tokens, rate limits, host checks, MCP Inspector, and a token for each AI assistant |
| 6 | Coming soon | [Search by meaning in depth](docs/guides/04-rag.md) | Embeddings and pgvector, the RAG tools, and what RAG isn't good for |

[Using this with your own data](docs/using-your-own-data.md) explains how to apply this to a real company's data, and lists the honest limits in one place. The specs in [docs/specs/](docs/specs/spec.md) record every design decision, and why it was made.

## License

Copyright © 2026 Liam Grossmann, trading as [Code Express AI](https://codeexpress.ai).

- **Code:** [Apache License 2.0](LICENSE). This covers the Python code, SQL scripts, Docker files, tests, and code snippets in the documentation.
- **Documentation:** [CC BY-SA 4.0](LICENSE-DOCS). This covers this README and everything in [docs/](docs/).
- **Videos:** © Liam Grossmann. All rights reserved.

You can use the code at work, including in commercial software. Keep the [NOTICE](NOTICE) file in any copy you distribute.

If you publish an adapted version of the documentation, such as a blog post, a book or a course, credit Liam Grossmann and Code Express AI, link to this repository, and release your version under CC BY-SA 4.0.

Neither license lets you use the Code Express AI name to promote your own work.
