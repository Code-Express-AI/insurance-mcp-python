"""The MCP server's settings, read from .env.

Only the server's own settings are declared here. The admin connection string
(ADMIN_DATABASE_URL) is in the same .env file, but it isn't declared, so the
server never loads it and nothing in the server can connect as admin.
"""

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_TOKEN_LENGTH = 32


class Settings(BaseSettings):
    # extra="ignore": the settings for Docker and the setup command are in .env too.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reader_database_url: str

    # NoDecode: these are plain comma-separated text in .env, not JSON.
    # "claude-code:<token>,copilot:<token>" becomes {"claude-code": "<token>", ...}
    mcp_tokens: Annotated[dict[str, str], NoDecode]
    # "localhost,127.0.0.1" becomes ["localhost", "127.0.0.1"]
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]

    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 1000
    db_pool_max_size: int = 5
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("mcp_tokens", mode="before")
    @classmethod
    def parse_tokens(cls, value: str) -> dict[str, str]:
        tokens = {}
        for pair in value.split(","):
            name, _, token = pair.strip().partition(":")
            if not name or not token:
                raise ValueError("MCP_TOKENS must be name:token pairs, separated by commas.")
            if name in tokens:
                raise ValueError(f"The token name {name!r} is used twice in MCP_TOKENS.")
            if len(token) < MIN_TOKEN_LENGTH:
                raise ValueError(
                    f"The token for {name!r} is shorter than {MIN_TOKEN_LENGTH} characters. "
                    "Make one with: uv run python -m insurance_mcp.auth"
                )
            tokens[name] = token
        return tokens

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        return [host.strip() for host in value.split(",") if host.strip()]
