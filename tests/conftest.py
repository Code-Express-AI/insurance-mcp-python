"""Shared test setup: a throwaway PostgreSQL container for the whole test run."""

import os
import re
from pathlib import Path

import docker
import pytest
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).parent.parent


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


@pytest.fixture(scope="session")
def admin_url(postgres) -> str:
    """The container's admin connection string, in the plain postgresql:// form psycopg uses."""
    return postgres.get_connection_url()
