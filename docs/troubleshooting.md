# Troubleshooting

Find the step you're on, then the message you see.

## Setting up

**`Field required` for `admin_database_url` or `reader_database_url`.** There's no `.env` file, or the command isn't running in the repository folder. Run `cd insurance-mcp-python`, then `cp .env.example .env` (on Windows, `copy .env.example .env`).

**`The token for 'local' is shorter than 32 characters.`** A token in `MCP_TOKENS` is too short. Make one with `uv run python -m insurance_mcp.auth` and put it in `MCP_TOKENS`.

## The database

**`Cannot connect to the Docker daemon`** or **`docker: command not found`.** Docker isn't started, or isn't installed. Open Docker Desktop and wait until it says it's running, then run the command again.

**`no configuration file provided: not found`.** You're not in the project folder, so Docker can't find `docker-compose.yml`. Run `cd insurance-mcp-python`, then run the command again.

**`password authentication failed for user "postgres"`.** Docker only reads `POSTGRES_PASSWORD` the first time it creates the database. If you changed it afterwards, the database still has the old one. Either put the old password back, or delete the database with `docker compose down -v` and run the quickstart's step 2 again. It happens with a second copy of the repository too, in a folder with the same name, such as a fresh clone somewhere else. Docker names the database volume after the folder, so both copies share one database, with the first copy's password. If you changed the passwords in the first copy, copy its `.env` into the second.

**`port is already allocated` or `address already in use`.** Something else on your machine, probably another PostgreSQL, is using port 5432. Stop it, or change the first `5432` under `ports:` in `docker-compose.yml` (for example to `127.0.0.1:5433:5432`) and use the same port in both connection strings in `.env`.

**`Setup stopped: The mcp_reader password in READER_DATABASE_URL must be at least 24 characters.`** Make a longer one with `uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`.

**`connection refused`.** The database isn't running. Start Docker, then run `docker compose up -d --wait`.

## The server

**`The token for 'local' is shorter than 32 characters.`** Make a token with `uv run python -m insurance_mcp.auth` and put it in `MCP_TOKENS`.

**`MCP_TOKENS must be name:token pairs, separated by commas.`** Each entry needs a name, a colon and a token, such as `local:abc...`, with a comma between entries.

**The server stops with `Connection refused` and `Application startup failed`.** It checks the database when it starts, and stops if it can't connect. Start Docker, then run `docker compose up -d --wait`.

**`password authentication failed for user "mcp_reader"`.** The password in `READER_DATABASE_URL` isn't the one in the database. The setup command sets it, so run it again after changing the password: `uv run python -m insurance_mcp.setup_db`.

**`address already in use`.** Something else is using port 8000. Stop it, or set `PORT` in `.env` to another port, such as `8001`, and use that port in the URLs.

**Every tool answers, but finds nothing (0 customers).** The token's name isn't one the database knows. Use `local`, or one of `claude`, `copilot` and `inspector` from [guide 3](guides/03-server-security.md#give-each-client-its-own-token). [Row-level security](guides/02-database-security.md#row-level-security-step-by-step) explains why.

**`401 Unauthorized` with a token.** The header must be `Authorization: Bearer <token>`, with the word `Bearer` and one space. Check the token matches one in `MCP_TOKENS` exactly, and restart the server after changing `.env`: it reads the file only when it starts.

**`421` and `Invalid Host header`.** The request was addressed to a host name that isn't in `ALLOWED_HOSTS`. Use `localhost` or `127.0.0.1` in the URL, or add the name to `ALLOWED_HOSTS`.

**`403` and `Invalid Origin header`.** The request came from a web page. AI clients don't run in a browser, so the server refuses any request a web page sends.

**`429 Too Many Requests`.** Wait the number of seconds in the `Retry-After` header. The counts are kept in memory, so restarting the server resets them.

## VS Code and Copilot

**VS Code shows connection errors for `insurance` when you paste the config.** Paste the config while the server is stopped, then start the server. That's the order that works reliably. If it's already in a bad state, restart the `insurance` server in VS Code: **MCP: List Servers**, `insurance`, **Restart Server**.

**No insurance tools in the tools picker.** Check the server is still running and `http://localhost:8000/health` returns `{"status":"ok"}`, then restart the `insurance` server in VS Code: run **MCP: List Servers** from the Command Palette, choose `insurance`, then **Restart Server**.

**`401` or "unauthorized" errors.** The token doesn't match. Check that the header reads `Bearer ` followed by the exact token, with no `<` or `>` left in, then restart the `insurance` server. If you changed `MCP_TOKENS`, restart the server too: it reads `.env` only when it starts.

**"Input and command variables are not supported by the Copilot harness".** The configuration still uses `${input:...}`. Replace it with the token itself, as the README shows, and delete the `inputs` block.

**"Failed to read configuration from .../.copilot/mcp-config.json: mcpServers: Required".** The Copilot CLI's own configuration file is empty or invalid, and Copilot's agent reads it as well as the VS Code configuration. Delete it, then restart VS Code.

Windows (PowerShell):

```powershell
Remove-Item "$HOME\.copilot\mcp-config.json"
```

macOS / Linux:

```bash
rm ~/.copilot/mcp-config.json
```

**Copilot lists the tools but never calls them.** It's probably reading them from the code in the repository, and that answer looks right even when nothing is connected. Ask again, starting with "Use the insurance server to...", and check that Copilot shows a tool call. The 13 tools should also be listed and selected in the tools picker.

**It works in MCP Inspector but not in VS Code.** The server is fine, so check the URL and the header in the VS Code configuration.

**`429 Too Many Requests`.** The assistant has made more than 60 calls in a minute, or 1,000 in a day. Wait, or restart the server, which resets the counts.

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

**Answers are empty, or a customer "doesn't exist".** Check which token the client uses. `local` sees everything. `claude`, `copilot` and `inspector` each see part of the data, and any other name sees nothing. See [Give each client its own token](guides/03-server-security.md#give-each-client-its-own-token).

**`/mcp` doesn't list `insurance` at all.** Either the session started before you added the server, so start a new one, or you ran `claude mcp add` from a different folder. Run `claude mcp list` from the repository folder to check, and add it again from there if it's missing.

To see which servers Claude Code has for this folder and whether each one connects, or to remove `insurance` so you can add it again (for example with a new token), run these from the repository folder. Stop the server before you remove and add `insurance`, and start it again afterwards.

```bash
claude mcp list
claude mcp remove insurance
```

## Search by meaning (RAG)

**The assistant says "Run the embed command first."** Either the embed command hasn't been run, or the setup command has been run since. Run `uv run python -m insurance_mcp.embed`. If you ran it with `--booklets-only`, the policy questions work but the claim searches don't: run it again without the flag.

**`permission denied to create extension "vector"`** from the setup command. pgvector can only be installed by a superuser. Locally, `ADMIN_DATABASE_URL` connects as `postgres`, which is one. On a hosted database, use the admin role the service gives you, or install the extension from the service's dashboard.

**The download stops or fails.** Hugging Face can be slow, or limit requests. Stop the command and run it again.
