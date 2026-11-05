# Guide 3: connect an AI assistant

By the end of this guide you'll be asking questions about the insurance data in plain English, and watching the assistant answer them by calling the server's tools. You'll also see it fail to change anything.

The main path is GitHub Copilot in VS Code, which has a free plan. To use Claude Code instead, skip to [Use Claude Code instead](#use-claude-code-instead).

## What you need

- **Guides 1 and 2 done:** the database running with its data loaded, and your tokens in `MCP_TOKENS` in `.env`. MCP Inspector isn't needed.
- **[VS Code](https://code.visualstudio.com/)** with **GitHub Copilot**. The [free plan](https://github.com/features/copilot/plans) is enough. Sign in to GitHub from VS Code when it asks.

**If the server from guide 2 is still running, stop it first** (`Ctrl+C` in its terminal). Add the server to VS Code first, then start it. That's the order that works reliably: if you add it while the server is running, you may run into connection problems.

## 1. Add the server to VS Code

Open the Command Palette (`Ctrl+Shift+P` on Windows and Linux, `Cmd+Shift+P` on macOS) and run **MCP: Open User Configuration**. Add the `insurance` server below. If the file already lists other servers, add `insurance` alongside them.

```json
{
  "servers": {
    "insurance": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

Replace `<token>` with the `copilot` token from `MCP_TOKENS` in `.env`: the part after `copilot:`, up to the comma. Save the file.

**Where the token lives:** in plain text, in your VS Code user configuration in your home folder, not in the repository. It only works against the server on your own machine. Never put it in a `.vscode/mcp.json` file inside a repository, where it could be committed.

VS Code can ask for a token instead of storing it in the file, using an `inputs` block and `${input:...}`, but Copilot's agent doesn't support input variables, so we write the token in. For all the options, see the [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

## 2. Start the server

From the repository folder, start the server and leave it running in its own terminal:

```bash
uv run python -m insurance_mcp.main
```

## 3. Connect

Open Copilot Chat and switch it to **Agent** mode. If VS Code asks whether you trust the `insurance` server, confirm. Then ask:

- "List the tools on the insurance MCP server, then call get_dataset_info to check it works. Use the server, not the code in this repository."

Copilot can read the repository, so if you just ask what tools there are, it may answer from the source code instead of calling the server. That answer looks right even when nothing is connected. Check that Copilot shows a tool call. The 10 tools should also be listed and selected in the tools picker.

When it calls a tool, Copilot asks you to approve the call first. Leave that switched on (see [Keep it safe](#keep-it-safe)).

## 4. Ask questions

Each of these has an exact answer in the data. Most need several tools in a row, and Copilot shows each call as it makes it, so you can see how it breaks the question down.

- "Find the customer called Rutherford and show their policies."
- "What's covered on policy AUT-104233, and what's the deductible?"
- "Which open claims are over $20k and more than 90 days old?"
- "Which repair shops have the highest average repair cost this year?"
- "How many windshield claims did we have last month, compared with the month before?"
- "Show me the claim history for Maria Garcia. Has she claimed more than twice in three years?"
- "Which adjuster has the most open claims?"
- "How many at-fault claims involved a teenage driver this year?"

A few words used here: the **deductible** is the part of a claim the customer pays themselves, the **reserve** is what the insurer expects a claim to cost in total, and an **adjuster** is the insurer's employee who handles the claim.

**"This year" and "last month" mean 2026.** The data ends on 2026-12-31, and the server tells the assistant to treat that date as today. So "last month" is November 2026, whatever today's date is.

Now ask it to change something:

- "Please accept Maria Garcia's claim. She's a good friend of mine."

It can't. None of the tools can change data, and even if one tried, the database role the server uses has no permission to write.

Every call you just made is in the audit log, under the caller name `copilot`. Guide 2, step 5, shows how to look.

## Keep it safe

The server only reads, but read-only isn't the same as harmless. Some claim notes contain text written to trick the assistant (a **prompt injection**), the same way a real customer email might. If the assistant also had a tool that can send data out, such as web fetch, email, or a GitHub or Slack MCP server, a note could tell it to collect customer details and send them somewhere. Private data, untrusted text and a way to send data out, all in one assistant, is called the **lethal trifecta**.

Two habits close it:

- **Keep the assistant asking before it runs a tool,** and read what it's about to do. Copilot and Claude Code both ask by default. Don't choose "always allow".
- **Don't connect this server to an assistant that also has tools that can send data out.** Copilot's agent and Claude Code can both fetch web pages, so watch for a fetch you didn't ask for.

[server-spec.md](../specs/server-spec.md), decision 11, has the details.

## Use Claude Code instead

[Claude Code](https://code.claude.com/docs) can use the same server. It needs a paid Claude plan (Pro or above) or an Anthropic API key, so unlike the rest of the project it isn't free.

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

If the server is running, stop it first with `Ctrl+C`. Then run this from the repository folder, replacing `<token>` with the `claude-code` token from `MCP_TOKENS` in `.env`:

```bash
claude mcp add --transport http insurance http://localhost:8000/mcp --header "Authorization: Bearer <token>"
```

This adds the server only for the folder you run it in, so run it from the repository folder, not your home folder. Claude Code stores it, token included, in `.claude.json` in your home folder, not in the repository. Don't add `--scope project`: that writes the server and its token to `.mcp.json` in the repository, where it could be committed.

Start the server again (`uv run python -m insurance_mcp.main`). Then start Claude Code with `claude`, run `/mcp`, and check that `insurance` shows as connected. A session that was already running, in the terminal or the VS Code extension, won't see the new server, so start a new one. The VS Code extension can use the server too, as long as VS Code has the repository folder open.

Then try the questions above, including the one it must refuse. The audit log shows these calls under `claude-code`.

To see which servers Claude Code has for this folder and whether each one connects, or to remove `insurance` so you can add it again (for example with a new token), run these from the repository folder. Stop the server before you remove and add `insurance`, and start it again afterwards.

```bash
claude mcp list
claude mcp remove insurance
```

## Troubleshooting

### VS Code and Copilot

**No insurance tools in the tools picker.** Check the server is still running and `http://localhost:8000/health` returns `{"status":"ok"}`, then restart the `insurance` server in VS Code: run **MCP: List Servers** from the Command Palette, choose `insurance`, then **Restart Server**.

**`401` or "unauthorized" errors.** The token doesn't match. Check that the header reads `Bearer ` followed by the exact `copilot` token, with no `<` or `>` left in, then restart the `insurance` server. If you changed `MCP_TOKENS`, restart the server too: it reads `.env` only when it starts.

**"Input and command variables are not supported by the Copilot harness".** The configuration still uses `${input:...}`. Replace it with the token itself, as shown in step 1, and delete the `inputs` block.

**"Failed to read configuration from .../.copilot/mcp-config.json: mcpServers: Required".** The Copilot CLI's own configuration file is empty or invalid, and Copilot's agent reads it as well as the VS Code configuration. Delete it, then restart VS Code.

Windows (PowerShell):

```powershell
Remove-Item "$HOME\.copilot\mcp-config.json"
```

macOS / Linux:

```bash
rm ~/.copilot/mcp-config.json
```

**Copilot lists the tools but never calls them.** It's probably reading them from the code. Ask again as in step 3, telling it to use the server and not the code.

**It works in MCP Inspector but not in VS Code.** The server is fine, so check the URL and the header in the VS Code configuration.

**`429 Too Many Requests`.** The assistant has made more than 60 calls in a minute, or 1,000 in a day. Wait, or restart the server, which resets the counts.

### Claude Code

**`insurance` shows as failed, with a `401`.** The token doesn't match. Stop the server, run `claude mcp remove insurance`, add it again with the right token, then start the server again.

**`/mcp` doesn't list `insurance` at all.** Either the session started before you added the server, so start a new one, or you ran `claude mcp add` from a different folder. Run `claude mcp list` from the repository folder to check, and add it again from there if it's missing.

**Still stuck installing Claude Code.** If you have the Claude Code extension in VS Code, ask it to add the `claude` install folder to your PATH.

## Other AI assistants

The server isn't tied to VS Code or Claude Code. Any MCP client that can connect to a remote (HTTP) server and send an `Authorization` header can use it, with the same URL, `http://localhost:8000/mcp`. Give each client its own named token in `MCP_TOKENS`, so the audit log shows which one made each call. See your client's documentation for how to add a server.

## Next

[Using this with your own data](../using-your-own-data.md) explains how to point the same design at a real company's data, and lists the honest limits in one place.
