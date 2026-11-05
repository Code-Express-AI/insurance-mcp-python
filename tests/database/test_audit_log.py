"""The audit log is append-only, and its hash chain shows any change."""

import psycopg
import pytest
from psycopg import errors


@pytest.fixture
def audit_rows(reader) -> None:
    """Write three audit rows the way the MCP server does."""
    for tool in ("get_dataset_info", "find_customers", "get_policy"):
        reader.execute(
            "select mcp.write_audit('test', %s, '{\"name\": \"Smith\"}', 1, 5, true, null)",
            [tool],
        )


@pytest.mark.parametrize(
    "statement",
    [
        "update insurance.audit_log set caller = 'someone else'",
        "delete from insurance.audit_log",
        "truncate insurance.audit_log",
    ],
)
def test_the_audit_log_cannot_be_changed_even_by_the_admin(admin, audit_rows, statement):
    with pytest.raises(errors.RaiseException, match="append-only"):
        admin.execute(statement)


def test_verify_finds_no_problem_in_an_untouched_log(admin, audit_rows):
    assert admin.execute("select insurance.verify_audit_log()").fetchone()[0] is None


def latest_ids(conn, count: int) -> list[int]:
    rows = conn.execute(
        "select id from insurance.audit_log order by id desc limit %s", [count]
    ).fetchall()
    return sorted(row[0] for row in rows)


def test_verify_reports_the_row_that_was_edited(admin_url, audit_rows):
    # Not autocommit: the tampering happens in a transaction that's rolled back,
    # so the shared test database's log is left as it was.
    with psycopg.connect(admin_url) as conn:
        first, middle, last = latest_ids(conn, 3)
        # Only the table's owner (here, the admin through its membership) can do this.
        conn.execute(
            "alter table insurance.audit_log disable trigger audit_log_no_update_or_delete"
        )
        conn.execute("update insurance.audit_log set caller = 'nobody' where id = %s", [middle])

        assert conn.execute("select insurance.verify_audit_log()").fetchone()[0] == middle
        conn.rollback()


def test_verify_reports_the_row_after_a_deleted_one(admin_url, audit_rows):
    with psycopg.connect(admin_url) as conn:
        first, middle, last = latest_ids(conn, 3)
        conn.execute(
            "alter table insurance.audit_log disable trigger audit_log_no_update_or_delete"
        )
        conn.execute("delete from insurance.audit_log where id = %s", [middle])

        # The deleted row is gone, so the break shows on the next one.
        assert conn.execute("select insurance.verify_audit_log()").fetchone()[0] == last
        conn.rollback()
