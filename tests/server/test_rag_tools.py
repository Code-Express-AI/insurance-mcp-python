"""The RAG tools end to end, with the model replaced by a hand-made embedding.

The real model is checked in tests/rag/test_embedding_model.py.
"""

import threading

import pytest
from psycopg.types.numeric import Float4

from insurance_mcp import embeddings

from .conftest import connect
from .test_tools import RAG_TOOLS, audit_row_count, latest_audit_row, text_of

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_model(monkeypatch, unit_vector):
    """Every question embeds to unit vector 0, the embedding fake_embeddings gives
    every accident description. Records which thread it ran in."""
    threads = []

    def embed_query(text: str) -> list[Float4]:
        threads.append(threading.current_thread())
        return [Float4(number) for number in unit_vector(0)]

    monkeypatch.setattr(embeddings, "embed_query", embed_query)
    return threads


# Before the embed command has run ---------------------------------------------------
# First in the file, before fake_embeddings fills the embeddings (see
# tests/database/test_rag_functions.py).


async def test_without_the_model_a_search_says_run_the_embed_command_first(
    settings, admin, monkeypatch
):
    def model_not_downloaded(text: str):
        raise embeddings.ModelNotDownloaded

    monkeypatch.setattr(embeddings, "embed_query", model_not_downloaded)
    before = audit_row_count(admin)
    async with connect(settings) as client:
        result = await client.call_tool("search_policy_wording", {"query": "Is flood covered?"})

    assert result.is_error
    assert text_of(result) == (
        "Error executing tool search_policy_wording: Run the embed command first."
    )
    # It stopped before the database, so there's no audit row, as for a bad argument.
    assert audit_row_count(admin) == before


async def test_without_embeddings_similar_claims_says_run_the_embed_command_first(settings, admin):
    async with connect(settings) as client:
        result = await client.call_tool("find_similar_claims", {"claim_number": "CLM-1037552"})

    assert result.is_error
    assert text_of(result).endswith("Run the embed command first.")
    assert latest_audit_row(admin)["error"] == "Run the embed command first."


# With embeddings ---------------------------------------------------------------------

RAG_TOOL_CALLS = [
    (
        "search_claim_text",
        {"query": "hit while parked at a supermarket", "status": "open"},
        {
            "query": "hit while parked at a supermarket",
            "search_in": "descriptions",
            "claim_type": None,
            "status": "open",
            "period": None,
            "min_reserve": None,
            "limit": 10,
        },
    ),
    (
        "find_similar_claims",
        {"claim_number": "CLM-1037552"},
        {
            "claim_number": "CLM-1037552",
            "claim_type": None,
            "status": None,
            "period": None,
            "min_reserve": None,
            "limit": 10,
        },
    ),
    (
        "search_policy_wording",
        {"query": "Is flood covered?", "coverage_level": "full"},
        {"query": "Is flood covered?", "coverage_level": "full", "limit": 5},
    ),
]


def test_every_rag_tool_has_an_end_to_end_test():
    assert {name for name, _, _ in RAG_TOOL_CALLS} == RAG_TOOLS


@pytest.mark.parametrize(
    ("tool", "arguments", "audited_arguments"),
    RAG_TOOL_CALLS,
    ids=[name for name, _, _ in RAG_TOOL_CALLS],
)
async def test_every_rag_tool_works_end_to_end_and_audits_the_question_not_the_embedding(
    fake_embeddings, fake_model, settings, admin, tool, arguments, audited_arguments
):
    async with connect(settings) as client:
        result = await client.call_tool(tool, arguments)

    assert not result.is_error, text_of(result)
    assert result.structured_content["result"]
    row = latest_audit_row(admin)
    assert (row["tool_name"], row["succeeded"], row["caller"]) == (tool, True, "local")
    # The question, as the caller wrote it. Never the 384 numbers.
    assert row["arguments"] == audited_arguments


async def test_the_question_is_embedded_in_a_worker_thread(fake_embeddings, fake_model, settings):
    # On the event loop, one search's CPU work would stall every other request.
    async with connect(settings) as client:
        await client.call_tool("search_claim_text", {"query": "hit while parked"})

    assert len(fake_model) == 1
    assert fake_model[0] is not threading.main_thread()


async def test_similar_claims_needs_no_model(fake_embeddings, settings, monkeypatch):
    def no_model(text: str):
        raise AssertionError("find_similar_claims must not use the model")

    monkeypatch.setattr(embeddings, "embed_query", no_model)
    async with connect(settings) as client:
        result = await client.call_tool("find_similar_claims", {"claim_number": "CLM-1037552"})

    assert not result.is_error, text_of(result)
