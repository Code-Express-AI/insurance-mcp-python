"""Run a tool's database function and record the call in the audit log. Fail closed.

Every tool call goes through audited_call, so every call gets exactly one
audit row, including calls that fail. If the audit row can't be written, the
result isn't returned: no audit, no answer.
"""

import json
import logging
import time
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from psycopg import errors
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from insurance_mcp.db import call_function

logger = logging.getLogger(__name__)

# What the model gets for anything unexpected. The details go to the server log only.
GENERIC_ERROR = "The database could not complete this request."


async def audited_call(
    pool: AsyncConnectionPool,
    caller: str,
    function: str,
    arguments: dict[str, Any],
    audit_arguments: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run mcp.<function>, write its audit row, and return its rows.

    Each mcp function has the same name as its tool, so `function` is also the
    tool name in the audit log. The audit row records `arguments`, unless
    `audit_arguments` is given: the RAG tools pass the question there, rather
    than the 384 numbers the function gets.
    """
    started = time.perf_counter()
    rows = None
    error = None
    try:
        rows = await call_function(pool, caller, function, arguments)
    except errors.RaiseException as exception:
        # SQLSTATE P0001: RAISE EXCEPTION in one of our own functions, such as
        # "Unknown policy number...". The message is written for the model, so it's
        # safe to pass on. Only the message: its context line names our functions.
        error = exception.diag.message_primary
    except Exception:
        # Anything else: a bug, the database is down, a timeout. The full error
        # and stack trace go to the server log, and the model gets the generic message.
        logger.exception("The database call for %s failed", function)
        error = GENERIC_ERROR
    duration_ms = round((time.perf_counter() - started) * 1000)

    try:
        await call_function(
            pool,
            caller,
            "write_audit",
            {
                "caller": caller,
                "tool_name": function,
                # default=str: UUIDs and dates are written as text.
                "arguments": Jsonb(
                    arguments if audit_arguments is None else audit_arguments,
                    dumps=lambda value: json.dumps(value, default=str),
                ),
                "rows_returned": len(rows) if rows is not None else None,
                "duration_ms": duration_ms,
                "succeeded": error is None,
                "error": error,
            },
        )
    except Exception:
        logger.exception("Could not write the audit row for %s, so no result is returned", function)
        raise ToolError(GENERIC_ERROR) from None

    if error is not None:
        raise ToolError(error)
    return rows
