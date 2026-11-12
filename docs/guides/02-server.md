# Guide 2: the MCP server

By the end of this guide the MCP server will be running on your own machine, connected to the database from guide 1, and only answering requests that carry one of your named tokens. You can also call its tools from MCP Inspector if you like.

Everything here is free, and the commands are the same on Windows, macOS and Linux.

## What you need

- **Guide 1 done:** the database running in Docker (`docker compose ps` says `healthy`) and the data loaded.
- **Optional, for MCP Inspector only:** [Node.js](https://nodejs.org/), the current LTS version. It provides `npx`, which downloads and runs Inspector. The server itself doesn't need Node.js.

## 1. Make your token

AI clients prove who they are with a **bearer token**: a long random secret sent in the `Authorization` header of every request. Each token has a name. You start with one, called `local`:

```text
MCP_TOKENS=local:<a long random token>
```

The name is who the server thinks is calling. It goes in the audit log next to every tool call, the rate limits count calls per name, and it decides which customers the caller sees: `local` sees them all (see [row-level security](01-database.md#row-level-security-step-by-step) in guide 1). Guides 2 and 3 use `local` for every client. At the end of guide 3 you give each client its own token, so the audit log shows which client did what.

This command prints a new random token:

```bash
uv run python -m insurance_mcp.auth
```

Paste it into `MCP_TOKENS` in your `.env`, in place of `replace-with-a-generated-token`. Keep the name `local`: a name the database doesn't know sees no customers at all. Tokens must be at least 32 characters, and the server refuses to start with a shorter one.

Treat tokens like passwords: they stay in `.env`, which is git-ignored. Guide 3 shows how to give a token to an AI client without pasting it into a file that might get committed.

### The server settings

The other server settings in `.env` have sensible defaults, so you don't need to change them.

| Setting | What it's for | Default |
|---|---|---|
| `MCP_TOKENS` | The named tokens, as `name:token` pairs separated by commas | None: you must set it |
| `ALLOWED_HOSTS` | The host names the server answers to. A request addressed to any other name is refused. | `localhost,127.0.0.1` |
| `RATE_LIMIT_PER_MINUTE` | How many requests each caller may make per minute | `60` |
| `RATE_LIMIT_PER_DAY` | How many requests each caller may make per day | `1000` |
| `DB_POOL_MAX_SIZE` | The most database connections the server opens at once | `5` |
| `HOST`, `PORT` | Where the server listens. `127.0.0.1` means only this machine can reach it. | `127.0.0.1`, `8000` |

The server reads `READER_DATABASE_URL` to connect as `mcp_reader`. It never reads `ADMIN_DATABASE_URL`: nothing in the server can connect as admin.

## 2. Start the server

```bash
uv run python -m insurance_mcp.main
```

You should see:

```text
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO: mcp.server.streamable_http_manager: StreamableHTTP session manager started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Leave it running, and open a second terminal for the rest of this guide. Press `Ctrl+C` to stop the server.

The server is a [FastAPI](https://fastapi.tiangolo.com/) app run by uvicorn. It has two addresses:

- **`/mcp`** is the MCP endpoint, where AI clients send their requests. It needs a token.
- **`/health`** says the server is up, for Docker and hosting checks. It needs no token, and says nothing about the database.

## 3. Check it's working

```bash
curl http://localhost:8000/health
```

```text
{"status":"ok"}
```

Now try the MCP endpoint without a token:

```bash
curl -i -X POST http://localhost:8000/mcp
```

```text
HTTP/1.1 401 Unauthorized
...
{"error":"Missing or invalid bearer token."}
```

On Windows, `curl` is built in from Windows 10 onwards. In Windows PowerShell 5.1, type `curl.exe` rather than `curl`, which there means a different command.

In the server's terminal, the rejected request is logged without its token:

```text
WARNING: insurance_mcp.main: Rejected request: status=401 caller=None ip='127.0.0.1'
INFO:     127.0.0.1:65431 - "POST /mcp HTTP/1.1" 401 Unauthorized
```

## 4. Optional: call a tool from MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) is the MCP project's own tool for testing servers. It shows you the tools exactly as an AI client sees them, and lets you call them by hand. It needs Node.js.

```bash
npx @modelcontextprotocol/inspector@2.14.0
```

The version is pinned, so you run the one this guide was tested with. The first time, `npx` asks to download it. It then prints an address with a long token on the end, and opens it in your browser. That token is Inspector's own, not one of yours. In Inspector:

1. Choose the **Streamable HTTP** transport.
2. Enter the URL `http://localhost:8000/mcp`.
3. Add a header `Authorization` with the value `Bearer <your token>`: the word `Bearer`, a space, then your `local` token from `MCP_TOKENS`.
4. Connect, open the tools list, and run `get_dataset_info`. It takes no arguments.

You should get:

```json
{
  "as_of_date": "2026-12-31",
  "first_date_reported": "2024-01-01",
  "customer_count": 12002,
  "policy_count": 14930,
  "claim_count": 15090,
  "open_claim_count": 781
}
```

Look at the tool's details too: its description is written for the model, and it's marked read-only (`readOnlyHint`).

Then try a tool that takes arguments: run `get_policy` with the policy number `AUT-104233`, then with `AUT-999999`, which doesn't exist. The second comes back as a tool error with a message that tells the model how to find the right number. Try `AUT-12` as well: the server rejects it before it reaches the database.

**Prefer the command line?** Inspector has a CLI mode that makes one call and prints the result:

```bash
npx @modelcontextprotocol/inspector@2.14.0 --cli http://localhost:8000/mcp --transport http --header "Authorization: Bearer <your token>" --method tools/call --tool-name get_dataset_info
```

Replace `--method tools/call --tool-name get_dataset_info` with `--method tools/list` to list the tools. Arguments go in `--tool-arg`, for example `--tool-name get_policy --tool-arg policy_number=AUT-104233`. The token ends up in your shell's history this way, so it's for trying things out, not for every day.

## 5. See the audit log

Every tool call is recorded in the audit log, in the database. Look at the latest rows as the admin role:

```bash
docker compose exec db psql -U postgres -d insurance -c "select occurred_at, caller, tool_name, rows_returned, succeeded from insurance.audit_log order by id desc limit 5"
```

```text
          occurred_at          |   caller    |    tool_name     | rows_returned | succeeded
-------------------------------+-------------+------------------+---------------+-----------
 2026-11-05 22:41:07.512836+00 | local       | get_dataset_info |             1 | t
```

The `caller` is the name of the token that made the call. If the server can't write the audit row, it doesn't return the tool's result either: no audit, no answer. Requests that never reach a tool, such as ones with a bad token, aren't in the audit log. They're in the server's own log, because anyone can send a bad token, and the audit log can never be cleaned up.

## What happens to each request

Every request to `/mcp` passes these checks in order, and each one holds even if the one before it fails:

| # | Check | Done by | If it fails |
|---|---|---|---|
| 1 | **Token:** does it carry one of the named tokens? | Our code ([`main.py`](../../src/insurance_mcp/main.py), [`auth.py`](../../src/insurance_mcp/auth.py)) | `401` |
| 2 | **Rate limit:** has this caller made too many requests? | Our code ([`rate_limit.py`](../../src/insurance_mcp/rate_limit.py)) | `429`, with a `Retry-After` header saying how many seconds to wait |
| 3 | **Host:** is it addressed to a name in `ALLOWED_HOSTS`, and not sent by a web page? | The MCP SDK | `421` for the host, `403` for a web page |
| 4 | **Size:** is the body under 64 KB? | The MCP SDK | `413` |
| 5 | **Tool and arguments:** is it one of our tools, with valid arguments and nothing else? | The MCP SDK, and our check for unknown arguments ([`tools.py`](../../src/insurance_mcp/tools.py)) | A tool error, with a message the model can act on |
| 6 | **Database:** the tool runs exactly one `mcp` function as `mcp_reader` | [`db.py`](../../src/insurance_mcp/db.py) and the database (guide 1) | A tool error: the function's own message, or a generic one |
| 7 | **Audit:** the call is recorded | [`audit.py`](../../src/insurance_mcp/audit.py) | A generic tool error, and no result |

**Why the host check?** It blocks **DNS rebinding**, a trick where a web page you visit makes your own browser send requests to a server on your machine. A page like that doesn't have your token, so step 1 stops it anyway, but the MCP spec asks local servers to check the host too, and the SDK does it for us.

**Why tool errors and not HTTP errors?** MCP is JSON-RPC over HTTP. Once a request has reached a tool, problems come back as a normal response marked as an error, which the model reads, so it can fix its call. "No such policy" is a tool error, not a `404`.

[server-spec.md](../specs/server-spec.md) explains every check in detail.

## Run the server tests

With Docker running:

```bash
uv run pytest tests/server
```

The tests start the server inside the test process, with no network port, and talk to it with the MCP SDK's own client, through every check above. They prove, among other things, that a missing or wrong token gets `401`, that the call after the rate limit gets `429`, that an unknown argument is rejected without touching the database, and that a tool call returns nothing if its audit row can't be written.

## Troubleshooting

**`The token for 'local' is shorter than 32 characters.`** Make a token with `uv run python -m insurance_mcp.auth` and put it in `MCP_TOKENS`.

**`MCP_TOKENS must be name:token pairs, separated by commas.`** Each entry needs a name, a colon and a token, such as `local:abc...`, with a comma between entries.

**The server stops with `Connection refused` and `Application startup failed`.** It checks the database when it starts, and stops if it can't connect. Start Docker, then run `docker compose up -d`.

**`password authentication failed for user "mcp_reader"`.** The password in `READER_DATABASE_URL` isn't the one in the database. The setup command sets it, so run it again after changing the password: `uv run python -m insurance_mcp.setup_db`.

**`address already in use`.** Something else is using port 8000. Stop it, or set `PORT` in `.env` to another port, such as `8001`, and use that port in the URLs.

**Every tool answers, but finds nothing (0 customers).** The token's name isn't one the database knows. Use `local`, or one of `claude`, `copilot` and `inspector` from guide 3. [Row-level security](01-database.md#row-level-security-step-by-step) in guide 1 explains why.

**`401 Unauthorized` with a token.** The header must be `Authorization: Bearer <token>`, with the word `Bearer` and one space. Check the token matches one in `MCP_TOKENS` exactly, and restart the server after changing `.env`: it reads the file only when it starts.

**`421` and `Invalid Host header`.** The request was addressed to a host name that isn't in `ALLOWED_HOSTS`. Use `localhost` or `127.0.0.1` in the URL, or add the name to `ALLOWED_HOSTS`.

**`403` and `Invalid Origin header`.** The request came from a web page. AI clients don't run in a browser, so the server refuses any request a web page sends.

**`429 Too Many Requests`.** Wait the number of seconds in the `Retry-After` header. The counts are kept in memory, so restarting the server resets them.

## Next

[Guide 3](03-ai-assistant.md) connects an AI assistant to the server: GitHub Copilot in VS Code (free) or Claude Code.
