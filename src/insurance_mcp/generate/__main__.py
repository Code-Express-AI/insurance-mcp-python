"""uv run python -m insurance_mcp.generate [--size small]"""

import argparse

import psycopg

from insurance_mcp.generate import load_data
from insurance_mcp.generate.config import SIZES
from insurance_mcp.setup_db import SetupSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Reload the fake insurance data.")
    parser.add_argument(
        "--size",
        choices=list(SIZES),
        default="full",
        help="full for the demos (the default), small for a quick load",
    )
    args = parser.parse_args()

    settings = SetupSettings()
    # One transaction: if anything fails, the old data stays.
    with psycopg.connect(settings.admin_database_url) as conn:
        load_data(conn, args.size)


if __name__ == "__main__":
    main()
