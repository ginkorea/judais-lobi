---
name: stub_plane
skill:
  skill_id: stub_plane
  when_to_use: >
    Working a small governed plane: a catalogue that describes assets and
    will not hand over their source, a run view too big for a transcript,
    a step that fails, and arithmetic. Nothing here reaches the host.
  allowed_tools:
    - echo
    - add
    - always_fails
    - governed_read
    - governed_view
    - add_a_tool
    - late_arrival?
    - mcp.run_shell_command
  # No `policy:` block, for the reason `stub_skill.md` has none: the three
  # lines that were here are the framework's own conduct
  # (`core/runtime/prompts.py`), which every mission now carries. The two
  # manifests have to stay identical field for field —
  # `tests/test_eval_live.py` says so — so this one lost them together
  # with the other.
  output_format: >
    Short prose. Every identifier and every figure exactly as the plane
    spelled it.
  grounding:
    identifier_pattern: '\b[a-z]{1,6}\.[0-9a-z]{4,}\b'
    number_pattern: '(?<![\w.])[+-]?\d(?:[\d,_]*\d)?(?:\.\d+)?(?![\w])'
    planes:
      catalogue:
        tools:
          - mcp.governed_read
          - mcp.governed_view
        claims:
          - i read the catalogue
          - i looked the asset up
          - i pulled the run view
          - according to the catalogue
      arithmetic:
        tools:
          - mcp.add
        claims:
          - i had the plane add
          - the plane did the arithmetic
          - the plane added
---

# The stub plane, with a plane declared

This is `stub_skill.md` — the same closed set, the same (absent) policy,
the same grounding grammar — plus one block: `planes:`. It exists because
`python -m core.eval measure` switches grounding tiers on and off, and one
of the three tiers cannot be switched on by a switch.

`reading: true` and `critic: true` are switches; the harness writes them.
`planes:` is a **table**: which tools constitute a tool family on this
deployment, and what an answer says when it claims to have used one. That is
data a deployment owns — a framework that invented it would be naming your
tool families for you — so `core/eval/measure.py` never writes a `planes:`
block, it only keeps or strips the one the manifest declares. A manifest
without one gets the `planes` row of the matrix **skipped, with that
sentence as the note**.

So this file is the manifest a measurement is pointed at, and `stub_skill.md`
stays the manifest the corpus is recorded under. `tests/test_eval_live.py`
asserts that the two frontmatters are identical apart from `planes:`, so the
copy cannot drift into a second, disagreeing declaration of the same plane.

The two planes are the two kinds of work this plane can actually do. The
claims are written as **work claims** and not as descriptions: "i read the
catalogue" is an assertion about what this run did, where "the catalogue
describes assets" is an answer explaining what the plane is for. The
distinction is the whole point of the check — an answer that says it looked
something up when nothing was dispatched is reporting work that did not
happen — and a claim list that failed to draw it would flag every honest
orientation answer.

Work the plane, then answer. If a step fails, say what you did get and mark
the rest as unverified — an answer with a caveat is worth more than a
refusal.
