"""Rules every mcp function must follow, checked in the system catalogs.

These check the design itself, so a function added next year that breaks a rule
fails the build, even if nobody remembers the rule.
"""


def test_every_mcp_function_is_security_definer_with_a_fixed_search_path(admin):
    rows = admin.execute(
        """
        select p.proname, p.prosecdef, p.proconfig, p.proowner::regrole::text
        from pg_proc as p
        where p.pronamespace = 'mcp'::regnamespace
        """
    ).fetchall()
    assert len(rows) >= 2, "Expected at least get_dataset_info and write_audit."

    for name, security_definer, config, owner in rows:
        assert security_definer, f"mcp.{name} must be SECURITY DEFINER."
        assert config is not None and 'search_path=""' in config, (
            f"mcp.{name} must SET search_path = ''."
        )
        assert owner == "mcp_owner", f"mcp.{name} must be owned by mcp_owner."


def test_no_mcp_function_returns_a_bigint(admin):
    # Internal ids are bigint, so no bigint may leave the database at all.
    # Counts are returned as integer for the same reason.
    rows = admin.execute(
        """
        select p.proname
        from pg_proc as p
        where p.pronamespace = 'mcp'::regnamespace
          and (p.prorettype = 'bigint'::regtype
               or exists (
                   select from unnest(p.proallargtypes, p.proargmodes) as a(type, mode)
                   where a.mode in ('o', 't') and a.type = 'bigint'::regtype))
        """
    ).fetchall()
    assert rows == []


def test_the_audit_log_is_the_only_table_with_triggers(admin):
    # Triggers run hidden logic. The audit log's is the one exception, because
    # blocking changes can only be enforced in the database.
    # (Foreign keys use internal triggers, which are left out.)
    rows = admin.execute(
        "select distinct tgrelid::regclass::text from pg_trigger where not tgisinternal"
    ).fetchall()
    assert rows == [("insurance.audit_log",)]
