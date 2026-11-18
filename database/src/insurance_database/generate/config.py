"""The settings behind the data: its dates, its seed and its two sizes.

Change the seed and the random data changes, but not the planted records
(planted.py), so the docs' demo answers and the tests still hold.
"""

import datetime
from dataclasses import dataclass


def years_before(day: datetime.date, years: int) -> datetime.date:
    """The same day, `years` earlier. February 29 becomes February 28."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


# The dataset's "today" is the day the data is generated, so "last month" always
# has data in it, whenever someone installs this. Every date, planted facts
# included, is worked out from it. The seed keeps the customers, policies and
# claims the same for everyone: only their dates move with the calendar.
# Run setup_db again to bring the data up to date.
AS_OF_DATE = datetime.date.today()

# The data covers the three years up to the as-of date. Counted in days, not
# calendar years: a date range that's a day longer (a leap day) uses up the
# random numbers differently, and from then on everyone's data would differ.
# The same goes for every random date in the generator.
START_DATE = AS_OF_DATE - datetime.timedelta(days=3 * 365)

# The same seed gives everyone the same customers, policies and claims.
SEED = 4505

# Reference data, the same at both sizes.
REPAIR_SHOP_COUNT = 60
ADJUSTER_COUNT = 25


@dataclass(frozen=True)
class Size:
    customers: int
    claims: int


SIZES = {
    # For the demos and the guides.
    "full": Size(customers=12_000, claims=15_000),
    # About 1/20 of full, for the tests: it loads in about a second.
    "small": Size(customers=600, claims=750),
}
