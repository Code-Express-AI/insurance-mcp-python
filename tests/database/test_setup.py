"""The setup command."""

import psycopg
import pytest

from insurance_mcp.setup_db import SetupError, setup_database

# Never reached: the setup checks the reader settings before it connects.
UNUSED_ADMIN_URL = "postgresql://postgres:unused@127.0.0.1:1/unused"


def test_setup_refuses_a_reader_password_shorter_than_24_characters():
    short = "postgresql://mcp_reader:password123@127.0.0.1:5432/insurance"
    with pytest.raises(SetupError, match="at least 24 characters"):
        setup_database(UNUSED_ADMIN_URL, short)


def test_setup_refuses_a_reader_url_for_another_role():
    admin_as_reader = "postgresql://postgres:a-long-enough-password-here@127.0.0.1:5432/insurance"
    with pytest.raises(SetupError, match="must connect as mcp_reader"):
        setup_database(UNUSED_ADMIN_URL, admin_as_reader)


def test_a_wrong_admin_password_is_a_short_message_not_a_traceback(admin_url, reader_url):
    # What happens when .env has a new password but the Docker volume has the old one.
    wrong_password = admin_url.replace(":test-admin-password@", ":not-the-password@")
    with pytest.raises(SetupError, match="password authentication failed"):
        setup_database(wrong_password, reader_url)


def test_setup_can_run_again_to_start_over(admin_url, reader_url):
    # The first run happened when the test database was built. This one drops
    # and recreates everything, as running the command again would.
    setup_database(admin_url, reader_url, size="small")
    with psycopg.connect(reader_url) as reader:
        reader.execute("select * from mcp.get_dataset_info()")
