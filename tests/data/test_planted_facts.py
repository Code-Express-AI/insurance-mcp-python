"""The planted demo facts (src/insurance_mcp/generate/planted.py) hold.

For now these ask with plain SQL as the admin role. Each one will switch to its
mcp function, called as mcp_reader the way the model calls it, when that
function is written with its tool.

The facts that compare against the random data around them (the most expensive
shop, the busiest adjuster, the jump in windshield claims) only mean something
on full data, so they're marked full_data and run with:  uv run pytest -m full_data
"""

import datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg import sql

from insurance_mcp.generate import load_data, planted
from insurance_mcp.generate.config import AS_OF_DATE

# Facts that hold at either size ------------------------------------------------------


def test_the_as_of_date_is_the_one_in_the_generator(reader):
    row = reader.execute("select as_of_date from mcp.get_dataset_info()").fetchone()
    assert row[0] == AS_OF_DATE


def test_there_is_one_rutherford_with_two_policies(admin):
    rows = admin.execute("""
        select c.first_name, count(p.id)
        from insurance.customers as c
        join insurance.policies as p on p.customer_id = c.id
        where c.last_name = 'Rutherford'
        group by c.id
    """).fetchall()
    assert rows == [("Eleanor", 2)]


def test_policy_aut_104233_has_full_coverage_and_a_500_deductible(admin):
    row = admin.execute("""
        select coverage_level, deductible from insurance.policies
        where policy_number = 'AUT-104233'
    """).fetchone()
    assert row == ("full", 500)


def test_maria_garcia_has_claimed_three_times_in_three_years(admin):
    rows = admin.execute("""
        select c.status
        from insurance.customers as cu
        join insurance.policies as p on p.customer_id = cu.id
        join insurance.claims as c on c.policy_id = p.id
        where cu.first_name = 'Maria' and cu.last_name = 'Garcia'
          and c.date_reported > insurance.as_of_date() - interval '3 years'
        order by c.date_reported
    """).fetchall()
    # The last one is still open, for "please accept Maria Garcia's claim".
    assert rows == [("settled",), ("settled",), ("open",)]


def test_there_is_only_one_maria_garcia(admin):
    query = """
        select count(*) from insurance.customers
        where first_name = 'Maria' and last_name = 'Garcia'
    """
    assert admin.execute(query).fetchone()[0] == 1


def test_six_open_claims_are_over_20k_and_more_than_90_days_old(admin):
    query = """
        select count(*) from insurance.claims
        where status = 'open' and reserve > 20000
          and date_reported < insurance.as_of_date() - 90
    """
    assert admin.execute(query).fetchone()[0] == 6


def test_the_parking_lot_claims_are_planted(admin):
    query = "select count(*) from insurance.claims where description = any(%s)"
    found = admin.execute(query, [list(planted.PARKING_LOT_DESCRIPTIONS)]).fetchone()[0]
    assert found == len(planted.PARKING_LOT_DESCRIPTIONS)


def test_each_prompt_injection_note_is_planted_once(admin):
    for note in planted.PROMPT_INJECTION_NOTES:
        query = "select count(*) from insurance.claim_notes where note = %s"
        assert admin.execute(query, [note]).fetchone()[0] == 1


# Facts that compare against the random data: full data only --------------------------


@pytest.fixture(scope="module")
def full_data(admin_url):
    """Reload the test database with full data. Only for a run of just these tests."""
    with psycopg.connect(admin_url) as conn:
        load_data(conn, "full")


@pytest.mark.full_data
def test_one_repair_shop_is_clearly_the_most_expensive_this_year(full_data, admin):
    # Average repair cost per claim, on claims reported this year, for shops
    # with at least 5 claims. The same rules mcp.get_repair_shop_costs will use.
    rows = admin.execute("""
        select s.name, sum(cp.amount) / count(distinct c.id) as average_repair_cost
        from insurance.claims as c
        join insurance.repair_shops as s on s.id = c.repair_shop_id
        join insurance.claim_payments as cp on cp.claim_id = c.id and cp.payment_type = 'repair'
        where c.date_reported >= date_trunc('year', insurance.as_of_date())
        group by s.id
        having count(distinct c.id) >= 5
        order by average_repair_cost desc
        limit 2
    """).fetchall()
    (top_name, top_cost), (_, second_cost) = rows
    assert top_name == "Copper State Collision"
    # Money comes back from PostgreSQL as Decimal, which doesn't mix with floats.
    assert top_cost > Decimal("1.2") * second_cost


@pytest.mark.full_data
def test_windshield_claims_jump_last_month(full_data, admin):
    rows = admin.execute("""
        select date_trunc('month', date_reported)::date, count(*)
        from insurance.claims
        where claim_type = 'glass'
        group by 1
    """).fetchall()
    per_month = dict(rows)
    last_month = planted.LAST_MONTH_START
    month_before = (last_month - datetime.timedelta(days=1)).replace(day=1)
    assert per_month[last_month] > 1.5 * per_month[month_before]


@pytest.mark.full_data
def test_one_adjuster_clearly_has_the_most_open_claims(full_data, admin):
    rows = admin.execute("""
        select a.first_name || ' ' || a.last_name, count(*) as open_claims
        from insurance.claims as c
        join insurance.adjusters as a on a.id = c.adjuster_id
        where c.status = 'open'
        group by a.id
        order by open_claims desc
        limit 2
    """).fetchall()
    (top_name, top_count), (_, second_count) = rows
    assert top_name == "Dana Whitfield"
    assert top_count > 1.25 * second_count


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
