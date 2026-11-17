"""The connection pool, and the one helper that calls a database function."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def connection_pool(database_url: str, max_size: int) -> AsyncGenerator[AsyncConnectionPool]:
    """Open a pool of connections as mcp_reader, and close it at the end.

    autocommit: nothing stays open between calls. Each call opens its own short
    transaction (call_function, below).
    dict_row: rows come back as dictionaries, ready to return as JSON.
    timeout: a call waits at most 5 seconds for a free connection.
    configure: money (numeric) comes back as float, not Decimal (below).

    It waits for the first connection, so the server refuses to start, with the
    connection error in the log, if the database isn't running or the password is wrong.
    """
    pool = AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=max_size,
        timeout=5,
        kwargs={"autocommit": True, "row_factory": dict_row},
        configure=load_numbers_as_float,
        open=False,
    )
    await pool.open(wait=True, timeout=10)
    try:
        yield pool
    finally:
        await pool.close()


async def load_numbers_as_float(conn: AsyncConnection) -> None:
    """Read numeric columns, such as money, as float rather than Decimal.

    The SDK writes a Decimal into JSON as a string ("500.00"), but money inside
    a jsonb list arrives as a number. As floats, every amount reaches the model
    as a JSON number. The values are only displayed, never added up in Python,
    so float's rounding doesn't matter here. The database still stores numeric.
    """
    conn.adapters.register_loader("numeric", FloatLoader)


async def call_function(
    pool: AsyncConnectionPool, caller: str, name: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run one function in the mcp schema, as `caller`, and return its rows.

    call_function(pool, "copilot", "find_customers", {"name": "Smith"}) runs
        select set_config('mcp.caller_key', %s, true)
        select * from mcp.find_customers(p_name => %s)
    in one transaction, with "copilot" and "Smith" passed separately as
    parameters, never put into the SQL text.

    The first line tells the database who's calling, so row-level security
    (sql/06_row_security.sql) returns only that caller's rows. true: the setting
    ends with the transaction, so the next caller to borrow this connection
    starts with no key, and sees nothing until it sets its own.

    `name` and the argument names are always fixed strings in our code, never
    taken from a request. sql.Identifier quotes them anyway.
    """
    named_arguments = sql.SQL(", ").join(
        sql.SQL("{} => {}").format(sql.Identifier(f"p_{key}"), sql.Placeholder())
        for key in arguments
    )
    query = sql.SQL("select * from mcp.{}({})").format(sql.Identifier(name), named_arguments)

    async with pool.connection() as conn, conn.transaction():
        await conn.execute("select set_config('mcp.caller_key', %s, true)", [caller])
        cursor = await conn.execute(query, list(arguments.values()))
        return await cursor.fetchall()
