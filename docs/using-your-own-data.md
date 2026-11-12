# Using this with your own data

This project stands in for a common real situation: a company wants its AI assistants to answer questions from data it already has. This page explains how to do that safely with the same design, and lists everything the design can't protect against, in one place.

It's a pointer, not a build. Nothing on this page is in the code.

## Never point it at the live database

The live database is the one the business runs on: policies are sold, claims are opened and payments are made in it, all day. (Its technical name is the **OLTP** database, for online transaction processing.) AI questions can be slow and unpredictable, and the live system must never be at the mercy of them.

## Use a read-only data warehouse

Instead, copy the data the assistants need into a **read-only data warehouse**: a separate PostgreSQL database, loaded on a schedule (for example nightly) from the live system, and used only for reading. That's what this project's database is:

- **The data generator stands in for the nightly load.** In a real company, an **ETL** job (extract, transform, load) would fill these tables from the live system instead.
- **Copy only the tables and columns the tools need.** Data that isn't in the warehouse can't leak from it. Our database has no Social Security numbers or bank details, because no question needs them.
- **Nothing reads back into the live system.** Even if every layer failed, only a copy would be exposed.

## What you add to the warehouse

The warehouse tables stay as they are, apart from switching on row-level security. On top of them you add the same pieces this project has:

1. **The two roles:** `mcp_owner`, which owns the functions and only has `SELECT` on the tables, and `mcp_reader`, which the server logs in as and which can only run the functions it's granted. See `sql/01_roles.sql` and `sql/03_permissions.sql`.
2. **One `mcp` function per question,** with fixed columns, a row limit, and masking on anything sensitive. See `sql/04_functions.sql`.
3. **The audit log,** append-only and hash-chained. See `sql/05_audit.sql`.
4. **Row-level security,** if different callers should see different rows: a table that maps each caller to what it may see, and a policy on each table with customer data. Switching it on (`alter table ... enable row level security`) is the one change to the warehouse tables themselves. See `sql/06_row_security.sql`.
5. **One tool per function** in the server, with its arguments checked. See `src/insurance_mcp/tools.py`.

The lockdown tests in `tests/database/` check the system catalogs, so they also check functions you add: each one must be `SECURITY DEFINER`, set its `search_path` and be owned by `mcp_owner`.

**On a big table, check the searches are fast.** Our name search uses `ILIKE '%name%'`, which reads the whole table. On our 12,000 customers that takes about a millisecond. On millions, add a trigram index with the `pg_trgm` extension.

## For staff, consider a front end you build yourself

A general-purpose assistant such as Copilot or Claude Code may also have tools that can send data out, such as web fetch or email. Together with private data and untrusted text, that's the **lethal trifecta** (see [Honest limits](#honest-limits)). A front end with a fixed set of tools, which never loads remote images, closes it by design. It then becomes the thing to keep closed: a feature like "email this report" opens it again. This project doesn't build one.

## Honest limits

Each of these is a real gap. Some are fixed by something outside the app, and some aren't fixed at all. The specs have the detail.

### What the assistant does

- **Prompt injection isn't solved.** Claim notes are text written by people, and some of ours contain planted instructions. The server tells the model to treat notes as data, which lowers the risk but doesn't remove it. A fooled model can't change anything through this server. ([server-spec.md](specs/server-spec.md), decision 11)
- **Read-only isn't harmless.** If the same assistant also has a tool that can send data out, a planted note could tell it to send customer details somewhere. We can't control which other tools someone's assistant has. Keep the assistant asking before each tool call, and don't connect this server next to tools that send data out. ([server-spec.md](specs/server-spec.md), decision 11)
- **Relative dates can still go wrong.** The tools that need a period take one (`last_month`) and the server works out the dates, so those can't be wrong. Everywhere else, the model is only told which date is "today", and can occasionally ignore it. ([data-generator-spec.md](specs/data-generator-spec.md), decision 3)

### Who sees what

- **The database trusts the server to say who's calling.** Row-level security filters every query by a caller key that the server sets on each call. `mcp_reader` can set any key it likes, so anyone with its password can see every customer. Keep that password as secret as the tokens. Making the database check each person itself would mean a database login per person, which isn't how web apps normally connect. ([database-spec.md](specs/database-spec.md), decision 15)
- **Who sees what is a fixed table.** `caller_states` maps each token name to its states. In a company, fill it from your identity provider's groups, such as "Texas claims team". A new token name sees nothing until it's given rows. ([database-spec.md](specs/database-spec.md), decision 15)
- **A token names a client, not a person.** The audit log shows `copilot`, not who was typing. To know the person, a hosted server would need OAuth: Entra ID, Okta, Auth0, or Google sign-in through a broker. Only the function that works out the caller would change. The database and its row-level security stay as they are. ([server-spec.md](specs/server-spec.md), decision 5)
- **Redaction catches patterns, not meaning.** Phone numbers and email addresses in claim notes become `[phone]` and `[email]`. Names, street addresses and injuries get through. ([database-spec.md](specs/database-spec.md), decision 9)
- **Anyone connected can read the table and function definitions** in the system catalogs, and run PostgreSQL's built-in functions, such as `pg_sleep()`. Revoking these breaks normal tools. It only matters to someone who can send raw SQL, which the server never allows. ([database-spec.md](specs/database-spec.md), decision 6)

### The audit log

- **The database admin can rewrite it.** The admin can switch off the trigger, change rows and recompute the hash chain. No database can fully protect a log from its own admin. The fix is to copy the latest hash somewhere the admin can't reach. ([database-spec.md](specs/database-spec.md), decision 10)
- **Whoever has the `mcp_reader` password can write audit rows,** with any caller name, and call the functions without being audited, because the server writes the audit rows, not the functions. Functions that log themselves wouldn't fix it: in PostgreSQL a caller can roll the log row back along with its own transaction. The database limits what can be done; the server records who did it. Keep that password long and secret. ([database-spec.md](specs/database-spec.md), decision 10)
- **Personal data is kept forever.** The log records what was searched for, such as a customer's name, and an append-only table can't have it removed. Privacy laws such as the GDPR give people a right to have their data deleted, so a real system needs a retention period. ([database-spec.md](specs/database-spec.md), decision 10)
- **The trigger doesn't stop `DROP TABLE`.** Blocking it needs a real superuser, which hosted databases don't give you. ([database-spec.md](specs/database-spec.md), decision 10)

### Search by meaning (RAG)

- **A small local model is sensitive to wording.** It's free and keeps the text on your machine, but a hosted model finds better matches. Test your own questions on your own data, and count how many of the top results are right. ([spec.md](specs/spec.md), decision 11)
- **The embeddings are made from the unredacted text.** Research shows embeddings can be partly turned back into text. Ours never leave the database, and no tool returns them. ([spec.md](specs/spec.md), decision 11)
- **Every search is exact, with no vector index.** That's fast enough for 100,000 texts, and always correct with filters. At millions of rows, add pgvector's HNSW index, with its "iterative scans" switched on, or a filtered search can return fewer results than it should. ([spec.md](specs/spec.md), decision 11)
- **Planted instructions can come back in search results too,** like any other note. The same advice applies: the model is told to treat text as data, and no tool can change anything. ([server-spec.md](specs/server-spec.md), decision 11)

### Running it

- **The query timeout is a default.** Through the server it holds, but someone connecting directly as `mcp_reader` could turn it off. ([database-spec.md](specs/database-spec.md), decision 11)
- **Rate limits are counted in memory,** per server process. A restart resets them, and several servers behind a load balancer would each count separately and need a shared store. ([server-spec.md](specs/server-spec.md), decision 7)
- **Slow-sending attacks and floods of connections** are a job for a reverse proxy in front of a hosted server, not for the app. Locally, the server only listens on `127.0.0.1`, so they don't apply. ([server-spec.md](specs/server-spec.md), decision 14)
- **The tokens are in plain text** in `.env` and in each AI client's configuration, in your home folder. Locally that's acceptable, because the server only listens on `127.0.0.1`. A hosted server needs its tokens in a secrets store. ([server-spec.md](specs/server-spec.md), decision 5)
