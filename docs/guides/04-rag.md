# Guide 4: search by meaning in depth

This is the guide for [video 4 on YouTube](https://www.youtube.com/@CodeExpressAI).

## Embed the claims

The quickstart's `--booklets-only` embedded the policy booklets. The claim searches need the full embed:

```bash
uv run python -m insurance_database.embed
```

The accident descriptions take about a minute, and that's all the questions in this guide need. The adjusters' notes take a few minutes on a fast laptop, and 15 or more on an older one, with the fans running loud. Stopping it with `Ctrl+C` is fine: run it again and it carries on where it stopped.

## RAG: find the text, then answer from it

**RAG**, retrieval-augmented generation: the server finds the most relevant text, and the AI assistant writes its answer from it. The embedding model only finds the text. Copilot or Claude reads it and writes the answer.

Keyword search fails here, and fails silently. No claim says "supermarket", so a search for the word returns 0 rows and no error. Search by meaning finds the claims at Kroger, Safeway and a grocery store, because those mean supermarket.

The search can also be narrowed with exact filters, in the same query. This is **filtered vector search** (also called metadata filtering): search by meaning, plus ordinary SQL `where` conditions. It's often called **hybrid search**, but in RAG that name usually means search by meaning combined with keyword search, which this isn't. The claim search tool can filter by:

- **Claim type:** collision, theft, glass (windshields and windows), fire, vandalism or weather.
- **Status:** open, settled, denied or withdrawn.
- **When it was reported:** last month, the last 3 months, the last 12 months, this year or last year.
- **Minimum reserve:** the expected total cost of the claim, in dollars.

The assistant picks the filters from the question, so "only the collisions" becomes `claim_type: "collision"`. The PostgreSQL function `mcp.search_claim_text` applies them, each one an ordinary `where` condition, skipped when it's null. [See its filters](../../sql/080_mcp_functions.sql#L698-L702):

```sql
where c.embedding is not null
  and (p_claim_type is null or c.claim_type = p_claim_type)
  and (p_status is null or c.status = p_status)
  and (p_min_reserve is null or c.reserve >= p_min_reserve)
  and (p_period is null or c.date_reported between v_start and v_end)
order by c.embedding operator(public.<=>) v_query, c.claim_number
```

`operator(public.<=>)` is pgvector's `<=>`, how far apart in meaning (more on it below). It's written in full because the function's `search_path` is empty.

## Embeddings: a text becomes 384 numbers

- **An embedding** is a list of 384 numbers that stands for what a text is about. Texts that mean similar things land close together, with nobody labeling them.
- **The model** is [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2): 90 MB, it runs on your CPU, and it's free, with no API key. The claims never leave your machine.
- **Why this model:** we tested four small models on our own data, and it found the right claims most often, and was the fastest ([the spec, section 11](../specs/spec.md#11-rag-extension)).
- **It reads about 256 word pieces (tokens)** of each text and silently ignores the rest. Notes are under 100 and booklet sections under 256, and a test checks it. For other kinds of text, see [picking an embedding model](#further-reading-picking-an-embedding-model).
- **The map in the video is squashed** from 384 dimensions to 2. The search uses all 384.

## pgvector: the embedding is just a column

The embedding sits next to the text, in the same table, in the same PostgreSQL ([sql/020_schema.sql](../../sql/020_schema.sql)):

```sql
embedding public.vector(384)  -- of the description, for RAG
```

No separate vector database to run, pay for, secure or keep in sync. See the first few numbers of some embeddings, once the embed command has run:

```bash
docker compose exec db psql -U postgres -d insurance -c "select claim_number, left(description, 60) as description, left(embedding::text, 50) as embedding from insurance.claims where embedding is not null limit 3;"
```

Pinecone, the best-known separate vector database, now has search that runs inside PostgreSQL too: [pg_pinecone](https://www.pinecone.io/blog/introducing-pg-pinecone/), open source, released in October 2026.

## One search, end to end

1. The question goes through the same model, so its 384 numbers can be compared with the stored ones.
2. PostgreSQL returns the closest texts first. pgvector's `<=>` is the cosine distance, how far apart two texts are in meaning: 0 is the same meaning, and the similarity score is 1 minus the distance.
3. Meaning alone lets near misses in, such as hail in a Target parking lot. An ordinary `where` takes them out, in the same query.
4. The rows go to the assistant, which writes the answer.

Simplified, the query is:

```sql
select description, similarity
from claims
where claim_type = 'collision'
order by embedding <=> :question
limit 10
```

The `where` line is the filtered part of filtered vector search: `claim_type = 'collision'` takes out the hail and theft claims that are close in meaning.

The real one is `mcp.search_claim_text` in [sql/080_mcp_functions.sql](../../sql/080_mcp_functions.sql#L646), with the same permissions and the same audit log as every other tool. The model picks the filter, the database applies it, and the model never writes SQL.

## What RAG isn't for

Counts, amounts and exact lookups are SQL questions, and the exact tools answer them. The search tool's docstring says so ([server/src/insurance_mcp/tools.py](../../server/src/insurance_mcp/tools.py#L256)):

```text
Not for exact questions (counts, amounts, numbers): use search_claims for those.
```

## Try it

Ask your assistant the video's questions:

- "Find claims where the car was hit while parked at a supermarket." None of the results says "supermarket".
- "Find claims where the wind blew something into the car." Look for the neighbor's trampoline.
- "Only the collisions: cars hit while parked at a supermarket." The tool call has `claim_type: "collision"`, and the hail and theft claims are gone.
- "How many claims were reported last month?" The assistant uses `count_claims_by_month`, not the search, and gets an exact number.

## Further reading: picking an embedding model

all-MiniLM-L6-v2 suits this repo because the text is short, plain English, and must stay on your machine. Your text may need something else. Some questions to ask before you choose:

- **How long is each text?** A model reads a fixed number of tokens and silently drops the rest. Small local models read a few hundred tokens, and hosted ones read thousands. Either way, split long documents into chunks at their headings or paragraphs, as the booklets are, so each embedding stands for one idea.
- **What kind of text is it?** General models are trained mostly on web pages and question-and-answer pairs. They do well on customer support tickets and claim notes, which are everyday language. Scientific papers are full of terms a general model barely knows, so try one trained on them, such as [SPECTER2](https://huggingface.co/allenai/specter2), which learned from which papers cite which. Posts on X are short, informal, full of slang, hashtags and emoji, and often in several languages, so try a multilingual model and check it on real posts. Legal, financial and code search have their own models too.
- **Which languages?** An English-only model like ours puts a Spanish claim in the wrong place. Multilingual models embed many languages onto the same map, so a question in English can find a note in Spanish.
- **Can the text leave your machine?** A hosted embeddings API sees every text you embed, personal data included, and charges for it. A local model costs nothing and sends nothing, but runs on your own hardware.
- **How many numbers?** More dimensions can capture more, but take more storage and make each search slower. pgvector can index up to 2,000 dimensions with its `vector` type ([pgvector's README](https://github.com/pgvector/pgvector)). Many hosted models let you choose a smaller size.

Then **test it on your own data.** Write 20 or so questions with the answers you expect, and check which model finds them most often. That's how this repo picked its model ([the spec, section 11](../specs/spec.md#11-rag-extension)): the smallest of the four we tried did best. A leaderboard shows how a model does on public benchmarks, not on your text.

**Changing model means embedding everything again.** Numbers from two models can't be compared, so the stored embeddings and the question must always come from the same one.

Where to look:

- **Leaderboards:** the [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard) ranks embedding models on many tasks and languages. Use it to pick a shortlist, then test the shortlist yourself.
- **Open source, free to run locally:** the [Sentence Transformers model list](https://sbert.net/docs/sentence_transformer/pretrained_models.html), and families such as BAAI's BGE, Snowflake's Arctic Embed, Microsoft's multilingual E5 and Google's [EmbeddingGemma](https://huggingface.co/google/embeddinggemma-300m). Check each model's license and its card's instructions: some need a prefix such as `query: ` on the question.
- **Commercial, hosted:** [OpenAI](https://developers.openai.com/api/docs/guides/embeddings), [Voyage AI](https://docs.voyageai.com/docs/embeddings) (with models for law, finance and code), [Cohere](https://docs.cohere.com/docs/cohere-embed) and Google. Anthropic doesn't make an embedding model, and [its docs suggest Voyage AI](https://platform.claude.com/docs/en/build-with-claude/embeddings).

## Summary

Search by meaning turns each text into 384 numbers with a free local model, and finds the closest ones. With pgvector, those numbers are a column in PostgreSQL, so one query combines meaning with exact SQL filters, behind the same permissions and audit log as every other tool. Use it to find text, and the exact tools for counts and numbers.
