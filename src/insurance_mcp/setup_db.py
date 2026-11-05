"""Build the database from scratch: run the files in sql/ in order, then set the reader password.

Run it with:  uv run python -m insurance_mcp.setup_db

It connects as the admin role, using ADMIN_DATABASE_URL from .env. It drops and
recreates everything it owns, so it's safe to run again to start over.
"""

import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from pydantic_settings import BaseSettings, SettingsConfigDict

SQL_DIR = Path(__file__).parent.parent.parent / "sql"
MIN_READER_PASSWORD_LENGTH = 24


class SetupSettings(BaseSettings):
    """The two connection strings the setup needs, read from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_database_url: str
    reader_database_url: str


class SetupError(Exception):
    """A problem with the settings, explained in plain words."""


def reader_password(reader_database_url: str) -> str:
    """Take the mcp_reader password from its connection string: it's written in one place only."""
    parts = conninfo_to_dict(reader_database_url)
    if parts.get("user") != "mcp_reader":
        raise SetupError("READER_DATABASE_URL must connect as mcp_reader.")
    password = parts.get("password") or ""
    if len(password) < MIN_READER_PASSWORD_LENGTH:
        raise SetupError(
            f"The mcp_reader password in READER_DATABASE_URL must be at least "
            f"{MIN_READER_PASSWORD_LENGTH} characters."
        )
    return password


def setup_database(admin_database_url: str, reader_database_url: str) -> None:
    """Run every file in sql/ in order, in one transaction, then set the reader password."""
    password = reader_password(reader_database_url)

    # One transaction: if any file fails, nothing changes.
    with psycopg.connect(admin_database_url) as conn:
        for path in sorted(SQL_DIR.glob("*.sql")):
            print(f"Running {path.name}")
            conn.execute(path.read_text())

        # ALTER ROLE can't take a $1 parameter like a query can, so psycopg
        # quotes the password safely as a literal instead.
        conn.execute(sql.SQL("alter role mcp_reader password {}").format(sql.Literal(password)))
    print("Database ready.")


def main() -> None:
    settings = SetupSettings()
    try:
        setup_database(settings.admin_database_url, settings.reader_database_url)
    except SetupError as error:
        sys.exit(f"Setup stopped: {error}")


if __name__ == "__main__":
    main()
