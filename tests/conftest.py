"""Shared test setup: one throwaway PostgreSQL container for the whole test run."""

import os
import re
from pathlib import Path

import docker
import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

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
    needs superuser rights.
    """
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        conn.execute(f"create role app_admin login createrole password '{ADMIN_PASSWORD}'")
        conn.execute("create database insurance owner app_admin")

    url = connection_url(postgres, "app_admin", ADMIN_PASSWORD, "insurance")
    setup_database(url, reader_url_for(postgres), size="small")
    return url


def reader_url_for(postgres) -> str:
    return connection_url(postgres, "mcp_reader", READER_PASSWORD, "insurance")


@pytest.fixture(scope="session")
def reader_url(postgres, admin_url) -> str:
    """The mcp_reader connection string. Depends on admin_url, so the setup has run."""
    return reader_url_for(postgres)


@pytest.fixture
def admin(admin_url):
    """A connection as the admin role. Each statement commits on its own."""
    with psycopg.connect(admin_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def reader(reader_url):
    """A connection as mcp_reader, the role the MCP server uses."""
    with psycopg.connect(reader_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def anyio_backend() -> str:
    """The async tests (marked anyio) run on asyncio, like the server."""
    return "asyncio"
