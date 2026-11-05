"""The connection pool, and the one helper that calls a database function."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def connection_pool(database_url: str, max_size: int) -> AsyncIterator[AsyncConnectionPool]:
    """Open a pool of connections as mcp_reader, and close it at the end.

    autocommit: every call is one statement, so there's no transaction to keep open.
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
    pool: AsyncConnectionPool, name: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run one function in the mcp schema and return its rows.

    call_function(pool, "find_customers", {"name": "Smith"}) runs
        select * from mcp.find_customers(p_name => %s)
    with "Smith" passed separately as a parameter, never put into the SQL text.

    `name` and the argument names are always fixed strings in our code, never
    taken from a request. sql.Identifier quotes them anyway.
    """
    named_arguments = sql.SQL(", ").join(
        sql.SQL("{} => {}").format(sql.Identifier(f"p_{key}"), sql.Placeholder())
        for key in arguments
    )
    query = sql.SQL("select * from mcp.{}({})").format(sql.Identifier(name), named_arguments)

    async with pool.connection() as conn:
        cursor = await conn.execute(query, list(arguments.values()))
        return await cursor.fetchall()
