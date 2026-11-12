"""The mcp functions, called as mcp_reader: row limits, wildcards, unknown numbers, masking.

These call the functions directly, the way someone with the reader password
could, without the server's argument checks in front. So they prove the
database holds on its own.
"""

import re
import uuid

import pytest
from psycopg import errors
from psycopg.rows import dict_row

# What the functions must never return. Phone and email patterns match the
# ones insurance.redact_text replaces.
PHONE = re.compile(r"\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-. ][0-9]{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MASKED_EMAIL = re.compile(r"^.\*\*\*@example\.com$")


def rows(reader, query: str, *args) -> list[dict]:
    with reader.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, args).fetchall()


def maria_garcia_id(reader) -> uuid.UUID:
    return rows(reader, "select customer_id from mcp.find_customers('Maria Garcia')")[0][
        "customer_id"
    ]


# Row limits ---------------------------------------------------------------------------


def test_find_customers_returns_at_most_25(reader):
    # "an" matches far more than 25 names, even on small data.
    assert len(rows(reader, "select * from mcp.find_customers('an')")) == 25


def test_search_claims_returns_50_per_page(reader):
    found = rows(reader, "select * from mcp.search_claims()")
    assert len(found) == 50
    assert found[0]["total_count"] > 50


@pytest.mark.parametrize("page", [0, -5])
def test_search_claims_treats_a_page_below_1_as_page_1(reader, page):
    query = "select claim_number from mcp.search_claims(p_page => %s)"
    assert rows(reader, query, page) == rows(reader, query, 1)


@pytest.mark.full_data
def test_search_claims_stops_at_page_20(full_data, reader):
    # Small data has fewer than 20 pages of claims, so this needs full data.
    query = "select claim_number from mcp.search_claims(p_page => %s)"
    assert len(rows(reader, query, 20)) == 50
    assert rows(reader, query, 21) == rows(reader, query, 20)
    assert rows(reader, query, 999) == rows(reader, query, 20)


REPAIR_SHOP_COSTS = "select * from mcp.get_repair_shop_costs('last_12_months', %s)"


@pytest.mark.parametrize("limit", [0, -3])
def test_get_repair_shop_costs_treats_a_limit_below_1_as_1(reader, limit):
    assert len(rows(reader, REPAIR_SHOP_COSTS, limit)) == 1


@pytest.mark.full_data
@pytest.mark.parametrize(("limit", "expected"), [(1000, 20), (None, 10)])
def test_get_repair_shop_costs_lists_at_most_20_shops(full_data, reader, limit, expected):
    # Small data has only a few shops with 5 claims, so this needs full data.
    assert len(rows(reader, REPAIR_SHOP_COSTS, limit)) == expected


def test_get_claim_returns_the_latest_20_notes_and_counts_them_all(admin, reader):
    claim_id = admin.execute(
        "select id from insurance.claims where claim_number = 'CLM-1049306'"
    ).fetchone()[0]
    admin.execute(
        """
        insert into insurance.claim_notes (claim_id, adjuster_id, created_at, note)
        select %s, (select min(id) from insurance.adjusters),
               '2026-12-31 23:00+00'::timestamptz - n * interval '1 minute', 'Extra note ' || n
        from generate_series(1, 25) as n
        """,
        [claim_id],
    )
    try:
        claim = rows(reader, "select * from mcp.get_claim('CLM-1049306')")[0]
    finally:
        admin.execute("delete from insurance.claim_notes where note like 'Extra note %%'")

    assert len(claim["notes"]) == 20
    assert claim["note_count"] > 25
    # Newest first: Extra note 1 is a minute before 23:00 on the last day.
    assert claim["notes"][0]["note"] == "Extra note 1"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("select * from mcp.count_claims_by_month('last_12_months')", 12),
        ("select * from mcp.count_claims_by_month('last_month')", 1),
        ("select * from mcp.count_claims_by_driver_age('last_year')", 4),
    ],
)
def test_the_counts_return_every_month_or_band_and_no_more(reader, query, expected):
    assert len(rows(reader, query)) == expected


def test_get_adjuster_workload_returns_at_most_100(reader):
    assert 0 < len(rows(reader, "select * from mcp.get_adjuster_workload()")) <= 100


# Wildcards and short searches -------------------------------------------------------


def test_find_customers_finds_a_name_anywhere_in_first_and_last(reader):
    # The control for the tests below: a real search does find people.
    assert len(rows(reader, "select * from mcp.find_customers('Maria Garcia')")) == 1
    assert len(rows(reader, "select * from mcp.find_customers('rutherford')")) == 1


@pytest.mark.parametrize("search", ["%%", "__", "\\\\", "%_%"])
def test_find_customers_treats_wildcards_as_plain_characters(reader, search):
    # Without insurance.escape_like, "%%" would match every customer.
    assert rows(reader, "select * from mcp.find_customers(%s)", search) == []


# Invisible characters: the byte-order mark, the zero-width joiner, the zero-width
# space and the soft hyphen. Some databases' text rules ignore them when they
# compare, so two of them pass the 2-character minimum and match every name.
# PostgreSQL compares every character, so they match nothing, and the server
# doesn't need to filter them out.
@pytest.mark.parametrize("invisible", ["﻿", "‍", "​", "­"])
def test_find_customers_does_not_ignore_invisible_characters(reader, invisible):
    assert rows(reader, "select * from mcp.find_customers(%s)", invisible * 2) == []
    # Inside a real name too: "Gar<invisible>cia" isn't "Garcia".
    assert rows(reader, "select * from mcp.find_customers(%s)", f"Gar{invisible}cia") == []


@pytest.mark.parametrize("search", ["", "a", "  a  ", None])
def test_find_customers_needs_at_least_2_characters(reader, search):
    assert rows(reader, "select * from mcp.find_customers(%s)", search) == []


# Unknown ids, numbers and periods -----------------------------------------------------


@pytest.mark.parametrize(
    ("query", "argument", "message"),
    [
        (
            "select * from mcp.get_customer(%s)",
            uuid.uuid4(),
            "Unknown customer_id. Use find_customers to find it.",
        ),
        (
            "select * from mcp.get_policy(%s)",
            "AUT-999999",
            "Unknown policy number. Use find_customers, then get_customer, to find it.",
        ),
        (
            "select * from mcp.get_claim(%s)",
            "CLM-9999999",
            "Unknown claim number. Use search_claims to find it.",
        ),
    ],
)
def test_an_unknown_lookup_raises_p0001_with_a_helpful_message(reader, query, argument, message):
    # P0001 is the one SQLSTATE the server passes on to the model.
    with pytest.raises(errors.RaiseException) as raised:
        reader.execute(query, [argument])
    assert raised.value.sqlstate == "P0001"
    assert raised.value.diag.message_primary == message


@pytest.mark.parametrize(
    ("query", "period"),
    [
        ("select * from mcp.search_claims(p_period => %s)", "yesterday"),
        ("select * from mcp.count_claims_by_month(%s)", "yesterday"),
        ("select * from mcp.count_claims_by_month(%s)", None),
        ("select * from mcp.get_repair_shop_costs(%s)", "yesterday"),
        ("select * from mcp.get_repair_shop_costs(%s)", None),
        ("select * from mcp.count_claims_by_driver_age(%s)", "yesterday"),
        ("select * from mcp.count_claims_by_driver_age(%s)", None),
    ],
)
def test_an_unknown_or_missing_period_raises_rather_than_matching_everything(reader, query, period):
    # (In search_claims, no period means any date, so only an unknown one raises.)
    with pytest.raises(errors.RaiseException, match="Unknown period"):
        reader.execute(query, [period])


# Masking -------------------------------------------------------------------------


def everything_about_maria_garcia(reader) -> str:
    """Every function's result for Maria Garcia, her policy and her claims, as one text.

    Without the free text (descriptions and notes): free text can hold names and
    places that no pattern catches, an honest limit (database-spec.md, decision 9).
    The redaction tests further down check the free text separately.
    """
    customer_id = maria_garcia_id(reader)
    results = [
        rows(reader, "select * from mcp.find_customers('Garcia')"),
        rows(reader, "select * from mcp.get_customer(%s)", customer_id),
        rows(reader, "select * from mcp.get_policy('AUT-104233')"),
        rows(reader, "select * from mcp.search_claims(p_customer_id => %s)", customer_id),
    ]
    for number in ("CLM-1024817", "CLM-1037552", "CLM-1049306"):
        claim = rows(reader, "select * from mcp.get_claim(%s)", number)[0]
        results.append({k: v for k, v in claim.items() if k not in ("description", "notes")})
    return str(results)


def test_no_function_returns_maria_garcias_personal_data(admin, reader):
    email, license_number, street, phone, born = admin.execute(
        """
        select email, drivers_license_number, street_address, phone, date_of_birth
        from insurance.customers where first_name = 'Maria' and last_name = 'Garcia'
        """
    ).fetchone()
    returned = everything_about_maria_garcia(reader)

    assert "m***@example.com" in returned  # the control: her masked email is there
    for secret in (email, license_number, street, phone, phone[-8:], str(born), repr(born)):
        assert secret not in returned, f"{secret} was returned"


def test_every_email_returned_is_masked(reader):
    for customer in rows(reader, "select * from mcp.find_customers('an')"):
        assert MASKED_EMAIL.match(customer["email"]), customer["email"]
        detail = rows(reader, "select * from mcp.get_customer(%s)", customer["customer_id"])[0]
        assert MASKED_EMAIL.match(detail["email"])
        assert re.fullmatch(r"\*{5}.{4}", detail["drivers_license_number"])


def test_get_claim_redacts_phone_numbers_and_emails_in_notes(admin, reader):
    numbers = admin.execute(
        r"""
        select distinct c.claim_number
        from insurance.claims as c
        join insurance.claim_notes as n on n.claim_id = c.id
        where n.note ~ '[0-9]{3}[-. ][0-9]{4}' or n.note like '%%@%%'
        order by c.claim_number
        limit 50
        """
    ).fetchall()
    assert numbers, "Expected some notes with contact details in the generated data."

    for (number,) in numbers:
        claim = str(rows(reader, "select notes from mcp.get_claim(%s)", number))
        assert not PHONE.search(claim), f"{number} returned a phone number"
        assert not EMAIL.search(claim), f"{number} returned an email address"


def test_get_claim_replaces_the_customers_own_street_address_in_notes(admin, reader):
    # No tool returns customers.street_address, but some notes write it out.
    # The database knows whose claim it is, so it removes that exact address.
    claims = admin.execute(
        """
        select distinct c.claim_number, cu.street_address
        from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        join insurance.claim_notes as n on n.claim_id = c.id
        where position(cu.street_address in n.note) > 0
        order by c.claim_number
        limit 50
        """
    ).fetchall()
    assert claims, "Expected some notes with the customer's address in the generated data."

    for number, street_address in claims:
        notes = str(rows(reader, "select notes from mcp.get_claim(%s)", number))
        assert street_address not in notes, f"{number} returned {street_address}"
        assert "[address]" in notes


def test_get_claim_redacts_phone_numbers_and_emails_in_the_description(admin, reader):
    # No generated description has contact details, so the test writes one in.
    query = "select description from insurance.claims where claim_number = 'CLM-1037552'"
    original = admin.execute(query).fetchone()[0]
    admin.execute(
        "update insurance.claims set description = %s where claim_number = 'CLM-1037552'",
        [original + " Call me on (210) 555-0147 or email mgarcia84@example.com."],
    )
    try:
        claim = rows(reader, "select description from mcp.get_claim('CLM-1037552')")[0]
    finally:
        admin.execute(
            "update insurance.claims set description = %s where claim_number = 'CLM-1037552'",
            [original],
        )

    assert claim["description"].endswith(" Call me on [phone] or email [email].")
