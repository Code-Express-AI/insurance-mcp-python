"""The RAG functions, called as mcp_reader: the embedding check, row limits, filters, redaction.

The tests use hand-made embeddings (the fake_embeddings fixture), not the model,
so they need no download and run in seconds. They check what the functions
promise whatever the vectors mean. tests/rag/test_embedding_model.py checks the
real model.
"""

import re

import pytest
from psycopg import errors
from psycopg.rows import dict_row

PHONE = re.compile(r"\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-. ][0-9]{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

EMBEDDING_MESSAGE = "The embedding must be a list of exactly 384 numbers."


def rows(reader, query: str, *args) -> list[dict]:
    with reader.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(query, args).fetchall()


# Before the embed command has run ---------------------------------------------------
# These come first in the file: pytest runs a module's tests in order, and the
# fake_embeddings fixture fills the embeddings when the first test that asks for it runs.


def test_search_claim_text_says_run_the_embed_command_first(reader, unit_vector):
    with pytest.raises(errors.RaiseException, match="^Run the embed command first"):
        reader.execute("select * from mcp.search_claim_text(%s::real[])", [unit_vector(0)])


def test_find_similar_claims_says_run_the_embed_command_first(reader):
    with pytest.raises(errors.RaiseException, match="^Run the embed command first"):
        reader.execute("select * from mcp.find_similar_claims('CLM-1037552')")


def test_search_policy_wording_says_run_the_embed_command_first(reader, unit_vector):
    with pytest.raises(errors.RaiseException, match="^Run the embed command first"):
        reader.execute("select * from mcp.search_policy_wording(%s::real[])", [unit_vector(0)])


# The embedding check -----------------------------------------------------------------


BAD_EMBEDDINGS = [
    pytest.param(None, id="null"),
    pytest.param([0.5] * 383, id="383-numbers"),
    pytest.param([0.5] * 385, id="385-numbers"),
    pytest.param([], id="empty"),
    pytest.param([[0.5] * 192, [0.5] * 192], id="two-dimensional"),
    pytest.param([0.5] * 383 + [None], id="contains-a-null"),
]


@pytest.mark.parametrize("embedding", BAD_EMBEDDINGS)
@pytest.mark.parametrize("function", ["search_claim_text", "search_policy_wording"])
def test_anything_but_384_numbers_is_rejected(fake_embeddings, reader, function, embedding):
    # Without this check, a null would return rows with no score instead of an error.
    with pytest.raises(errors.RaiseException, match=f"^{re.escape(EMBEDDING_MESSAGE)}"):
        reader.execute(f"select * from mcp.{function}(%s::real[])", [embedding])


# search_claim_text --------------------------------------------------------------------


def search(reader, embedding, **arguments) -> list[dict]:
    named = "".join(f", p_{name} => %s" for name in arguments)
    query = f"select * from mcp.search_claim_text(%s::real[]{named})"
    return rows(reader, query, embedding, *arguments.values())


def test_search_claim_text_returns_10_by_default_and_at_most_50(
    fake_embeddings, reader, unit_vector
):
    assert len(search(reader, unit_vector(0))) == 10
    assert len(search(reader, unit_vector(0), limit=50)) == 50
    assert len(search(reader, unit_vector(0), limit=999)) == 50
    assert len(search(reader, unit_vector(0), limit=0)) == 1


def test_search_claim_text_searches_descriptions_or_notes(fake_embeddings, reader, unit_vector):
    # Descriptions have unit vector 0 and notes 1 (fake_embeddings).
    assert search(reader, unit_vector(0))[0]["similarity"] == 1
    assert search(reader, unit_vector(0), search_in="notes")[0]["similarity"] == 0
    assert search(reader, unit_vector(1), search_in="notes")[0]["similarity"] == 1


def test_search_claim_text_returns_each_claim_once_from_its_notes(
    fake_embeddings, reader, unit_vector
):
    # Most claims have several notes, all with the same embedding here, so
    # without "each claim once" the same claim would fill the results.
    found = search(reader, unit_vector(1), search_in="notes", limit=50)
    numbers = [row["claim_number"] for row in found]
    assert len(set(numbers)) == len(numbers) == 50


def test_search_claim_text_rejects_an_unknown_search_in(fake_embeddings, reader, unit_vector):
    with pytest.raises(errors.RaiseException, match='^Unknown search_in "both"'):
        search(reader, unit_vector(0), search_in="both")


def test_search_claim_text_finds_the_closest_text_first(
    fake_embeddings, admin, reader, unit_vector
):
    admin.execute(
        "update insurance.claims set embedding = %s where claim_number = 'CLM-1037552'",
        [str(unit_vector(5))],
    )
    try:
        best = search(reader, unit_vector(5))[0]
    finally:
        admin.execute(
            "update insurance.claims set embedding = %s where claim_number = 'CLM-1037552'",
            [str(unit_vector(0))],
        )

    assert best["claim_number"] == "CLM-1037552"
    assert best["similarity"] == 1


def test_search_claim_text_applies_every_filter(fake_embeddings, reader, unit_vector):
    found = search(
        reader,
        unit_vector(0),
        claim_type="collision",
        status="open",
        period="last_12_months",
        min_reserve=5000,
        limit=50,
    )
    assert found, "Expected some open collision claims over $5,000 on small data."
    for row in found:
        assert (row["claim_type"], row["status"]) == ("collision", "open")
        assert row["reserve"] >= 5000
        assert str(row["date_reported"]) >= "2026-01-01"


def test_search_claim_text_rejects_an_unknown_period(fake_embeddings, reader, unit_vector):
    with pytest.raises(errors.RaiseException, match='Unknown period "yesterday"'):
        search(reader, unit_vector(0), period="yesterday")


def test_search_claim_text_redacts_phone_numbers_and_emails(
    fake_embeddings, admin, reader, unit_vector
):
    # Point every note with contact details at the search, so they all come back.
    contact_details = r"n.note ~ '[0-9]{3}[-. ][0-9]{4}' or n.note like '%%@%%'"
    admin.execute(
        f"update insurance.claim_notes as n set embedding = %s where {contact_details}",
        [str(unit_vector(5))],
    )
    try:
        found = search(reader, unit_vector(5), search_in="notes", limit=50)
    finally:
        admin.execute(
            f"update insurance.claim_notes as n set embedding = %s where {contact_details}",
            [str(unit_vector(1))],
        )

    assert found and found[0]["similarity"] == 1, "Expected notes with contact details."
    for row in found:
        assert not PHONE.search(row["matched_text"]), row["matched_text"]
        assert not EMAIL.search(row["matched_text"]), row["matched_text"]


def test_search_claim_text_replaces_the_customers_own_street_address(
    fake_embeddings, admin, reader, unit_vector
):
    # A search turns collecting addresses into one query, so the notes branch
    # must remove them too. Point every note with its customer's address at the search.
    own_address = """
        n.claim_id in (
            select c.id
            from insurance.claims as c
            join insurance.policies as p on p.id = c.policy_id
            join insurance.customers as cu on cu.id = p.customer_id
            where position(cu.street_address in n.note) > 0)
    """
    admin.execute(
        f"update insurance.claim_notes as n set embedding = %s where {own_address}",
        [str(unit_vector(6))],
    )
    try:
        found = search(reader, unit_vector(6), search_in="notes", limit=50)
    finally:
        admin.execute(
            f"update insurance.claim_notes as n set embedding = %s where {own_address}",
            [str(unit_vector(1))],
        )
    address_of = dict(
        admin.execute(
            """
            select c.claim_number, cu.street_address
            from insurance.claims as c
            join insurance.policies as p on p.id = c.policy_id
            join insurance.customers as cu on cu.id = p.customer_id
            """
        ).fetchall()
    )

    assert found and found[0]["similarity"] == 1, "Expected notes with the customer's address."
    for row in found:
        assert address_of[row["claim_number"]] not in row["matched_text"], row["matched_text"]
        assert "[address]" in row["matched_text"], row["matched_text"]


# find_similar_claims ------------------------------------------------------------------


def similar(reader, claim_number: str, **arguments) -> list[dict]:
    named = "".join(f", p_{name} => %s" for name in arguments)
    query = f"select * from mcp.find_similar_claims(%s{named})"
    return rows(reader, query, claim_number, *arguments.values())


def test_find_similar_claims_finds_the_closest_and_leaves_out_the_claim_itself(
    fake_embeddings, admin, reader, unit_vector
):
    # Give two claims the same unusual embedding: each is the other's closest match.
    update = "update insurance.claims set embedding = %s where claim_number = any(%s)"
    pair = ["CLM-1037552", "CLM-1049306"]
    admin.execute(update, [str(unit_vector(5)), pair])
    try:
        found = similar(reader, "CLM-1037552")
    finally:
        admin.execute(update, [str(unit_vector(0)), pair])

    assert found[0]["claim_number"] == "CLM-1049306"
    assert found[0]["similarity"] == 1
    assert "CLM-1037552" not in [row["claim_number"] for row in found]


def test_find_similar_claims_returns_10_by_default_and_at_most_50(fake_embeddings, reader):
    assert len(similar(reader, "CLM-1037552")) == 10
    assert len(similar(reader, "CLM-1037552", limit=999)) == 50


def test_find_similar_claims_applies_its_filters(fake_embeddings, reader):
    found = similar(reader, "CLM-1037552", claim_type="glass", status="settled", limit=50)
    assert found
    assert {(row["claim_type"], row["status"]) for row in found} == {("glass", "settled")}


def test_find_similar_claims_rejects_an_unknown_claim_number(fake_embeddings, reader):
    with pytest.raises(errors.RaiseException, match="^Unknown claim number"):
        similar(reader, "CLM-9999999")


# search_policy_wording ----------------------------------------------------------------


def test_search_policy_wording_returns_5_by_default_and_at_most_50(
    fake_embeddings, reader, unit_vector
):
    query = "select * from mcp.search_policy_wording(%s::real[], p_limit => %s)"
    assert len(rows(reader, query, unit_vector(2), None)) == 5
    # The fixture loads 60 sections.
    assert len(rows(reader, query, unit_vector(2), 999)) == 50


def test_search_policy_wording_can_search_one_coverage_level(fake_embeddings, reader, unit_vector):
    query = "select * from mcp.search_policy_wording(%s::real[], 'full', 50)"
    found = rows(reader, query, unit_vector(2))
    assert len(found) == 20
    assert {row["coverage_level"] for row in found} == {"full"}
