"""The planted demo facts (database/src/insurance_database/generate/planted.py) hold.

Each one asks the demo question through the mcp functions, as mcp_reader, the
way the model does. The RAG facts (the parking lot claims and the
prompt-injection notes) still use plain SQL as the admin role, until their
search functions arrive with the RAG extension.

The facts that compare against the random data around them (the most expensive
shop, the busiest adjuster, the jump in windshield claims) only mean something
on full data, so they're marked full_data and run with:  uv run pytest -m full_data
"""

import datetime
from decimal import Decimal

import pytest
from psycopg import sql
from psycopg.rows import dict_row

from insurance_database.generate import planted
from insurance_database.generate.config import AS_OF_DATE, years_before


def rows(reader, query: str, *args) -> list[dict]:
    with reader.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, args).fetchall()


# Facts that hold at either size ------------------------------------------------------


def test_the_as_of_date_is_the_one_in_the_generator(reader):
    assert rows(reader, "select * from mcp.get_dataset_info()")[0]["as_of_date"] == AS_OF_DATE


def test_last_month_has_claims_whenever_the_data_is_set_up(reader):
    # "How many claims did we have last month?" The data runs up to the day it's
    # set up, so last month on the calendar is last month in the data.
    first_of_this_month = datetime.date.today().replace(day=1)
    last_month_end = first_of_this_month - datetime.timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    claims = rows(reader, "select * from mcp.search_claims(p_period => 'last_month')")
    assert claims
    assert all(last_month_start <= c["date_reported"] <= last_month_end for c in claims)


def test_there_is_one_rutherford_with_two_policies(reader):
    # "Find the customer called Rutherford and show their policies."
    (found,) = rows(reader, "select * from mcp.find_customers('Rutherford')")
    customer = rows(reader, "select * from mcp.get_customer(%s)", found["customer_id"])[0]
    assert customer["first_name"] == "Eleanor"
    assert [p["policy_number"] for p in customer["policies"]] == ["AUT-108514", "AUT-109372"]
    # One car on each policy, both insured now.
    cars = [
        rows(reader, "select * from mcp.get_policy(%s)", p)[0] for p in ("AUT-108514", "AUT-109372")
    ]
    assert [(c["make"], c["model"], c["status"]) for c in cars] == [
        ("Subaru", "Outback", "active"),
        ("Ford", "F-150", "active"),
    ]


def test_policy_aut_104233_has_full_coverage_and_a_500_deductible(reader):
    # "What's covered on policy AUT-104233, and what's the deductible?"
    policy = rows(reader, "select * from mcp.get_policy('AUT-104233')")[0]
    assert (policy["coverage_level"], policy["deductible"]) == ("full", 500)


def test_maria_garcia_has_claimed_three_times_in_three_years(reader):
    # "Show me the claim history for Maria Garcia. Has she claimed more than twice?"
    (maria,) = rows(reader, "select * from mcp.find_customers('Maria Garcia')")
    claims = rows(
        reader, "select * from mcp.search_claims(p_customer_id => %s)", maria["customer_id"]
    )
    # Newest first. The latest is still open, for "please accept Maria Garcia's claim".
    assert [c["status"] for c in claims] == ["open", "settled", "settled"]
    assert all(c["date_reported"] > years_before(AS_OF_DATE, 3) for c in claims)


def test_six_open_claims_are_over_20k_and_more_than_90_days_old(reader):
    # "Which open claims are over $20k and more than 90 days old?"
    claims = rows(
        reader,
        """
        select * from mcp.search_claims(
            p_status => 'open', p_min_reserve => 20000, p_min_days_open => 91)
        """,
    )
    assert len(claims) == 6


def test_the_parking_lot_claims_are_planted(admin):
    query = "select count(*) from insurance.claims where description = any(%s)"
    found = admin.execute(query, [list(planted.PARKING_LOT_DESCRIPTIONS)]).fetchone()[0]
    assert found == len(planted.PARKING_LOT_DESCRIPTIONS)


def test_each_prompt_injection_note_is_planted_once(admin):
    for note in planted.PROMPT_INJECTION_NOTES:
        query = "select count(*) from insurance.claim_notes where note = %s"
        assert admin.execute(query, [note]).fetchone()[0] == 1


# Facts that compare against the random data: full data only --------------------------


@pytest.mark.full_data
def test_one_repair_shop_is_clearly_the_most_expensive_this_year(full_data, reader):
    # "Which repair shops have the highest average repair cost this year?"
    top, second = rows(reader, "select * from mcp.get_repair_shop_costs('this_year', 2)")
    assert top["repair_shop_name"] == "Copper State Collision"
    # Money comes back from PostgreSQL as Decimal, which doesn't mix with floats.
    assert top["average_repair_cost"] > Decimal("1.2") * second["average_repair_cost"]


@pytest.mark.full_data
def test_windshield_claims_jump_last_month(full_data, reader):
    # "How many windshield claims did we have last month, compared with the month before?"
    per_month = {
        row["month"]: row["claim_count"]
        for row in rows(reader, "select * from mcp.count_claims_by_month('last_3_months', 'glass')")
    }
    last_month = planted.LAST_MONTH_START
    month_before = (last_month - datetime.timedelta(days=1)).replace(day=1)
    assert per_month[last_month] > 1.5 * per_month[month_before]


@pytest.mark.full_data
def test_one_adjuster_clearly_has_the_most_open_claims(full_data, reader):
    # "Which adjuster has the most open claims?"
    top, second = rows(reader, "select * from mcp.get_adjuster_workload()")[:2]
    assert top["adjuster_name"] == "Dana Whitfield"
    assert top["open_claim_count"] > 1.25 * second["open_claim_count"]


@pytest.mark.full_data
@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("customers", 12_000),
        ("policies", 15_000),
        ("drivers", 20_000),
        ("claims", 15_000),
        ("claim_notes", 75_000),
    ],
)
def test_full_data_has_about_the_volumes_in_the_spec(full_data, admin, table, expected):
    query = sql.SQL("select count(*) from {}").format(sql.Identifier("insurance", table))
    rows = admin.execute(query).fetchone()[0]
    assert 0.9 * expected <= rows <= 1.1 * expected


# The row-level security examples in guides 2 and 3: one customer only each
# named token can find. They aren't planted: the fixed seed puts them there.
ONLY_FOUND_BY = {"Wei Kim": "claude", "Mei Cruz": "copilot", "Ana Cook": "inspector"}


@pytest.mark.full_data
@pytest.mark.parametrize("name", list(ONLY_FOUND_BY))
def test_the_guides_row_security_examples_are_found_by_one_named_token(full_data, reader_as, name):
    found_by = [
        caller_key
        for caller_key in ("claude", "copilot", "inspector")
        if rows(reader_as(caller_key), "select * from mcp.find_customers(%s)", name)
    ]
    assert found_by == [ONLY_FOUND_BY[name]]
    assert rows(reader_as("local"), "select * from mcp.find_customers(%s)", name)
