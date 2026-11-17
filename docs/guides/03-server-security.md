# Guide 3: server security

Before a tool call reaches the database, the MCP server checks who's calling, how often, where the request is addressed, how big it is, and every argument. This guide shows each check, with `curl` and MCP Inspector, and ends with a token for each AI assistant, so each one sees its own part of the data.

You need the quickstart done, with the server running (`uv run python -m insurance_mcp.main`). Open a second terminal for the commands here.

## Tokens

AI clients prove who they are with a **bearer token**: a long random secret sent in the `Authorization` header of every request. Each token has a name. The `.env` you copied has one, called `local`:

```text
MCP_TOKENS=local:local-only-token-replace-with-your-own
```

The name is who the server thinks is calling. It goes in the audit log next to every tool call, the rate limits count calls per name, and it decides which customers the caller sees: `local` sees them all (see [row-level security](02-database-security.md#row-level-security-step-by-step) in guide 2). At the end of this guide you give each client its own token, so the audit log shows which client did what.

This command prints a new random token:

```bash
uv run python -m insurance_mcp.auth
```

Tokens must be at least 32 characters, and the server refuses to start with a shorter one. A name the database doesn't know sees no customers at all.

Treat tokens like passwords: they stay in `.env`, which is git-ignored.

### Replace the example token

The example token is in a public repository, so everyone knows it. On your own machine that's fine: the server only listens on `127.0.0.1`, so nothing else can reach it. Before you run the server anywhere else, replace it:

1. Make a new token with `uv run python -m insurance_mcp.auth`.
2. Put it in `MCP_TOKENS` in `.env`, after `local:`, and restart the server. It reads `.env` only when it starts.
3. Put it in your AI assistant too. For Copilot, run **MCP: Open User Configuration**, choose **Copilot Global**, and replace the token after `Bearer `. In Claude Code, stop the server, run `claude mcp remove insurance`, run the `claude mcp add` line from the README with the new token, and start the server again.

Replace the example database passwords the same way: [guide 2](02-database-security.md#the-database-settings) shows how.

### Where your AI assistant keeps the token

- **VS Code** keeps it in plain text in your user configuration, in your home folder, not in the repository. Never put it in a `.vscode/mcp.json` file inside a repository, where it could be committed. VS Code can ask for a token instead of storing it, using an `inputs` block and `${input:...}`, but Copilot's agent doesn't support input variables, so the token is written in. See the [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers).
- **Claude Code** keeps it in `.claude.json` in your home folder. `claude mcp add` adds the server only for the folder you run it in, so run it from the repository folder. Don't add `--scope project`: that writes the server and its token to `.mcp.json` in the repository, where it could be committed.

## The server settings

The other server settings in `.env` have sensible defaults, so you don't need to change them.

| Setting | What it's for | Default |
|---|---|---|
| `MCP_TOKENS` | The named tokens, as `name:token` pairs separated by commas | None: you must set it |
| `ALLOWED_HOSTS` | The host names the server answers to. A request addressed to any other name is refused. | `localhost,127.0.0.1` |
| `RATE_LIMIT_PER_MINUTE` | How many requests each caller may make per minute | `60` |
| `DB_POOL_MAX_SIZE` | The most database connections the server opens at once | `5` |
| `HOST`, `PORT` | Where the server listens. `127.0.0.1` means only this machine can reach it. | `127.0.0.1`, `8000` |

The server reads `READER_DATABASE_URL` to connect as `mcp_reader`. It never reads `ADMIN_DATABASE_URL`: nothing in the server can connect as admin.

## The two addresses

The server is a [FastAPI](https://fastapi.tiangolo.com/) app run by uvicorn. It has two addresses:

- **`/mcp`** is the MCP endpoint, where AI clients send their requests. It needs a token.
- **`/health`** says the server is up, for Docker and hosting checks. It needs no token, and says nothing about the database.

## Try the checks with curl

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

## Optional: call a tool from MCP Inspector

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

## What happens to each request

Every request to `/mcp` passes these checks in order, and each one holds even if the one before it fails:

| # | Check | Done by | If it fails |
|---|---|---|---|
| 1 | **Token:** does it carry one of the named tokens? | Our code ([`main.py`](../../src/insurance_mcp/main.py), [`auth.py`](../../src/insurance_mcp/auth.py)) | `401` |
| 2 | **Rate limit:** has this caller made too many requests? | Our code ([`rate_limit.py`](../../src/insurance_mcp/rate_limit.py)) | `429`, with a `Retry-After` header saying how many seconds to wait |
| 3 | **Host:** is it addressed to a name in `ALLOWED_HOSTS`, and not sent by a web page? | The MCP SDK | `421` for the host, `403` for a web page |
| 4 | **Size:** is the body under 64 KB? | The MCP SDK | `413` |
| 5 | **Tool and arguments:** is it one of our tools, with valid arguments and nothing else? | The MCP SDK, and our check for unknown arguments ([`tools.py`](../../src/insurance_mcp/tools.py)) | A tool error, with a message the model can act on |
| 6 | **Database:** the tool runs exactly one `mcp` function as `mcp_reader` | [`db.py`](../../src/insurance_mcp/db.py) and the database ([guide 2](02-database-security.md)) | A tool error: the function's own message, or a generic one |
| 7 | **Audit:** the call is recorded | [`audit.py`](../../src/insurance_mcp/audit.py) and the [audit log](02-database-security.md#the-audit-log) | A generic tool error, and no result |

**Why the host check?** It blocks **DNS rebinding**, a trick where a web page you visit makes your own browser send requests to a server on your machine. A page like that doesn't have your token, so step 1 stops it anyway, but the MCP spec asks local servers to check the host too, and the SDK does it for us.

**Why tool errors and not HTTP errors?** MCP is JSON-RPC over HTTP. Once a request has reached a tool, problems come back as a normal response marked as an error, which the model reads, so it can fix its call. "No such policy" is a tool error, not a `404`.

[server-spec.md](../specs/server-spec.md) explains every check in detail.

## Keep it safe

The server only reads, but read-only isn't the same as harmless. Some claim notes contain text written to trick the assistant (a **prompt injection**), the same way a real customer email might. If the assistant also had a tool that can send data out, such as web fetch, email, or a GitHub or Slack MCP server, a note could tell it to collect customer details and send them somewhere. Private data, untrusted text and a way to send data out, all in one assistant, is called the **lethal trifecta**.

Two habits close it:

- **Keep the assistant asking before it runs a tool,** and read what it's about to do. Copilot and Claude Code both ask by default. Don't choose "always allow".
- **Don't connect this server to an assistant that also has tools that can send data out.** Copilot's agent and Claude Code can both fetch web pages, so watch for a fetch you didn't ask for.

[server-spec.md](../specs/server-spec.md), decision 11, has the details.

## Give each client its own token

So far every client has used `local`, so the audit log can't tell Copilot's calls from Claude Code's, and every client sees every customer. Now give each client its own token. Each named token sees Texas and Colorado, where the demo customers live, plus one state of its own:

| Token | States | Sees, but the other two don't |
|---|---|---|
| `claude` | TX, CO, OK | Oklahoma |
| `copilot` | TX, CO, NM | New Mexico |
| `inspector` | TX, CO, AZ | Arizona |

This is row-level security, which [guide 2](02-database-security.md#row-level-security-step-by-step) shows in SQL. Here you see it through the clients you already use.

**1. Make three more tokens.** Run this three times:

```bash
uv run python -m insurance_mcp.auth
```

**2. Add them to `MCP_TOKENS` in `.env`,** after `local`, on the same line:

```text
MCP_TOKENS=local:<your local token>,claude:<new token 1>,copilot:<new token 2>,inspector:<new token 3>
```

Keep `local`: it still sees everything, which is handy for checking an answer.

**3. Give each client its token.** Stop the server first (`Ctrl+C`).

- **Copilot:** run **MCP: Open User Configuration**, choose **Copilot Global**, and replace the token after `Bearer ` with the `copilot` token.
- **Claude Code:** from the repository folder, remove the server and add it again with the `claude` token:

  ```bash
  claude mcp remove insurance
  claude mcp add --transport http insurance http://localhost:8000/mcp --header "Authorization: Bearer <claude token>"
  ```

Then start the server again (`uv run python -m insurance_mcp.main`), restart the `insurance` server in VS Code (**MCP: List Servers**, `insurance`, **Restart Server**), and start a new Claude Code session.

**4. Ask both the same questions:**

- "Find the customer called Wei Kim." Claude Code finds them in Oklahoma City. Copilot finds nobody: to Copilot, Wei Kim doesn't exist.
- "Find the customer called Mei Cruz." The other way round: Copilot finds them in Albuquerque, Claude Code doesn't.
- "Show me the claim history for Maria Garcia." Both find her, because both see Texas.

The `inspector` token sees Arizona: try `Ana Cook` in [MCP Inspector](#optional-call-a-tool-from-mcp-inspector) with it.

**5. Check the audit log.** As in [guide 2](02-database-security.md#the-audit-log), the `caller` column now shows `claude` and `copilot` instead of `local`.

**Your own token names.** A name the database doesn't know sees no customers at all: every answer comes back empty. To give a new name its states, connect as the admin (`docker compose exec db psql -U postgres -d insurance`) and add a row per state:

```sql
insert into insurance.caller_states (caller_key, state) values ('my-client', 'TX'), ('my-client', 'AZ');
```

Reloading the data keeps these rows. The setup command rebuilds the database from scratch, so after running it, add them again.

## Other AI assistants

The server isn't tied to VS Code or Claude Code. Any MCP client that can connect to a remote (HTTP) server and send an `Authorization` header can use it, with the same URL, `http://localhost:8000/mcp`. Give each client its own named token in `MCP_TOKENS`, so the audit log shows which one made each call, and give its name some states, as in [Give each client its own token](#give-each-client-its-own-token). See your client's documentation for how to add a server.

## Run the server tests

With Docker running:

```bash
uv run pytest tests/server
```

The tests start the server inside the test process, with no network port, and talk to it with the MCP SDK's own client, through every check above. They prove, among other things, that a missing or wrong token gets `401`, that the call after the rate limit gets `429`, that an unknown argument is rejected without touching the database, and that a tool call returns nothing if its audit row can't be written.

## Next

[Guide 4](04-rag.md) goes deep on search by meaning: how the embeddings are made and searched, the RAG tools, and what RAG isn't good for.

[Using this with your own data](../using-your-own-data.md) explains how to point the same design at a real company's data, and lists the honest limits in one place.
