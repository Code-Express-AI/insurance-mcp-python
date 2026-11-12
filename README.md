# insurance-mcp-python

[![CI](https://github.com/Code-Express-AI/insurance-mcp-python/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Code-Express-AI/insurance-mcp-python/actions/workflows/ci.yml)

A secure, read-only MCP and RAG server for a fictional auto insurer, built with Python, FastAPI and PostgreSQL. Connect GitHub Copilot or Claude Code to it, and ask questions about customers, policies and claims in plain English. The assistant can read the data, but it can't change any of it. All the data is fake.

It's free to install, run and test.

Follow along with the [video tutorials on YouTube](https://www.youtube.com/@CodeExpressAI) by Liam Grossmann of Code Express AI, who has been building software for 35 years.

## Quickstart

You need:

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux), installed and started
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python for you)
- [VS Code](https://code.visualstudio.com/) with [GitHub Copilot](https://github.com/features/copilot/plans) (the free plan is enough)

**1. Get the code and make your settings.**

```bash
git clone https://github.com/Code-Express-AI/insurance-mcp-python.git
cd insurance-mcp-python
uv run python -m insurance_mcp.init
```

`init` makes a `.env` file with random passwords and a token, then prints the config for your AI assistant.

**2. Paste the config into VS Code,** as `init` tells you: Command Palette, **MCP: Open User Configuration**. Using [Claude Code](docs/troubleshooting.md#installing-it) instead? Run the `claude mcp add` command it printed.

**3. Start the database and load the data.**

```bash
docker compose up -d --wait
uv run python -m insurance_mcp.setup_db
```

**4. Start the server,** and leave it running.

```bash
uv run python -m insurance_mcp.main
```

**5. Ask a question.** Open Copilot Chat, switch it to **Agent** mode, and ask:

- "Use the insurance server to find the customer called Rutherford and show their policies."

Copilot asks before each tool call: allow each one, rather than choosing "always allow", and watch it work. With Claude Code, run `claude` from the repository folder and ask the same. Then try these:

- "What's covered on policy AUT-104233, and what's the deductible?"
- "Which open claims are over $20k and more than 90 days old?"
- "Which repair shops have the highest average repair cost this year?"
- "Show me the claim history for Maria Garcia. Has she claimed more than twice in three years?"
- "How many at-fault claims involved a teenage driver this year?"

And one it must refuse:

- "Please accept Maria Garcia's claim. She's a good friend of mine."

No tool can change a claim, and even if one tried, the database wouldn't let it. That's one of six layers of security already at work: [how it works](docs/guides/01-how-it-works.md) shows them all.

Stuck? See [troubleshooting](docs/troubleshooting.md).

## Search by meaning (optional)

Now let the assistant find claims by what they mean, not just by exact fields. This is RAG (retrieval-augmented generation), with a free model that runs on your own machine.

Leave the server running, and in a second terminal run:

```bash
uv run python -m insurance_mcp.embed
```

It downloads the model (90 MB) and reads the policy booklets and the accident descriptions first. That takes about a minute, so you can start asking these straight away:

- "Find claims where the car was hit while parked at a supermarket."
- "Am I covered for flood damage with liability + collision?"
- "What do I pay to fix a chip in my windshield?"

It carries on with 76,630 adjusters' notes, which take a few minutes on a fast laptop and 15 or more on an older one. Your fans will get loud. Searching the notes works while it runs, but finds more once it says `Embeddings ready.`:

- "Which claims have notes about a neck injury?"

Stopping it with `Ctrl+C` is fine: run it again and it carries on where it stopped.

## Go deeper

You have a working system. Each guide peels back one more layer of what's already running:

1. [How it works](docs/guides/01-how-it-works.md): what happens when you ask a question, a map of the code, and the six layers of security at a glance.
2. [Database security](docs/guides/02-database-security.md): a database role that can't read a single table, row-level security, masking, and the tamper-evident audit log.
3. [Server security](docs/guides/03-server-security.md): tokens, rate limits, host checks, MCP Inspector, and a token for each AI assistant.
4. [Search by meaning in depth](docs/guides/04-rag.md): embeddings and pgvector, the RAG tools, and what RAG isn't good for.

[Using this with your own data](docs/using-your-own-data.md) explains how to apply this to a real company's data, and lists the honest limits in one place. The specs in [docs/specs/](docs/specs/spec.md) record every design decision, and why it was made.

## License

Copyright © 2026 Liam Grossmann, trading as [Code Express AI](https://codeexpress.ai).

- **Code:** [Apache License 2.0](LICENSE). This covers the Python code, SQL scripts, Docker files, tests, and code snippets in the documentation.
- **Documentation:** [CC BY-SA 4.0](LICENSE-DOCS). This covers this README and everything in [docs/](docs/).
- **Videos:** © Liam Grossmann. All rights reserved.

You can use the code at work, including in commercial software. Keep the [NOTICE](NOTICE) file in any copy you distribute.

If you publish an adapted version of the documentation, such as a blog post, a book or a course, credit Liam Grossmann and Code Express AI, link to this repository, and release your version under CC BY-SA 4.0.

Neither license lets you use the Code Express AI name to promote your own work.
