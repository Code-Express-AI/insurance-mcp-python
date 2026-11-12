"""The init command: it makes a working .env, and never changes one that exists."""

import json
import shutil
from pathlib import Path

from insurance_mcp import init
from insurance_mcp.settings import Settings
from insurance_mcp.setup_db import SetupSettings, reader_password

ROOT = Path(__file__).parent.parent


def make_env(tmp_path, monkeypatch, capsys) -> str:
    """Run init in an empty folder with a copy of .env.example, and return what it printed."""
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    monkeypatch.chdir(tmp_path)
    init.main()
    return capsys.readouterr().out


def test_every_placeholder_is_replaced():
    env = init.env_from_example((ROOT / ".env.example").read_text())

    assert "change-me" not in env
    assert "replace-with" not in env


def test_the_admin_password_matches_in_both_places(tmp_path, monkeypatch, capsys):
    make_env(tmp_path, monkeypatch, capsys)
    lines = dict(
        line.split("=", 1) for line in Path(".env").read_text().splitlines() if "=" in line
    )

    assert f":{lines['POSTGRES_PASSWORD']}@" in lines["ADMIN_DATABASE_URL"]


def test_the_new_env_passes_the_setup_and_server_checks(tmp_path, monkeypatch, capsys):
    make_env(tmp_path, monkeypatch, capsys)

    reader_password(SetupSettings().reader_database_url)  # raises if too short
    assert "local" in Settings().mcp_tokens  # raises if the token is too short


def test_it_prints_the_client_config_with_the_token(tmp_path, monkeypatch, capsys):
    out = make_env(tmp_path, monkeypatch, capsys)
    token = Settings().mcp_tokens["local"]

    vs_code = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert vs_code["servers"]["insurance"]["headers"]["Authorization"] == f"Bearer {token}"
    assert f'--header "Authorization: Bearer {token}"' in out


def test_it_never_changes_an_existing_env(tmp_path, monkeypatch, capsys):
    make_env(tmp_path, monkeypatch, capsys)
    before = Path(".env").read_text()

    out = make_env(tmp_path, monkeypatch, capsys)

    assert Path(".env").read_text() == before
    assert "unchanged" in out
    assert Settings().mcp_tokens["local"] in out


def test_each_run_makes_new_secrets():
    example = (ROOT / ".env.example").read_text()

    assert init.env_from_example(example) != init.env_from_example(example)
