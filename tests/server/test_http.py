"""The HTTP checks in front of the tools: token, rate limits, host, size and format."""

import json
import logging

import pytest

from insurance_mcp import main as main_module
from insurance_mcp.main import reject

from .conftest import COPILOT_TOKEN, LIST_TOOLS, LOCAL_TOKEN, MCP_HEADERS, serve

pytestmark = pytest.mark.anyio


async def post(http, body, headers=None, **kwargs):
    """POST to /mcp the way an MCP client does, with any header changed."""
    return await http.post(
        "/mcp", content=body, headers={**MCP_HEADERS, **(headers or {})}, **kwargs
    )


# Health ---------------------------------------------------------------------------


async def test_health_needs_no_token_and_says_nothing_about_the_database(settings):
    async with serve(settings, token=None) as http:
        response = await http.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Token ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer wrong-token-0123456789abcdefghijklmnop",
        f"Token {LOCAL_TOKEN}",
        "Bearer",
        LOCAL_TOKEN,
    ],
    ids=["missing", "wrong", "wrong-scheme", "no-token", "no-scheme"],
)
async def test_a_request_without_a_valid_token_gets_401(settings, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    async with serve(settings, token=None) as http:
        response = await http.post("/mcp", json=LIST_TOOLS, headers=headers)

    assert response.status_code == 401


async def test_a_valid_token_gets_through(settings):
    async with serve(settings) as http:
        response = await post(http, json.dumps(LIST_TOOLS))

    assert response.status_code == 200
    assert "get_dataset_info" in response.text


async def test_tokens_never_appear_in_the_log(settings, caplog):
    caplog.set_level(logging.DEBUG)
    wrong = "wrong-token-0123456789abcdefghijklmnop"
    async with serve(settings) as http:
        await post(http, json.dumps(LIST_TOOLS))
        await post(http, json.dumps(LIST_TOOLS), {"Authorization": f"Bearer {wrong}"})

    assert "Rejected request: status=401" in caplog.text
    assert LOCAL_TOKEN not in caplog.text
    assert wrong not in caplog.text


def test_an_address_with_spaces_cant_forge_fields_in_the_log(caplog):
    # Behind a proxy, the address comes from a header the client writes.
    reject(401, "Missing or invalid bearer token.", "10.0.0.1 status=200 caller=copilot")

    assert "ip='10.0.0.1 status=200 caller=copilot'" in caplog.text


def test_the_server_ignores_x_forwarded_for(settings, monkeypatch):
    # uvicorn would otherwise take the client's address from X-Forwarded-For on
    # any request from 127.0.0.1, and a fake address per request dodges the
    # bad-token limit. These tests call the app directly, so they check the
    # setting main() passes to uvicorn.
    passed = {}
    monkeypatch.setattr(main_module, "Settings", lambda: settings)
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, **options: passed.update(options))
    main_module.main()

    assert passed["proxy_headers"] is False


# Rate limits ----------------------------------------------------------------------


async def test_the_call_after_the_per_minute_limit_gets_429_and_others_are_unaffected(settings):
    settings = settings.model_copy(update={"rate_limit_per_minute": 3})
    async with serve(settings) as http:
        statuses = [(await post(http, json.dumps(LIST_TOOLS))).status_code for _ in range(4)]
        limited = await post(http, json.dumps(LIST_TOOLS))
        copilot = await post(
            http, json.dumps(LIST_TOOLS), {"Authorization": f"Bearer {COPILOT_TOKEN}"}
        )

    assert statuses == [200, 200, 200, 429]
    assert int(limited.headers["Retry-After"]) > 0
    assert copilot.status_code == 200


async def test_the_11th_bad_token_in_a_minute_from_one_address_gets_429(settings):
    bad = {"Authorization": "Bearer wrong-token-0123456789abcdefghijklmnop"}
    async with serve(settings) as http:
        statuses = [(await post(http, json.dumps(LIST_TOOLS), bad)).status_code for _ in range(11)]

    assert statuses == [401] * 10 + [429]


# Host and origin (the SDK's checks) -------------------------------------------------


async def test_an_unexpected_host_gets_421(settings):
    async with serve(settings) as http:
        response = await post(http, json.dumps(LIST_TOOLS), {"Host": "evil.example.com"})

    assert response.status_code == 421


async def test_a_browser_origin_gets_403(settings):
    async with serve(settings) as http:
        response = await post(http, json.dumps(LIST_TOOLS), {"Origin": "http://evil.example.com"})

    assert response.status_code == 403


async def test_a_bad_host_without_a_token_gets_401_because_the_token_check_is_first(settings):
    async with serve(settings, token=None) as http:
        response = await http.post("/mcp", json=LIST_TOOLS, headers={"Host": "evil.example.com"})

    assert response.status_code == 401


# Size and format ------------------------------------------------------------------


async def test_a_body_over_64_kb_gets_413_with_a_content_length(settings):
    body = json.dumps({**LIST_TOOLS, "padding": "x" * 70_000})
    async with serve(settings) as http:
        response = await post(http, body)

    assert response.status_code == 413


async def test_a_body_over_64_kb_gets_413_without_a_content_length(settings):
    async def chunks():
        # Sent in pieces, so there's no Content-Length header: the size is
        # counted as the bytes arrive.
        for _ in range(70):
            yield b"x" * 1024

    async with serve(settings) as http:
        response = await post(http, chunks())

    assert "content-length" not in response.request.headers
    assert response.status_code == 413


async def test_a_json_rpc_batch_gets_400_and_no_tool_runs(settings):
    call = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "get_dataset_info"}}
    batch = [{**call, "id": 1}, {**call, "id": 2}]
    async with serve(settings) as http:
        response = await post(http, json.dumps(batch))

    assert response.status_code == 400
    assert "as_of_date" not in response.text


async def test_deeply_nested_json_gets_400_without_crashing_the_server(settings):
    nested = '{"a":' * 10_000 + "1" + "}" * 10_000
    async with serve(settings) as http:
        response = await post(http, nested)
        after = await post(http, json.dumps(LIST_TOOLS))

    assert response.status_code == 400
    assert after.status_code == 200


async def test_invalid_json_gets_400(settings):
    async with serve(settings) as http:
        response = await post(http, "{not json")

    assert response.status_code == 400


# Event stream -------------------------------------------------------------------


async def test_a_get_for_an_event_stream_gets_405_instead_of_a_stream_left_open(settings):
    async with serve(settings) as http:
        response = await http.get("/mcp", headers={"Accept": "text/event-stream"})

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


async def test_a_get_without_a_token_still_gets_401(settings):
    async with serve(settings, token=None) as http:
        response = await http.get("/mcp", headers={"Accept": "text/event-stream"})

    assert response.status_code == 401


# CORS -----------------------------------------------------------------------------


async def test_no_response_carries_a_cors_header(settings):
    origin = {"Origin": "http://evil.example.com"}
    async with serve(settings) as http:
        responses = [
            await http.get("/health", headers=origin),
            await post(http, json.dumps(LIST_TOOLS)),
            await post(http, json.dumps(LIST_TOOLS), origin),
            await post(http, json.dumps(LIST_TOOLS), {"Authorization": "Bearer wrong"}),
            await http.options("/mcp", headers={**origin, "Access-Control-Request-Method": "POST"}),
        ]

    for response in responses:
        assert "access-control-allow-origin" not in response.headers
