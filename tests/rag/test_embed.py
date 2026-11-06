"""The embed command's own logic: splitting the booklets, and the progress line."""

from pathlib import Path

import pytest

from insurance_mcp.embed import BOOKLETS_DIR, progress_line, split_booklet

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
