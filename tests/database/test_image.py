"""The Docker image is the one the project needs."""

import psycopg


def test_postgres_major_version_is_18(superuser_url):
    with psycopg.connect(superuser_url) as conn:
        version = conn.execute("show server_version_num").fetchone()[0]
    assert version.startswith("18")


def test_pgvector_extension_is_available(superuser_url):
    with psycopg.connect(superuser_url) as conn:
        row = conn.execute(
            "select name from pg_available_extensions where name = 'vector'"
        ).fetchone()
    assert row is not None, "The image has no pgvector: use pgvector/pgvector, not plain postgres."
