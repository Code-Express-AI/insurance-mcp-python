"""The embed command's own logic: splitting the booklets, the progress line, and
the text it embeds."""

import re
from pathlib import Path

import pytest

from insurance_mcp.embed import (
    BOOKLETS_DIR,
    DESCRIPTIONS,
    NOTES,
    progress_line,
    split_booklet,
)

PHONE = re.compile(r"\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-. ][0-9]{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

BOOKLETS = sorted(BOOKLETS_DIR.glob("*.md"))


def test_there_is_one_booklet_per_coverage_level():
    assert [path.stem for path in BOOKLETS] == ["full", "liability", "liability_collision"]


def test_split_booklet_makes_one_chunk_per_heading_and_leaves_out_the_title():
    text = "# Title\n\nIntro.\n\n## First\n\nOne.\n\nTwo.\n\n## Second\n\nThree.\n"
    assert split_booklet(text) == [("First", "One.\n\nTwo."), ("Second", "Three.")]


@pytest.mark.parametrize("path", BOOKLETS, ids=[path.stem for path in BOOKLETS])
def test_every_booklet_section_has_a_unique_heading_and_some_text(path: Path):
    sections = split_booklet(path.read_text(encoding="utf-8"))
    headings = [heading for heading, _ in sections]
    assert len(sections) >= 5
    assert len(set(headings)) == len(headings)
    assert all(content for _, content in sections)


@pytest.mark.parametrize("path", BOOKLETS, ids=[path.stem for path in BOOKLETS])
def test_every_booklet_says_it_is_not_real_insurance(path: Path):
    assert "It is not real insurance" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("done", "total", "seconds_left", "expected"),
    [
        (0, 76630, None, "Claim notes:        0 / 76,630 (0%)"),
        (23040, 76630, 290, "Claim notes:        23,040 / 76,630 (30%), about 5 min left"),
        (76000, 76630, 20, "Claim notes:        76,000 / 76,630 (99%), less than a minute left"),
        (76630, 76630, None, "Claim notes:        76,630 / 76,630 (100%)"),
    ],
)
def test_the_progress_line_shows_the_count_and_the_time_left(done, total, seconds_left, expected):
    assert progress_line("Claim notes", done, total, seconds_left) == expected


# The text it embeds: what the tools show, not the raw text --------------------------


@pytest.mark.parametrize(
    ("select_batch", "table"),
    [(DESCRIPTIONS, "claims"), (NOTES, "claim_notes")],
    ids=["descriptions", "notes"],
)
def test_the_embed_command_reads_every_row_redacted(admin, select_batch, table):
    # A limit bigger than the table, so one "batch" holds every row.
    texts = [text for _, text in admin.execute(select_batch, [10_000_000]).fetchall()]
    total = admin.execute(f"select count(*) from insurance.{table}").fetchone()[0]

    assert len(texts) == total  # the joins to the customer lose no rows
    for text in texts:
        assert not PHONE.search(text), text
        assert not EMAIL.search(text), text


def test_the_embed_command_replaces_the_customers_own_street_address(admin):
    addresses = dict(
        admin.execute(
            """
        select n.id, cu.street_address
        from insurance.claim_notes as n
        join insurance.claims as c on c.id = n.claim_id
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        where position(cu.street_address in n.note) > 0
        """
        ).fetchall()
    )
    assert addresses, "Expected some notes with the customer's address in the generated data."

    for note_id, text in admin.execute(NOTES, [10_000_000]).fetchall():
        if note_id in addresses:
            assert addresses[note_id] not in text, text
            assert "[address]" in text
