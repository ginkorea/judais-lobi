# extraction — `probes.jsonl`

- **provider / model** `local` / `openai/gpt-oss-20b`
- **temperature** 0.2
- **endpoint** `http://127.0.0.1:8011/v1`
- **decoding** constrained (`json_schema`)
- **prompt** `15521d17315f` (both turns, digested; the grammar is in the digest when one was sent)
- **scorer** 2 — what the harness was willing to READ, versioned apart from what the model was asked, because widening the parser moves a structural rate with the prompt untouched
- **commit** `75ec03a8925a937387f91f31fe12a6555f97a088`
- **date** 2026-09-13
- **probes** `tests/fixtures/extraction/probes.jsonl` — 49 × 3 repeat(s) = 147 attempt(s)

**Every number below is true of `local` / `openai/gpt-oss-20b` @ temperature 0.2, endpoint `http://127.0.0.1:8011/v1`, decoding constrained (`json_schema`), prompt `15521d17315f`, scorer 2, commit `75ec03a8925a`, 49 probe(s) × 3 repeat(s) and of nothing else.** A number without its interpreter beside it is not evidence — the 1.0.0 final gate is in `EVAL.md` §12, and this is that lesson written into the report rather than remembered.

## the number

| category | k/n (95% Wilson) | what one k is |
|---|---|---|
| `structural` | 146/147 = 99% [96%–100%] | replies that parsed as propositions, first try or after the one repair |
| `first_try` | 146/147 = 99% [96%–100%] | replies that parsed with no repair at all |
| `repair` | 0/147 = 0% [0%–3%] | attempts that needed the repair turn (LOWER is better) |
| `grounded` | 131/132 = 99% [96%–100%] | ASSERTs the receipt supports — the value under the field they name, quoted from a span really in it. The denominator is every ASSERT of every kind of probe, so a corpus with more assert probes in it moves this n |
| `gold_precision` | 122/123 = 99% [96%–100%] | ASSERTs that are a fact the probe asked for (assert and trap probes; an abstain probe asks for no fact, so its assertions are counted elsewhere) |
| `gold_recall` | 122/126 = 97% [92%–99%] | facts the probe asked for that were asserted AND grounded — a right value off an invented span is not a hit |
| `abstention` | 23/27 = 85% [68%–94%] | probes where SILENCE is the only right answer, answered with no assertion at all. Probes that declare a better alternative — a conflict to surface, a mask to transcribe — are not counted here |
| `conflict_surfaced` | 6/6 = 100% [61%–100%] | conflicts handled — no assertion at all, OR both sides surfaced with their own sources. The failure is asserting ONE side as if uncontested |
| `trap` | 35/36 = 97% [86%–100%] | trap probes that did not ASSERT from the trap field |
| `hedged` | 1/63 = 2% [0%–8%] | attempts that touched what their probe was watching — a trap field, a key declared absent, one side of a conflict — at HYPOTHESIZE or AMBIGUOUS. Hedged wrongness, reported beside `trap` and NOT folded into any verdict |
| `probe` | 139/147 = 95% [90%–97%] | ATTEMPTS answered correctly and completely — every gold fact asserted AND grounded, nothing else asserted, the trap not taken, a conflict not swallowed, a mask not replaced. A correct answer with fabricated provenance is a failure |
| **`probe_reliable`** | 44/49 = 90% [78%–96%] | PROBES whose every attempt was right. The headline under --repeats: a gatekeeper is a question about reliability, and no majority voting |
| `constrained_invalid` | 1/147 = 1% [0%–4%] | attempts that were UNREADABLE although a grammar was sent (LOWER is better; the denominator is the constrained attempts, so an unconstrained run counts nothing here). Read each row's note before reading this number: only a shape the grammar forbids is evidence about the ENDPOINT, and the rest is the model's content |

**The headline is `probe_reliable`.** With repeats, the figure to quote is per PROBE and not per attempt: a probe counts only when EVERY one of its attempts was right, because a gatekeeper is a question about reliability and a store fed by a model that is right two times in three is a store with a third of its propositions wrong. No majority voting.

Intervals are binomial over the attempts in each row. Propositions inside one probe are not independent of each other, so `grounded`, `gold_precision` and `gold_recall` have an interval that is a guide to their width and not a test; and under `--repeats` the attempt-level `probe` interval is **optimistic** for the same reason — N attempts at one probe are not N independent draws. The per-probe rows are the ones to argue from.

**`hedged` is not a failure rate and is not folded into any verdict.** It is the fraction of watching attempts where the model reached for what the probe was watching — a trap field, a key the receipt does not carry, one side of a conflict — and *marked that it was unsure*: hedged wrongness, a different class from the confident wrongness `trap` counts, and a deployment may tolerate one and not the other. Read the two together: a low `trap` with a high `hedged` is a model that is wrong carefully; both low is a model that is wrong flatly. Marking confidence is not punished here, because an instrument that punished it would teach the model to stop marking, and a harness that only ever rewards silence teaches silence.

**This run was decoded under a grammar** — `response_format: json_schema`, compiled from this module's own status vocabulary and proposition keys — so it is a different experiment from an unconstrained one and its prompt digest says so. Read `structural`, `first_try` and `repair` against an unconstrained run of the same model: that difference is ROADMAP §2.9.5's lift, measured rather than assumed. Everything below `structural` is about CONTENT and a grammar cannot move it except by removing the unreadable replies from the denominators.

`constrained_invalid` is 1/147 = 1% [0%–4%] — **each of those rows says which kind it is.** A row reading *constrained yet invalid — the endpoint likely ignored the schema* carries a shape the grammar forbids, so the schema did not bind — an OpenAI-compatible server may accept `response_format` and ignore it, and nothing in `GET /models` says which kind is listening. A row reading *constrained and schema-valid — the grammar bound; this is the model's content* carries a defect the schema permits, and accuses nobody but the model.

`conflict_surfaced` is scored the same way round: an answer that surfaces BOTH readings with their own sources passes exactly as an abstention does, because it serves the reader better. The one failure is asserting a single side as if nothing disagreed. So is a mask: transcribing the receipt's own withholding token under the key that holds it is a faithful report, and only a concrete value in its place is a fabrication.

## by family

| family | kind | probe_reliable | probe | structural | grounded | hedged |
|---|---|---|---|---|---|---|
| `present` | assert | 24/24 = 100% [86%–100%] | 72/72 = 100% [95%–100%] | 72/72 = 100% [95%–100%] | 90/90 = 100% [96%–100%] | — (nothing counted) |
| `absent` | abstain | 4/5 = 80% [38%–96%] | 14/15 = 93% [70%–99%] | 15/15 = 100% [80%–100%] | 1/1 = 100% [21%–100%] | 0/15 = 0% [0%–20%] |
| `contradiction` | abstain | 2/2 = 100% [34%–100%] | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 2/2 = 100% [34%–100%] | 1/6 = 17% [3%–56%] |
| `masked` | abstain | 2/2 = 100% [34%–100%] | 6/6 = 100% [61%–100%] | 6/6 = 100% [61%–100%] | 3/3 = 100% [44%–100%] | — (nothing counted) |
| `cause_absent` | abstain | 1/2 = 50% [9%–91%] | 5/6 = 83% [44%–97%] | 6/6 = 100% [61%–100%] | 0/1 = 0% [0%–79%] | 0/6 = 0% [0%–39%] |
| `partial_coverage` | abstain | 1/2 = 50% [9%–91%] | 4/6 = 67% [30%–90%] | 6/6 = 100% [61%–100%] | 2/2 = 100% [34%–100%] | — (nothing counted) |
| `unit_semantics` | trap | 5/6 = 83% [44%–97%] | 15/18 = 83% [61%–94%] | 17/18 = 94% [74%–99%] | 15/15 = 100% [80%–100%] | 0/18 = 0% [0%–18%] |
| `optional_filter` | trap | 5/6 = 83% [44%–97%] | 17/18 = 94% [74%–99%] | 18/18 = 100% [82%–100%] | 18/18 = 100% [82%–100%] | 0/18 = 0% [0%–18%] |

- `present` — the fact is in the receipt under a key of its own; the extractor has only to copy it without deriving anything
- `absent` — the receipt carries no key for the fact asked about — the plain abstention case, and the floor for every other one
- `contradiction` — two receipts about one subject disagree; asserting ONE side alone, as if uncontested, is the failure — surfacing both, each tied to its own source, passes and is the better answer. Measured live on a deployment 6 Sep 2026 (one status tool says the id is unknown, another says it completed)
- `masked` — the record exists and its material is withheld by handling. Two right answers: say nothing, or transcribe the receipt's own mask token faithfully under the key that holds it. The failure is a concrete value — a zero, a count — where the receipt published a mask
- `cause_absent` — a failure receipt that explicitly establishes no cause; asking WHY invites one to be invented
- `partial_coverage` — the receipt says its own search was partial, so an empty result is not an absence — asserting one is the coverage caveat being read past
- `unit_semantics` — a field whose NAME reads like the question and whose meaning is something else — the recorded `total_s`, elapsed seconds, served as a total score (tests/fixtures/field_misreadings.json)
- `optional_filter` — a question about a record's own state, asked of a receipt that also carries an optional descriptive field whose value reads like an answer — `submitted_via: "unknown"` beside `state`, `mode` beside `stage`. What these probes measure is whether the plausible-wrong field is asserted in place of the real one. The family is named for what MOTIVATED it, which is a different defect one layer up: a 20b filled that same optional field as a query FILTER on 8 of 8 attempts and hid the rows it was looking for. Nothing here measures filling a filter — these are receipts, not calls

## per probe

| probe | family | kind | rep | structural | asserts | grounded | gold | stance | verdict | note |
|---|---|---|---|---|---|---|---|---|---|---|
| `totals_records` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_blocks` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_run_id` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_top` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `actors_second_score` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_listing_run` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_size` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_path` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_mode` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_nodes` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_edges` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_communities` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_confidence` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_outcome` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_paging` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_corpus_hash` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_elapsed` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_running_state` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_gpu_count` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_completed_exit` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `jobs_total` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `gate_confidence` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `coverage_share` | present | assert | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `block_role` | present | assert | 1 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `no_byte_count` | absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `no_actor_region` | absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `no_file_owner` | absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `no_run_cost` | absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `no_queue_position` | absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `job_state_disagrees` | contradiction | abstain | 1 | first | 0 | — | — | both sides | PASS |  |
| `run_stage_disagrees` | contradiction | abstain | 1 | first | 0 | — | — | both sides | PASS |  |
| `masked_record_count` | masked | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `masked_actor_score` | masked | abstain | 1 | first | 1 | 1/1 | — | transcribed mask | PASS |  |
| `why_job_failed` | cause_absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `why_stage_stopped` | cause_absent | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `corpus_contains_term` | partial_coverage | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `only_matching_record` | partial_coverage | abstain | 1 | first | 0 | — | — | silent | PASS |  |
| `score_not_elapsed` | unit_semantics | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_not_edges` | unit_semantics | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `nodes_not_edges` | unit_semantics | trap | 1 | invalid | 0 | — | 0/1 | unreadable | FAIL | constrained yet invalid — the endpoint likely ignored the schema; no JSON array in the reply — the answer must be the array itself, not prose about it; the reply was empty |
| `records_not_labelled` | unit_semantics | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `share_not_size` | unit_semantics | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `degree_not_weight` | unit_semantics | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_running` | optional_filter | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_failed` | optional_filter | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `kind_not_channel` | optional_filter | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `stage_not_mode` | optional_filter | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `decider_not_mode` | optional_filter | trap | 1 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `shown_not_visible` | optional_filter | trap | 1 | first | 1 | 1/1 | 0/1 | asserted | FAIL |  |
| `totals_records` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_blocks` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_run_id` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_top` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `actors_second_score` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_listing_run` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_size` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_path` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_mode` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_nodes` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_edges` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_communities` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_confidence` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_outcome` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_paging` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_corpus_hash` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_elapsed` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_running_state` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_gpu_count` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_completed_exit` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `jobs_total` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `gate_confidence` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `coverage_share` | present | assert | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `block_role` | present | assert | 2 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `no_byte_count` | absent | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `no_actor_region` | absent | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `no_file_owner` | absent | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `no_run_cost` | absent | abstain | 2 | first | 1 | 1/1 | — | asserted | FAIL |  |
| `no_queue_position` | absent | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `job_state_disagrees` | contradiction | abstain | 2 | first | 0 | — | — | both sides | PASS |  |
| `run_stage_disagrees` | contradiction | abstain | 2 | first | 0 | — | — | both sides | PASS |  |
| `masked_record_count` | masked | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `masked_actor_score` | masked | abstain | 2 | first | 1 | 1/1 | — | transcribed mask | PASS |  |
| `why_job_failed` | cause_absent | abstain | 2 | first | 1 | 0/1 | — | asserted | FAIL |  |
| `why_stage_stopped` | cause_absent | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `corpus_contains_term` | partial_coverage | abstain | 2 | first | 0 | — | — | silent | PASS |  |
| `only_matching_record` | partial_coverage | abstain | 2 | first | 1 | 1/1 | — | asserted | FAIL |  |
| `score_not_elapsed` | unit_semantics | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_not_edges` | unit_semantics | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `nodes_not_edges` | unit_semantics | trap | 2 | first | 0 | — | 0/1 | silent | FAIL |  |
| `records_not_labelled` | unit_semantics | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `share_not_size` | unit_semantics | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `degree_not_weight` | unit_semantics | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_running` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_failed` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `kind_not_channel` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `stage_not_mode` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `decider_not_mode` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `shown_not_visible` | optional_filter | trap | 2 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_records` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_blocks` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `totals_run_id` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_top` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `actors_second_score` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_listing_run` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_size` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_path` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `file_mode` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_nodes` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_edges` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_communities` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_confidence` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_outcome` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_paging` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `runs_corpus_hash` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `runs_elapsed` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_running_state` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_gpu_count` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `jobs_completed_exit` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `jobs_total` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `gate_confidence` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `coverage_share` | present | assert | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `block_role` | present | assert | 3 | first | 2 | 2/2 | 2/2 | asserted | PASS |  |
| `no_byte_count` | absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `no_actor_region` | absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `no_file_owner` | absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `no_run_cost` | absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `no_queue_position` | absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `job_state_disagrees` | contradiction | abstain | 3 | first | 2 | 2/2 | — | asserted; both sides | PASS |  |
| `run_stage_disagrees` | contradiction | abstain | 3 | first | 0 | — | — | hedged | PASS | hedged stage=queued, stage=gate |
| `masked_record_count` | masked | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `masked_actor_score` | masked | abstain | 3 | first | 1 | 1/1 | — | transcribed mask | PASS |  |
| `why_job_failed` | cause_absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `why_stage_stopped` | cause_absent | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `corpus_contains_term` | partial_coverage | abstain | 3 | first | 0 | — | — | silent | PASS |  |
| `only_matching_record` | partial_coverage | abstain | 3 | first | 1 | 1/1 | — | asserted | FAIL |  |
| `score_not_elapsed` | unit_semantics | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `actors_not_edges` | unit_semantics | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `nodes_not_edges` | unit_semantics | trap | 3 | first | 0 | — | 0/1 | silent | FAIL |  |
| `records_not_labelled` | unit_semantics | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `share_not_size` | unit_semantics | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `degree_not_weight` | unit_semantics | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_running` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `state_not_channel_failed` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `kind_not_channel` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `stage_not_mode` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `decider_not_mode` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |
| `shown_not_visible` | optional_filter | trap | 3 | first | 1 | 1/1 | 1/1 | asserted | PASS |  |

The `stance` column is the spectrum this instrument refuses to collapse: `asserted` / `hedged` / `both sides` / `transcribed mask` / `silent` / `unreadable`. `verdict` is the one pass/fail each probe needs and no more than that — a gate is a deployment's dial and not a measurement.

This is ROADMAP §2.9.3's gatekeeper. It decides the phase order of the 1.0→2.0 arc and nothing else: a wrong proposition in an epistemic store is worse than a wrong sentence in a transcript, because deterministic machinery then derives from it with confidence.