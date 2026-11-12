"""The server's settings: tokens are checked at startup, and there's no admin connection."""

import pytest
from pydantic import ValidationError

from insurance_mcp.auth import new_token
from insurance_mcp.settings import Settings


def make_settings(**values) -> Settings:
    """Settings from these values only: _env_file=None, so your own .env is never read."""
    return Settings(_env_file=None, reader_database_url="postgresql://mcp_reader@x/db", **values)


def test_tokens_are_read_as_name_and_token_pairs():
    first, second = new_token(), new_token()
    settings = make_settings(mcp_tokens=f"claude:{first}, copilot:{second}")

    assert settings.mcp_tokens == {"claude": first, "copilot": second}


def test_the_server_refuses_to_start_with_a_token_under_32_characters():
    with pytest.raises(ValidationError, match="shorter than 32 characters"):
        make_settings(mcp_tokens="claude:too-short")


@pytest.mark.parametrize("tokens", ["no-colon-at-all", ":no-name", "no-token:"])
def test_the_server_refuses_to_start_with_a_malformed_token_setting(tokens):
    with pytest.raises(ValidationError, match="name:token pairs"):
        make_settings(mcp_tokens=tokens)


def test_the_server_refuses_to_start_with_a_token_name_used_twice():
    with pytest.raises(ValidationError, match="used twice"):
        make_settings(mcp_tokens=f"claude:{new_token()},claude:{new_token()}")


def test_allowed_hosts_are_read_as_a_list():
    settings = make_settings(mcp_tokens=f"a:{new_token()}", allowed_hosts="localhost, 127.0.0.1")

    assert settings.allowed_hosts == ["localhost", "127.0.0.1"]


def test_the_server_settings_have_no_admin_connection_string():
    assert not any("admin" in name for name in Settings.model_fields)


def test_a_new_token_is_long_enough():
    assert len(new_token()) >= 32
