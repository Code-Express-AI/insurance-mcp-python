"""Shared setup for the server tests: settings, and a server running inside the test.

The server runs in the test process, with no network port. httpx2 (the HTTP
client the MCP SDK uses) sends requests straight to the app, and the SDK's own
Client talks to it through httpx2, so tool calls go through the real MCP
protocol and every check in the request path.
"""

from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from insurance_mcp.main import create_app
from insurance_mcp.settings import Settings

# local sees every state, and is what the tests use unless they say otherwise.
# The other three see part of the data (sql/06_row_security.sql).
LOCAL_TOKEN = "local-test-token-0123456789abcdefghijklm"
CLAUDE_TOKEN = "claude-test-token-0123456789abcdefghijk"
COPILOT_TOKEN = "copilot-test-token-0123456789abcdefghij"
INSPECTOR_TOKEN = "inspector-test-token-0123456789abcdefgh"
TOKENS = (
    f"local:{LOCAL_TOKEN},claude:{CLAUDE_TOKEN},copilot:{COPILOT_TOKEN},inspector:{INSPECTOR_TOKEN}"
)

BASE_URL = "http://localhost:8000"
MCP_URL = f"{BASE_URL}/mcp"

# What an MCP client sends with every POST.
MCP_HEADERS = {
    "Authorization": f"Bearer {LOCAL_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# A minimal valid MCP request: list the tools, in the 2026-07-28 protocol.
LIST_TOOLS = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
}


@pytest.fixture
def settings(reader_url) -> Settings:
    """The server's settings for the tests. _env_file=None: your own .env is never read."""
    return Settings(_env_file=None, reader_database_url=reader_url, mcp_tokens=TOKENS)


@asynccontextmanager
async def serve(settings: Settings, token: str | None = LOCAL_TOKEN):
    """Start a new app, and yield an HTTP client that sends requests to it."""
    app = create_app(settings)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url=BASE_URL, headers=headers
        ) as http:
            yield http


@asynccontextmanager
async def connect(settings: Settings, mode: str = "auto", token: str = LOCAL_TOKEN):
    """Start a new app, and yield an MCP client connected to it.

    mode="auto" uses the 2026-07-28 protocol, mode="legacy" the older one with
    the connection handshake.
    """
    async with serve(settings, token) as http:
        async with Client(streamable_http_client(MCP_URL, http_client=http), mode=mode) as client:
            yield client
