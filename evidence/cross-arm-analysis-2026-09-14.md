# Cross-arm request analysis — the handed-over 111 run dirs

Conducted 2026-09-14 on the platform's handover
(`judais-runs-2026-09-14/`, 69 champion-window "AM" dirs 03:00–08:59Z +
42 v1.4.0 "PM" dirs 10:1x–10:5xZ). Companion to
`diagnosis-v1.4.0-regression-2026-09-14.md`; this closes the one question
that document could not reach — whether the request CONTENT was identical
across arms.

## Verdict

**The requests are byte-identical across arms** after masking exactly one
pattern: a 143-character clause the platform's own MCP server added to its
`mcp.compute_nodes` tool description between the windows (the mesh apply —
it rides twice, once in the rendered catalogue and once in the tool
schema, hence a +286-char per-request delta, confirmed independently by
`core.eval context`). Nothing judais-lobi emits distinguishes the arms.
Only the model's output length moved.

Key results:

* **Masked system-prompt hash across all 214 mission calls in all 111
  dirs: one value.** Masked 48-tool block: one value. Every single-turn
  scenario's full first request hashes identically across windows (plot,
  plot_trig, install, governed, empty, web ×3, deepresearch ×2). No
  timestamp, date, run id, or nonce is injected into the prompt at all.
  Multi-turn scenarios differ only by the prior run's assistant answer —
  and two prior-answer hashes collide ACROSS windows (the model produced
  the identical prior answer in both), which is confirmation.
* **Sampling parameters constant to the last key**, 214/214 calls:
  `{stream: true, temperature: 0.2, tool_choice: auto, tools: [48]}`.
  No max_tokens, no top_p, no reasoning_effort, no seed — in EITHER
  window. Nothing on our side removed a cap that used to be there.
* **Completion tails**: AM max 3,166 tokens (a 72 s `governed` answer —
  ordinary, not a stall); PM max 8,794 (plot_trig, 214 s) and 7,096
  (followup_plot, 176 s). AM has ZERO calls ≥150 s; PM has five. Three PM
  runs wrote zero model records at all (first call never returned;
  orphaned) — the true PM tail is worse than the report showed.
* **Decode rate constant**: AM median 40.6 tok/s, PM 37.4; the two worst
  PM stalls decode at 41.1 and 40.3 tok/s — dead centre. The server was
  not slower; it emitted 4–8× more tokens at the same speed.
* **The v1.1.3 224 s ceiling run is NOT in the 69 AM dirs**, and the AM
  batch structure (3 evenly-spaced full reps of the 14-scenario set)
  looks like ONE arm's three reps — the v1.1.3 arm may not be in the
  handover at all. Arm separation inside AM was not possible: every
  candidate signal (schema, event vocabulary, mission_started fields,
  flags, prompt hash) is constant across all 111 dirs.
* **Context size did not move**: +0.31% chars/call, +0.16% prompt
  tokens/call (~89.3k per call both windows); system-side head
  byte-stable on every multi-call run. (First run of the merged
  `core.eval context` analyzer on real platform recordings — clean.)

## What remains

Two candidate causes, both platform-side, neither framework:

1. **The serving day** — a decode-length shift at temperature 0.2 with no
   seed; the discriminator the diagnosis named is now the only one left a
   recording cannot answer: the two vLLM launch lines and versions side
   by side (chat template, gpt-oss reasoning_effort default,
   max-model-len, prefix-cache settings).
2. **The 143-char mesh-apply clause** — the one real prompt delta.
   Unlikely on its face (a GPU-placement sentence no plot turn reads),
   but at 87k tokens on a 20b it is technically an arm. The queued
   plot×5 same-session A/B discriminates: both tags will share the
   current mesh text, so a tail that follows v1.4.0 only would exonerate
   the clause; a tail on both tags implicates the day.

Everything a recording can answer has been answered, and it exonerates
the framework twice over: byte-identical requests in, normal decode rate
throughout, 4–8× output length as the only moved variable.
