"""Shared test setup: one throwaway PostgreSQL container for the whole test run."""

import os
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path

import docker
import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from insurance_mcp.generate import load_data
from insurance_mcp.setup_db import setup_database

ROOT = Path(__file__).parent.parent

# The test database's passwords. They only exist inside the throwaway container.
ADMIN_PASSWORD = "test-admin-password"
READER_PASSWORD = "test-reader-password-24-chars"


def postgres_image() -> str:
    """The image from docker-compose.yml, so the tests and your database can't drift apart."""
    compose = (ROOT / "docker-compose.yml").read_text()
    return re.search(r"^\s*image:\s*(\S+)", compose, re.MULTILINE).group(1)


def docker_is_running() -> bool:
    try:
        docker.from_env().ping()
        return True
    except docker.errors.DockerException:
        return False


@pytest.fixture(scope="session")
def postgres():
    """Start one PostgreSQL container for the test run, and delete it at the end.

    Without Docker, the database tests are skipped with one clear reason.
    In CI (GitHub sets CI=true), they fail instead: a skipped test looks green.
    """
    if not docker_is_running():
        message = "Docker isn't running, so the database tests can't start PostgreSQL."
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    with PostgresContainer(postgres_image(), driver=None) as container:
        yield container


def connection_url(postgres, user: str, password: str, dbname: str) -> str:
    host = postgres.get_container_host_ip()
    port = postgres.get_exposed_port(5432)
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="session")
def superuser_url(postgres) -> str:
    """The container's own superuser. Only used to create the admin role below."""
    return postgres.get_connection_url()


@pytest.fixture(scope="session")
def admin_url(postgres, superuser_url) -> str:
    """The admin role, after the setup command has built the database and loaded small data.

    Like a hosted database's admin, it isn't a superuser: it can create roles and
    owns the database, nothing more. So every test run proves the setup never
    needs superuser rights, apart from installing pgvector (below).
    """
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        conn.execute(f"create role app_admin login createrole password '{ADMIN_PASSWORD}'")
        conn.execute("create database insurance owner app_admin")

    # pgvector isn't a "trusted" extension, so only a superuser can install it.
    # A hosted service lets its admin role install it, so the container's
    # superuser stands in for that here. The setup's "create extension if not
    # exists" then does nothing.
    superuser = connection_url(postgres, postgres.username, postgres.password, "insurance")
    with psycopg.connect(superuser) as conn:
        conn.execute("create extension vector")

    url = connection_url(postgres, "app_admin", ADMIN_PASSWORD, "insurance")
    setup_database(url, reader_url_for(postgres), size="small")
    return url


def reader_url_for(postgres) -> str:
    return connection_url(postgres, "mcp_reader", READER_PASSWORD, "insurance")


@pytest.fixture(scope="session")
def reader_url(postgres, admin_url) -> str:
    """The mcp_reader connection string. Depends on admin_url, so the setup has run."""
    return reader_url_for(postgres)


@pytest.fixture(scope="session")
def full_data(admin_url):
    """Reload the test database with full data, for the tests marked full_data.

    They run on their own (uv run pytest -m full_data), because every other test
    expects small data.
    """
    with psycopg.connect(admin_url) as conn:
        load_data(conn, "full")


@pytest.fixture
def admin(admin_url):
    """A connection as the admin role. Each statement commits on its own."""
    with psycopg.connect(admin_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def reader(reader_url):
    """A connection as mcp_reader, the role the MCP server uses, as the local caller.

    local sees every state, so the tests check all the data. The setting lasts
    for the whole connection (false), not one transaction like the server's.
    The row-level security tests use reader_as instead.
    """
    with connect_as_caller(reader_url, "local") as conn:
        yield conn


@pytest.fixture
def reader_as(reader_url):
    """Open mcp_reader connections as any caller key: reader_as("claude")."""
    with ExitStack() as connections:
        yield lambda caller_key: connections.enter_context(
            connect_as_caller(reader_url, caller_key)
        )


@contextmanager
def connect_as_caller(reader_url: str, caller_key: str | None):
    """A connection as mcp_reader with mcp.caller_key set, or none set if None."""
    with psycopg.connect(reader_url, autocommit=True) as conn:
        if caller_key is not None:
            conn.execute("select set_config('mcp.caller_key', %s, false)", [caller_key])
        yield conn


@pytest.fixture
def anyio_backend() -> str:
    """The async tests (marked anyio) run on asyncio, like the server."""
    return "asyncio"


# Hand-made embeddings, so the RAG functions can be tested without the model ---------

DIMENSIONS = 384


def make_unit_vector(position: int) -> list[float]:
    """384 numbers, all 0 except a 1 at `position`.

    Two of these at the same position have similarity 1 (the same "meaning").
    At different positions, similarity 0 (nothing in common).
    """
    return [1.0 if i == position else 0.0 for i in range(DIMENSIONS)]


@pytest.fixture
def unit_vector():
    """make_unit_vector, for the tests (a fixture, because tests don't import conftest)."""
    return make_unit_vector


@pytest.fixture(scope="module")
def fake_embeddings(admin_url):
    """Give every claim and note a hand-made embedding, and load 60 hand-made booklet
    sections. Removed again at the end of the test module, so every other test sees
    the database as the setup left it, with no embeddings.

    Every description gets unit vector 0, every note 1, every section 2. A test
    that needs a clear best match points one row somewhere else.
    """
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("update insurance.claims set embedding = %s", [str(make_unit_vector(0))])
        conn.execute("update insurance.claim_notes set embedding = %s", [str(make_unit_vector(1))])
        levels = ["liability", "liability_collision", "full"]
        conn.cursor().executemany(
            "insert into insurance.policy_document_chunks"
            " (coverage_level, heading, content, embedding) values (%s, %s, %s, %s)",
            [
                (levels[i % 3], f"Section {i}", f"Text of section {i}.", str(make_unit_vector(2)))
                for i in range(60)
            ],
        )
        yield
        conn.execute("update insurance.claims set embedding = null")
        conn.execute("update insurance.claim_notes set embedding = null")
        conn.execute("delete from insurance.policy_document_chunks")
