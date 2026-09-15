# A3−A2 — suite `benchmark`, arm `compiled-context`

- **provider / model** `local` / `openai/gpt-oss-20b` (identical both sides, checked)
- **repeats** 5, both sides
- **declaring table** commit `ce5f917663d5e9a7d9530791ab478b515e339d24` — 109 subject link(s) across 60 reasoning log(s): the design's **A3**
- **withheld table** commit `ce5f917663d5e9a7d9530791ab478b515e339d24` — 0 subject link(s) across 60 reasoning log(s): the design's **A2**

Which table is which is read off the runs' own reasoning logs above, never off the file names. The delta below is EVAL.md §20's **A3−A2 — the spine**: what declared identity and the subject join buy on top of the compiled view. It is a paired reading of one suite run twice with the plane as the only dial; it is never a reading of two arms within one table.

## train

| mission | flag | A2 (withheld) | A3 (declaring) | A3−A2 |
|---|---|---|---|---|
| `three_receipts_one_total` | chaining | FAIL | FAIL | — |
| `who_owns_that_entry` | absence | FAIL | FAIL | — |
| `two_counts_for_one_entry` | partial_synthesis | FAIL | FAIL | — |
| `release_the_entry_you_were_given` | chaining | PASS | PASS | — |
| `release_whichever_one_came_back` | chaining | PASS | PASS | — |
| `the_operation_is_not_called_subtract` | orientation | FAIL | PASS | FIXED |
| `how_much_settled_not_how_long` | synthesis | FAIL | FAIL | — |
| `settled_is_not_outstanding` | synthesis | FAIL | PASS | FIXED |

A3−A2 over train: **+2 fixed, -0 broke, 6 unchanged**. Runs: A2 23/40, A3 29/40 — all-must-pass over 5 repeat(s), same rules as the tables this is read from.

## test

| mission | flag | A2 (withheld) | A3 (declaring) | A3−A2 |
|---|---|---|---|---|
| `out_and_back_on_one_route` | synthesis | FAIL | FAIL | — |
| `which_route_ran_that_window` | absence | FAIL | FAIL | — |
| `the_count_will_not_settle` | partial_synthesis | PASS | PASS | — |
| `the_kinds_are_not_the_words` | orientation | PASS | PASS | — |

A3−A2 over test: **+0 fixed, -0 broke, 4 unchanged**. Runs: A2 14/20, A3 13/20 — all-must-pass over 5 repeat(s), same rules as the tables this is read from.

Read beside §20's standing rule: small gain = simplify or stop, measured against the instrument's own noise, never re-rolled.
