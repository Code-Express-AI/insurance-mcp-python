"""Embed the text the RAG tools search: the policy booklets, the accident
descriptions and the claim notes.

Run it with:  uv run python -m insurance_mcp.embed

Run it after the setup command. It connects as the admin role, using
ADMIN_DATABASE_URL from .env. The first run downloads the model (90 MB).

It takes minutes and keeps every CPU core busy, so it shows its progress. It's
safe to stop: each batch is saved as soon as it's embedded, and only rows
without an embedding are embedded. Run it again and it carries on.
"""

import sys
import time
from pathlib import Path

import psycopg
from fastembed import TextEmbedding
from psycopg import sql
from pydantic_settings import BaseSettings, SettingsConfigDict

from insurance_mcp.embeddings import load_model

BOOKLETS_DIR = Path(__file__).parent / "booklets"

# Texts per batch: embedded together, then saved together.
BATCH_SIZE = 256


class EmbedSettings(BaseSettings):
    """The one setting the embed command needs, read from .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_database_url: str


# The booklets -----------------------------------------------------------------------


def split_booklet(text: str) -> list[tuple[str, str]]:
    """Split a booklet at its "## " headings, so each section is one chunk about one topic.

    Returns (heading, content) pairs. The title line ("# ...") is left out.
    """
    sections = []
    for part in text.split("\n## ")[1:]:
        heading, _, content = part.partition("\n")
        sections.append((heading.strip(), content.strip()))
    return sections


def load_booklets(conn: psycopg.Connection, model: TextEmbedding) -> None:
    """Split, embed and load the three booklets, in one go. They take a second or two."""
    if conn.execute("select exists (select from insurance.policy_document_chunks)").fetchone()[0]:
        print("Policy booklets:    already loaded")
        return

    chunks = []
    for path in sorted(BOOKLETS_DIR.glob("*.md")):
        # The file name is the coverage level: liability_collision.md -> liability_collision.
        for heading, content in split_booklet(path.read_text(encoding="utf-8")):
            chunks.append((path.stem, heading, content))

    # The heading is embedded with its section: "Hitting an animal" says what it's about.
    embeddings = model.passage_embed([f"{heading}\n{content}" for _, heading, content in chunks])
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            insert into insurance.policy_document_chunks
                (coverage_level, heading, content, embedding)
            values (%s, %s, %s, %s::public.vector)
            """,
            [
                (*chunk, embedding.tolist())
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ],
        )
    conn.commit()
    print(f"Policy booklets:    {len(chunks)} sections")


# The claim text ---------------------------------------------------------------------

# What gets embedded is the text the tools show: redacted, as in the mcp functions.
# The search ranks on these embeddings, so text the tools hide shouldn't count
# towards a match. And with a hosted embedding model, the raw notes, phone
# numbers and all, would otherwise be sent to the provider.
# Each query takes the next batch of rows without an embedding: (id, text).
DESCRIPTIONS = """
    select c.id, insurance.redact_text(c.description)
    from insurance.claims as c
    where c.embedding is null
    order by c.id
    limit %s
"""

NOTES = """
    select n.id, insurance.redact_text(replace(n.note, cu.street_address, '[address]'))
    from insurance.claim_notes as n
    join insurance.claims as c on c.id = n.claim_id
    join insurance.policies as p on p.id = c.policy_id
    join insurance.customers as cu on cu.id = p.customer_id
    where n.embedding is null
    order by n.id
    limit %s
"""


def time_left(seconds: float) -> str:
    if seconds < 60:
        return "less than a minute left"
    return f"about {round(seconds / 60)} min left"


def progress_line(label: str, done: int, total: int, seconds_left: float | None) -> str:
    """Claim notes:        23,040 / 76,630 (30%), about 5 min left"""
    percent = done * 100 // total if total else 100
    line = f"{label + ':':<19} {done:,} / {total:,} ({percent}%)"
    if seconds_left is not None:
        line += f", {time_left(seconds_left)}"
    return line


def embed_rows(
    conn: psycopg.Connection, model: TextEmbedding, label: str, table: str, select_batch: str
) -> None:
    """Embed every row of insurance.<table> that has no embedding yet, a batch at a time.

    select_batch is DESCRIPTIONS or NOTES: it returns the next batch's ids and texts.
    """
    total, done = conn.execute(
        sql.SQL("select count(*), count(embedding) from insurance.{}").format(sql.Identifier(table))
    ).fetchone()
    save = sql.SQL("update insurance.{} set embedding = %s::public.vector where id = %s").format(
        sql.Identifier(table)
    )

    # \r goes back to the start of the line, so the line updates in place.
    print(progress_line(label, done, total, None), end="", flush=True)
    started, done_at_start = time.monotonic(), done

    while rows := conn.execute(select_batch, [BATCH_SIZE]).fetchall():
        ids, texts = zip(*rows, strict=True)
        embeddings = model.passage_embed(texts)
        with conn.cursor() as cursor:
            cursor.executemany(
                save,
                [
                    (embedding.tolist(), row_id)
                    for embedding, row_id in zip(embeddings, ids, strict=True)
                ],
            )
        conn.commit()  # saved: if the command is stopped now, this batch is kept

        done += len(rows)
        per_second = (done - done_at_start) / (time.monotonic() - started)
        seconds_left = (total - done) / per_second if done < total else None
        # Padded with spaces, so a shorter line fully covers the one before it.
        print("\r" + progress_line(label, done, total, seconds_left).ljust(70), end="", flush=True)
    print()


# The command ------------------------------------------------------------------------


def embed_everything(admin_database_url: str) -> None:
    print("Loading the embedding model. The first time, it downloads it (90 MB).")
    model = load_model()

    with psycopg.connect(admin_database_url) as conn:
        load_booklets(conn, model)
        embed_rows(conn, model, "Claim descriptions", "claims", DESCRIPTIONS)
        embed_rows(conn, model, "Claim notes", "claim_notes", NOTES)
    print("Embeddings ready.")


def main() -> None:
    settings = EmbedSettings()
    try:
        embed_everything(settings.admin_database_url)
    except KeyboardInterrupt:
        # Ctrl+C. Every finished batch is already saved.
        sys.exit("\nStopped. Run the command again to carry on where it stopped.")


if __name__ == "__main__":
    main()
