"""Row-level security through the server: the token's name decides which customers it sees.

The tokens are in conftest.py. local sees every state, and claude, copilot and
inspector each see TX and CO plus one state of their own (sql/060_row_security.sql).
"""

import pytest

from insurance_mcp.db import call_function, connection_pool

from .conftest import CLAUDE_TOKEN, COPILOT_TOKEN, LOCAL_TOKEN, connect

pytestmark = pytest.mark.anyio

# A token whose name has no rows in insurance.caller_states.
NOBODY_TOKEN = "nobody-test-token-0123456789abcdefghijk"


def an_oklahoma_customer(admin) -> str:
    """A customer in Oklahoma, which claude sees and copilot doesn't, whose name
    matches nobody in another state."""
    return admin.execute(
        """
        select cu.first_name || ' ' || cu.last_name from insurance.customers as cu
        where cu.state = 'OK'
          and not exists (
              select from insurance.customers as other
              where other.state <> 'OK'
                and other.first_name || ' ' || other.last_name
                    ilike '%%' || cu.first_name || ' ' || cu.last_name || '%%'
          )
        order by cu.last_name, cu.first_name
        limit 1
        """
    ).fetchone()[0]


async def find_customers(settings, token: str, name: str) -> list[dict]:
    async with connect(settings, token=token) as client:
        result = await client.call_tool("find_customers", {"name": name})
    assert not result.is_error, result.content[0].text
    return result.structured_content["result"]


async def test_two_tokens_get_different_answers_to_the_same_question(settings, admin):
    name = an_oklahoma_customer(admin)

    assert await find_customers(settings, CLAUDE_TOKEN, name)
    assert await find_customers(settings, COPILOT_TOKEN, name) == []
    assert await find_customers(settings, LOCAL_TOKEN, name)


async def test_every_token_finds_maria_garcia(settings):
    for token in (LOCAL_TOKEN, CLAUDE_TOKEN, COPILOT_TOKEN):
        assert len(await find_customers(settings, token, "Maria Garcia")) == 1


async def test_another_states_claim_is_unknown(settings, admin):
    (claim_number,) = admin.execute(
        """
        select c.claim_number from insurance.claims as c
        join insurance.policies as p on p.id = c.policy_id
        join insurance.customers as cu on cu.id = p.customer_id
        where cu.state = 'OK'
        order by c.claim_number limit 1
        """
    ).fetchone()

    async with connect(settings, token=COPILOT_TOKEN) as client:
        result = await client.call_tool("get_claim", {"claim_number": claim_number})

    assert result.is_error
    assert "Unknown claim number" in result.content[0].text


async def test_a_token_with_no_states_gets_empty_answers_not_errors(settings):
    settings.mcp_tokens["nobody"] = NOBODY_TOKEN

    assert await find_customers(settings, NOBODY_TOKEN, "Maria Garcia") == []


async def test_a_call_leaves_no_caller_key_on_its_connection(reader_url):
    # Every call sets its own key first, so a leftover key would only matter if
    # some future code path forgot to. That's why the key is set with true (for
    # this transaction only): the connection goes back to the pool with no key.
    async with connection_pool(reader_url, max_size=1) as pool:
        await call_function(pool, "local", "get_dataset_info", {})
        async with pool.connection() as conn:
            cursor = await conn.execute("select current_setting('mcp.caller_key', true) as key")
            leftover = await cursor.fetchone()

    assert leftover == {"key": ""}
