"""mcp_reader, the role the MCP server connects as, can run the granted functions, nothing else."""

import psycopg
import pytest
from psycopg import errors, sql


def insurance_tables(admin) -> list[str]:
    """Every table in the insurance schema, read from the catalog, so a new table is covered too."""
    rows = admin.execute(
        "select tablename from pg_tables where schemaname = 'insurance' order by tablename"
    ).fetchall()
    return [row[0] for row in rows]


def test_reader_can_call_the_granted_functions(reader):
    # The control for every test below: the reader isn't simply locked out of everything.
    reader.execute("select * from mcp.get_dataset_info()")
    reader.execute("select mcp.write_audit('test', 'test_tool', '{}', 0, 1, true, null)")


@pytest.mark.parametrize(
    "statement",
    [
        "select * from {}",
        "insert into {} default values",
        "update {} set id = id",
        "delete from {}",
    ],
)
def test_reader_cannot_use_any_table(admin, reader, statement):
    tables = insurance_tables(admin)
    assert "claims" in tables and "audit_log" in tables

    for table in tables:
        query = sql.SQL(statement).format(sql.Identifier("insurance", table))
        with pytest.raises(errors.InsufficientPrivilege):
            reader.execute(query)


def test_reader_cannot_read_the_audit_log(reader):
    reader.execute("select mcp.write_audit('test', 'test_tool', '{}', 0, 1, true, null)")
    with pytest.raises(errors.InsufficientPrivilege):
        reader.execute("select * from insurance.audit_log")


@pytest.mark.parametrize("schema", ["public", "mcp", "insurance"])
def test_reader_cannot_create_a_table(reader, schema):
    with pytest.raises(errors.InsufficientPrivilege):
        reader.execute(sql.SQL("create table {} (id int)").format(sql.Identifier(schema, "t")))


def test_reader_cannot_create_a_temporary_table(reader):
    with pytest.raises(errors.InsufficientPrivilege):
        reader.execute("create temporary table t (id int)")


@pytest.mark.parametrize("schema", ["public", "mcp", "insurance"])
def test_reader_cannot_create_a_function(reader, schema):
    query = sql.SQL("create function {}() returns int language sql as 'select 1'").format(
        sql.Identifier(schema, "f")
    )
    with pytest.raises(errors.InsufficientPrivilege):
        reader.execute(query)


def test_reader_cannot_call_the_helper_functions(reader):
    with pytest.raises(errors.InsufficientPrivilege):
        reader.execute("select insurance.as_of_date()")


def test_reader_cannot_call_an_mcp_function_that_was_never_granted(admin, reader):
    # Proves the default EXECUTE for PUBLIC is revoked: without that, PostgreSQL
    # would let every role call a new function the moment it's created.
    admin.execute("set role mcp_owner")
    admin.execute("create function mcp.not_granted() returns int language sql as 'select 1'")
    admin.execute("reset role")
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            reader.execute("select mcp.not_granted()")
    finally:
        admin.execute("drop function mcp.not_granted()")


def test_a_slow_query_is_canceled_after_the_statement_timeout(reader):
    # pg_sleep is a built-in function every role can call. The 5 second timeout
    # is set on the role, so it applies without the server doing anything.
    with pytest.raises(errors.QueryCanceled):
        reader.execute("select pg_sleep(6)")


def test_reader_cannot_log_in_with_a_wrong_password(reader_url):
    wrong = reader_url.replace(":test-reader-password", ":wrong-password")
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(wrong)
