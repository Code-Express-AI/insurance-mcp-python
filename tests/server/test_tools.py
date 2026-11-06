"""The tools, end to end through the MCP protocol: results, audit rows and errors."""

import datetime
import logging

import pytest

from insurance_mcp.audit import GENERIC_ERROR
from insurance_mcp.tools import INSTRUCTIONS, TOOL_ARGUMENTS

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
        await client.call_tool("find_customers", {"name": "Rutherford"})
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
    assert "Eleanor" not in server_log
    # The rejected argument is logged with the caller, tool and argument name.
    assert (
        "Rejected argument: caller=claude-code tool=get_dataset_info argument='customer_name'"
        in server_log
    )


# Every tool, end to end ------------------------------------------------------------

# One real call per tool, with the arguments a model would send for a demo question.
# get_customer needs an id from find_customers, so it has its own test below.
TOOL_CALLS = [
    ("get_dataset_info", {}),
    ("find_customers", {"name": "Rutherford"}),
    ("get_policy", {"policy_number": "AUT-104233"}),
    ("search_claims", {"status": "open", "min_reserve": 20000, "min_days_open": 91}),
    ("get_claim", {"claim_number": "CLM-1049306"}),
    ("count_claims_by_month", {"period": "last_3_months", "claim_type": "glass"}),
    ("get_repair_shop_costs", {"period": "last_12_months"}),
    ("get_adjuster_workload", {}),
    ("count_claims_by_driver_age", {"period": "this_year", "fault": "at_fault"}),
]


# The RAG tools need embeddings, so their end-to-end tests are in test_rag_tools.py.
RAG_TOOLS = {"search_claim_text", "find_similar_claims", "search_policy_wording"}


def test_every_tool_has_an_end_to_end_test():
    assert {name for name, _ in TOOL_CALLS} | {"get_customer"} | RAG_TOOLS == set(TOOL_ARGUMENTS)


@pytest.mark.parametrize(("tool", "arguments"), TOOL_CALLS, ids=[name for name, _ in TOOL_CALLS])
async def test_every_tool_works_end_to_end_and_is_audited(settings, admin, tool, arguments):
    async with connect(settings) as client:
        result = await client.call_tool(tool, arguments)

    assert not result.is_error, text_of(result)
    assert result.structured_content
    row = latest_audit_row(admin)
    assert (row["tool_name"], row["succeeded"], row["caller"]) == (tool, True, "claude-code")


async def test_get_customer_takes_the_customer_id_from_find_customers(settings):
    async with connect(settings) as client:
        found = await client.call_tool("find_customers", {"name": "Rutherford"})
        customer_id = found.structured_content["result"][0]["customer_id"]
        result = await client.call_tool("get_customer", {"customer_id": customer_id})

    assert not result.is_error
    assert result.structured_content["last_name"] == "Rutherford"
    assert len(result.structured_content["policies"]) == 2


async def test_money_reaches_the_model_as_json_numbers(settings):
    async with connect(settings) as client:
        policy = await client.call_tool("get_policy", {"policy_number": "AUT-104233"})
        claim = await client.call_tool("get_claim", {"claim_number": "CLM-1037552"})

    # Not "500.00": the SDK writes a Decimal as a string (db.load_numbers_as_float).
    assert policy.structured_content["deductible"] == 500
    assert '"deductible": 500.0' in text_of(policy)
    assert isinstance(claim.structured_content["total_paid"], float)


async def test_spaces_around_a_search_are_trimmed(settings, admin):
    async with connect(settings) as client:
        result = await client.call_tool("find_customers", {"name": "  Rutherford  "})

    assert len(result.structured_content["result"]) == 1
    assert latest_audit_row(admin)["arguments"] == {"name": "Rutherford"}


async def test_an_unknown_number_gets_the_functions_message_and_is_audited(settings, admin):
    async with connect(settings) as client:
        result = await client.call_tool("get_policy", {"policy_number": "AUT-999999"})

    message = "Unknown policy number. Use find_customers, then get_customer, to find it."
    assert result.is_error
    # Only the message: never the context line, which names our functions.
    assert text_of(result) == f"Error executing tool get_policy: {message}"
    row = latest_audit_row(admin)
    assert (row["succeeded"], row["rows_returned"], row["error"]) == (False, None, message)


async def test_a_search_that_finds_nothing_is_an_empty_list_not_an_error(settings):
    async with connect(settings) as client:
        result = await client.call_tool("find_customers", {"name": "Zzyzx"})

    assert not result.is_error
    assert result.structured_content == {"result": []}


# Input limits: rejected before the database is called ---------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "argument", "expected"),
    [
        pytest.param(
            "find_customers", {"name": "x" * 101}, "name", "at most 100 characters", id="too-long"
        ),
        pytest.param(
            "find_customers",
            {"name": "Ma\x00ria"},
            "name",
            "must not contain a null byte",
            id="null-byte",
        ),
        pytest.param(
            "find_customers", {"name": "   "}, "name", "at least 2 characters", id="blank"
        ),
        pytest.param(
            "get_policy",
            {"policy_number": "AUT-12"},
            "policy_number",
            "should match pattern",
            id="bad-policy-number",
        ),
        pytest.param(
            "get_policy",
            {"policy_number": "AUT-104233\x00"},
            "policy_number",
            "should match pattern",
            id="null-byte-in-policy-number",
        ),
        pytest.param(
            "get_claim",
            {"claim_number": "CLM-104930"},
            "claim_number",
            "should match pattern",
            id="bad-claim-number",
        ),
        pytest.param(
            "get_customer",
            {"customer_id": "not-a-uuid"},
            "customer_id",
            "valid UUID",
            id="bad-uuid",
        ),
        pytest.param(
            "search_claims", {"page": 21}, "page", "less than or equal to 20", id="page-too-high"
        ),
        pytest.param(
            "search_claims",
            {"min_reserve": -1},
            "min_reserve",
            "greater than or equal to 0",
            id="negative-reserve",
        ),
        pytest.param(
            "search_claims",
            {"status": "approved"},
            "status",
            "'open', 'settled', 'denied' or 'withdrawn'",
            id="unknown-status",
        ),
        pytest.param("count_claims_by_month", {}, "period", "Field required", id="missing-period"),
        pytest.param(
            "get_repair_shop_costs",
            {"period": "this_year", "limit": 21},
            "limit",
            "less than or equal to 20",
            id="limit-too-high",
        ),
        pytest.param(
            "search_claim_text",
            {"query": "x" * 501},
            "query",
            "at most 500 characters",
            id="rag-query-too-long",
        ),
        pytest.param(
            "search_claim_text",
            {"query": "parked\x00"},
            "query",
            "must not contain a null byte",
            id="null-byte-in-rag-query",
        ),
        pytest.param(
            "search_claim_text",
            {"query": "parked", "search_in": "both"},
            "search_in",
            "'descriptions' or 'notes'",
            id="unknown-search-in",
        ),
        pytest.param(
            "find_similar_claims",
            {"claim_number": "CLM-1037552", "limit": 51},
            "limit",
            "less than or equal to 50",
            id="rag-limit-too-high",
        ),
        pytest.param(
            "search_policy_wording",
            {"query": "flood", "coverage_level": "comprehensive"},
            "coverage_level",
            "'liability', 'liability_collision' or 'full'",
            id="unknown-coverage-level",
        ),
    ],
)
async def test_a_bad_argument_is_a_tool_error_and_the_database_is_never_called(
    settings, admin, tool, arguments, argument, expected
):
    before = audit_row_count(admin)
    async with connect(settings) as client:
        result = await client.call_tool(tool, arguments)

    assert result.is_error
    # The SDK's message names the argument and the rule it broke.
    assert f"\n{argument}\n" in text_of(result)
    assert expected in text_of(result)
    assert audit_row_count(admin) == before


async def test_a_rejected_value_is_logged_without_the_value(settings, caplog):
    caplog.set_level(logging.INFO)
    async with connect(settings) as client:
        await client.call_tool("find_customers", {"name": "Rutherford" * 20})

    server_log = "\n".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("mcp.client", "httpx2"))
    )
    assert "Tool 'find_customers' rejected arguments: ['name']" in server_log
    assert "Rutherford" not in server_log
