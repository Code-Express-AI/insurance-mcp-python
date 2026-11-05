"""The helper functions the mcp functions use. None of these need any data."""

import datetime

import pytest
from psycopg import errors


def call(admin, query: str, *args):
    return admin.execute(query, args).fetchone()[0]


@pytest.mark.parametrize(
    ("name", "matches"),
    [
        ("100%% Auto Glass", True),  # really contains %%
        ("Smith", False),  # a bare %% would match this too
        ("Mary_Jones", False),  # _ would match any one character
    ],
)
def test_escape_like_makes_wildcards_plain_characters(admin, name, matches):
    query = "select %s ilike '%%' || insurance.escape_like(%s) || '%%'"
    assert call(admin, query, name, "%%") is matches


def test_escape_like_escapes_backslashes_first(admin):
    assert call(admin, "select insurance.escape_like(%s)", "a\\b%c_d") == "a\\\\b\\%c\\_d"


def test_mask_email_keeps_the_first_letter_and_the_domain(admin):
    assert call(admin, "select insurance.mask_email(%s)", "maria.garcia@example.com") == (
        "m***@example.com"
    )


def test_mask_last4_always_shows_five_stars(admin):
    assert call(admin, "select insurance.mask_last4(%s)", "D1234567") == "*****4567"
    assert call(admin, "select insurance.mask_last4(%s)", "X98765432109") == "*****2109"


@pytest.mark.parametrize(
    "phone", ["(512) 555-0142", "512-555-0142", "512.555.0142", "512 555 0142"]
)
def test_redact_text_hides_phone_numbers(admin, phone):
    text = f"Called the claimant on {phone} about the estimate."
    assert call(admin, "select insurance.redact_text(%s)", text) == (
        "Called the claimant on [phone] about the estimate."
    )


def test_redact_text_hides_email_addresses(admin):
    text = "Sent photos to mgarcia84@example.com yesterday."
    assert call(admin, "select insurance.redact_text(%s)", text) == (
        "Sent photos to [email] yesterday."
    )


def test_redact_text_leaves_ordinary_numbers_alone(admin):
    text = "Repair estimate $2,450 for the 2019 Toyota Camry, ZIP 78701."
    assert call(admin, "select insurance.redact_text(%s)", text) == text


@pytest.mark.parametrize(
    ("period", "start", "end"),
    [
        ("last_month", "2026-11-01", "2026-11-30"),
        ("last_3_months", "2026-10-01", "2026-12-31"),
        ("last_12_months", "2026-01-01", "2026-12-31"),
        ("this_year", "2026-01-01", "2026-12-31"),
        ("last_year", "2025-01-01", "2025-12-31"),
    ],
)
def test_period_dates_in_whole_calendar_months(admin, period, start, end):
    row = admin.execute(
        "select * from insurance.period_dates(%s, '2026-12-31')", [period]
    ).fetchone()
    assert row == (datetime.date.fromisoformat(start), datetime.date.fromisoformat(end))


def test_period_dates_works_for_an_as_of_date_mid_month(admin):
    row = admin.execute(
        "select * from insurance.period_dates('last_month', '2026-03-15')"
    ).fetchone()
    assert row == (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))


def test_period_dates_rejects_an_unknown_period(admin):
    with pytest.raises(errors.RaiseException, match="Unknown period"):
        admin.execute("select * from insurance.period_dates('yesterday', '2026-12-31')")
