"""The update command: reload the mcp functions, keep everything else."""

import psycopg
import pytest

from insurance_database.setup_db import SetupError
from insurance_database.update_db import MCP_FUNCTIONS_FILE, update_database

# What the update must leave alone: the data, an embedding and the audit log.
KEPT = """
select (select count(*) from insurance.claims),
       (select count(*) from insurance.claim_notes),
       (select count(*) from insurance.claims where embedding is not null),
       (select count(*) from insurance.audit_log),
       insurance.verify_audit_log()
"""

# Every mcp function, with its arguments, who may run it and its security settings,
# and who may use the schema.
FUNCTIONS = """
select f.proname, pg_get_function_identity_arguments(f.oid), f.proacl::text,
       f.prosecdef, f.proconfig, f.proowner::regrole::text
from pg_proc as f
where f.pronamespace = 'mcp'::regnamespace
union all
select 'schema mcp', '', n.nspacl::text, null, null, n.nspowner::regrole::text
from pg_namespace as n
where n.nspname = 'mcp'
order by 1, 2
"""


@pytest.fixture
def one_embedding_and_an_audit_row(admin, reader, unit_vector):
    """One embedded claim and one audit row, so the test can see they survive."""
    admin.execute("update insurance.claims set embedding = %s where id = 1", [str(unit_vector(0))])
    reader.execute(
        "select mcp.write_audit('local', 'test_update_db', '{}'::jsonb, 0, 1, true, null)"
    )
    yield
    admin.execute("update insurance.claims set embedding = null")


def test_the_update_keeps_the_data_embeddings_and_audit_log(
    admin, admin_url, one_embedding_and_an_audit_row
):
    before = admin.execute(KEPT).fetchone()
    assert before[2] == 1 and before[3] >= 1 and before[4] is None
    update_database(admin_url)
    assert admin.execute(KEPT).fetchone() == before


def test_the_update_gives_the_same_functions_and_grants_as_the_setup(admin, admin_url):
    before = admin.execute(FUNCTIONS).fetchall()
    update_database(admin_url)
    assert admin.execute(FUNCTIONS).fetchall() == before


def test_the_reader_can_call_the_functions_after_the_update(admin_url, reader):
    update_database(admin_url)
    assert reader.execute("select claim_count from mcp.get_dataset_info()").fetchone()[0] > 0


def test_a_function_left_in_the_schema_is_removed(admin, admin_url):
    # As if a tool was removed from the file, or its function renamed.
    admin.execute("create function mcp.removed_tool() returns integer language sql as 'select 1'")
    update_database(admin_url)
    assert admin.execute("select to_regproc('mcp.removed_tool')").fetchone()[0] is None


def test_a_file_with_an_error_changes_nothing(admin, admin_url, tmp_path):
    before = admin.execute(FUNCTIONS).fetchall()
    # The real file with a mistake at the end, after the schema was dropped and
    # every function created again.
    broken = tmp_path / "07_mcp_functions.sql"
    broken.write_text(
        MCP_FUNCTIONS_FILE.read_text() + "\nselect no_such_column from insurance.claims;\n"
    )
    with pytest.raises(SetupError, match="has an error, so nothing changed"):
        update_database(admin_url, broken)
    assert admin.execute(FUNCTIONS).fetchall() == before


def test_the_update_refuses_a_database_that_was_never_set_up(superuser_url):
    # The container's own "test" database has no insurance schema.
    with pytest.raises(SetupError, match="Run: uv run python -m insurance_database.setup_db"):
        update_database(superuser_url)


def test_a_running_server_keeps_working_after_the_update(admin_url, reader_url):
    # The server's pooled connections prepare a statement once it's been used a
    # few times. PostgreSQL plans it again when the function it calls is replaced.
    with psycopg.connect(reader_url, autocommit=True) as server:
        server.execute("select set_config('mcp.caller_key', 'local', false)")
        server.execute("select * from mcp.get_dataset_info()", prepare=True)
        update_database(admin_url)
        row = server.execute("select * from mcp.get_dataset_info()", prepare=True).fetchone()
        assert row[4] > 0
