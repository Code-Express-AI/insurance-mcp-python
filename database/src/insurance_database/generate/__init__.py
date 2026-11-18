"""The data generator: fake customers, policies and claims, the same for everyone.

Run it with:  uv run python -m insurance_database.generate [--size small]

The setup command runs it too, so you only need it to reload the data. It
empties the business tables and loads everything again, in one transaction.

All data is fake. Nothing describes a real person, vehicle or company.
"""

import random

import psycopg

from insurance_database.generate import planted, random_data
from insurance_database.generate.config import ADJUSTER_COUNT, REPAIR_SHOP_COUNT, SEED, SIZES
from insurance_database.generate.database import load_dataset
from insurance_database.generate.records import Dataset


def build_dataset(size: str) -> Dataset:
    """Every record, in Python. The order matters: each step uses the one random
    object in turn, so changing the order changes the data."""
    rng = random.Random(SEED)
    counts = SIZES[size]
    data = Dataset()

    data.repair_shops = random_data.make_repair_shops(rng, REPAIR_SHOP_COUNT - 1)
    data.repair_shops.append(planted.most_expensive_shop())
    data.adjusters = random_data.make_adjusters(rng, ADJUSTER_COUNT - 1)
    data.adjusters.append(planted.busiest_adjuster())

    random_data.add_customers_and_policies(rng, data, counts.customers)
    random_data.add_claims(rng, data, counts.claims)
    planted.add_planted_records(rng, data)

    # A fresh random object for the rest. Some planted claims depend on the
    # calendar ("last month"), so they can use up the random numbers differently
    # from one month to the next. Starting again here keeps everyone's claim
    # numbers, payments and notes the same, whenever the data is set up.
    rng = random.Random(SEED + 1)
    random_data.give_out_numbers(rng, data)
    random_data.add_payments_and_notes(rng, data)
    return data


def load_data(conn: psycopg.Connection, size: str) -> None:
    """Build the dataset and load it, in the caller's transaction."""
    data = build_dataset(size)
    load_dataset(conn, data)
    notes = sum(len(c.notes) for c in data.claims)
    print(
        f"Loaded {size} data: {len(data.customers):,} customers, {len(data.policies):,} policies, "
        f"{len(data.claims):,} claims, {notes:,} claim notes."
    )
