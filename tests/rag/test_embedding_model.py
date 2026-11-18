"""The embed command and the searches, with the real model, on small data.

They download the model (90 MB) the first time and take under a minute, so they
only run when asked for: uv run pytest -m embedding_model
"""

import psycopg
import pytest
from psycopg.rows import dict_row

from insurance_database.embed import BOOKLETS_DIR, embed_everything, split_booklet
from insurance_database.generate.planted import PARKING_LOT_DESCRIPTIONS
from insurance_mcp.embeddings import embed_query, load_model

pytestmark = pytest.mark.embedding_model


@pytest.fixture(scope="module")
def embedded(admin_url):
    """Run the embed command on the test database, and remove the embeddings at the end."""
    embed_everything(admin_url)
    yield
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("update insurance.claims set embedding = null")
        conn.execute("update insurance.claim_notes set embedding = null")
        conn.execute("delete from insurance.policy_document_chunks")


def search_wording(reader, question: str, coverage_level: str | None = None) -> list[dict]:
    with reader.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "select * from mcp.search_policy_wording(%s, %s)",
            [embed_query(question), coverage_level],
        ).fetchall()


def test_every_text_fits_in_what_the_model_reads(admin):
    # The model reads at most 256 word pieces (tokens) and silently ignores the rest.
    tokenizer = load_model().model.tokenizer
    tokenizer.no_truncation()

    def tokens(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    for path in sorted(BOOKLETS_DIR.glob("*.md")):
        for heading, content in split_booklet(path.read_text(encoding="utf-8")):
            assert tokens(f"{heading}\n{content}") <= 256, f"{path.name}: {heading}"
    for column, table in [("description", "claims"), ("note", "claim_notes")]:
        longest = admin.execute(
            f"select {column} from insurance.{table} order by length({column}) desc limit 1"
        ).fetchone()[0]
        assert tokens(longest) <= 256, table


def test_booklets_only_loads_the_booklets_and_leaves_the_claims(admin, admin_url):
    # The README's RAG quickstart: the booklets in seconds, the claims later.
    # Runs before the `embedded` fixture, so nothing is embedded yet.
    embed_everything(admin_url, booklets_only=True)
    try:
        counts = admin.execute(
            """
            select (select count(*) from insurance.policy_document_chunks),
                   (select count(*) from insurance.claims where embedding is not null),
                   (select count(*) from insurance.claim_notes where embedding is not null)
            """
        ).fetchone()
        assert counts == (37, 0, 0)
    finally:
        admin.execute("delete from insurance.policy_document_chunks")


def test_the_embed_command_embeds_every_text(embedded, admin):
    missing = admin.execute(
        """
        select (select count(*) from insurance.claims where embedding is null),
               (select count(*) from insurance.claim_notes where embedding is null),
               (select count(*) from insurance.policy_document_chunks)
        """
    ).fetchone()
    assert missing == (0, 0, 37)


def test_running_the_embed_command_again_embeds_nothing_new(embedded, admin, admin_url, capsys):
    # The number of notes depends on the day the data was made, so ask the database.
    notes = admin.execute("select count(*) from insurance.claim_notes").fetchone()[0]
    embed_everything(admin_url)
    output = capsys.readouterr().out
    assert "Policy booklets:    already loaded" in output
    assert f"Claim notes:        {notes:,} / {notes:,} (100%)\n" in output


def test_the_embed_command_carries_on_where_it_stopped(embedded, admin, admin_url):
    admin.execute("update insurance.claim_notes set embedding = null where id % 10 = 0")
    embed_everything(admin_url)
    assert admin.execute(
        "select count(*) from insurance.claim_notes where embedding is null"
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("question", "coverage_level", "expected"),
    [
        (
            "Am I covered for flood damage?",
            "liability_collision",
            "What Liability + collision does not cover",
        ),
        ("I hit a deer", None, "Hitting an animal"),
        (
            "My windshield has a chip from a stone. What do I pay?",
            None,
            "Windshield and window glass",
        ),
        # The README's combined questions: Eleanor Rutherford's two cars and the
        # hailstorm, and Maria Garcia's windshield chip (full coverage).
        ("Is hail damage covered?", "full", "Weather damage"),
        (
            "Is hail damage covered?",
            "liability_collision",
            "What Liability + collision does not cover",
        ),
        (
            "What does it cost to fix a chip in the windshield?",
            "full",
            "Windshield and window glass",
        ),
    ],
)
def test_policy_questions_find_the_right_section(
    embedded, reader, question, coverage_level, expected
):
    assert search_wording(reader, question, coverage_level)[0]["heading"] == expected


# The RAG demo questions -------------------------------------------------------------

# Accident descriptions where the car was hit by another vehicle while parked:
# the planted ones and the random library's own.
HIT_WHILE_PARKED = (
    *PARKING_LOT_DESCRIPTIONS,
    "parking lot while I was inside",
    "While I was parked outside",
    "pulling up to the next pump hit my rear door",
    "In the morning the driver's side was caved in",
)


def search_claims_by_meaning(reader, question: str, **filters) -> list[str]:
    with reader.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select matched_text from mcp.search_claim_text(%s, %s, %s)",
            [
                embed_query(question),
                filters.get("search_in", "descriptions"),
                filters.get("claim_type"),
            ],
        ).fetchall()
    return [row["matched_text"] for row in rows]


def test_the_parking_lot_demo_finds_cars_hit_while_parked(embedded, reader):
    # None of the matches needs the word "supermarket": that's the point of RAG.
    # Checked by hand on full data too, where it finds 10 out of 10.
    found = search_claims_by_meaning(
        reader,
        "Find claims where the car was hit while parked at a supermarket",
        claim_type="collision",
    )
    hits = [text for text in found if any(phrase in text for phrase in HIT_WHILE_PARKED)]
    assert len(hits) >= 8, found


def test_a_notes_search_finds_injuries(embedded, reader):
    found = search_claims_by_meaning(
        reader, "claimant still in pain from a neck injury", search_in="notes"
    )
    assert all("neck" in text for text in found[:5]), found
