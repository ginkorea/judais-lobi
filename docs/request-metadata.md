# Request identity, stop reasons and observation coverage

The existing `Ledger` remains the only token accumulator. Optional
`mission_finished.telemetry.request_tracking` records now distinguish logical
requests from physical HTTP attempts; none of the latter increments token
spend. Existing `usage` fields and `Usage.as_record()` are unchanged.

## Request and provider facts

Instrumented calls carry a minted `call_id`, optional `parent_call_id`, phase,
logical run identity and branch. The earlier `request_id` remains for existing
consumers; its counter can repeat after resume, so new consumers should use
`call_id` for unique identity. A replay makes new calls against its recording
and therefore receives new call IDs. Parent IDs are present only for an
observed continuation or synthesis repair, not inferred from chronological
adjacency. A missing parent is not evidence that there was no upstream work.

`call` carries provider, requested model and endpoint **origin only**. It never
copies URL userinfo, paths (including serving-consumer credentials), query or
fragment. Missing metadata remains null. Known secret-shaped/environment
values are removed by the shared scrubber before identity publication; opaque
unknown secrets cannot be recognized universally. Prompts, tool arguments,
document content, reasoning text and provider exception strings are excluded.

Provider stop reasons are captured independently of token usage through the
existing per-call `SideChannels`. Only a closed machine-code vocabulary is
published as `raw_stop_reason`; other values are marked unrecognized without
copying text. The normalized reason distinguishes completion, tool use,
output/context/token limits, refusal and provider pause. `model_length` is
deliberately the less-specific token limit. A failed/cancelled request has its
own ending rather than treating an earlier provider stop as successful return.
This telemetry does not change the answer-continuation policy, which still
uses its existing Usage stop-reason seam.

`usage_detail` names each count's reported/derived/missing provenance. Numeric
OpenAI-compatible cached-prompt and reasoning-completion fields are subsets;
Anthropic cache-read/cache-write input fields are separate input components,
not subsets of its uncached input count. Legacy Anthropic totals remain
uncached input plus output; these additional reported cache components do not
redefine the existing totals. Neither kind is automatically added to the
ledger. Visible output is unknown, never completion minus reasoning.
Arbitrary provider extras are not copied into telemetry.

## Coverage, not an assertion of completeness

Request records cover windowed mission calls and the staged routing, planning,
verification, synthesis and synthesis-repair calls that use the tracked plain
call owner. They do not claim all model calls anywhere in an application.
Custom no-window library callers retain their original ledger-only behavior.
The existing per-request character/framing estimates remain estimates, not
measured tokenizer occupancy. Context-capacity provenance remains independent.
Plain staged requests report zero native-tool schema tokens because they send
no native tool namespace. The existing window fitter may still conservatively
reserve the shared window's schema allowance; this telemetry does not change
that fitting policy or reinterpret its compaction thresholds.

Local and Mistral raw-HTTP backends report the number of observed transport
attempts. SDK-internal retries are not visible and are explicitly unavailable.
Per-attempt usage is unavailable, even when the logical request reports a total;
do not distribute that total among retries. Nested model calls made inside an
opaque tool, external verifier, supervisor or application service are not
measured by this record. Their absence is not a zero. An application must
instrument those owners separately before claiming complete nested usage.

Compaction receipts add their trigger, trigger/target input thresholds,
estimate method and structurally retained categories. The loop can also state
that its compaction note retains result-store handles and current-task
projection. This is retention of references, not a claim that every referenced
archive remains available. Earlier synthesis evidence-block selection and
unobserved external compaction are outside `instrumented_window_fits_only`
coverage. No compaction is inferred from cumulative token spend.

Records retain the existing first-256/latest bound; counters continue beyond
retention and omitted records remain explicit. Child-ledger absorption retains
phase coverage but does not invent a completion ordering or a global latest.
