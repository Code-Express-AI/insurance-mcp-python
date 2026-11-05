"""Load a dataset into the database with COPY, the standard fast way to bulk-load PostgreSQL.

Tables are loaded parents first. The database creates each row's id, so after
loading a parent table we read the ids back, matched on a column we already
know (a policy's policy_number, for example), before loading its children.
"""

import psycopg
from psycopg import sql

from insurance_mcp.generate.records import Dataset

# Every business table. Never the audit log, which can't be emptied anyway.
BUSINESS_TABLES = (
    "claim_notes",
    "claim_payments",
    "claims",
    "adjusters",
    "repair_shops",
    "drivers",
    "vehicles",
    "policies",
    "customers",
)


def copy_rows(conn: psycopg.Connection, table: str, columns: list[str], rows) -> None:
    """COPY rows into insurance.<table>. The names are quoted by psycopg, never pasted in."""
    statement = sql.SQL("copy {table} ({columns}) from stdin").format(
        table=sql.Identifier("insurance", table),
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    with conn.cursor().copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def read_ids(conn: psycopg.Connection, query: str) -> dict:
    """{known column: id}. With more than one known column, the key is a tuple."""
    ids = {}
    for *key, id_ in conn.execute(query):
        ids[key[0] if len(key) == 1 else tuple(key)] = id_
    return ids


def load_dataset(conn: psycopg.Connection, data: Dataset) -> None:
    """Empty the business tables, then load the dataset. Runs in the caller's transaction."""
    tables = sql.SQL(", ").join(sql.Identifier("insurance", t) for t in BUSINESS_TABLES)
    # RESTART IDENTITY starts the ids at 1 again, so a reload gives the same ids.
    conn.execute(sql.SQL("truncate {} restart identity").format(tables))

    copy_rows(
        conn,
        "customers",
        ["first_name", "last_name", "date_of_birth", "street_address", "city", "state",
         "zip_code", "email", "phone", "drivers_license_number"],
        ((c.first_name, c.last_name, c.date_of_birth, c.street_address, c.city, c.state,
          c.zip_code, c.email, c.phone, c.drivers_license_number) for c in data.customers),
    )  # fmt: skip
    customer_ids = read_ids(conn, "select drivers_license_number, id from insurance.customers")

    copy_rows(
        conn,
        "policies",
        ["policy_number", "customer_id", "coverage_level", "premium", "deductible",
         "start_date", "end_date", "status"],
        ((p.policy_number, customer_ids[p.customer.drivers_license_number], p.coverage_level,
          p.premium, p.deductible, p.start_date, p.end_date, p.status) for p in data.policies),
    )  # fmt: skip
    policy_ids = read_ids(conn, "select policy_number, id from insurance.policies")

    copy_rows(
        conn,
        "vehicles",
        ["policy_id", "license_plate", "make", "model", "model_year", "value"],
        ((policy_ids[p.policy_number], p.vehicle.license_plate, p.vehicle.make, p.vehicle.model,
          p.vehicle.model_year, p.vehicle.value) for p in data.policies),
    )  # fmt: skip

    copy_rows(
        conn,
        "drivers",
        ["policy_id", "first_name", "last_name", "date_of_birth", "relationship"],
        ((policy_ids[p.policy_number], d.first_name, d.last_name, d.date_of_birth, d.relationship)
         for p in data.policies for d in p.drivers),
    )  # fmt: skip
    # A driver's first name is unique within a policy.
    driver_ids = read_ids(conn, "select policy_id, first_name, id from insurance.drivers")

    copy_rows(
        conn,
        "repair_shops",
        ["name", "city", "state"],
        ((s.name, s.city, s.state) for s in data.repair_shops),
    )
    shop_ids = read_ids(conn, "select name, id from insurance.repair_shops")

    copy_rows(
        conn,
        "adjusters",
        ["first_name", "last_name"],
        ((a.first_name, a.last_name) for a in data.adjusters),
    )
    adjuster_ids = read_ids(conn, "select first_name, last_name, id from insurance.adjusters")

    def claim_row(c):
        policy_id = policy_ids[c.policy.policy_number]
        return (
            c.claim_number,
            policy_id,
            driver_ids[(policy_id, c.driver.first_name)],
            adjuster_ids[(c.adjuster.first_name, c.adjuster.last_name)],
            shop_ids[c.repair_shop.name] if c.repair_shop else None,
            c.claim_type, c.fault, c.status, c.date_of_loss, c.date_reported, c.date_closed,
            c.reserve, c.description,
        )  # fmt: skip

    copy_rows(
        conn,
        "claims",
        ["claim_number", "policy_id", "driver_id", "adjuster_id", "repair_shop_id",
         "claim_type", "fault", "status", "date_of_loss", "date_reported", "date_closed",
         "reserve", "description"],
        map(claim_row, data.claims),
    )  # fmt: skip
    claim_ids = read_ids(conn, "select claim_number, id from insurance.claims")

    copy_rows(
        conn,
        "claim_payments",
        ["claim_id", "payment_type", "amount", "payment_date"],
        ((claim_ids[c.claim_number], p.payment_type, p.amount, p.payment_date)
         for c in data.claims for p in c.payments),
    )  # fmt: skip

    copy_rows(
        conn,
        "claim_notes",
        ["claim_id", "adjuster_id", "created_at", "note"],
        ((claim_ids[c.claim_number], adjuster_ids[(n.adjuster.first_name, n.adjuster.last_name)],
          n.created_at, n.note) for c in data.claims for n in c.notes),
    )  # fmt: skip

    # Fresh statistics, so the query planner knows how big the tables are now.
    conn.execute(sql.SQL("analyze {}").format(tables))
