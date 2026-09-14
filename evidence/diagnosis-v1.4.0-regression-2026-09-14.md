# v1.4.0 completion regression — diagnosis

Conducted 2026-09-14 by a local diagnosis lane against the transcripts the
reference platform delivered (ablate-v1.4.0-2026-09-14T10-14-05Z, 39 files)
and both tag worktrees. Pool untouched (standing constraint). The three
benchmark scripts referenced below run from any checkout and lived at
`~/data/tmp/diag-v14-regression/{bench_step,bench_windup,bench_mcp}.py`
when this was written.

## Verdict

**No judais-lobi change between v1.2.0 and v1.4.0 can produce the observed
stall, and two independent lines of evidence kill each named hypothesis.**
The stall is *one model call that generates for 176–292 s*. The flags-off
request path did not move between the tags: prompt bytes identical, request
parameters identical, per-step Python cost identical — all three measured,
not argued. The regression is attributable to the measurement conditions,
not the framework.

## 1. What the transcripts show

Every ceiling event has one shape: `STEP_STARTED`, then a single model call
that never returns inside the 220 s turn ceiling.

| case | step | STEP_STARTED → next event | next event |
|---|---|---|---|
| `plot` run 1 | step 0 | **>218 s**, no further event | — |
| `plot` run 2 | step 0 | **>218 s**, no further event | — |
| `plot` run 3 | step 0 | **214 s** | `TOOL_CALL_START mcp.run_code` |
| `coref` run 1 turn 2 | step 0 | **>272 s**, no further event | — |
| `followup_plot` run 2 turn 2 | step 0 | **176 s** | `TOOL_CALL_START mcp.run_code` |

Over all 98 model calls in the three runs: **median 6.0 s, p90 18.0 s**,
then 176, 214, and four that never terminated. A heavy right tail on the
code-writing turns.

Three facts pin the mechanism:

1. **No `model_state` event fires during any stall.** The backend raises
   `queued` after `FIRST_BYTE_QUEUED_S = 20.0` of silence, and it *did*
   fire on a genuinely cold call (`coref` run 1 turn 1: queued at 20 s,
   loaded at 34 s). Its absence means the first byte arrived inside 20 s —
   the call was **streaming**, not queued, not blocked.
2. **Where the stalled call finished, it finished correctly.** `plot` run 3
   emitted a complete, sensible `mcp.run_code` payload (matplotlib,
   `savefig`, `wait_s: 60`) at 214 s. Nothing malformed; the model simply
   took 214 s.
3. **Arithmetic.** These runs decode at ~20–25 tok/s (`followup_plot`
   run 3 turn 2: 2306 completion tokens across 97 s of step time).
   176–214 s ≈ **4,000–5,300 completion tokens** on a turn whose median
   sibling produces 150–700. The model wrote a chain of thought 5–10×
   normal length.

## 2. Hypothesis #1 — the Phase 19b supervisor rework. DEAD.

*Transcripts.* Every stall is a run of 1–3 steps that never got past its
first model call. A wind-up regression needs a run that keeps stepping —
there is none here, and no review/nudge/steer event appears anywhere in
the three runs.

*Local repro* (`bench_windup.py`, same file in both worktrees; scripted
backend repeating one identical tool call forever, `Bounds()` defaults,
cognition off): mission asks before wind-up 12 vs 12, review turns 4 vs 4,
termination `stuck` vs `stuck`. Identical for scripted verdicts `stuck`,
`progressing`, `nudge`.

*Code.* `FROZEN_FRONTIER` cannot fire without a `progress` reading carrying
every name in `supervisor.READING`; `Run._cognitive_progress()` returns
`None` whenever `store.cognition is None` — every run without
`--cognition`/`--compiled-context` — so `_frozen_frontier` returns `False`
on its first line. `NEVER_WINDS_UP` contains **only** `FROZEN_FRONTIER`,
so both new escape hatches are unreachable flags-off, and `_ask`'s
fallback always yields `STUCK` for procedural signals because `verdicts`
is the full triple there.

## 3. Hypothesis #2 — the MCP refusal-body capture (313cb1c). DEAD.

*Transcripts.* 54 MCP calls across the three runs: **median 1.0 s, max
26.0 s** (a `web_search`). None near the 120 s the pane passes. Every
stall is *before* its turn's first `TOOL_CALL_START` — no MCP call is in
flight during any of them.

*Local repro* (`bench_mcp.py`, repo's own stub server over real
streamable HTTP, 40 `call_tool` round trips): median 12.25 ms (v1.2.0)
vs 10.96 ms (v1.4.0) — v1.4.0 marginally *faster*. The hook returns on
`status < 400` before touching the body.

*Timeout plumbing intact:* `DEFAULT_TIMEOUT_S = 30.0` is the same literal
v1.2.0 had inline at three constructor defaults; the flag→fleet→client→
`future.result` chain is unchanged. The v1.3.1 consolidation changed the
*spelling* of the number and the refusal *sentence*, not the number or
the wait.

## 4. Hypothesis #3 — everything else reachable. Nothing found.

Every reachable hunk read; all inert with their arguments absent.
Positive exclusions, measured:

1. **The prompt-owning modules did not change at all.**
   `git diff v1.2.0..v1.4.0 --stat` over `prompts.py`, `grounding.py`,
   `context_window.py`, `mission.py`, `core/tools/`, `core/agent/`
   returns `core/tools/mcp_client.py` and **nothing else**.
2. **The replay corpus is byte-identical between the tags**, and each
   tag's own guard passes against it (114 passed in each).
3. **`bench_step.py`** (48 tools × 6 KB descriptions, 12 steps, flags
   off): prompt bytes per call identical to the byte (291,655 on call 0
   and the same sequence after), per-step Python cost identical
   (~1.5 ms), outcome identical.

## 5. What did change — ranked, with the discriminator for each

1. **The serving environment (most likely).** Different days, different
   card pairs (champion 2+3, this arm 0+1), sessions that did not share a
   pool. Anything lengthening the 20b's chain of thought on code-writing
   turns produces exactly this profile — easy missions flat or *faster*
   (`pivot` 82.7→56 s, `governed` 66.7→44 s, `deepresearch` 26.7→18.7 s
   mean), code missions 4–10×. Candidates: vLLM version/launch line, chat
   template or gpt-oss `reasoning_effort` default, `--max-model-len`,
   prefix-cache settings. **Discriminator: the two vLLM launch lines and
   versions side by side.**
2. **The platform's own system prompt moved.** Every call carries
   **~87,000 prompt tokens** — the platform's 48-tool catalogue plus six
   skills; framework text is a rounding error in it. The report's own
   conditions line records the service tree's newest file at
   `2026-09-14T00:09:16Z`, **after** the champion row was measured
   (`2026-09-13T19:10:49`). At 87k tokens a model's behaviour is not
   stable under a catalogue edit. **Discriminator, cheapest by a
   distance: per-call `prompt_tokens` from the champion run's ledger
   events, compared with 87k.** If the base prompt moved, the tool plane
   was an arm, not a constant.
3. **n = 3 on a heavy-tailed instrument.** The same harness's **v1.1.3**
   arm already hit this ceiling once — `followup_plot` run 1, 224.16 s,
   `ended: ["timeout","finished"]` — so the failure mode predates v1.4.0
   by two releases. **Discriminator: `plot` ×5 on both tags in one
   session on one card pair.**
4. **Environment leakage into the new flag (low, free to check).**
   `JUDAIS_LOBI_COMPILED_CONTEXT` is new in v1.3.0 and implies
   `--cognition`. It would not explain a 214 s call, but it would mean
   the arm was not flags-off. **Discriminator: `reasoning.jsonl` in the
   arm's run directories.**

## 6. What a follow-up release should carry

**No v1.4.0 defect was found, so nothing reverts.** The instrumentation
whose absence made this take six passes instead of one — all additive,
none changes the flags-off path:

1. **A `model_state` report for a call that is still streaming.**
   `FIRST_BYTE_QUEUED_S` catches a server that says nothing; nothing
   catches a call that trickles for 200 s — which is why every stall
   here is a hole in the event stream rather than a fact.
2. **An output bound the mission path actually sets.** The mission path
   sends **no `max_tokens` at all**, so a served endpoint lets the model
   run to `max_model_len − prompt_tokens`. Pre-existing (identical in
   v1.2.0), and it is the mechanism that turns a long chain of thought
   into somebody else's 220 s ceiling instead of a bounded, visible
   truncation the harness can report.
3. **Per-call `prompt_tokens` on the wire**, not only the turn's ledger
   total. The single most useful number in this investigation was
   reachable only by dividing a turn total by a call count.

**For the platform:** re-measure both arms in one session on one card
pair, recording the vLLM launch line and per-call `prompt_tokens` as
conditions. Wall clock was already flagged as the weakest criterion for
being measured across days; on this evidence **completion is measured
across days too**, and inherits the same weakness. The pin-forward
decision should not be made on this ablation as it stands.
