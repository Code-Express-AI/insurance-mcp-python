"""Rules every mcp function and table must follow, checked in the system catalogs.

These check the design itself, so a function or table added next year that
breaks a rule fails the build, even if nobody remembers the rule.
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


def test_every_search_by_meaning_checks_for_384_numbers(admin):
    # A query embedding comes in as real[]. Without insurance.to_vector's check,
    # a null or wrong-sized one returns rows with no score instead of an error.
    rows = admin.execute(
        """
        select p.proname
        from pg_proc as p
        where p.pronamespace = 'mcp'::regnamespace
          and 'real[]'::regtype = any(p.proargtypes::oid[])
          and p.prosrc not like '%insurance.to_vector(%'
        """
    ).fetchall()
    assert rows == [], "Pass the real[] argument through insurance.to_vector()."


def test_every_embedding_column_holds_384_numbers(admin):
    # The model makes 384 numbers. Any other size fails when the text is loaded,
    # or can't be compared with a query.
    columns = admin.execute(
        """
        select a.attrelid::regclass::text || '.' || a.attname,
               format_type(a.atttypid, a.atttypmod)
        from pg_attribute as a
        join pg_class as c on c.oid = a.attrelid
        where c.relnamespace = 'insurance'::regnamespace
          and c.relkind = 'r'
          and a.atttypid = 'public.vector'::regtype
          and not a.attisdropped
        """
    ).fetchall()
    assert len(columns) >= 3, "Expected the claims, notes and booklet embeddings."
    wrong = [column for column, type in columns if type != "vector(384)"]
    assert wrong == [], "Use public.vector(384): the model makes 384 numbers."
