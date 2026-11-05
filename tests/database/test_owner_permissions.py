"""mcp_owner, whose rights the mcp functions run with, can only read."""

import pytest


def test_mcp_owner_cannot_change_any_table(admin):
    rows = admin.execute(
        """
        select t.tablename, p.privilege
        from pg_tables as t
        cross join unnest(array['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) as p(privilege)
        where t.schemaname = 'insurance'
          and has_table_privilege('mcp_owner', format('insurance.%I', t.tablename), p.privilege)
        order by 1, 2
        """
    ).fetchall()
    # The one exception: write_audit adds rows to the audit log.
    assert rows == [("audit_log", "INSERT")]


def test_mcp_owner_can_read_only_two_audit_log_columns(admin):
    rows = admin.execute(
        """
        select column_name from information_schema.column_privileges
        where grantee = 'mcp_owner' and table_name = 'audit_log' and privilege_type = 'SELECT'
        order by column_name
        """
    ).fetchall()
    assert rows == [("id",), ("row_hash",)]


def test_mcp_owner_owns_nothing_in_the_insurance_schema(admin):
    owned = admin.execute(
        """
        select c.relname from pg_class as c
        where c.relnamespace = 'insurance'::regnamespace and c.relowner = 'mcp_owner'::regrole
        union all
        select p.proname from pg_proc as p
        where p.pronamespace = 'insurance'::regnamespace and p.proowner = 'mcp_owner'::regrole
        """
    ).fetchall()
    assert owned == []


def test_a_stable_function_cannot_write(admin):
    # STABLE is a second guard: even a write mcp_owner is allowed to make (adding
    # an audit row) is refused inside a STABLE function.
    admin.execute("set role mcp_owner")
    admin.execute(
        """
        create function mcp.stable_writer() returns void language plpgsql stable as $$
        begin
            insert into insurance.audit_log (occurred_at, caller, tool_name, arguments,
                                             succeeded, row_hash)
            values (now(), 'x', 'x', '{}', true, 'x');
        end;
        $$
        """
    )
    try:
        with pytest.raises(Exception, match="not allowed in a non-volatile function"):
            admin.execute("select mcp.stable_writer()")
    finally:
        admin.execute("reset role")
        admin.execute("drop function mcp.stable_writer()")
