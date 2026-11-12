"""An unedited copy of .env.example must work: the quickstart relies on it."""

import shutil
from pathlib import Path

from insurance_mcp.settings import Settings
from insurance_mcp.setup_db import SetupSettings, reader_password

ROOT = Path(__file__).parent.parent


def copy_example(tmp_path, monkeypatch) -> dict[str, str]:
    """Copy .env.example to .env in an empty folder, as the quickstart does."""
    shutil.copy(ROOT / ".env.example", tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    lines = Path(".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def test_the_server_accepts_the_example_settings(tmp_path, monkeypatch):
    copy_example(tmp_path, monkeypatch)

    assert "local" in Settings().mcp_tokens  # raises if the token is too short


def test_the_setup_command_accepts_the_example_settings(tmp_path, monkeypatch):
    copy_example(tmp_path, monkeypatch)

    reader_password(SetupSettings().reader_database_url)  # raises if too short


def test_the_admin_password_matches_in_both_places(tmp_path, monkeypatch):
    env = copy_example(tmp_path, monkeypatch)

    assert f":{env['POSTGRES_PASSWORD']}@" in env["ADMIN_DATABASE_URL"]


def test_the_readme_shows_the_example_token():
    # The README's VS Code and Claude Code config has the token filled in.
    token = "local-only-token-replace-with-your-own"

    assert f"MCP_TOKENS=local:{token}\n" in (ROOT / ".env.example").read_text()
    assert (ROOT / "README.md").read_text().count(f"Bearer {token}") == 2
