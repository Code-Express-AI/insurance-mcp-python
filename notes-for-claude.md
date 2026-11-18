# Notes for Claude

Things to put in the skills when we write them. From the video planning (2026-11-18).

## The "last month" date problem: fixed (Liam, 2026-11-18)

The data's "as of" date is now the day `setup_db` runs (`AS_OF_DATE = date.today()` in `generate/config.py`), so "last month" has data whenever someone installs it. A test checks it (`test_last_month_has_claims_whenever_the_data_is_set_up`). Still open, Liam's call: explicit `reported_from` / `reported_to` dates in place of the `period` names.

## Videos 3 and 5: safe to follow along (Liam, 2026-11-18)

In videos 3 and 5 the viewer's own assistant writes the code, so their run won't match the video. If they get stuck there, they leave the series. "If these two fail, the whole series fails."

- **A known-good branch for each video**, e.g. `video-3-done` (the `get_customer_with_policies` tool) and `video-5-done` (the adjusters' manual table, function and tool). Each one passes `uv run pytest`. `main` stays without them, so there's still something to build.
- **The README points to them**, near the guides: "Your code will look a bit different from the video. If you get stuck, compare with this branch, or check it out and carry on." The videos say the same line and pin it in a comment.
- **Rehearse both on Copilot's free plan**, from a fresh clone, start to finish. The free plan has a monthly limit on chat and agent requests; check how many one run of each video uses, and that videos 3 and 5 together fit inside it with room for retries. If they don't, the skills need fewer round trips (or the videos say so).
- **Rehearse each one more than once.** Different runs write different code. The skills should make the result predictable: name the files, the function, the test to add, in order.
- **The skills end with a review list for the human.** Writing the code costs almost nothing now; reading it is the viewer's job (video 3: "The AI writes it. You sign it off."). The last step of each skill: show the new SQL function and the new grant, and say what to check (the columns returned, the masking, the row limit). The rule tests catch a missing grant or `security definer`; they don't catch a function returning a column it shouldn't.

## Video 5: without the skill, then with it (Liam, 2026-11-18)

Video 3 builds a tool with the skill. Video 5 asks the same thing twice, word for word, in fresh sessions: first with the skill switched off, then on. The point: show what the skill is for, and that the tests catch the run without it.

- **A typing guide for video 5 too:** the same steps for adding a table with embeddings, by hand, like video 3's guide. Viewers who'd rather type it themselves follow that.
- **A clean way to switch the skill off** for the first run, so the assistant really can't find it (for example, a branch without the skill, or the skill's folder moved aside), and back on for the second. Both Claude Code and Copilot. Document it in the README next to the guides, so viewers can try the comparison themselves.
- **Rehearse the run without the skill before anything else, more than once.** The video's point depends on what it actually gets wrong. The likely slip: the search function hits permission denied, and the assistant "fixes" it with `grant select on <table> to mcp_reader`, so the server's login can read a table. `test_reader_permissions.py` should catch that; check it does. Other possible slips: no `security definer` or fixed `search_path`, the wrong vector size, no 384-number check, chunks over 256 word pieces. Write down what happened for Liam; don't tune anything to make it fail. If it gets everything right, tell Liam: the video's point changes.
- **The tests must catch each slip above.** If one of them would pass the tests (for example, a function that returns too many columns), that's a gap in the tests worth knowing about before recording, whether or not the video shows it.
- ○ Optional: keep the run without the skill on a branch (e.g. `video-5-without-skill`), so viewers can see the failing code and the red test for themselves.

## Add-a-tool skill

- **PL/pgSQL: output columns are variables.** In a `RETURNS TABLE (customer_id uuid, ...)` function, every output column is also a variable, so a query that mentions a column of the same name fails with "column reference is ambiguous". The rule the skill must state: prefix every argument with `p_`, alias every table and qualify every column with its alias, and use `order by <position>` (with a comment) when ordering by an output column. Video 3 records the assistant writing a new function live, so the skill has to prevent this error, not leave the assistant to debug it on camera.
- **Nested results: build them in SQL, like `get_claim`.** A tool that returns a parent with its children (a customer with their policies) returns one row with the children as a `jsonb` list (`jsonb_agg(jsonb_build_object(...))`), as `get_claim` does for payments and notes. Not two functions, and not stitched together in Python: one function call, one audit row.
- **Counts by period return every period, zeros included.** Use `generate_series` for the periods, as `count_claims_by_month` does, so a month with no rows shows as 0. A missing month reads to the model as "no data", or gets skipped.
- **Every `LIKE` / `ILIKE` argument goes through `escape_like()`.** Parameters stop SQL injection, not wildcards: a search for `%%` is valid and matches every row, so the model could page through the whole table. Copy how `find_customers` does it.
- **Date arguments take a `period`, not raw dates.** Like the existing tools: `period: "last_month"`, with the dates worked out in the database from the data's "as of" date. The model is given today's real date, so a model-supplied "last month" can point past the end of the data and return nothing.
- **"Not found" uses `FOUND`.** After `RETURN QUERY`, `if not found then raise exception 'Unknown ...'`: three lines, the same message as a made-up id (so it doesn't confirm what exists). Copy `get_policy`.
- **Patterns use `[0-9]`, never `\d`.** In Python `\d` matches any Unicode digit, so `AUT-١٠٤٢٣٣` would pass. Match the tables' `CHECK` constraints, as the existing argument types do.

## Add-a-table-with-embeddings skill (video 5)

- **Keep each chunk under 256 word pieces.** `all-MiniLM-L6-v2` silently drops the rest (the booklets' glossary was 261). Count with the model's own tokenizer, as the existing booklet test does, and add the same test for the new text.
- **The search function checks for exactly 384 numbers.** `embedding <=> null` is null, so a null or wrong-sized query vector returns rows with no score instead of an error. Copy the check from the existing RAG functions.
