"""The tools, end to end through the MCP protocol: results, audit rows and errors."""

import datetime
import logging

import pytest

from insurance_mcp.audit import GENERIC_ERROR
from insurance_mcp.tools import INSTRUCTIONS

from .conftest import connect

pytestmark = pytest.mark.anyio


def latest_audit_row(admin) -> dict:
    cursor = admin.execute(
        "select caller, tool_name, arguments, rows_returned, succeeded, error"
        " from insurance.audit_log order by id desc limit 1"
    )
    return dict(zip([column.name for column in cursor.description], cursor.fetchone(), strict=True))


def audit_row_count(admin) -> int:
    return admin.execute("select count(*) from insurance.audit_log").fetchone()[0]


def text_of(result) -> str:
    return result.content[0].text


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_get_dataset_info_works_with_both_protocol_versions(settings, admin, mode):
    async with connect(settings, mode) as client:
        result = await client.call_tool("get_dataset_info", {})

    assert not result.is_error
    assert '"as_of_date": "2026-12-31"' in text_of(result)
    customers = admin.execute("select count(*) from insurance.customers").fetchone()[0]
    assert f'"customer_count": {customers}' in text_of(result)


async def test_every_tool_call_writes_one_audit_row_with_the_caller(settings, admin):
    before = audit_row_count(admin)
    async with connect(settings) as client:
        await client.call_tool("get_dataset_info", {})

    assert audit_row_count(admin) == before + 1
    assert latest_audit_row(admin) == {
        "caller": "claude-code",
        "tool_name": "get_dataset_info",
        "arguments": {},
        "rows_returned": 1,
        "succeeded": True,
        "error": None,
    }


async def test_every_tool_is_marked_read_only(settings):
    async with connect(settings) as client:
        tools = (await client.list_tools()).tools

    assert tools
    assert all(tool.annotations.read_only_hint for tool in tools)


async def test_every_tool_and_argument_has_a_description(settings):
    async with connect(settings) as client:
        tools = (await client.list_tools()).tools

    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        for name, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}({name}) has no description"


async def test_the_server_instructions_are_sent_and_their_date_matches_the_data(settings, reader):
    async with connect(settings) as client:
        assert client.instructions == INSTRUCTIONS

    as_of = reader.execute("select as_of_date from mcp.get_dataset_info()").fetchone()[0]
    assert as_of == datetime.date(2026, 12, 31)
    assert f"The data ends on {as_of.isoformat()}." in INSTRUCTIONS


async def test_an_unknown_tool_is_a_tool_error(settings):
    async with connect(settings) as client:
        result = await client.call_tool("drop_tables", {})

    assert result.is_error
    assert text_of(result) == "Unknown tool: drop_tables"


async def test_an_unknown_argument_is_rejected_and_the_database_is_never_called(settings, admin):
    before = audit_row_count(admin)
    async with connect(settings) as client:
        result = await client.call_tool("get_dataset_info", {"customer_name": "Rutherford"})

    assert result.is_error
    assert text_of(result) == (
        "Unknown argument: customer_name. get_dataset_info takes: no arguments."
    )
    assert audit_row_count(admin) == before


def revoke_from_reader(admin, function: str) -> None:
    admin.execute(
        f"set role mcp_owner; revoke execute on function {function} from mcp_reader; reset role"
    )


def grant_to_reader(admin, function: str) -> None:
    admin.execute(
        f"set role mcp_owner; grant execute on function {function} to mcp_reader; reset role"
    )


async def test_a_database_error_reaches_the_caller_as_the_generic_message_only(settings, admin):
    # mcp_reader loses the right to run the function, so PostgreSQL raises
    # "permission denied for function get_dataset_info".
    revoke_from_reader(admin, "mcp.get_dataset_info()")
    try:
        async with connect(settings) as client:
            result = await client.call_tool("get_dataset_info", {})
    finally:
        grant_to_reader(admin, "mcp.get_dataset_info()")

    assert result.is_error
    assert text_of(result) == f"Error executing tool get_dataset_info: {GENERIC_ERROR}"
    # The failed call is audited too, with the short error only.
    row = latest_audit_row(admin)
    assert (row["tool_name"], row["succeeded"], row["error"]) == (
        "get_dataset_info",
        False,
        GENERIC_ERROR,
    )


WRITE_AUDIT = "mcp.write_audit(text, text, jsonb, integer, integer, boolean, text)"


async def test_if_the_audit_row_cannot_be_written_the_result_is_not_returned(settings, admin):
    revoke_from_reader(admin, WRITE_AUDIT)
    try:
        async with connect(settings) as client:
            result = await client.call_tool("get_dataset_info", {})
    finally:
        grant_to_reader(admin, WRITE_AUDIT)

    assert result.is_error
    assert text_of(result) == f"Error executing tool get_dataset_info: {GENERIC_ERROR}"
    assert "as_of_date" not in text_of(result)


async def test_the_log_has_no_tool_arguments_or_results(settings, caplog):
    caplog.set_level(logging.DEBUG)
    async with connect(settings) as client:
        await client.call_tool("get_dataset_info", {})
        await client.call_tool("get_dataset_info", {"customer_name": "Rutherford"})

    # Only the server's log lines: the test's own MCP client logs what it sends at DEBUG.
    server_log = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("mcp.client", "httpx2"))
    )
    assert "as_of_date" not in server_log
    assert "2026-12-31" not in server_log
    assert "Rutherford" not in server_log
    # The rejected argument is logged with the caller, tool and argument name.
    assert (
        "Rejected argument: caller=claude-code tool=get_dataset_info argument='customer_name'"
        in server_log
    )
