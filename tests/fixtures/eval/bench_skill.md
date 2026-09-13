---
name: bench_plane
skill:
  skill_id: bench_plane
  when_to_use: >
    Working a small governed ledger: entries that have to be listed before
    they can be read, an audit that is allowed to disagree with the
    ledger, window summaries, a calculator, and a release that refuses
    every token but the one an entry's own record carries. Nothing here
    reaches the host.
  allowed_tools:
    - ledger_index
    - ledger_entry
    - audit_count
    - window_index
    - window_rollup
    - arithmetic
    - release_entry
  # No `policy:` block, and its absence is the point here twice over.
  # `stub_skill.md` states the first reason at length: the framework's own
  # conduct is in every mission's system turn (`core/runtime/prompts.py`),
  # and a manifest that repeats it is the second emitter this repository
  # keeps paying for.
  #
  # The second reason belongs to a BENCHMARK. This manifest first carried
  # two lines — give both figures where two sources disagree; a figure only
  # answers the question its own field name asks — plus a closing paragraph
  # telling the model that a refusal names the next call. Those are the
  # answers to three of the six classes, written where the model would read
  # them. A pack whose manifest solves its own missions measures the
  # manifest. What is left is the closed set, the output shape and the
  # grammar the suite is scored with, and none of those names a failure
  # mode.
  output_format: >
    Short prose. Every identifier and every figure exactly as the plane
    spelled it.
  grounding:
    identifier_pattern: '\bled\.[0-9a-z]{2,}\b'
    number_pattern: '(?<![\w.])[+-]?\d(?:[\d,_]*\d)?(?:\.\d+)?(?![\w])'
---

# The bench plane

This is the skill `core.eval.benchmark_suite` is run under, and like
`stub_skill.md` it is a worked example as much as a fixture.

The closed set is the seven tools `tests/bench_stub_server.py` serves, all
of them bare: none shares a name with a tool this process dispatches, so
none needs a namespace to keep a server from replacing a local tool, and
none runs code on this host.

The grounding grammar is the half that makes the suite scoreable without a
reader. `identifier_pattern` catches a ledger id the answer names and no
tool returned — the fabrication the `absence` missions are written for —
and `number_pattern` is the figure grammar from `NumericGroundingCheck.
FIGURE` itself, so a figure in an answer and a figure in a payload are
found the same way.

What the grammar deliberately does **not** catch is the misleading class:
`154.024` is a real figure from a real receipt, and every check that asks
only "did this number come from a tool" passes an answer built on it. That
is the point of those two missions, and the reason the class is in the
pack: it is the failure a runtime has to hold the problem to prevent, and
no grounding grammar will.

Work the plane, then answer.
