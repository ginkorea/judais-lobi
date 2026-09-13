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
    - window_rollup
    - arithmetic
    - release_entry
  # No `policy:` block, for the reason `stub_skill.md` states at length:
  # the framework's own conduct is in every mission's system turn
  # (`core/runtime/prompts.py`), and a manifest that repeats it is the
  # second emitter this repository keeps paying for. What is left is what
  # is particular to THIS plane.
  policy:
    - The ledger and the audit are two sources. Where they disagree, give
      both figures and say which came from which; picking one silently is
      the failure this plane is built to catch.
    - A window summary and an entry record are not the same thing. A field
      that is in one is not in the other, and a figure is only an answer to
      the question its own field name asks.
  output_format: >
    Short prose. Every identifier and every figure exactly as the plane
    spelled it, and the field a figure came from named where two figures in
    one result could both be read as the answer.
  grounding:
    identifier_pattern: '\bled\.[0-9a-z]{2,}\b'
    number_pattern: '(?<![\w.])[+-]?\d(?:[\d,_]*\d)?(?:\.\d+)?(?![\w])'
---

# The bench plane

This is the skill `core.eval.benchmark_suite` is run under, and like
`stub_skill.md` it is a worked example as much as a fixture.

The closed set is the six tools `tests/bench_stub_server.py` serves, all of
them bare: none of them shares a name with a tool this process dispatches,
so none of them needs a namespace to keep a server from replacing a local
tool, and none of them runs code on this host.

The `policy:` block is two sentences and both are about **this plane**
rather than about agents in general. The first is the contradiction rule —
two sources, both quoted, neither silently preferred — which is the owner's
ruling that surfacing beats silence, written where a deployment would write
it. The second is the misleading-field rule: a result here can hold three
numbers of which exactly one answers the question, and the difference
between them is a field name.

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

Work the plane, then answer. If a call is refused, read what the refusal
says and act on it — a plane that names the fix has told you the next call,
and a capability is absent only where the catalogue or a refusal says so.
