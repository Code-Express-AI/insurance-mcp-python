"""The embedding model, used by the embed command and by the server's RAG tools.

An embedding is a list of 384 numbers that stands for the meaning of a text.
The same model must make both the stored embeddings and the embedding of each
question, or the numbers can't be compared. So the model is fixed here, once.
"""

from functools import cache
from pathlib import Path

from fastembed import TextEmbedding
from psycopg.types.numeric import Float4

# A small, fast English model. It reads at most 256 word pieces of each text
# and ignores the rest, so every text we embed is kept shorter than that.
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# A fixed, git-ignored folder at the root of the repo. fastembed's default is
# the system's temp folder, which macOS clears from time to time, and then the
# server would download the model again in the middle of a search.
CACHE_DIR = Path(__file__).parents[3] / ".cache" / "fastembed"


class ModelNotDownloaded(Exception):
    """The server found no model in CACHE_DIR: the embed command hasn't been run."""


def load_model(download: bool = True) -> TextEmbedding:
    """Load the model, downloading it (90 MB) the first time if `download` is True."""
    try:
        return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR), local_files_only=not download)
    except ValueError as error:
        # What fastembed raises when local_files_only is set and the model isn't there.
        raise ModelNotDownloaded from error


@cache
def server_model() -> TextEmbedding:
    """The server's copy of the model, loaded on the first RAG call, then kept.

    The server never downloads it. A download takes a minute or more, far too
    long in the middle of a tool call, so the embed command does it instead.
    If loading fails, nothing is cached, and the next call tries again.
    """
    return load_model(download=False)


def embed_query(text: str) -> list[Float4]:
    """Embed one question for a search. CPU work: the server runs it in a worker thread.

    The numbers are wrapped as Float4 so psycopg sends them as real[], the type
    the mcp functions take. The model makes 32-bit floats, which is what real is.
    """
    embedding = next(server_model().query_embed(text))
    return [Float4(number) for number in embedding]
