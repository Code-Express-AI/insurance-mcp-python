"""Build the database from scratch: run the files in sql/ in order, set the
reader password, then load the data.

Run it with:  uv run python -m insurance_mcp.setup_db [--size small]

It connects as the admin role, using ADMIN_DATABASE_URL from .env. It drops and
recreates everything it owns, so it's safe to run again to start over.
"""

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from pydantic_settings import BaseSettings, SettingsConfigDict

from insurance_mcp.generate import load_data
from insurance_mcp.generate.config import SIZES

SQL_DIR = Path(__file__).parent.parent.parent / "sql"
MIN_READER_PASSWORD_LENGTH = 24


class SetupSettings(BaseSettings):
    """The two connection strings the setup needs, read from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_database_url: str
    reader_database_url: str


class SetupError(Exception):
    """A problem with the settings or the connection, explained in plain words."""


def connect(database_url: str) -> psycopg.Connection:
    """Connect as the admin. If it fails, say so in a few lines, not a traceback.

    psycopg's own message is kept, because it says what went wrong, such as
    "password authentication failed", and the troubleshooting page matches on it.
    """
    try:
        return psycopg.connect(database_url)
    except psycopg.OperationalError as error:
        raise SetupError(
            f"Couldn't connect to the database.\n{error}\nSee docs/troubleshooting.md."
        ) from None


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


def setup_database(admin_database_url: str, reader_database_url: str, size: str = "full") -> None:
    """Run every file in sql/ in order, set the reader password, and load `size` data.

    All in one transaction: if any step fails, nothing changes.
    """
    password = reader_password(reader_database_url)

    with connect(admin_database_url) as conn:
        for path in sorted(SQL_DIR.glob("*.sql")):
            print(f"Running {path.name}")
            conn.execute(path.read_text())

        # Hashed here, before it's sent, as psql's \password does. Sent as it
        # is, the password would be in the SQL text, and a database that logs
        # its statements (log_statement = 'ddl', common on hosted ones) would
        # write it to the log. PostgreSQL stores a SCRAM hash exactly as it's given.
        verifier = conn.pgconn.encrypt_password(password.encode(), b"mcp_reader", b"scram-sha-256")
        # ALTER ROLE can't take a $1 parameter like a query can, so psycopg
        # quotes it safely as a literal instead.
        conn.execute(
            sql.SQL("alter role mcp_reader password {}").format(sql.Literal(verifier.decode()))
        )

        load_data(conn, size)
    print("Database ready.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the database from scratch and load the data."
    )
    parser.add_argument(
        "--size",
        choices=list(SIZES),
        default="full",
        help="full for the demos (the default), small for a quick load",
    )
    args = parser.parse_args()

    settings = SetupSettings()
    try:
        setup_database(settings.admin_database_url, settings.reader_database_url, args.size)
    except SetupError as error:
        sys.exit(f"Setup stopped: {error}")


if __name__ == "__main__":
    main()
