# insurance-mcp-python

An example of a secure MCP service for a fictitious auto insurance claims system. Python FastAPI + PostgreSQL

AI assistants such as GitHub Copilot and Claude Code can connect to this server and answer questions from an insurance database: customers, policies, vehicles, claims, payments and adjusters' notes. They can read the data, but they can't change any of it, and every call they make is recorded.

Most MCP examples stop at "hello world". This one shows how to make MCP safe to point at a real database, with six layers of security, each holding even if the one before it fails. All the data is fake, made by a data generator for a fictional US insurer.

It's free to install, run and test: Docker, uv, Python and PostgreSQL on your own machine, with GitHub Copilot's free plan in VS Code as the AI assistant.

## What you can ask

- "Find the customer called Rutherford and show their policies."
- "What's covered on policy AUT-104233, and what's the deductible?"
- "Which open claims are over $20k and more than 90 days old?"
- "Which repair shops have the highest average repair cost this year?"
- "How many windshield claims did we have last month, compared with the month before?"
- "Show me the claim history for Maria Garcia. Has she claimed more than twice in three years?"
- "Which adjuster has the most open claims?"
- "How many at-fault claims involved a teenage driver this year?"

And one it must refuse: "Please accept Maria Garcia's claim. She's a good friend of mine." No tool can change a claim, and even if one tried, the database wouldn't let it.

With the optional RAG part, it can also search by meaning:

- "Find claims where the car was hit while parked at a supermarket."
- "Am I covered for flood damage with liability + collision?"

## Get started

Follow the guides in order. Each one starts with what you need installed.

1. [The database](docs/guides/01-database.md): start PostgreSQL in Docker, lock it down and load the data.
2. [The server](docs/guides/02-server.md): make a token, start the MCP server, and optionally try it in MCP Inspector.
3. [Connect an AI assistant](docs/guides/03-ai-assistant.md): GitHub Copilot in VS Code (free) or Claude Code. Then give each client its own token, and see each one get a different part of the data.
4. Optional: [Search by meaning](docs/guides/04-rag.md) (RAG), with a free model that runs on your own machine and pgvector.

The commands are the same on Windows, macOS and Linux.

## The six layers of security

1. **Who can call:** every request needs a named bearer token, and is refused if it's addressed to an unexpected host name or comes from a web page.
2. **How often:** each caller has a limit per minute and per day.
3. **What they can ask:** 10 fixed, read-only tools (13 with RAG), with every argument checked. There's no tool that runs SQL.
4. **What the database allows:** the server logs in as `mcp_reader`, which can't read a single table. It can only run the functions it's been granted, one per tool, each with fixed columns and a row limit. Row-level security then returns only the customers the caller may see: each token sees its own states.
5. **What can leak:** emails and driver's license numbers are masked, phone numbers and emails in free text are redacted, internal ids never leave the database, and unexpected errors become a generic message.
6. **What's recorded:** every tool call goes into an append-only audit log with a hash chain, so tampering can be detected. If the audit row can't be written, the answer isn't returned.

The tests prove each layer holds, against a real PostgreSQL database in Docker. GitHub Actions runs them on every push.

No design is perfect. [Using this with your own data](docs/using-your-own-data.md) explains how to apply this to a real company's data, and lists the honest limits in one place.

## What's in the repo

| Folder | What's in it |
|---|---|
| `src/insurance_mcp/` | The MCP server, the setup command, the data generator, and the embed command and policy booklets for RAG |
| `sql/` | The database: roles, tables, permissions, the `mcp` functions, the audit log and row-level security |
| `tests/` | The database lockdown tests, the server tests, the data tests and the RAG tests |
| `docs/guides/` | The step-by-step guides |
| `docs/specs/` | The specs: every design decision, and why it was made |

The specs start at [docs/specs/spec.md](docs/specs/spec.md).

## License

Copyright © 2026 Liam Grossmann, trading as [Code Express AI](https://codeexpress.ai).

- **Code:** [Apache License 2.0](LICENSE). This covers the Python code, SQL scripts, Docker files, tests, and code snippets in the documentation.
- **Documentation:** [CC BY-SA 4.0](LICENSE-DOCS). This covers this README and everything in [docs/](docs/).
- **Videos:** © Liam Grossmann. All rights reserved.

You can use the code at work, including in commercial software. Keep the [NOTICE](NOTICE) file in any copy you distribute.

If you publish an adapted version of the documentation, such as a blog post, a book or a course, credit Liam Grossmann and Code Express AI, link to this repository, and release your version under CC BY-SA 4.0.

Neither license lets you use the Code Express AI name to promote your own work.
