# tests/test_cognition_compile.py — the view, compiled from a store alone

"""``compile_view`` is pure, so this file needs no mission and has none.

``ROADMAP.md`` §2.9.5 asks for the *context compiler*: the problem state as
the smallest useful model input.  :mod:`core.cognition.compile` is the whole
of the compiling and it takes a :class:`~core.cognition.state.CognitiveState`
and a budget — no run, no store, no clock — which is exactly what makes it
testable as a *unit*: every claim below is "this state is worth this block",
stated in milliseconds.

Four things are load-bearing and each has its own section:

* **what is in the block** — the facts with the receipt handle each came
  from, both sides of every open conflict, and the model's own claims kept
  apart from both;
* **what the bands say** — five authorities, four words, and ``None`` is
  not the bottom of the scale but a refusal to grade;
* **what the budget does** — a hard cap, and never a silent one;
* **that it is deterministic** — the same state, the same bytes, and a
  digest that says so without pasting the block into an assertion.

The runtime half — the flag, the injection point, the failure isolation and
the corpus — is ``tests/test_cognition_compiled_context.py``.
"""

import json

import pytest

from core.cognition import (CognitiveState, EvidenceAuthority, EvidenceRef,
                            compile_view)
from core.cognition import compile as mod
from core.cognition.compile import (BANDS, BUDGET_CHARS, CONFLICTS_HEADING,
                                    DISPUTED, FACTS_HEADING,
                                    HYPOTHESES_HEADING, OMITTED, TITLE,
                                    UNGRADED, CompiledView, band)


def receipt(handle: str) -> EvidenceRef:
    """The evidence a deterministic harvest makes, in this file's shape."""
    return EvidenceRef(kind="receipt", locator=f"run-1/{handle}/mcp.tool")


def observe(state: CognitiveState, entity: str, field: str, value,
            authority: EvidenceAuthority = EvidenceAuthority.DETERMINISTIC
            ) -> str:
    return state.assert_observation(
        (entity, field, value), evidence=(receipt(entity.split("#")[-1]),),
        authority=authority)


def guess(state: CognitiveState, entity: str, field: str, value,
          authority: EvidenceAuthority = EvidenceAuthority.MODEL_HYPOTHESIS
          ) -> str:
    return state.assert_hypothesis(
        (entity, field, value),
        evidence=(EvidenceRef(kind="model", locator="step-2"),),
        authority=authority)


@pytest.fixture
def ledger() -> CognitiveState:
    """Three receipts, one of them disagreeing with another about a figure.

    ``units`` is declared ``one`` because that is the only way a store is
    ever asked to notice a collision — the kernel's default is ``many``, on
    the grounds that a false ``CONTESTED`` is destructive — and a fixture
    that did not declare it would be testing a conflict section against a
    state that has no conflicts in it.
    """
    state = CognitiveState()
    state.declare_field("units", "one")
    observe(state, "mcp.ledger_entry#r1", "units", 120)
    observe(state, "mcp.ledger_entry#r2", "units", 86)
    observe(state, "mcp.audit#r3", "units", 47)
    observe(state, "mcp.audit#r3", "checked", True)
    # A model's claim about a figure the store observed. It moves nothing —
    # the hypothesis stays hypothesized and the receipt stays live — and it
    # is the conflict a shadow run actually produces: the v1 harvest gives
    # each receipt its own entity, so two receipts never collide with each
    # other, and the disagreements that exist are a model against a receipt.
    guess(state, "mcp.audit#r3", "units", 50)
    return state


def _imports() -> list:
    """Every module :mod:`core.cognition.compile` imports, off the AST."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "core" / "cognition"
              / "compile.py").read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


def lines_of(view: CompiledView) -> list:
    return view.text.splitlines()


def section(view: CompiledView, heading: str) -> list:
    """The lines under one heading, up to the next blank line."""
    lines = lines_of(view)
    assert heading in lines, view.text
    out = []
    for line in lines[lines.index(heading) + 1:]:
        if not line:
            break
        out.append(line)
    return out


# ── what is in the block ─────────────────────────────────────────────────────


class TestTheFactsCarryTheirReceipts:
    """Every fact line is true on its own.

    The discipline the whole harness is built on — a figure is quoted with
    where it came from — applied to the one place a model is *handed*
    figures.  A block whose lines needed a heading to say which receipt
    they belonged to would be one scroll away from a figure attributed to
    nothing.
    """

    def test_a_fact_is_entity_field_value_and_a_band(self, ledger):
        view = compile_view(ledger)
        assert "mcp.ledger_entry#r1 · units = 120  [verified]" in \
            section(view, FACTS_HEADING)

    def test_every_fact_line_names_its_entity(self, ledger):
        for line in section(compile_view(ledger), FACTS_HEADING):
            assert line.split(" · ")[0].startswith("mcp."), line

    def test_the_value_keeps_its_type(self):
        """``8`` and ``"8"`` are different receipts and must not read the
        same: the shadow drops a string rather than convert it precisely
        because the conversion is the lie, and a renderer that printed both
        as ``8`` would put the lie back one layer up."""
        state = CognitiveState()
        observe(state, "t#r1", "count", 8)
        observe(state, "t#r2", "count", "8")
        rendered = section(compile_view(state), FACTS_HEADING)
        assert any("count = 8  [" in line for line in rendered), rendered
        assert any('count = "8"  [' in line for line in rendered), rendered

    def test_a_boolean_is_a_boolean(self, ledger):
        assert any("checked = true" in line
                   for line in section(compile_view(ledger), FACTS_HEADING))

    def test_one_entity_s_facts_are_contiguous(self, ledger):
        entities = [line.split(" · ")[0]
                    for line in section(compile_view(ledger), FACTS_HEADING)]
        assert len(set(entities)) == len(
            [name for index, name in enumerate(entities)
             if index == 0 or entities[index - 1] != name])

    def test_the_newest_entity_is_first(self, ledger):
        """Recency, and it is the store's insertion order rather than a
        clock: there is no clock in the kernel, and a view that sorted on
        one could not be replayed."""
        first = section(compile_view(ledger), FACTS_HEADING)[0]
        assert first.startswith("mcp.audit#r3")

    def test_a_retracted_claim_is_not_a_fact(self, ledger):
        """Contesting takes both sides out of belief, and a view that went
        on rendering them would be showing the model a figure the store has
        stopped standing behind."""
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "t#r1", "units", 120)
        observe(state, "t#r2", "units", 999)
        state.refute(state.claim(("t#r1", "units", 120)),
                     evidence=(receipt("r9"),))
        assert not any("units = 120" in line
                       for line in section(compile_view(state),
                                           FACTS_HEADING))

    def test_the_header_counts_the_receipts_under_the_facts(self, ledger):
        view = compile_view(ledger)
        assert lines_of(view)[0].startswith(TITLE)
        assert "compiled from 3 receipts" in lines_of(view)[0]
        assert view.receipts == 3

    def test_an_empty_state_compiles_to_nothing_at_all(self):
        """Not a heading over nothing: a mission that has taken no receipt
        gains nothing from this feature and must pay nothing for it."""
        view = compile_view(CognitiveState())
        assert view.text == ""
        assert not view
        assert not view.truncated


class TestBothSidesOfEveryConflict:
    """The owner's rule of 13 September 2026, rendered.

    Surfacing both sides beats silence, and a compiled view that quietly
    picked one would be the laundering the kernel's two doors exist to
    stop.  So the line names both claims and both handles, and a reader can
    go and look at either.
    """

    @pytest.fixture
    def contested(self):
        state = CognitiveState()
        state.declare_field("units", "one")
        # ONE entity, two receipts about it — which is a rule pack's world
        # rather than the raw harvest's, and the shape a `value` collision
        # needs: the kernel collides on `(entity, field)`, so two receipts
        # each carrying their own entity disagree about nothing.
        state.assert_observation(("led.a41", "units", 120),
                                 evidence=(receipt("r1"),),
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.assert_observation(("led.a41", "units", 98),
                                 evidence=(receipt("r2"),),
                                 authority=EvidenceAuthority.DETERMINISTIC)
        return state

    def test_the_line_names_both_sides(self, contested):
        line = section(compile_view(contested), CONFLICTS_HEADING)[0]
        assert "led.a41 · units = 120" in line
        assert "led.a41 · units = 98" in line

    def test_the_line_names_the_kind(self, contested):
        assert section(compile_view(contested),
                       CONFLICTS_HEADING)[0].startswith("value:")

    def test_a_model_s_disagreement_is_a_conflict_too(self):
        """The signal the shadow layer wants before any other — the model
        said one thing and the receipt said another — and the kernel moves
        no status for it, so both sides are still live and both are here."""
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "t#r1", "units", 120)
        guess(state, "t#r1", "units", 999)
        line = section(compile_view(state), CONFLICTS_HEADING)[0]
        assert line.startswith("hypothesis:")
        assert "units = 999" in line and "units = 120" in line

    def test_a_refutation_names_the_claim_and_says_it_was_refuted(self):
        """The one kind with no second proposition: the other side is the
        evidence somebody unseated it with, and the kernel's own detail is
        what the line carries in its place."""
        state = CognitiveState()
        pid = observe(state, "t#r1", "units", 120)
        state.refute(pid, evidence=(receipt("r9"),))
        line = section(compile_view(state), CONFLICTS_HEADING)[0]
        assert line.startswith("refutation:")
        assert "t#r1 · units = 120" in line
        assert "refuted" in line.split(" ⇄  ")[1]

    def test_a_settled_conflict_is_history_and_not_here(self, contested):
        """``settle`` is the one way out of a contradiction and it is an
        evidenced judgement somebody made. A view still reporting it would
        be asking the model to re-decide what a person already decided."""
        clash = contested.contradictions()[0]
        contested.settle(clash.id, keep=clash.left,
                         evidence=(receipt("r9"),))
        assert CONFLICTS_HEADING not in compile_view(contested).text

    def test_a_contested_fact_is_marked_where_it_still_shows(self):
        """A ``hypothesis`` collision moves no status, so the observation
        is still a live fact — and quoting it alone is exactly the mistake
        the mark exists to prevent."""
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "t#r1", "units", 120)
        guess(state, "t#r1", "units", 999)
        line = [row for row in section(compile_view(state), FACTS_HEADING)
                if "units = 120" in row][0]
        assert DISPUTED in line


class TestAGuessIsNeverAFact:
    def test_a_hypothesis_is_in_its_own_section(self):
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        guess(state, "t#r2", "units", 999)
        view = compile_view(state)
        assert "units = 999" in "\n".join(
            section(view, HYPOTHESES_HEADING))
        assert not any("units = 999" in line
                       for line in section(view, FACTS_HEADING))

    def test_the_sections_are_in_the_documented_order(self):
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "t#r1", "units", 120)
        observe(state, "t#r2", "units", 86)
        guess(state, "t#r2", "units", 999)
        text = compile_view(state).text
        assert text.index(FACTS_HEADING) < text.index(CONFLICTS_HEADING) \
            < text.index(HYPOTHESES_HEADING)

    def test_a_guess_is_dropped_before_a_fact_is(self):
        """The one trade this block must never make: a model's claim goes
        before a receipt's figure does.

        Budgeted a few hundred characters under the whole view, which is
        the scale at which the question is real — the omission sentence is
        itself a line, so a block small enough that the sentence costs more
        than the section it replaces cannot truncate at all, and compiles
        to nothing instead. That floor is its own test below.
        """
        state = CognitiveState()
        for index in range(30):
            observe(state, f"t#r{index}", "units", index)
        for index in range(10):
            guess(state, f"t#g{index}", "route", f"road-{index}")
        whole = compile_view(state)
        tight = compile_view(state, budget_chars=len(whole.text) - 100)
        assert tight.hypotheses_omitted
        assert tight.facts_omitted == 0
        assert "units = 29" in tight.text


# ── what the bands say ───────────────────────────────────────────────────────


class TestTheFourBands:
    """Five authorities, four words, and one refusal that is not a word.

    A reader deciding whether to trust a figure needs "a model interpreted
    this" and "a model guessed this" to land in the same place; the kernel
    still holds the difference for anything that needs it.
    """

    def test_every_authority_has_a_band(self):
        for authority in EvidenceAuthority:
            assert authority in BANDS, authority

    def test_the_bands_are_the_four_words(self):
        assert set(BANDS.values()) == {"verified", "sourced",
                                       "model-extracted", "speculative"}

    @pytest.mark.parametrize("authority,word", [
        (EvidenceAuthority.DETERMINISTIC, "verified"),
        (EvidenceAuthority.SOURCE, "sourced"),
        (EvidenceAuthority.MODEL_EXTRACTION, "model-extracted"),
        (EvidenceAuthority.MODEL_INTERPRETATION, "speculative"),
        (EvidenceAuthority.MODEL_HYPOTHESIS, "speculative"),
    ])
    def test_each_authority_renders_as_its_band(self, authority, word):
        assert band(authority) == word

    def test_no_grade_is_not_the_bottom_of_the_scale(self):
        """``support`` returns ``None`` for a claim the store has stopped
        standing behind, and rendering that as a weak grade would turn a
        refusal into an opinion — which is what its own docstring says."""
        assert band(None) == UNGRADED
        assert UNGRADED not in set(BANDS.values())

    def test_the_grade_is_on_every_fact_line(self, ledger):
        for line in section(compile_view(ledger), FACTS_HEADING):
            assert line.rstrip().endswith("]"), line
            assert any(word in line for word in BANDS.values()), line

    def test_a_sourced_receipt_is_not_a_verified_one(self):
        state = CognitiveState()
        observe(state, "t#r1", "units", 120,
                authority=EvidenceAuthority.SOURCE)
        assert "[sourced]" in compile_view(state).text


# ── what the budget does ─────────────────────────────────────────────────────


class TestTheBudgetIsHardAndNeverSilent:
    """Truncation that says nothing is the defect this section exists for.

    §2.9.5 requires a widening escape from day one: the compiled view may
    omit the decisive clue, and the model must be able to reach past it.
    v1's escape is the cheapest one there is — the receipts are still in
    the transcript — and the sentence that says so is the whole of it.
    """

    @pytest.fixture
    def wide(self):
        state = CognitiveState()
        for index in range(40):
            observe(state, f"mcp.ledger_entry#r{index}", "units", index)
        return state

    def test_the_default_is_the_module_s_one_number(self, wide):
        assert len(compile_view(wide).text) == len(
            compile_view(wide, budget_chars=BUDGET_CHARS).text)

    def test_the_cap_is_never_exceeded(self, wide):
        for budget in (4000, 2000, 900, 400, 250):
            assert len(compile_view(wide, budget_chars=budget).text) <= budget

    def test_what_was_dropped_is_counted_in_the_block(self, wide):
        view = compile_view(wide, budget_chars=900)
        assert view.facts_omitted
        assert OMITTED.format(what=f"+{view.facts_omitted} facts") in view.text
        assert "transcript" not in view.text

    def test_the_escape_points_at_the_result_store(self, wide):
        """NOT at the transcript. This block is window pressure like
        anything else — at a tight window the reviewer measured two tool
        round trips evicted to make room for one view — so a sentence
        promising the receipts are "above" can be falsified by the block
        that promised it. The result store cannot be evicted, and every
        fact line already prints the handle that addresses it."""
        text = compile_view(wide, budget_chars=900).text
        assert "result store" in text
        assert "handle" in text
        assert "transcript" not in text

    def test_a_block_too_small_for_its_own_sentence_compiles_nothing(self):
        """The floor the test above leans on, stated on its own.

        The omission sentence is a line, so a view with two lines in it
        cannot truncate to one and still explain itself. Rather than lie by
        omission or exceed the cap, there is no block — and the step is
        exactly the step it would have been with the flag off.
        """
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        guess(state, "t#r2", "route", "north")
        whole = compile_view(state)
        assert compile_view(state,
                            budget_chars=len(whole.text) - 1).text == ""

    def test_nothing_is_dropped_without_saying_so(self, wide):
        """The mutation this catches is one line long: drop the sentence
        and every assertion about the *cap* still passes."""
        whole = compile_view(wide)
        tight = compile_view(wide, budget_chars=900)
        assert tight.facts < whole.facts
        assert tight.truncated
        assert "not shown" in tight.text

    def test_a_view_that_fits_says_nothing_about_truncation(self, ledger):
        view = compile_view(ledger)
        assert not view.truncated
        assert "not shown" not in view.text

    def test_the_oldest_entity_goes_first(self, wide):
        """A view is trimmed from the end, and the end is the oldest
        receipt: the one the mission just took is the one the next step is
        about."""
        tight = compile_view(wide, budget_chars=900)
        assert "mcp.ledger_entry#r39" in tight.text
        assert "mcp.ledger_entry#r0 ·" not in tight.text

    def test_a_conflict_outlives_a_fact(self):
        """An unresolved disagreement the model cannot see is the failure
        this block exists to prevent; a fact whose receipt is still in the
        transcript is not."""
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "led.a41", "units", 120)
        guess(state, "led.a41", "units", 98)
        for index in range(20):
            observe(state, f"mcp.c#r{index}", "route", index)
        tight = compile_view(state, budget_chars=700)
        assert tight.conflicts == 1
        assert tight.facts_omitted

    def test_a_budget_too_small_to_explain_itself_compiles_nothing(self,
                                                                   wide):
        """A cap that is exceeded to apologise for itself is not a cap, and
        a block that is all apology is not worth a step."""
        assert compile_view(wide, budget_chars=80).text == ""


class TestTheCutIsArithmeticAndNotRepeatedRendering:
    """The review's M1, pinned as a call count rather than as a stopwatch.

    The first version dropped one line and re-rendered the whole block, per
    line — quadratic against a store that only grows, measured at 482 ms
    for four thousand live facts **on the model-call path**.  The cut is
    now chosen against prefix sums and the block is rendered exactly twice:
    once under upper bounds for the header and the omission sentence, once
    with the lengths the first pass produced.

    A number that moves with the machine is no good in a test; the number
    of renders is the thing that was wrong, so that is what is asserted.
    """

    def _spy(self, monkeypatch):
        calls = []
        real = mod._render

        def counted(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        monkeypatch.setattr(mod, "_render", counted)
        return calls

    @pytest.mark.parametrize("facts", [1, 10, 100, 1000])
    def test_two_renders_whatever_the_store_holds(self, monkeypatch, facts):
        state = CognitiveState()
        for index in range(facts):
            observe(state, f"t#r{index}", "units", index)
        calls = self._spy(monkeypatch)
        assert compile_view(state).text
        assert len(calls) == 2, len(calls)

    @pytest.mark.parametrize("facts", [10, 100, 1000])
    def test_two_renders_when_the_budget_bites_as_well(self, monkeypatch,
                                                       facts):
        """The path that used to be the quadratic one: the tighter the
        budget, the more lines the old loop dropped and the more whole
        blocks it built to find that out."""
        state = CognitiveState()
        for index in range(facts):
            observe(state, f"t#r{index}", "units", index)
        calls = self._spy(monkeypatch)
        assert compile_view(state, budget_chars=800).text
        assert len(calls) == 2, len(calls)

    def test_a_budget_that_fits_nothing_renders_nothing(self, monkeypatch):
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        calls = self._spy(monkeypatch)
        assert compile_view(state, budget_chars=30).text == ""
        assert calls == []

    @pytest.mark.parametrize("budget", [300, 420, 517, 900, 1000, 2048])
    def test_the_cut_is_tight(self, budget):
        """Safe is not enough: a cut that dropped everything would satisfy
        every cap assertion in this file.  This says the block is the
        LARGEST one that fits — putting back one dropped line takes it over
        — which is the half that a conservative arithmetic bug would pass
        and the half that says the size model agrees with the renderer.
        """
        state = CognitiveState()
        for index in range(60):
            observe(state, f"mcp.ledger_entry#r{index}", "units", index)
        view = compile_view(state, budget_chars=budget)
        assert view.facts_omitted, "pick a budget that actually truncates"
        assert len(view.text) <= budget

        # Exactly what the next line would have cost: itself and the
        # newline joining it, plus the section's heading and blank line
        # when the cut left the section closed. The omission sentence
        # cannot grow when fewer lines are dropped, so this is the whole
        # of the difference.
        whole = compile_view(state, budget_chars=100_000)
        following = section(whole, FACTS_HEADING)[view.facts]
        extra = len(following) + 1 + (0 if view.facts
                                      else len(FACTS_HEADING) + 2)
        assert compile_view(state,
                            budget_chars=budget + extra).facts > view.facts

    def test_the_renderer_and_the_arithmetic_are_checked_against_each_other(
            self, monkeypatch):
        """The size model is a second reader of the block's shape, which
        this package otherwise refuses to have — so it is never trusted.
        A renderer that disagreed with it yields NO block rather than one
        over the cap somebody set."""
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        monkeypatch.setattr(mod, "_render", lambda *a, **k: "x" * 10_000)
        assert compile_view(state).text == ""


# ── that it is deterministic ─────────────────────────────────────────────────


class TestTheSameStateIsTheSameBlock:
    def test_two_compilations_are_byte_identical(self, ledger):
        assert compile_view(ledger).text == compile_view(ledger).text

    def test_the_digest_is_stable(self, ledger):
        assert compile_view(ledger).digest() == compile_view(ledger).digest()

    def test_two_states_built_the_same_way_digest_the_same(self):
        def build():
            state = CognitiveState()
            observe(state, "t#r1", "units", 120)
            observe(state, "t#r2", "units", 86)
            return state

        assert compile_view(build()).digest() == compile_view(build()).digest()

    def test_a_different_block_digests_differently(self, ledger):
        before = compile_view(ledger).digest()
        observe(ledger, "mcp.ledger_entry#r4", "units", 7)
        assert compile_view(ledger).digest() != before

    def test_the_digest_is_of_the_text_and_not_of_the_counts(self):
        """Two views with the same shape and different figures are two
        different blocks, and a digest that called them one would be a
        cache key that served the wrong view."""
        first, second = CognitiveState(), CognitiveState()
        observe(first, "t#r1", "units", 120)
        observe(second, "t#r1", "units", 121)
        assert compile_view(first).digest() != compile_view(second).digest()


class TestItIsAReadAndNothingMore:
    """The kernel's constitution, checked from outside it.

    Pure means the store is not changed by being looked at — with the one
    documented exception every kernel reader shares, the implicit flush,
    which is why the runtime compiles *after* its own defined flush point.
    """

    def test_compiling_writes_no_event(self, ledger):
        ledger.derive()
        before = len(ledger.events)
        compile_view(ledger)
        compile_view(ledger)
        assert len(ledger.events) == before

    def test_compiling_moves_no_status(self, ledger):
        before = [(prop.id, prop.status) for prop in ledger.propositions()]
        compile_view(ledger)
        assert [(prop.id, prop.status)
                for prop in ledger.propositions()] == before

    def test_it_imports_nothing_from_the_runtime(self):
        """The dependency runs one way, on purpose and permanently: a
        kernel that cannot be imported on its own cannot be swapped for a
        different one.

        Read off the syntax tree and not off the text, because the text
        *names* :mod:`core.runtime.cognition` — the docstrings point at the
        attachment that calls this, which is documentation and not a
        dependency, and a grep could not tell the two apart."""
        for name in _imports():
            assert not name.startswith("core.runtime"), name

    def test_there_is_no_clock_and_no_randomness_in_it(self):
        """Both would make a view unreproducible, and a view that cannot be
        reproduced cannot be replayed beside the run that saw it."""
        for name in _imports():
            assert name.split(".")[0] not in ("time", "datetime", "random",
                                              "os", "uuid"), name


class TestTheViewReportsItself:
    def test_the_counts_are_what_was_rendered(self, ledger):
        view = compile_view(ledger)
        assert view.facts == len(section(view, FACTS_HEADING))
        assert view.conflicts == len(section(view, CONFLICTS_HEADING))

    def test_a_view_is_falsy_when_it_has_nothing_to_say(self):
        assert not CompiledView()
        assert CompiledView(text="x")

    def test_the_header_s_counts_are_all_about_the_same_population(self):
        """One sentence, one population.

        The header states receipts, facts and conflicts in one breath. The
        facts are the ones this block SHOWS, so the receipts have to be the
        receipts of those — a count over the whole store beside a count of
        the rendered facts is two populations in one sentence with nothing
        on the line to say which is which, and a model reading "40
        receipts, 12 facts" has been told something untrue about what it is
        looking at.
        """
        state = CognitiveState()
        for index in range(40):
            observe(state, f"mcp.t#r{index}", "units", index)
        view = compile_view(state, budget_chars=900)
        assert view.facts_omitted, "this budget has to truncate"
        assert view.receipts == view.facts
        assert f"compiled from {view.facts} receipts, {view.facts} facts" \
            in lines_of(view)[0]

    def test_the_header_states_the_three_counts(self, ledger):
        head = lines_of(compile_view(ledger))[0]
        assert "3 receipts" in head and "4 facts" in head \
            and "1 conflict" in head

    def test_one_of_something_is_singular(self):
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        head = lines_of(compile_view(state))[0]
        assert "1 receipt," in head and "1 fact," in head \
            and "0 conflicts." in head

    def test_a_text_only_claim_is_not_dropped(self):
        """The v1 harvest never makes one — it reads JSON figures and
        nothing else — and a later extractor that does must not find its
        claims silently missing from the runtime's own view."""
        state = CognitiveState()
        state.assert_observation(text="the deployment refused, and the "
                                 "schema has no field for why",
                                 evidence=(receipt("r1"),))
        assert "the deployment refused" in compile_view(state).text


def test_the_block_is_plain_text(ledger):
    """No JSON, no markdown fences, nothing a decoder has to be told
    about: the block is read by a language model and by a person reading
    ``model.jsonl``, and both read prose."""
    text = compile_view(ledger).text
    assert not text.startswith("{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
