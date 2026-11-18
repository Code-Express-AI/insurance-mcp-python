"""Reload the mcp functions, keeping the data, the embeddings and the audit log.

Run it with:  uv run python -m insurance_database.update_db

Use it after changing sql/07_mcp_functions.sql, such as when adding a tool. It
runs that one file, which drops the mcp schema and creates it again, all in one
transaction: if anything fails, nothing changes. A new or changed table still
needs setup_db.

It connects as the admin role, using ADMIN_DATABASE_URL from .env.
"""

import sys
from pathlib import Path

import psycopg
from pydantic_settings import BaseSettings, SettingsConfigDict

from insurance_database.setup_db import SQL_DIR, SetupError, connect

MCP_FUNCTIONS_FILE = SQL_DIR / "07_mcp_functions.sql"


class UpdateSettings(BaseSettings):
    """The one connection string the update needs, read from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_database_url: str


def update_database(admin_database_url: str, path: Path = MCP_FUNCTIONS_FILE) -> None:
    """Run the mcp functions file in one transaction. The tests pass a broken copy as `path`."""
    with connect(admin_database_url) as conn:
        # The functions read the insurance tables, so the database must be set up first.
        if conn.execute("select to_regclass('insurance.audit_log')").fetchone()[0] is None:
            raise SetupError(
                "The database isn't set up yet. Run: uv run python -m insurance_database.setup_db"
            )
        print(f"Running {path.name}")
        try:
            conn.execute(path.read_text())
        except psycopg.Error as error:
            # PostgreSQL's message names the problem, such as a misspelled
            # column. The transaction is rolled back, so the old functions stay.
            raise SetupError(f"{path.name} has an error, so nothing changed.\n{error}") from None
    print("The mcp functions are reloaded. The data, embeddings and audit log are unchanged.")


def main() -> None:
    settings = UpdateSettings()
    try:
        update_database(settings.admin_database_url)
    except SetupError as error:
        sys.exit(f"Update stopped: {error}")


if __name__ == "__main__":
    main()
