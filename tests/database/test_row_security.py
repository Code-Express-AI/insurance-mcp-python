"""Row-level security: each caller key sees only the customers in its own states.

The tests call the mcp functions as mcp_reader, with a caller key set the way the
server sets it. They check the answers against the admin, whom row-level security
doesn't filter. The keys and their states are in sql/060_row_security.sql.
"""

import pytest
from psycopg import errors
from psycopg.rows import dict_row

ALL_STATES = {"TX", "OK", "CO", "NM", "AZ"}
STATES = {
    "local": ALL_STATES,
    "claude": {"TX", "CO", "OK"},
    "copilot": {"TX", "CO", "NM"},
    "inspector": {"TX", "CO", "AZ"},
}
# The one state only this named key can see.
OWN_STATE = {"claude": "OK", "copilot": "NM", "inspector": "AZ"}

# The seven tables with customer data, which row-level security filters.
FILTERED_TABLES = [
    "claim_notes",
    "claim_payments",
    "claims",
    "customers",
    "drivers",
    "policies",
    "vehicles",
]


def rows(conn, query: str, *args) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, args).fetchall()


def dataset_info(conn) -> dict:
    return rows(conn, "select * from mcp.get_dataset_info()")[0]


def counts_in_states(admin, states: set[str]) -> dict:
    """What get_dataset_info should report for a caller who sees these states."""
    return rows(
        admin,
        """
        select
            (select count(*)::integer from insurance.customers as cu
             where cu.state = any(%s)) as customer_count,
            (select count(*)::integer from insurance.policies as p
             join insurance.customers as cu on cu.id = p.customer_id
             where cu.state = any(%s)) as policy_count,
            (select count(*)::integer from insurance.claims as c
             join insurance.policies as p on p.id = c.policy_id
             join insurance.customers as cu on cu.id = p.customer_id
             where cu.state = any(%s)) as claim_count
        """,
        list(states),
        list(states),
        list(states),
    )[0]


def a_customer_only_in(admin, state: str) -> str:
    """The full name of a customer in `state` whose name matches nobody outside it.

    find_customers matches any part of a name, so the name mustn't turn up,
    even as part of a longer name, in any other state.
    """
    return admin.execute(
        """
        select cu.first_name || ' ' || cu.last_name
        from insurance.customers as cu
        where cu.state = %s
          and not exists (
              select from insurance.customers as other
              where other.state <> %s
                and other.first_name || ' ' || other.last_name
                    ilike '%%' || cu.first_name || ' ' || cu.last_name || '%%'
          )
        order by cu.last_name, cu.first_name
        limit 1
        """,
        [state, state],
    ).fetchone()[0]


def state_of_claim(admin, claim_number: str) -> str:
    return admin.execute(
        """
        select cu.state from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        where c.claim_number = %s
        """,
        [claim_number],
    ).fetchone()[0]


def a_claim_in(admin, state: str) -> tuple[str, str]:
    """(claim number, policy number) of a claim from a customer in `state`."""
    return admin.execute(
        """
        select c.claim_number, p.policy_number from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        where cu.state = %s
        order by c.claim_number
        limit 1
        """,
        [state],
    ).fetchone()


# Fail closed --------------------------------------------------------------------------


@pytest.mark.parametrize("caller_key", [None, "", "nobody"])
def test_without_a_known_caller_key_every_function_returns_nothing(reader_as, caller_key):
    reader = reader_as(caller_key)

    info = dataset_info(reader)
    assert (info["customer_count"], info["policy_count"], info["claim_count"]) == (0, 0, 0)
    assert rows(reader, "select * from mcp.find_customers('Garcia')") == []
    assert rows(reader, "select * from mcp.search_claims()") == []
    assert rows(reader, "select * from mcp.get_adjuster_workload()") == []


# Each key sees its own states ---------------------------------------------------------


def test_local_sees_every_customer(admin, reader_as):
    info = dataset_info(reader_as("local"))
    total = admin.execute("select count(*) from insurance.customers").fetchone()[0]

    assert info["customer_count"] == total


@pytest.mark.parametrize("caller_key", ["claude", "copilot", "inspector"])
def test_each_named_key_sees_only_its_own_states(admin, reader_as, caller_key):
    info = dataset_info(reader_as(caller_key))
    expected = counts_in_states(admin, STATES[caller_key])

    assert {name: info[name] for name in expected} == expected
    # The control: it really is part of the data, not all of it.
    assert info["customer_count"] < dataset_info(reader_as("local"))["customer_count"]


@pytest.mark.parametrize("own_key", ["claude", "copilot", "inspector"])
def test_a_customer_in_one_keys_own_state_is_hidden_from_the_others(admin, reader_as, own_key):
    name = a_customer_only_in(admin, OWN_STATE[own_key])

    for caller_key in STATES:
        found = rows(reader_as(caller_key), "select * from mcp.find_customers(%s)", name)
        can_see = OWN_STATE[own_key] in STATES[caller_key]
        assert bool(found) == can_see, f"{caller_key} searching for {name}"


@pytest.mark.parametrize("caller_key", list(STATES))
def test_every_key_finds_the_planted_demo_customers(reader_as, caller_key):
    # Maria Garcia is in TX and Rutherford in CO, the two states every key sees,
    # so the demo questions work with any token.
    reader = reader_as(caller_key)

    assert len(rows(reader, "select * from mcp.find_customers('Maria Garcia')")) == 1
    assert len(rows(reader, "select * from mcp.find_customers('Rutherford')")) == 1


@pytest.mark.parametrize("caller_key", ["claude", "copilot", "inspector"])
def test_search_claims_returns_only_claims_from_the_keys_states(admin, reader_as, caller_key):
    found = rows(reader_as(caller_key), "select claim_number from mcp.search_claims()")

    assert found
    assert {state_of_claim(admin, row["claim_number"]) for row in found} <= STATES[caller_key]


# A hidden record is "unknown" ---------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "column", "message"),
    [
        ("select * from mcp.get_claim(%s)", 0, "Unknown claim number"),
        ("select * from mcp.get_policy(%s)", 1, "Unknown policy number"),
    ],
)
def test_another_states_record_gets_the_same_message_as_a_missing_one(
    admin, reader_as, query, column, message
):
    # An Oklahoma claim: claude sees it, copilot doesn't.
    number = a_claim_in(admin, "OK")[column]
    missing = "CLM-1999999" if column == 0 else "AUT-199999"

    assert rows(reader_as("claude"), query, number)

    copilot = reader_as("copilot")
    with pytest.raises(errors.RaiseException) as hidden:
        rows(copilot, query, number)
    with pytest.raises(errors.RaiseException) as unknown:
        rows(copilot, query, missing)

    assert message in hidden.value.diag.message_primary
    assert hidden.value.diag.message_primary == unknown.value.diag.message_primary


# The RAG functions --------------------------------------------------------------------


@pytest.mark.parametrize("search_in", ["descriptions", "notes"])
def test_search_claim_text_returns_only_claims_from_the_keys_states(
    fake_embeddings, admin, reader_as, unit_vector, search_in
):
    # Every description has unit vector 0 and every note 1, so all match equally.
    embedding = unit_vector(0 if search_in == "descriptions" else 1)
    found = rows(
        reader_as("copilot"),
        "select claim_number from mcp.search_claim_text(%s::real[], p_search_in => %s,"
        " p_limit => 50)",
        embedding,
        search_in,
    )

    assert len(found) == 50
    assert {state_of_claim(admin, row["claim_number"]) for row in found} <= STATES["copilot"]


def test_find_similar_claims_hides_other_states(fake_embeddings, admin, reader_as):
    oklahoma_claim = a_claim_in(admin, "OK")[0]
    query = "select claim_number from mcp.find_similar_claims(%s, p_limit => 50)"

    # claude sees the Oklahoma claim, but only gets similar claims from its own states.
    found = rows(reader_as("claude"), query, oklahoma_claim)
    assert len(found) == 50
    assert {state_of_claim(admin, row["claim_number"]) for row in found} <= STATES["claude"]

    # copilot can't see it at all.
    with pytest.raises(errors.RaiseException, match="Unknown claim number"):
        rows(reader_as("copilot"), query, oklahoma_claim)


# How the key is set -------------------------------------------------------------------


def test_the_caller_key_ends_with_the_transaction(reader_as):
    # The way the server sets it: true, so it lasts only for this transaction.
    reader = reader_as(None)
    with reader.transaction():
        reader.execute("select set_config('mcp.caller_key', 'local', true)")
        assert dataset_info(reader)["customer_count"] > 0

    # The next caller to borrow this connection starts with no key.
    assert reader.execute("select current_setting('mcp.caller_key', true)").fetchone()[0] == ""
    assert dataset_info(reader)["customer_count"] == 0


def test_mcp_reader_can_choose_any_caller_key(reader_as):
    # The honest limit, written down as a test: the database trusts whoever sets
    # the key. The MCP server sets it from the token, and no tool runs raw SQL,
    # so a model can't change it. Someone with the mcp_reader password can.
    reader = reader_as("copilot")
    reader.execute("select set_config('mcp.caller_key', 'local', false)")

    assert dataset_info(reader) == dataset_info(reader_as("local"))


# The setup ----------------------------------------------------------------------------


def test_row_level_security_is_on_for_exactly_the_customer_data_tables(admin):
    # A new table must be added to FILTERED_TABLES or left out on purpose: does
    # it hold customer data? FORCE is off, so the tables' owner (the admin, who
    # loads the data) isn't filtered.
    found = admin.execute(
        """
        select c.relname, c.relforcerowsecurity
        from pg_class as c
        where c.relnamespace = 'insurance'::regnamespace and c.relrowsecurity
        order by c.relname
        """
    ).fetchall()

    assert found == [(table, False) for table in FILTERED_TABLES]


def test_every_filtered_table_has_one_select_policy_for_mcp_owner(admin):
    found = admin.execute(
        """
        select tablename, cmd, roles from pg_policies
        where schemaname = 'insurance'
        order by tablename
        """
    ).fetchall()

    assert found == [(table, "SELECT", ["mcp_owner"]) for table in FILTERED_TABLES]


def test_the_admin_still_sees_and_can_delete_every_row(admin, reader_as):
    total = admin.execute("select count(*) from insurance.customers").fetchone()[0]
    assert total == dataset_info(reader_as("local"))["customer_count"]

    # Reloading the data starts by emptying the tables as the admin. If
    # row-level security filtered the admin, the delete would miss rows.
    with admin.transaction(force_rollback=True):
        admin.execute("delete from insurance.claim_payments")
        assert admin.execute("select count(*) from insurance.claim_payments").fetchone()[0] == 0
