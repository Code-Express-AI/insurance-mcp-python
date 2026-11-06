# Guide 4: search by meaning (RAG)

By the end of this guide your AI assistant can find claims by what they mean, not just by exact fields: "claims where the car was hit while parked at a supermarket" finds them even when none of those words appear. It can also answer "am I covered?" questions by quoting the policy booklets.

This is **RAG**, retrieval-augmented generation: the server finds the most relevant text, and the assistant writes its answer from it. Everything runs on your own machine, for free. The notes never leave it, apart from the search results your assistant reads.

## What you need

- **Guides 1 to 3 done:** the database loaded, the server running, and an AI assistant connected.
- **About 300 MB of disk space** for the model and the embeddings.
- Nothing else. No account, no API key, no extra app.

## How it works

An **embedding** is a list of 384 numbers that stands for the meaning of a text. Texts that mean similar things get similar lists, even with no words in common. A small model, [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), makes them on your CPU.

1. **Once, in bulk:** the embed command makes an embedding for every accident description, every adjuster's note and every section of the three policy booklets, and stores them in PostgreSQL, next to the text, with the pgvector extension.
2. **For each search:** the server makes an embedding of the question with the same model, and the database returns the stored texts whose embeddings are closest to it.

The embedding model isn't the chat model. It only finds the text. Copilot or Claude still reads the results and writes the answer.

## 1. Embed the text

```bash
uv run python -m insurance_mcp.embed
```

The first time, it downloads the model (90 MB) into a `.cache` folder in the repository. Hugging Face, where the model comes from, may print a warning about `HF_TOKEN`. Ignore it: no account is needed. The download can be slow, and if it stalls, stop it and run the command again.

Then it embeds the text, showing its progress as it goes:

```text
Policy booklets:    37 sections
Claim descriptions: 15,090 / 15,090 (100%)
Claim notes:        23,040 / 76,630 (30%), about 2 min left
```

**It takes a few minutes, and your fans will run loud.** The model uses every CPU core, and that's normal. On a fast laptop it takes about 3.5 minutes. An older one can take 15 minutes or more.

**Stopping it is fine.** Press Ctrl+C at any time. Every finished batch is already saved, so run the command again and it carries on where it stopped.

**After running the setup command again** (guide 1), run the embed command again too. The setup command rebuilds the database, and the embeddings with it.

You don't need to restart the server. It loads the model the first time a RAG tool is used, so the MCP part from guides 1 to 3 never loads it.

## 2. Ask questions

The server has three tools for this:

| Tool | What it does |
|---|---|
| `search_claim_text` | Finds claims whose accident descriptions, or whose adjusters' notes, are closest in meaning to the question. Takes the same filters as `search_claims`. |
| `find_similar_claims` | Finds claims whose descriptions are most like one claim's. It compares the stored embeddings, so it doesn't even need the model. |
| `search_policy_wording` | Finds the sections of the policy booklets that answer a question, for one coverage level or all three. |

Try these in your assistant:

- "Find claims where the car was hit while parked at a supermarket."
- "Which claims have notes about a neck injury?"
- "Find claims similar to CLM-1037552, and tell me how they were settled."
- "Am I covered for flood damage with liability + collision?"
- "What do I pay to fix a chip in my windshield?"

For the first one, look at what comes back: "My car was parked at a gas station when a delivery van pulling up to the next pump hit my rear door", "My Toyota Camry was parked on Park Avenue overnight. In the morning the driver's side was caved in". None of them says "supermarket", but every one is a car hit while parked. If the assistant adds the filter `claim_type: collision`, every result is a car hit while parked. That's the main selling point of doing this in PostgreSQL: one query combines search by meaning with exact SQL filters, behind the same permissions and audit log as every other tool.

Each result has a **similarity** score: 1 means the same meaning, and lower is weaker. The assistant can use it to tell a strong match from a weak one.

A few US insurance terms in the booklets: **comprehensive** covers damage to your own car that isn't a crash, such as theft, hail or a deer, and **actual cash value** is what the car was worth just before the loss.

## When it isn't RAG

Now ask: "What's the deductible on policy AUT-104233?"

The assistant should use `get_policy`, not a search. A deductible is an exact fact about one policy, and SQL gets it exactly right. Search by meaning is for finding text, not for looking up numbers. In the same way, "How many collision claims did we have this year?" is a count, and counts come from the exact tools.

## What to watch for

- **Wording matters.** The model is small. "Find claims where the car was hit while parked at a supermarket" works much better than "hit while parked at a supermarket". If a search looks poor, ask again in a full sentence, or ask the assistant to add a filter.
- **The same story can come back several times.** The claim text is built from templates with a different street or store each time, so many claims share one sentence. Real claim text is far more varied.
- **Descriptions or notes, not both at once.** Descriptions say what happened. Notes say how the claim was handled: injuries, statements, suspicions. The assistant picks one with `search_in`.
- **Results are redacted like everything else.** Phone numbers and emails in the text come back as `[phone]` and `[email]`. Names and injuries still get through.

## Run the RAG tests

The tests for the RAG functions and tools are part of the normal test run, `uv run pytest`. They use hand-made embeddings, so they don't need the model.

The tests that use the real model run on their own:

```bash
uv run pytest -m embedding_model
```

They embed the small test data, check that the demo questions find the right things, and take under a minute once the model is downloaded.

## Troubleshooting

**The assistant says "Run the embed command first."** Either the embed command hasn't been run, or the setup command has been run since. Run step 1.

**`permission denied to create extension "vector"`** from the setup command. pgvector can only be installed by a superuser. Locally, `ADMIN_DATABASE_URL` connects as `postgres`, which is one. On a hosted database, use the admin role the service gives you, or install the extension from the service's dashboard.

**The download stops or fails.** Hugging Face can be slow, or limit requests. Stop the command and run it again.

## Next

[Using this with your own data](../using-your-own-data.md) explains how to point the same design at a real company's data, and lists the honest limits in one place.
