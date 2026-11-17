"""uv run python -m insurance_database.generate [--size small]"""

import argparse
import sys

from insurance_database.generate import load_data
from insurance_database.generate.config import SIZES
from insurance_database.setup_db import SetupError, SetupSettings, connect


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
    try:
        # One transaction: if anything fails, the old data stays.
        with connect(settings.admin_database_url) as conn:
            load_data(conn, args.size)
    except SetupError as error:
        sys.exit(f"Loading stopped: {error}")


if __name__ == "__main__":
    main()
