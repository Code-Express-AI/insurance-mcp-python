"""Builds the FastAPI app: the token check, the rate limits, /health and the MCP endpoint.

Run the server with:  uv run python -m insurance_mcp.main

Every request to /mcp passes these checks in order:
  1. Token      our middleware below: 401 without a valid named token.
  2. Rate limit our middleware below: 429 if this caller made too many calls.
  3. Host       the MCP SDK: 421 for an unexpected Host, 403 for a browser Origin.
  4. Size       the MCP SDK: 413 for a body over 64 KB.
  5. Arguments  the MCP SDK and tools.py: a tool error the model can act on.
  6. Database   the tool runs one mcp function as mcp_reader (tools.py).
  7. Audit      the call is recorded, or no result is returned (audit.py).
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from insurance_mcp.auth import caller_for
from insurance_mcp.db import connection_pool
from insurance_mcp.rate_limit import RateLimiter
from insurance_mcp.settings import Settings
from insurance_mcp.tools import create_mcp_server

# Named in full: run with python -m, this module's __name__ would be "__main__".
logger = logging.getLogger("insurance_mcp.main")

MAX_REQUEST_BODY_SIZE = 64 * 1024
FAILED_TOKENS_PER_MINUTE = 10


def create_app(settings: Settings | None = None) -> FastAPI:
    """A new app. The tests build one each, with their own settings."""
    settings = settings or Settings()

    @asynccontextmanager
    async def open_database(server):
        """The MCP server's lifespan: the tools get this pool as their lifespan context."""
        async with connection_pool(settings.reader_database_url, settings.db_pool_max_size) as pool:
            yield pool

    mcp = create_mcp_server(lifespan=open_database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Starts the SDK's request handling, which opens the pool above.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    per_minute = RateLimiter(settings.rate_limit_per_minute, window_seconds=60)
    failed_tokens = RateLimiter(FAILED_TOKENS_PER_MINUTE, window_seconds=60)

    @app.middleware("http")
    async def check_token_and_rate_limit(request: Request, call_next):
        """Steps 1 and 2. Everything except /health needs a token."""
        if request.url.path == "/health":
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        caller = caller_for(request.headers.get("authorization"), settings.mcp_tokens)

        if caller is None:
            # Never log the token, not even a wrong one.
            if wait := failed_tokens.hit(ip):
                return reject(429, "Too many requests with a bad token.", ip, retry_after=wait)
            return reject(401, "Missing or invalid bearer token.", ip)

        if wait := per_minute.hit(caller):
            return reject(429, "Rate limit reached.", ip, caller, retry_after=wait)

        # The tools read the caller's name from here, for the audit log.
        request.state.caller = caller
        return await call_next(request)

    @app.get("/health")
    async def health():
        """For Docker and hosting checks. No token, and nothing about the database."""
        return {"status": "ok"}

    # The SDK checks Host and Origin (DNS rebinding protection). The Host header
    # includes the port, hence localhost:*. No browser origin is allowed: the AI
    # clients aren't web pages, so they don't send one.
    hosts = settings.allowed_hosts + [f"{host}:*" for host in settings.allowed_hosts]
    app.mount(
        "/",
        mcp.streamable_http_app(
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]),
            max_request_body_size=MAX_REQUEST_BODY_SIZE,
        ),
    )
    return app


def reject(
    status: int, message: str, ip: str, caller: str | None = None, retry_after: int | None = None
) -> JSONResponse:
    """Log a rejected request (never its token) and answer it."""
    # %r puts quotes around the address, so a value with spaces in it can't
    # pass itself off as more fields on the line.
    logger.warning("Rejected request: status=%s caller=%s ip=%r", status, caller, ip)
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
    # The SDK logs "Terminating session: None" for every request from an older
    # client. In stateless mode there's no session, so it's only noise.
    logging.getLogger("mcp.server.streamable_http").setLevel(logging.WARNING)
    settings = Settings()
    # uvicorn trusts an X-Forwarded-For header from 127.0.0.1 by default, as if
    # every program on this machine were a proxy. The header is whatever the
    # client writes, so a new fake address per request would dodge the bad-token
    # limit. With no proxy in front, the address the connection comes from is
    # the only one to trust. A hosted server behind a proxy would pass the
    # proxy's address as forwarded_allow_ips instead.
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, proxy_headers=False)


if __name__ == "__main__":
    main()
