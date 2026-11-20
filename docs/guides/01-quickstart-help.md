# Guide 1: quickstart help and troubleshooting

This is the guide for [video 1 on YouTube](https://www.youtube.com/@CodeExpressAI), and the help page for every guide. Something not working? Find the step you're on, then the message you see. The videos explain how it all works.

## More questions to try

Each of these has an exact answer in the data, and most need several tools in a row. Watch the tool calls: you can see how the assistant breaks each question down, and which tool answers which part.

- "What's covered on policy AUT-104233, and what's the deductible?"
- "Which open claims are over $20k and more than 90 days old?"
- "Which repair shops have the highest average repair cost in the last 12 months?"
- "How many windshield claims did we have last month, compared with the month before?"
- "Show me the claim history for Maria Garcia. Has she claimed more than twice in three years?"
- "Which adjuster has the most open claims?"
- "How many at-fault claims involved a teenage driver in the last 12 months?"

**"Last month" means last month.** The data runs up to the day you ran the setup command, so relative dates work as you'd expect. If you set it up a while ago, run `uv run python -m insurance_database.setup_db` again to bring it up to today.

A few insurance words: the **deductible** is the part of a claim the customer pays themselves, the **reserve** is what the insurer expects a claim to cost in total, and an **adjuster** is the insurer's employee who handles the claim.

## Run the tests

The tests prove each layer of security holds, against a real PostgreSQL database. Run them from the repository folder, with Docker running:

```bash
uv run pytest
```

They start their own throwaway PostgreSQL container, build the database from scratch, load a small set of data, and delete the container at the end, so they never touch your database. If Docker isn't running, the database tests are skipped, not failed: start Docker and run them again.

The few tests that need the embedding model run only when you ask for them. The first run downloads the model:

```bash
uv run pytest -m embedding_model
```

GitHub Actions runs all of them on every push to `main` and every pull request.

## Setting up

**`Field required` for `admin_database_url` or `reader_database_url`.** There's no `.env` file, or the command isn't running in the repository folder. Run `cd insurance-mcp-python`, then `cp .env.example .env` (on Windows, `copy .env.example .env`).

## The database

**`Cannot connect to the Docker daemon`** or **`docker: command not found`.** Docker isn't started, or isn't installed. Open Docker Desktop and wait until it says it's running, then run the command again.

**`no configuration file provided: not found`.** You're not in the project folder, so Docker can't find `docker-compose.yml`. Run `cd insurance-mcp-python`, then run the command again.

**`password authentication failed for user "postgres"`.** Docker only reads `POSTGRES_PASSWORD` the first time it creates the database. If you changed it afterwards, the database still has the old one. Either put the old password back, or delete the database with `docker compose down -v` and run the quickstart's step 2 again. It happens with a second copy of the repository too, in a folder with the same name, such as a fresh clone somewhere else. Docker names the database volume after the folder, so both copies share one database, with the first copy's password. If you changed the passwords in the first copy, copy its `.env` into the second.

**`port is already allocated` or `address already in use`.** Something else on your machine is using port 5432. Often it's another copy of this repository, still running its own database: run `docker ps` to see it, then `docker compose stop` in that copy's folder. If it's another PostgreSQL, stop it, or change the first `5432` under `ports:` in `docker-compose.yml` (for example to `127.0.0.1:5433:5432`) and use the same port in both connection strings in `.env`.

**`Setup stopped: The mcp_reader password in READER_DATABASE_URL must be at least 24 characters.`** Make a longer one with `uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`.

**`connection refused`.** The database isn't running. Start Docker, then run `docker compose up -d --wait`.

## The server

**`The token for 'local' is shorter than 32 characters.`** A token in `MCP_TOKENS` is too short. Make one with `uv run python -m insurance_mcp.auth` and put it in `MCP_TOKENS`.

**`MCP_TOKENS must be name:token pairs, separated by commas.`** Each entry needs a name, a colon and a token, such as `local:abc...`, with a comma between entries.

**The server stops with `Connection refused` and `Application startup failed`.** It checks the database when it starts, and stops if it can't connect. Start Docker, then run `docker compose up -d --wait`.

**`password authentication failed for user "mcp_reader"`.** The password in `READER_DATABASE_URL` isn't the one in the database. The setup command sets it, so run it again after changing the password: `uv run python -m insurance_database.setup_db`.

**`address already in use`.** Something else is using port 8000, often the server from another copy of this repository, still running in another terminal. Stop it with `Ctrl+C`, or set `PORT` in `.env` to another port, such as `8001`, and use that port in the URLs.

**Is the assistant really using the server?** Each tool call prints one line in the server's terminal, such as `Tool call: caller=local tool=find_customers rows=1 ms=12 succeeded=True`. No line, no tool call.

**Every tool answers, but finds nothing (0 customers).** The token's name isn't one the database knows. Use `local`, or one of `claude`, `copilot` and `inspector` from [appendix A](appendix-a-server-security.md#give-each-client-its-own-token). [Row-level security](appendix-b-database-security.md#row-level-security-step-by-step) explains why.

**`401 Unauthorized` with a token.** The header must be `Authorization: Bearer <token>`, with the word `Bearer` and one space. Check the token matches one in `MCP_TOKENS` exactly, and restart the server after changing `.env`: it reads the file only when it starts.

**`421` and `Invalid Host header`.** The request was addressed to a host name that isn't in `ALLOWED_HOSTS`. Use `localhost` or `127.0.0.1` in the URL, or add the name to `ALLOWED_HOSTS`.

**`403` and `Invalid Origin header`.** The request came from a web page. AI clients don't run in a browser, so the server refuses any request a web page sends.

**`429 Too Many Requests`.** Wait the number of seconds in the `Retry-After` header. The counts are kept in memory, so restarting the server resets them.

## VS Code and Copilot

**VS Code shows connection errors for `insurance` when you paste the config.** Paste the config while the server is stopped, then start the server. That's the order that works reliably. If it's already in a bad state, restart the `insurance` server in VS Code: **MCP: List Servers**, `insurance`, **Restart Server**.

**No insurance tools in the tools picker.** Check the server is still running and `http://localhost:8000/health` returns `{"status":"ok"}`, then restart the `insurance` server in VS Code: run **MCP: List Servers** from the Command Palette, choose `insurance`, then **Restart Server**.

**`401` or "unauthorized" errors.** The token doesn't match. Check that the header reads `Bearer ` followed by the exact token, with no `<` or `>` left in, then restart the `insurance` server. If you changed `MCP_TOKENS`, restart the server too: it reads `.env` only when it starts.

**"Input and command variables are not supported by the Copilot harness".** The configuration still uses `${input:...}`. Replace it with the token itself, as the README shows, and delete the `inputs` block.

**"Failed to read configuration from .../.copilot/mcp-config.json: mcpServers: Required".** The file is empty or invalid. Run **MCP: Open User Configuration**, choose **Copilot Global**, make sure it matches the JSON in the README, with everything inside `"mcpServers"`, then restart VS Code.

**Copilot lists the tools but never calls them.** It's probably reading them from the code in the repository, and that answer looks right even when nothing is connected. Ask again, starting with "Use the insurance server to...", and check that Copilot shows a tool call, and the server's terminal a `Tool call:` line. The 13 tools should also be listed and selected in the tools picker.

**It works in MCP Inspector but not in VS Code.** The server is fine, so check the URL and the header: run **MCP: Open User Configuration** and choose **Copilot Global**.

**`429 Too Many Requests`.** The assistant has made more than 60 calls in a minute. Wait a minute, or restart the server, which resets the count.

## Claude Code

[Claude Code](https://code.claude.com/docs) needs a paid Claude plan (Pro or above) or an Anthropic API key, so unlike the rest of the project it isn't free.

### Installing it

If the `claude` command isn't installed yet, install it, open a new terminal, and check it with `claude --version`:

Windows (PowerShell):

```powershell
irm https://claude.ai/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

The installer shows nothing while it downloads, which can take a minute or two, so give it time. The Claude Code extension for VS Code doesn't add the `claude` command, so install it even if you already use the extension. For other install options, see the [setup guide](https://code.claude.com/docs/en/setup).

If a new terminal still says `claude` isn't found, the install folder isn't on your PATH. Add it, then open another new terminal:

Windows (PowerShell):

```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.local\bin", "User")
```

macOS / Linux (on Linux with bash, use `~/.bashrc` instead of `~/.zshrc`):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

In VS Code on Windows, a new terminal isn't enough: quit and reopen VS Code. If `claude` still isn't found, see [Fix your PATH](https://code.claude.com/docs/en/troubleshoot-install#command-not-found-claude-after-installation).

**Still stuck installing Claude Code.** If you have the Claude Code extension in VS Code, ask it to add the `claude` install folder to your PATH.

### Using it

**`/mcp` shows `insurance` as failed.** Check the server is running and `http://localhost:8000/health` returns `{"status":"ok"}`, then start a new Claude Code session with `claude`. A session that was already running, in the terminal or the VS Code extension, won't see a newly added server.

**`insurance` shows as failed, with a `401`.** The token doesn't match. Stop the server, run `claude mcp remove insurance`, add it again with the right token, then start the server again.

**Answers are empty, or a customer "doesn't exist".** Check which token the client uses. `local` sees everything. `claude`, `copilot` and `inspector` each see part of the data, and any other name sees nothing. See [Give each client its own token](appendix-a-server-security.md#give-each-client-its-own-token).

**`/mcp` doesn't list `insurance` at all.** Either the session started before you added the server, so run `/clear` (or start a new session) and `/mcp` again, or you ran `claude mcp add` from a different folder. Run `claude mcp list` from the repository folder to check, and add it again from there if it's missing.

To see which servers Claude Code has for this folder and whether each one connects, or to remove `insurance` so you can add it again (for example with a new token), run these from the repository folder. Stop the server before you remove and add `insurance`, and start it again afterwards.

```bash
claude mcp list
claude mcp remove insurance
```

## Search by meaning (RAG)

**The assistant says "Run the embed command first."** Either the embed command hasn't been run, or the setup command has been run since. Run `uv run python -m insurance_database.embed`. If you ran it with `--booklets-only`, the policy questions work but the claim searches don't: run it again without the flag.

**`permission denied to create extension "vector"`** from the setup command. pgvector can only be installed by a superuser. Locally, `ADMIN_DATABASE_URL` connects as `postgres`, which is one. On a hosted database, use the admin role the service gives you, or install the extension from the service's dashboard.

**`You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN`.** You can ignore it. Hugging Face shows it for every download without a token, but the model is free and public, so you don't need an account or a token.

**The download stops or fails.** Hugging Face can be slow, or limit requests. Stop the command and run it again.

## Remove everything

Use this to start again from scratch, or to remove the project for good. Three things live outside the repository folder: the database, the Docker image and your assistant's entry for the server. Run these from the repository folder, in this order:

1. **Stop the MCP server** with `Ctrl+C`, if it's running.
2. **Remove the server from your assistant.**
   - Claude Code: `claude mcp remove insurance`.
   - Copilot: run **MCP: Open User Configuration**, choose **Copilot Global**, and delete the `insurance` entry.
3. **Delete the database**, with Docker running: `docker compose down -v`. Do it before you delete the folder, because Docker names the database after the folder. Otherwise the database stays behind, and a new copy in a folder with the same name gets the old data and the old password.
4. **Delete the Docker images**, if you're removing the project for good. Keep them if you're starting again: they're a large download. `pgvector/pgvector:pg18` is the database, and the tests use `testcontainers/ryuk` to clean up their containers:

   ```bash
   docker image rm pgvector/pgvector:pg18
   docker image ls testcontainers/ryuk
   ```

   Delete each `ryuk` image listed with `docker image rm` and its name, such as `testcontainers/ryuk:0.8.1`.
5. **Delete the folder.** The `.env` file, the Python environment and the downloaded model are all inside it, so they go with it.
6. **Delete your fork**, if you made one on GitHub: on the fork's page, **Settings**, then **Delete this repository** at the bottom. A plain clone needs nothing more.

To start again, follow the quickstart from step 1.

If you missed step 3: run `docker volume ls`, find the volume named after the folder, such as `insurance-mcp-python_pgdata`, and delete it with `docker volume rm` and its name.

**The tools you installed for it,** such as Docker, uv, VS Code or Claude Code, are yours to keep or remove. If you want to remove them, each one's own docs say how, for example [uninstalling uv](https://docs.astral.sh/uv/getting-started/installation/#uninstallation) and [uninstalling Claude Code](https://code.claude.com/docs/en/setup#uninstall-claude-code). Claude Code's steps also delete your settings for every project, not just this one.
