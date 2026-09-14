# MODELS.md — adapting a model to judais-lobi

The framework is model-agnostic by contract: nothing in `core/` names a
model, and every model-facing behaviour is a declared capability, a flag, or
a measurement. **Adapting a model is therefore a process, not a port** — you
serve it, declare it, measure it, tune the runtime around what the numbers
say, and only then (and only if the residual is *capability* rather than
*conduct*) fine-tune it. This page is that process, in order. It exists
because the project deliberately does not peg itself to one model: the same
steps take a 20B through a 70B through a quantised edge model, and the
fine-tuning step is designed to be repeated per model, not amortised into
one blessed checkpoint.

Each step says whether it ships today, is landing, or is planned — a
process document that overclaims is worse than none.

## 1. Serve it *(ships today)*

Any OpenAI-compatible endpoint works: `--provider local --model <name>`
against vLLM, SGLang, or equivalent (hosted `openai`, `mistral` and
`anthropic` providers are the same door). The backend carries a capability
declaration (`core/runtime/backends/base.py`) and the runtime refuses at the
door what the backend does not declare, rather than failing mid-mission:

| capability | what it promises | who declares it today |
|---|---|---|
| `supports_streaming` | deltas arrive as they are produced | all four |
| `supports_json_mode` | the reply will be *some* JSON | `local`, `openai`, `mistral` |
| `supports_json_schema` | **the request carries a JSON schema** for the server to enforce while decoding (`response_format: {type: json_schema}`) — ROADMAP §2.9.5's grammar compiler. The promise stops at the request: whether the endpoint honours it is the endpoint's, and the consumer's validator is what catches a server that accepted the parameter and ignored it | `local`, `openai` |
| `supports_tool_calls` | tools declared as functions | `local`, `openai`, `anthropic` |
| `supports_parallel_tool_calls` | more than one call per reply | `local`, `openai`, `anthropic` |
| `supports_tool_choice_required` | the decoder must emit a call, not prose | `local`, `openai`, `anthropic` |

A declaration is a promise a caller plans against, so it is made from a
measured or documented-and-implemented parameter and never from a model
card: `mistral` declares the two constrained forms **absent** because
nothing here has run them against the live endpoint, and `anthropic`
declares `json_schema` absent because the Messages API expresses that
capability as a different request (`output_config.format`, strict tool
schemas) which this backend does not implement. Adapting a *new* backend
means declaring honestly and leaving the door shut where it does not apply
— a silently unconstrained run is the one outcome worse than a refused one.

Protocol: `--protocol json` is the floor and the default — every
instruction-following model speaks it. `--protocol native` (function
calling with `tool_choice=required` and schema-checked arguments) is opt-in
per deployment and should be turned on only after step 2 measures it better
for *this* model, not assumed from the model card.

## 2. Baseline it *(ships today; one instrument landing)*

Nothing about a model is believed until measured, and no number travels
without its interpreter: **model + temperature + endpoint beside every
figure**. The instrument-variance lesson is binding — a 20-scenario tier at
a 20B is 20 dice landing 14–16, so every comparison states its `n` and
pairs its arms; a lucky single is not a result.

- `core.eval check | run | score | measure` (see `EVAL.md`) — behavioural
  rates on recorded and live missions; `--replay` re-scores yesterday's
  runs after a change, no GPU needed.
- `core.eval extraction` *(landing — Phase 16 instrument)* — semantic
  reliability: real recorded receipts in, typed propositions with
  abstention out, scored mechanically (value-and-field existence via the
  grounding harvester) plus trap classes built from measured production
  misreads (elapsed-seconds-read-as-score, optional-filter fields). This
  number is what Phase 19's A/B and any fine-tune are judged against.
  Run it **twice on a model that declares `supports_json_schema`**, once
  with `--constrained` and once without: the difference in `structural`,
  `first_try` and `repair` is what constrained decoding is worth on *this*
  model, and it is usually the cheapest lift available (ROADMAP §2.9.5).
  The two runs are two experiments and the instrument says so — the
  fingerprint and the identity line carry the decoding, and `--baseline`
  warns when a constrained report is paired against an unconstrained one.
  A model whose backend cannot enforce a grammar is refused rather than
  measured as if it had one.
- `core.eval corpus` is not an instrument and measures nothing — it is
  step 4.1's builder, listed here only because the same reports feed both:
  a report you measured with is a report you can train from.
- Conduct adherence is a measured property of the model, not an assumption:
  the reference 20B binds instructions placed *last* (why the conduct
  renders after the catalogue), followed the conduct roughly half the time,
  and sat at the edge of usable at ~20 offered tools. Expect these numbers
  to differ per model; measure them rather than inheriting them.

## 3. Tune the runtime around the numbers *(ships today)*

Everything here is a deployment knob, never a core edit:

- **Temperature** belongs to the platform's calls, not the framework.
- **`--mcp-timeout` / `MCP_TIMEOUT_S`** — a slower plane or model needs a
  longer leash (the reference platform runs 120 s against a 30 s default).
- **Tool surface** — keep the offered set near what the model can select
  from reliably (measured edge for a 20B: about 20); skills' closed sets
  and composition (`PLATFORMS.md` §Composing skills) are the lever.
- **Schema shaping** — prefer required-or-absent over optional-filter
  parameters on agent-facing tools; a 20B filled an optional
  `submitted_via` filter 8 runs of 8 and hid the real data from itself
  (`PLATFORMS.md`).
- **`--compiled-context`** — put the runtime's view of the problem into
  each step's input instead of leaving the model to re-read the transcript
  for facts the runtime already holds. The knob a *weaker* model is most
  likely to need: it is off by default, it implies `--cognition`, it costs
  up to 4,000 characters of the window, and whether it pays is a measured
  question per model — run it as the `compiled-context` arm of
  `python -m core.eval ablation` against your own baseline before turning
  it on for a deployment.
- **Grounding strictness** — the tiers are off by default, `--no-grounding`
  exists, and the owner's ruling stands: evidence is great, a functioning
  harness is better. Turn checks on where the measurements say the model
  needs them, not everywhere.

## 4. Fine-tune — per model, when the residual is capability *(process ships; step 1 ships, steps 2–4 planned — Phase 21)*

First separate conduct from capability: if a failure closes when the
prompt, ordering, timeout or schema changes, it was conduct — no weights
needed. The reference iteration's residual (`staged_arithmetic` 0/4,
`label_set_choice` 1/4, stable across five release candidates of runtime
change) is what a *capability* residual looks like, and that is what
fine-tuning is for.

The loop, repeatable per model:

1. **Corpus from validated traces** *(ships today — `core.eval corpus`)* —
   recorded runs (`EVAL.md` §10) where the behaviour was right, and the
   extraction instrument's passing attempts; heavy on abstention (a useful
   model must know when *not* to create a fact). Scrub credentials;
   principals become roles.

   ```
   python -m core.eval corpus --out corpus.jsonl \
       --from-extraction evidence/extraction/<report>.json \
       --probes tests/fixtures/extraction/probes.jsonl \
       --from-runs ~/runs --note "<whose data this is>"
   ```

   What it writes is `{messages, completion, meta}` per line under a header
   carrying the counts, the abstention share and the scrub statement, and it
   prints a sha256 of the file — **the corpus is an experiment input, so it
   carries an identity** and a tuned checkpoint can name which bytes it was
   tuned on. The one rule: a completion is the model's own reply, copied,
   **never** a synthesised ideal answer. Training on imagined behaviour is
   how a tune moves prose quality and moves no rate.

   The bar and the honest v1 bounds are in `EVAL.md` §17: only attempts that
   *passed* their probe and runs that *answered* with the grounding
   satisfied; no synthetic repair and no editing; a `--protocol native` turn
   has no text completion to copy and is counted rather than rendered into
   one. `--balance` downsamples the assert half to the abstention floor
   (0.40 by default, warned and never enforced) deterministically, so two
   people building from the same report get the same file.
2. **Train an adapter** (LoRA-class) per model — never fold one model's
   adapter into the framework's assumptions.
3. **Evaluate as reliability, not fluency** — the same instruments as step
   2, base vs tuned, paired, `n` stated. A tune that moves prose quality
   but not the extraction or mission rates did not work.
4. **Record the result** beside the model identity, so the next person
   knows what this checkpoint was tuned *for*.

## 5. Register the profile *(the store ships today — v1; routing still planned, Phase 20)*

The last step of the loop is writing the numbers down somewhere a later
reader finds them **beside the interpreter that produced them**.
`evidence/registry.json` is that place, and `python -m core.eval registry`
is the only way in:

```
python -m core.eval registry add <report.json>    # extraction | ablation | measure
python -m core.eval registry show [--model NAME]
python -m core.eval registry rm <digest>
```

**Nothing is hand-entered.** `add` takes a report file one of the three
measuring subcommands wrote, reads its identity sentence and its `k`/`n`,
and refuses a shape it does not recognise or a report whose `meta` does
not name a provider and a model — a figure without the model that produced
it is not a measurement of a model. Re-adding the same bytes is a quiet
no-op (the file's SHA-256 is the key). The endpoint is recorded as
`scheme://loopback|private|public` and never as a host, because this file
is committed and other people's reports pass through it.

What `show` renders is a **table per model, split by interpreter** —
subcommand, temperature, decoding, prompt digest, scorer, endpoint class —
with `n` beside every figure, an interval from the package's one Wilson,
an *insufficient sample* mark and **no interval** below n = 20, and the age
of the newest measurement. Two measurements on different interpreters are
two rows and are never averaged: **a profile is the table, never a
number.** `EVAL.md` §16 is the full account, including why the floor is 20.

**It does not route, and nothing in the runtime reads it.** ROADMAP §2.9.7
admits routing only when differences are statistically meaningful, so v1
is the evidence a router would have to read first. Four things have to be
true before routing lands: two models measured on the *same* interpreter;
both above n = 20 with non-overlapping intervals on the figure being routed
by; a figure that names the obligation rather than ranking models in
general; and a staleness rule, since an endpoint's weights, quantisation
and server defaults move with nothing in any log.

---

The one-sentence version: **serve, declare, measure, adapt the knobs,
fine-tune the residual, and write every number down with its interpreter**
— that last clause is §5, and it is a file now rather than a habit.
A model adapted this way can be swapped for another by repeating the steps
— which is the point.
