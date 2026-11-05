"""The generated data makes sense, its personal data is fake, and it's the same every time.

These run on the small data the test database is built with.
"""

import psycopg
from psycopg import sql

from insurance_mcp.generate import load_data


def count(admin, query: str) -> int:
    return admin.execute(query).fetchone()[0]


# Rows make sense ----------------------------------------------------------------------


def test_every_claims_driver_is_listed_on_the_claims_policy(admin):
    query = """
        select count(*) from insurance.claims as c
        join insurance.drivers as d on d.id = c.driver_id
        where d.policy_id <> c.policy_id
    """
    assert count(admin, query) == 0


def test_no_claim_happens_outside_its_policys_dates(admin):
    query = """
        select count(*) from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        where c.date_of_loss < p.start_date or c.date_of_loss > p.end_date
    """
    assert count(admin, query) == 0


def test_nobody_drives_before_they_are_16(admin):
    query = """
        select count(*) from insurance.claims as c
        join insurance.drivers as d on d.id = c.driver_id
        where extract(year from age(c.date_of_loss, d.date_of_birth)) < 16
    """
    assert count(admin, query) == 0


def test_every_claim_type_is_covered_by_its_policy(admin):
    # Only full coverage pays for theft, fire, vandalism, weather and glass.
    query = """
        select count(*) from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        where c.claim_type <> 'collision' and p.coverage_level <> 'full'
    """
    assert count(admin, query) == 0


def test_only_settled_claims_have_payments(admin):
    query = """
        select count(*) from insurance.claim_payments as cp
        join insurance.claims as c on c.id = cp.claim_id
        where c.status <> 'settled'
    """
    assert count(admin, query) == 0


def test_settled_claims_have_one_to_three_payments(admin):
    query = """
        select count(*) from insurance.claims as c
        where c.status = 'settled'
          and (select count(*) from insurance.claim_payments as cp where cp.claim_id = c.id)
              not between 1 and 3
    """
    assert count(admin, query) == 0


def test_payments_and_notes_are_dated_while_the_claim_was_open(admin):
    query = """
        select count(*) from insurance.claim_payments as cp
        join insurance.claims as c on c.id = cp.claim_id
        where cp.payment_date not between c.date_reported and c.date_closed
    """
    assert count(admin, query) == 0
    query = """
        select count(*) from insurance.claim_notes as n
        join insurance.claims as c on c.id = n.claim_id
        where n.created_at::date not between c.date_reported
                                         and coalesce(c.date_closed, insurance.as_of_date())
    """
    assert count(admin, query) == 0


def test_every_policy_has_its_policyholder_as_a_driver(admin):
    query = """
        select count(*) from insurance.policies as p
        where not exists (
            select from insurance.drivers as d
            where d.policy_id = p.id and d.relationship = 'policyholder'
        )
    """
    assert count(admin, query) == 0


def test_money_is_in_sensible_ranges(admin):
    # Liability only has no deductible. The others have one of five amounts.
    query = """
        select count(*) from insurance.policies
        where (coverage_level = 'liability') <> (deductible = 0)
           or deductible not in (0, 250, 500, 1000, 1500, 2000)
           or premium not between 300 and 6000
    """
    assert count(admin, query) == 0
    assert (
        count(
            admin, "select count(*) from insurance.vehicles where value not between 2000 and 60000"
        )
        == 0
    )
    assert (
        count(
            admin, "select count(*) from insurance.claims where reserve not between 100 and 100000"
        )
        == 0
    )


def test_every_gap_in_the_text_is_filled(admin):
    # A gap left as {store} would mean the text library and the generator disagree.
    assert count(admin, "select count(*) from insurance.claims where description like '%{%'") == 0
    assert count(admin, "select count(*) from insurance.claim_notes where note like '%{%'") == 0


# Personal data is fake ---------------------------------------------------------------


def test_every_email_is_at_example_com(admin):
    # example.com is reserved for examples: mail sent there is never delivered.
    query = r"""
        select count(*) from insurance.customers where email !~ '^[a-z0-9.]+@example\.com$'
    """
    assert count(admin, query) == 0


def test_every_phone_number_is_in_the_555_01xx_range(admin):
    # 555-0100 to 555-0199 is reserved for fiction.
    query = r"""
        select count(*) from insurance.customers where phone !~ '^\([0-9]{3}\) 555-01[0-9]{2}$'
    """
    assert count(admin, query) == 0


def test_drivers_license_numbers_are_unique(admin):
    # The loader finds each customer's id again by it.
    query = """
        select count(*) - count(distinct drivers_license_number) from insurance.customers
    """
    assert count(admin, query) == 0


# Same data every time ----------------------------------------------------------------

TABLES = (
    "customers",
    "policies",
    "vehicles",
    "drivers",
    "repair_shops",
    "adjusters",
    "claims",
    "claim_payments",
    "claim_notes",
)


def snapshot(admin) -> dict[str, list]:
    """Every row of every business table, without the random public_id."""
    query = sql.SQL("select to_jsonb(t) - 'public_id' from {} as t order by t.id")
    return {
        table: admin.execute(query.format(sql.Identifier("insurance", table))).fetchall()
        for table in TABLES
    }


def test_running_the_generator_again_gives_the_same_data(admin, admin_url):
    before = snapshot(admin)
    with psycopg.connect(admin_url) as conn:
        load_data(conn, "small")
    after = snapshot(admin)

    assert after == before
    assert all(before[table] for table in TABLES), "every table should have rows"
