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

## Extension — the v1.1.3 production window (78 dirs, second handover)

**The heavy tail already existed at v1.1.3, and it is worse there than at
v1.4.0.** The champion window is the only clean one of the three.

* Classification: 63 benchmark runs (three clean 14-scenario reps + one
  aborted partial + one full 27-scenario tier pass) / 13 tier-only
  singletons / 2 owner asks (set aside).
* **The 224 s run found and anatomized** (`b0ad00aa`, followup_plot
  turn 1 = plot): step 0 latency 212 s, **8,904 completion tokens at
  42.0 tok/s** — a clean matplotlib payload, produced too slowly for the
  pane's 220 s ceiling; the pane recorded `timeout` and launched turn 2
  into a dead harness while the turn-1 process ran on and `finished` at
  230.5 s. Identical signature to every v1.4.0 stall: long chain of
  thought at a dead-normal decode rate.
* v1.1.3's worst call: **15,926 tokens in one 402 s generation**
  (plot_trig) — 1.8× larger than anything in the v1.4.0 window. Three
  windows, all calls: v1.1.3 max 15,926 (three ≥4,000) · champion max
  3,166 (**zero** ≥4,000, zero steps ≥150 s) · v1.4.0 max 8,794 (two
  ≥4,000, five steps ≥150 s).
* **Request hashes: ten for ten identical across two release
  boundaries.** One masked system-prompt hash and one tool-block hash
  across all 408 mission calls in all three windows; every single-turn
  scenario's whole-request hash identical v1.1.3 = champion = v1.4.0.
  The mesh clause: 0/69 in v1.1.3, 0/43 champion, 39/39 v1.4.0 — absent
  from the window with the worst tail, so **the clause cannot be the
  cause**. Sampling params constant across all 408 calls; no event
  vocabulary drift at all across the releases; context size within 0.6%.
* **"The day" is too coarse.** The v1.1.3 production window
  (03:39–05:03Z) and the clean champion window (04:06–05:09Z) overlap
  by nearly an hour on the same platform: during the overlap, production
  drew a 212 s / 8,904-token stall while the benchmark harness, running
  byte-identical requests at the same decode rate, never exceeded 72 s.
  Same day, same hour, same bytes — one session tailed, one clean.

**Conclusion: the variable is per-session serving conditions** — which
node, which cards, which vLLM process a session landed on — not the
release, not the prompt, not the date. The v1.4.0 arm's 3/3 plot ceiling
is the same pre-existing failure mode drawn more often. The remaining
discriminator narrows to: the vLLM launch line, version, chat template
and reasoning-effort default **per serving process, per session**.
Everything a recording can answer is answered across three windows and
189 run directories, and none of it implicates the framework.

## Addendum — the v1.3.1 arm, and the censoring correction

* **v1.3.1's requests are bracketed, not hashed.** Its handover is
  pane-event format with no model requests recorded. What is measured:
  the pane's offered tool plane is byte-identical between the v1.3.1 and
  v1.4.0 arms (one tool_plane hash, 42/42 each); the arm is verifiably
  our tag (arm_sha = v1.3.1 = 605f919, venv parity 58/58); and the
  prompt-owning modules' whole v1.2.0..v1.4.0 diff is confined to
  mcp_client.py refusal-body capture, with both endpoints of the bracket
  measured byte-identical from raw recordings. Strong bracketed
  inference; the platform shipping the v1.3.1 arm's raw run dirs would
  close it to measurement.
* **Censoring correction.** In the one apples-to-apples per-turn
  comparison (v1.3.1 vs v1.4.0, same pane format, same scorer), v1.3.1
  generates MORE per call than v1.4.0 (415 vs 302 mean tokens/call) —
  v1.4.0 looks smaller only because five of its turns were killed
  before writing a ledger. Pane-format numbers are censored at exactly
  the top of the distribution; a turn the pane kills writes no ledger.
* **v1.3.1's plot stall anatomized**: a three-step turn — steps 0–1
  normal (31 s + 2 s), then step 2 ran ≥171 s with no output and no
  ledger before the 220.14 s kill (≈6,800 tokens at the four-window
  decode rate). Same mechanism, different step index.
* **The nine-runs table** (every `plot y=x^2` on 14 Sep, three releases,
  two panes, ONE request hash): first-call tokens run 550 → 8,904; the
  8,904 (v1.1.3 pane) and the 1,088 (champion pane) are thirteen
  minutes apart on the same pool. The tail is lease/session-scoped,
  not day-scoped — measured, not inferred.

## Final — the v1.3.1 bracket closed by direct measurement

The v1.3.1 arm's raw run dirs (42, handed over after the VPN returned)
confirm the bracketed inference in full: the mesh clause is PRESENT
(109/109 calls — it tracks the clock of the mesh apply, not the release),
the masked system-prompt and tool-block hashes match the other three
windows' single values, sampling parameters are identical, and all ten
single-turn scenarios now hash identical FOUR times over. Running total:
**517 recorded model calls across 231 run directories and four releases —
one request shape, zero drift.** Context spread across three release
boundaries: 0.6%.

The 220.14s plot stall's raw side adds a bound, honestly stated: the
recorder writes after the reply, so the killed call left no record — step 2
generated ≥171s silently, ≈6,800–7,200 tokens at the window's measured
decode rate, unbounded above. v1.3.1's recorded max (4,483) therefore
understates its true tail for the same censoring reason the pane numbers
did — the worst call of the window is exactly the one that left nothing.

Verdict unchanged and now unambiguous: the bisect gradient spans releases
whose requests are measured identical and runs in the wrong direction for
a framework story (the worst tail belongs to v1.1.3, two releases before
the "regression"). The open variable is the per-lease serving
configuration behind each pane — two panes, byte-identical prompts,
thirteen minutes apart, 8,904 vs 1,088 tokens. The framework is exonerated
on all four windows.
