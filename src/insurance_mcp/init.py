"""Make your .env file, then print the config your AI client needs.

Run it with:  uv run python -m insurance_mcp.init

With no .env, it copies .env.example to .env and puts in random passwords and a
token. With a .env already there, it changes nothing. Either way, it then prints
the config for VS Code and Claude Code, with your local token filled in.

It never changes a client's config itself: those files are in your home folder,
so you paste the config in.
"""

import json
import secrets
from pathlib import Path

from insurance_mcp.auth import new_token
from insurance_mcp.settings import Settings

ENV_FILE = Path(".env")
EXAMPLE_FILE = Path(".env.example")


def new_password() -> str:
    """32 random characters: letters, digits, - and _ only, so it fits in a URL unescaped."""
    return secrets.token_urlsafe(24)


def env_from_example(example: str) -> str:
    """The text of .env.example, with random secrets in place of the placeholders.

    The admin password appears twice (POSTGRES_PASSWORD and ADMIN_DATABASE_URL),
    and str.replace puts the same new password in both, so they match.
    """
    return (
        example.replace("change-me-admin-password", new_password())
        .replace("change-me-reader-password", new_password())
        .replace("replace-with-a-generated-token", new_token())
    )


def client_config(token: str, port: int) -> str:
    """What to paste into VS Code, and the command to run for Claude Code."""
    url = f"http://localhost:{port}/mcp"
    vs_code = {
        "servers": {
            "insurance": {
                "type": "http",
                "url": url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }
    return f"""\
VS Code: open the Command Palette (Cmd+Shift+P on macOS, Ctrl+Shift+P on
Windows and Linux), run "MCP: Open User Configuration", and paste this in.
If the file already lists other servers, add "insurance" alongside them.

{json.dumps(vs_code, indent=2)}

Claude Code: run this from this folder instead.

claude mcp add --transport http insurance {url} --header "Authorization: Bearer {token}"

The token is a secret: keep it out of any file in this repository."""


def main() -> None:
    if ENV_FILE.exists():
        print(".env already exists, so it's unchanged.\n")
    else:
        ENV_FILE.write_text(env_from_example(EXAMPLE_FILE.read_text()))
        print("Made .env with new random passwords and a token. It's git-ignored.\n")

    settings = Settings()
    if "local" not in settings.mcp_tokens:
        print("MCP_TOKENS in .env has no token called local, so there's no config to print.")
        return
    print(client_config(settings.mcp_tokens["local"], settings.port))


if __name__ == "__main__":
    main()
