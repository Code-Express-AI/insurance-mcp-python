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


# The snapshot -------------------------------------------------------------------------
# The tests above check the mistakes we thought of. This one lists everything
# mcp_reader can actually do, however it got the right: granted to it, to PUBLIC
# (every role is in PUBLIC) or to a role it's a member of. Any right the SQL
# files don't mean to give makes it fail, including one we never thought of.
# Adding a tool means adding its function to the list below.

# Every object in our schemas, and in public, with the rights to check on it.
# PostgreSQL's own schemas (pg_catalog, information_schema) are left out: every
# role can read them, and that can't be turned off. So are the objects that
# belong to an extension (pgvector's vector type and its functions), which
# PostgreSQL makes usable by everyone.
#
# Only our own database is checked. By default PUBLIC may connect to every
# database on the server and create temporary tables in it, so mcp_reader can
# open the empty "postgres" database too. 030_permissions.sql can only revoke
# that for our database. It gives no access to any table there.
EFFECTIVE_RIGHTS = """
with ours as (
    select oid from pg_namespace
    where nspname not like 'pg\\_%' and nspname <> 'information_schema'
),
not_extension as (
    select objid from pg_depend where deptype = 'e'
)
select 'role ' || r.rolname, a.attribute
from pg_roles as r
cross join lateral (values
    ('superuser', r.rolsuper), ('createrole', r.rolcreaterole), ('createdb', r.rolcreatedb),
    ('replication', r.rolreplication), ('bypassrls', r.rolbypassrls)
) as a(attribute, has_it)
where r.rolname = 'mcp_reader' and a.has_it

union all
select 'member of', m.roleid::regrole::text
from pg_auth_members as m
where m.member = 'mcp_reader'::regrole

union all
select 'database ' || d.datname, p.privilege
from pg_database as d
cross join unnest(array['CONNECT', 'CREATE', 'TEMPORARY']) as p(privilege)
where d.datname = current_database()
  and has_database_privilege('mcp_reader', d.oid, p.privilege)

union all
select 'schema ' || n.nspname, p.privilege
from pg_namespace as n
cross join unnest(array['USAGE', 'CREATE']) as p(privilege)
where n.oid in (select oid from ours)
  and has_schema_privilege('mcp_reader', n.oid, p.privilege)

union all
select 'table ' || c.oid::regclass::text, p.privilege
from pg_class as c
cross join unnest(
    array['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']
) as p(privilege)
where c.relnamespace in (select oid from ours)
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
  and c.oid not in (select objid from not_extension)
  and (has_table_privilege('mcp_reader', c.oid, p.privilege)
       -- A right on one column only, such as SELECT (id). Columns have only four kinds.
       or case when p.privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
               then has_any_column_privilege('mcp_reader', c.oid, p.privilege) end)

union all
select 'sequence ' || c.oid::regclass::text, p.privilege
from pg_class as c
cross join unnest(array['USAGE', 'SELECT', 'UPDATE']) as p(privilege)
where c.relnamespace in (select oid from ours)
  and c.relkind = 'S'
  and has_sequence_privilege('mcp_reader', c.oid, p.privilege)

union all
select 'function ' || f.oid::regproc::text, 'EXECUTE'
from pg_proc as f
where f.pronamespace in (select oid from ours)
  and f.oid not in (select objid from not_extension)
  and has_function_privilege('mcp_reader', f.oid, 'EXECUTE')

order by 1, 2
"""


def test_reader_holds_only_the_rights_the_sql_files_give(admin):
    database = admin.execute("select current_database()").fetchone()[0]

    expected = [
        (f"database {database}", "CONNECT"),
        ("function mcp.count_claims_by_driver_age", "EXECUTE"),
        ("function mcp.count_claims_by_month", "EXECUTE"),
        ("function mcp.find_customers", "EXECUTE"),
        ("function mcp.find_similar_claims", "EXECUTE"),
        ("function mcp.get_adjuster_workload", "EXECUTE"),
        ("function mcp.get_claim", "EXECUTE"),
        ("function mcp.get_customer", "EXECUTE"),
        ("function mcp.get_customer_with_policies", "EXECUTE"),
        ("function mcp.get_dataset_info", "EXECUTE"),
        ("function mcp.get_policy", "EXECUTE"),
        ("function mcp.get_repair_shop_costs", "EXECUTE"),
        ("function mcp.search_claim_text", "EXECUTE"),
        ("function mcp.search_claims", "EXECUTE"),
        ("function mcp.search_policy_wording", "EXECUTE"),
        ("function mcp.write_audit", "EXECUTE"),
        ("schema mcp", "USAGE"),
        # PostgreSQL's default: every role may look in public, but not create
        # anything there. It holds only pgvector, left out above.
        ("schema public", "USAGE"),
    ]

    assert admin.execute(EFFECTIVE_RIGHTS).fetchall() == sorted(expected)
