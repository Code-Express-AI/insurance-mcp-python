"""The fixed settings behind the data: its dates, its seed and its two sizes.

Change none of these once the docs are published: every answer in the docs
depends on them.
"""

import datetime
from dataclasses import dataclass

# The data covers three full calendar years.
START_DATE = datetime.date(2024, 1, 1)

# The dataset's "today". Every date, planted facts included, is worked out from
# it. It's in the past and fixed, so the data never changes with the calendar.
AS_OF_DATE = datetime.date(2026, 12, 31)

# The same seed gives everyone the same customers, policies and claims.
SEED = 2026

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
