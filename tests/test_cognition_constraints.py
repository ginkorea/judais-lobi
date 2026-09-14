# tests/test_cognition_constraints.py — what a pack says must be true, and
# what happens when it is not

"""The constraint checker (``ROADMAP.md`` §2.9.7, Phase 20c), from four sides.

A pack may declare arithmetic over the facts a run establishes.  This file is
the instrument for the claims that make that safe to ship:

* **it never gates** (§2.9.3, the owner's ruling of 13 September 2026:
  *cognition-on never blocks an answer*).  A violation is a row in the
  compiled view and a record in ``reasoning.jsonl``; nothing is held, nothing
  is refused, no supervisor signal is raised, and a checker that raises costs
  the *checking* and nothing else;
* **absence is never false.**  A field the store does not hold means the
  entity is not bound and there is no violation — the one mistake that would
  turn this feature into a generator of confident nonsense, because a
  receipt that has not arrived yet is not a receipt that said zero;
* **it needs nothing installed.**  ``require:`` is exact decimal arithmetic
  over a deliberately small language; ``require_z3:`` is an opt-in spelled in
  the manifest, and on a box without the extra it is refused **at the door**
  naming it rather than loading and checking nothing;
* **it is a record, not a diary.**  One line per ``(constraint, entity)``
  pair for the life of the run, resumes included, while the view shows what
  is true *now*.

The refusals are checked one expression at a time and by message, because a
refusal an author cannot act on is a refusal that costs them an afternoon.
"""

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition import (CognitiveState, EvidenceAuthority, EvidenceRef,
                            PropositionStatus)
from core.cognition.compile import (CONFLICTS_HEADING, SIDE_SEP, compile_view,
                                    violation_line)
from core.cognition.constraints import (MAX_EXPRESSION, SOLVER_EXTRA,
                                        VIOLATION_KIND, Constraint,
                                        ConstraintMalformed, Violation,
                                        check_constraints, have_z3,
                                        parse_constraint)
from core.durable import RunStore
from core.runtime.cognition import (NOTE_KEY, UNCHECKED_NOTE, VIOLATION_NOTE,
                                    RulePack, open_shadow, read_reasoning)
from core.runtime.skills import SkillManifestError, compose_manifests, load_skill

#: One receipt, four figures, two of them wrong about each other: the
#: `share` is over a hundred and the parts do not add up to the total.
RECEIPT = json.dumps({"totals": {"share": 121.2, "settled": 204,
                                 "pending": 631, "total": 631}})

#: The pack those two constraints live in.  No rules and no goals on purpose:
#: a constraint is a claim about the store, and it has to work on a store
#: that only ever observed.
PACK = {
    "constraints": [
        {"name": "share_bounded", "over": {"entity": "?e"},
         "require": "share <= 100"},
        {"name": "parts_sum", "over": {"entity": "?e"},
         "require": "settled + pending == total"},
    ],
}


def constraint(expression, name="c", **kwargs):
    return parse_constraint(name, {"entity": "?e"}, expression, **kwargs)


def store_with(**fields):
    """A state holding one entity's figures, each with a receipt behind it."""
    state = CognitiveState()
    ref = (EvidenceRef(kind="receipt", locator="run/r1/tool"),)
    for field, value in fields.items():
        state.assert_observation(("tool#r1", field, value), evidence=ref,
                                 authority=EvidenceAuthority.DETERMINISTIC)
    return state


def notes(path, which=None):
    return [note for note in read_reasoning(path)[2]
            if which is None or note.get(NOTE_KEY) == which]


@pytest.fixture
def runs(tmp_path):
    return RunStore(tmp_path / "store")


# ── the language, and everything it will not read ────────────────────────────


class TestTheDoorReadsTheExpressionOrRefusesIt:
    """Every refusal names what it refused and what the language is.

    The parser is a **whitelist over an `ast` walk**, which is the whole of
    the safety argument: nothing is executed or compiled, so a call or an
    attribute is not dangerous, it is simply not a node this module names.
    These are the sentences an author gets.
    """

    def test_a_comparison_over_a_field_is_read(self):
        parsed = constraint("share <= 100", name="share_bounded")
        assert parsed.name == "share_bounded"
        assert parsed.fields == ("share",)
        assert parsed.require == "share <= 100"
        assert parsed.engine == "linear"

    def test_the_fields_are_in_first_appearance_order(self):
        assert constraint("settled + pending == total").fields == \
            ("settled", "pending", "total")

    def test_a_field_named_twice_is_one_field(self):
        assert constraint("share + share <= total").fields == \
            ("share", "total")

    @pytest.mark.parametrize("expression,fragment", [
        ("share", "not a comparison"),
        ("1 < share < 100", "chains 2 comparisons"),
        ("share.total <= 100", "Attribute"),
        ("abs(share) <= 100", "Call"),
        ("share[0] <= 100", "Subscript"),
        ("share <= True", "a constant in an expression is a number"),
        ("share <= None", "a constant in an expression is a number"),
        ('share <= "100"', "a constant in an expression is a number"),
        ("share <= 1e400", "an infinity decides nothing"),
        ("1 <= 100", "names no field"),
        ("share ** 2 <= 100", "Pow"),
        ("share <= 100 if total else 0", "not a comparison"),
        ("share <= (1 if total else 0)", "IfExp"),
        ("share <= -total ** 2", "Pow"),
    ])
    def test_what_the_expression_language_is_not(self, expression, fragment):
        with pytest.raises(ConstraintMalformed) as raised:
            constraint(expression)
        assert fragment in str(raised.value)

    def test_a_syntax_error_is_a_sentence_and_not_a_traceback(self):
        with pytest.raises(ConstraintMalformed) as raised:
            constraint("share <= ")
        assert "not an expression this reader can take" in str(raised.value)

    def test_division_is_the_solvers_and_says_so(self):
        """The linear language's bound, and the refusal points at the door
        out of it rather than just saying no."""
        with pytest.raises(ConstraintMalformed) as raised:
            constraint("share / total <= 1")
        assert "require_z3" in str(raised.value)
        assert SOLVER_EXTRA in str(raised.value)

    def test_two_fields_multiplied_is_not_linear(self):
        with pytest.raises(ConstraintMalformed) as raised:
            constraint("share * rate <= 100")
        assert "one side of a `*` is a constant" in str(raised.value)

    def test_a_field_times_a_constant_is(self):
        assert constraint("2 * share <= total").fields == ("share", "total")

    def test_parentheses_and_unary_minus_are_in_the_language(self):
        assert constraint("-(settled - pending) <= 0").fields == \
            ("settled", "pending")

    def test_an_expression_longer_than_the_cap_is_refused(self):
        with pytest.raises(ConstraintMalformed) as raised:
            constraint("share + " * MAX_EXPRESSION + "1 <= 2")
        assert f"the limit is {MAX_EXPRESSION}" in str(raised.value)

    def test_an_expression_that_is_not_a_string_is_refused(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e"}, 100)
        assert "an expression is a string" in str(raised.value)


class TestOverNamesAVariableAndNothingElse:
    """``over:`` is a mapping with one key in v1, and the key takes a
    ?variable: an entity name is minted inside one run, so a literal one
    could only ever fail to match, and refusing says so at the door."""

    def test_a_variable_binds(self):
        assert constraint("share <= 1").entity_var == "?e"

    def test_a_literal_entity_is_refused(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "tool#r1"}, "share <= 1")
        assert "names a ?variable" in str(raised.value)

    def test_a_missing_over_is_refused(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", None, "share <= 1")
        assert "no usable `over:`" in str(raised.value)

    def test_an_unknown_over_key_is_refused_by_name(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e", "when": 1}, "share <= 1")
        assert "unknown `over:` key(s): when" in str(raised.value)


class TestOneConstraintIsOneExpressionInOneLanguage:
    """The two keys choose the engine, and exactly one of them per entry.

    The spelling is the decision this lane argued: the key names the engine,
    so an author reading their own file knows which grammar they are writing
    and whether the manifest needs an extra installed.
    """

    def test_neither_key_is_a_name_with_no_claim_under_it(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e"})
        assert "neither `require:` nor `require_z3:`" in str(raised.value)

    def test_an_empty_expression_is_the_same_as_not_writing_one(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e"}, "   ")
        assert "neither `require:` nor `require_z3:`" in str(raised.value)

    def test_both_keys_are_two_answers_about_which_engine_ran_it(self):
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e"}, "share <= 1",
                             "share <= 1")
        assert "both `require:` and `require_z3:`" in str(raised.value)

    def test_the_z3_form_without_the_extra_refuses_at_the_door(self):
        """The point of the whole opt-in: a manifest that needs the solver
        finds out when it LOADS, naming the extra, rather than loading and
        silently checking nothing for a whole mission.

        Patched rather than left to the box, because this has to be the
        refusal where the solver IS installed too.
        """
        with patch("core.cognition.constraints.have_z3", return_value=False):
            with pytest.raises(ConstraintMalformed) as raised:
                parse_constraint("c", {"entity": "?e"}, None,
                                 "share / total <= 1")
        assert SOLVER_EXTRA in str(raised.value)
        assert "require_z3" in str(raised.value)

    def test_the_z3_form_reads_what_the_linear_one_refuses(self):
        with patch("core.cognition.constraints.have_z3", return_value=True):
            parsed = parse_constraint("c", {"entity": "?e"}, None,
                                      "share / total <= 1")
        assert parsed.engine == "z3"
        assert parsed.fields == ("share", "total")


# ── binding: what the store has to hold before anything is checked ───────────


class TestAnEntityIsCheckedOnlyWhenItBinds:
    """THE RULE THIS FEATURE LIVES OR DIES BY.

    A field the store does not hold is ``UNKNOWN`` — not zero, not false —
    and a checker that read a missing ``pending`` as ``0`` would manufacture
    a violation out of a receipt that had simply not arrived. The same answer
    covers the two other ways a value can fail to be arithmetic: two live
    values for one field (choosing one is deciding a contradiction the kernel
    is deliberately keeping open), and a value that is text, a boolean or
    null.
    """

    def test_all_the_fields_present_and_wrong_is_a_violation(self):
        state = store_with(settled=204, pending=631, total=631)
        found = check_constraints(
            state, [constraint("settled + pending == total")])
        assert [v.entity for v in found] == ["tool#r1"]

    def test_a_missing_field_is_no_violation(self):
        """MUTATION TARGET. Treating the absent `pending` as zero makes
        `204 + 0 == 631` false and this store a violation — which is the
        checker inventing a figure no receipt carried."""
        state = store_with(settled=204, total=631)
        assert check_constraints(
            state, [constraint("settled + pending == total")]) == ()

    def test_a_field_the_store_holds_twice_is_no_violation(self):
        """Undeclared cardinality is `many`, so two receipts can leave one
        entity holding two live values for a field. Picking one would be
        this module settling a disagreement the kernel refuses to settle.

        **Both values violate**, deliberately: a checker that quietly took
        the first, or the last, or the smallest would report a violation
        here, so the assertion below is about the ambiguity and not about
        which number happened to win.
        """
        state = store_with(share=500)
        state.assert_observation(
            ("tool#r1", "share", 400),
            evidence=(EvidenceRef(kind="receipt", locator="run/r2/tool"),),
            authority=EvidenceAuthority.DETERMINISTIC)
        assert len(state.query(("tool#r1", "share", "?v"))) == 2
        assert check_constraints(state, [constraint("share <= 100")]) == ()

    @pytest.mark.parametrize("value,expression", [
        ("121.2", "share <= 100"),      # a numeric STRING is not a number
        (True, "share <= 0"),           # `True == 1` is a fact about Python
        (None, "share >= 1"),           # null is absence with a key on it
    ])
    def test_a_value_that_is_not_arithmetic_is_no_violation(self, value,
                                                            expression):
        """Each expression is chosen so that a checker which *coerced* the
        value would report a violation — otherwise the assertion would pass
        for a reader that had silently read `"121.2"` as a figure."""
        state = store_with(share=value)
        assert check_constraints(state, [constraint(expression)]) == ()

    def test_a_retracted_fact_is_not_checked(self):
        """Only LIVE propositions bind. A figure the store has stopped
        standing behind is not a figure to accuse anybody with."""
        state = store_with(share=121.2)
        pid = state.claim(("tool#r1", "share", 121.2))
        state.refute(pid, evidence=(EvidenceRef(kind="receipt",
                                                locator="run/r9/tool"),))
        assert check_constraints(state, [constraint("share <= 100")]) == ()

    def test_a_derived_fact_binds_like_an_observed_one(self):
        """A constraint is about what the run BELIEVES, conclusions
        included — which is why the check runs after the derive."""
        state = store_with(records=12481, blocks=7)
        rid = state.add_rule("sizeable", ["?v", "sizeable", "?n"],
                             [["?v", "records", "?n"]])
        state.promote_rule(rid, __import__(
            "core.cognition", fromlist=["RuleAuthority"]).RuleAuthority.SKILL)
        state.derive()
        found = check_constraints(state, [constraint("sizeable <= 100")])
        assert [v.entity for v in found] == ["tool#r1"]

    def test_every_entity_that_binds_is_checked(self):
        state = store_with(share=121.2)
        state.assert_observation(
            ("tool#r2", "share", 500),
            evidence=(EvidenceRef(kind="receipt", locator="run/r2/tool"),),
            authority=EvidenceAuthority.DETERMINISTIC)
        found = check_constraints(state, [constraint("share <= 100")])
        assert [v.entity for v in found] == ["tool#r1", "tool#r2"]

    def test_an_entity_that_holds_is_not_reported(self):
        state = store_with(share=99)
        assert check_constraints(state, [constraint("share <= 100")]) == ()

    def test_no_constraints_is_no_walk_and_no_violations(self):
        assert check_constraints(store_with(share=500), []) == ()


class TestTheOrderIsTheDeclarationsThenTheStores:
    """Determinism, which every reader of this package depends on: the log
    and the view are a function of what was believed, not of a dict."""

    def test_constraints_outer_entities_inner(self):
        state = store_with(share=500, total=1)
        state.assert_observation(
            ("tool#r2", "share", 400),
            evidence=(EvidenceRef(kind="receipt", locator="run/r2/tool"),),
            authority=EvidenceAuthority.DETERMINISTIC)
        found = check_constraints(state, [
            constraint("share <= 100", name="a"),
            constraint("share <= 200", name="b")])
        assert [(v.constraint, v.entity) for v in found] == [
            ("a", "tool#r1"), ("a", "tool#r2"),
            ("b", "tool#r1"), ("b", "tool#r2")]


# ── what a violation says ────────────────────────────────────────────────────


class TestTheViolationStatesWhatIsTrue:
    """The sentence is news about the store, not a restatement of the file.

    The comparison is **negated** — a violation of ``==`` reads ``!=`` — and
    every field carries the value the store holds for it, so a reader can
    check the arithmetic without opening the manifest. The manifest's own
    words are on the record beside it.
    """

    def test_the_arithmetic_is_in_the_detail(self):
        state = store_with(settled=204, pending=631, total=631)
        found = check_constraints(
            state, [constraint("settled + pending == total")])
        assert found[0].detail == \
            "settled 204 + pending 631 = 835 != total 631"

    def test_a_bare_side_is_not_restated_as_its_own_value(self):
        state = store_with(share=121.2)
        assert check_constraints(
            state, [constraint("share <= 100")])[0].detail == \
            "share 121.2 > 100"

    def test_precedence_is_rendered_with_the_parentheses_it_needs(self):
        state = store_with(settled=1, pending=5, total=0)
        assert check_constraints(
            state, [constraint("2 * (settled - pending) > total")]
        )[0].detail == "2 * (settled 1 - pending 5) = -8 <= total 0"

    def test_the_record_names_the_constraint_the_entity_and_the_receipts(self):
        state = store_with(settled=204, pending=631, total=631)
        found = check_constraints(
            state, [constraint("settled + pending == total", name="parts")])[0]
        assert found.constraint == "parts"
        assert found.entity == "tool#r1"
        assert found.require == "settled + pending == total"
        assert found.bindings == (("settled", 204), ("pending", 631),
                                  ("total", 631))
        assert found.sources == tuple(
            state.claim(("tool#r1", field, value))
            for field, value in found.bindings)

    def test_the_key_is_the_constraint_and_the_entity(self):
        found = check_constraints(store_with(share=500),
                                  [constraint("share <= 100", name="b")])[0]
        assert found.key == ("b", "tool#r1")

    def test_exact_decimal_arithmetic_and_not_float(self):
        """`0.1 + 0.2 == 0.3` is false in floats and true in the arithmetic
        a run is judged by. A checker that reported this store would be
        reporting Python's rounding as the run's fault."""
        state = store_with(a=0.1, b=0.2, c=0.3)
        assert check_constraints(state, [constraint("a + b == c")]) == ()


# ── the view ─────────────────────────────────────────────────────────────────


class TestViolationsRenderWhereConflictsDo:
    """One section, one grammar. A violation is a disagreement the block is
    showing, so it reads like the other disagreements and costs the budget
    like them."""

    @pytest.fixture
    def found(self):
        return check_constraints(store_with(share=121.2),
                                 [constraint("share <= 100", name="bounded")])

    def test_the_line_has_the_kind_the_entity_and_the_arithmetic(self, found):
        line = violation_line(found[0])
        assert line == (f"{VIOLATION_KIND}: bounded — tool#r1{SIDE_SEP}"
                        f"share 121.2 > 100")

    def test_it_lands_in_the_conflicts_section(self, found):
        view = compile_view(store_with(share=121.2), violations=found)
        body = view.text.split(CONFLICTS_HEADING)[1]
        assert violation_line(found[0]) in body

    def test_the_header_counts_it_with_the_conflicts(self, found):
        view = compile_view(store_with(share=121.2), violations=found)
        assert view.conflicts == 1
        assert "1 conflict." in view.text

    def test_passing_none_is_the_block_that_was_always_rendered(self, found):
        state = store_with(share=121.2)
        assert compile_view(state).text == \
            compile_view(state, violations=()).text

    def test_a_violation_alone_still_makes_a_block(self, found):
        """A store whose only news is a violated constraint is a store with
        something to say. (It cannot happen with the shadow's own harvest —
        a bound constraint means facts — and the branch is here so that a
        caller who checked against a state this module did not fill is not
        handed an empty string.)"""
        view = compile_view(CognitiveState(), violations=found)
        assert violation_line(found[0]) in view.text

    def test_the_budget_counts_the_line(self):
        state = store_with(share=121.2)
        found = check_constraints(state, [constraint("share <= 100")])
        bare = compile_view(state)
        wide = compile_view(state, violations=found)
        assert len(wide.text) > len(bare.text)
        tight = compile_view(state, budget_chars=len(wide.text) - 1,
                             violations=found)
        assert tight.text != wide.text
        assert len(tight.text) <= len(wide.text) - 1

    @pytest.mark.parametrize("budget", list(range(0, 900, 37)))
    def test_no_budget_is_ever_exceeded(self, budget):
        state = store_with(share=121.2, settled=204, pending=631, total=631)
        found = check_constraints(state, [
            constraint("share <= 100", name="bounded"),
            constraint("settled + pending == total", name="parts")])
        assert len(compile_view(state, budget_chars=budget,
                                violations=found).text) <= budget

    def test_a_violation_renders_after_the_stores_own_conflicts(self):
        """Which is the drop order, said where it can be read: a section
        loses its lines from the END, so a budget that takes one line out of
        CONFLICTS takes a pack's arithmetic before it takes a disagreement
        the kernel itself recorded."""
        state = store_with(share=121.2)
        state.declare_field("blocks", "one")
        for value, seq in ((7, "r1"), (9, "r2")):
            state.assert_observation(
                ("tool#r1", "blocks", value),
                evidence=(EvidenceRef(kind="receipt",
                                      locator=f"run/{seq}/tool"),),
                authority=EvidenceAuthority.DETERMINISTIC)
        found = check_constraints(state, [constraint("share <= 100")])
        view = compile_view(state, violations=found)
        assert view.conflicts == 2
        lines = view.text.splitlines()
        assert lines.index(violation_line(found[0])) == \
            max(index for index, line in enumerate(lines)
                if line.startswith(("value:", VIOLATION_KIND + ":")))


# ── the run ──────────────────────────────────────────────────────────────────


class TestTheShadowChecksAtTheStepBoundary:
    """After the derive and after the flush, once per step, and never in the
    way of anything."""

    @pytest.fixture
    def shadow(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=PACK)
        shadow.receipt("mcp.view", "r1", RECEIPT)
        shadow.close_step()
        return shadow

    def test_the_pack_carries_the_constraints(self, shadow):
        assert [c.name for c in shadow.constraints] == \
            ["share_bounded", "parts_sum"]
        assert shadow.pack.constraints == shadow.constraints

    def test_both_violations_are_found(self, shadow):
        assert [(v.constraint, v.detail) for v in shadow.violations] == [
            ("share_bounded", "share 121.2 > 100"),
            ("parts_sum", "settled 204 + pending 631 = 835 != total 631")]

    def test_the_counters_say_what_happened(self, shadow):
        assert (shadow.checked, shadow.check_failures) == (1, 0)
        assert shadow.checking and shadow.on

    def test_each_violation_is_one_line_in_the_log(self, shadow):
        written = notes(shadow.path, VIOLATION_NOTE)
        assert [note["constraint"] for note in written] == \
            ["share_bounded", "parts_sum"]
        assert written[0]["detail"] == "share 121.2 > 100"
        assert written[0]["require"] == "share <= 100"
        assert written[0]["entity"] == "mcp.view#r1"
        assert written[0]["sources"]

    def test_a_violation_is_not_a_kernel_event(self, shadow):
        """v1 records outside the store, so a replay of this log rebuilds
        the state it rebuilt before this feature existed."""
        assert not [event for event in read_reasoning(shadow.path)[1]
                    if "constraint" in json.dumps(event)]

    def test_the_same_violation_is_noted_once_however_many_steps_run(
            self, shadow):
        """MUTATION TARGET. Re-noting each step makes the file's length a
        function of how many steps ran rather than of what was believed."""
        for _ in range(4):
            shadow.close_step()
        assert len(notes(shadow.path, VIOLATION_NOTE)) == 2
        assert shadow.checked == 5

    def test_the_view_shows_what_is_true_now(self, shadow):
        """The list is REPLACED each step while the log accumulates: a
        violation the run corrected should leave the model's view, and the
        fact that it happened stays in the file."""
        shadow.compiling = True
        assert "share_bounded" in shadow.compiled_block()
        shadow.state.refute(
            shadow.state.claim(("mcp.view#r1", "share", 121.2)),
            evidence=(EvidenceRef(kind="receipt", locator="r/r2/t"),))
        shadow.close_step()
        assert [v.constraint for v in shadow.violations] == ["parts_sum"]
        assert "share_bounded" not in shadow.compiled_block()
        assert len(notes(shadow.path, VIOLATION_NOTE)) == 2

    def test_a_run_with_no_constraints_checks_nothing(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block={
            "cardinality": {"blocks": "one"}})
        shadow.receipt("mcp.view", "r1", RECEIPT)
        shadow.close_step()
        assert shadow.violations == () and shadow.checked == 0
        assert notes(shadow.path) == []

    def test_a_run_with_no_pack_at_all_checks_nothing(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id)
        shadow.receipt("mcp.view", "r1", RECEIPT)
        shadow.close_step()
        assert shadow.constraints == () and shadow.violations == ()


class TestAResumePicksTheConstraintsBackUp:
    """A constraint is the one part of a pack that is not in the log, so the
    resume reads it off the manifest — which is not the double-load the
    clauses would be, because there is nothing to replay."""

    @pytest.fixture
    def resumed(self, runs):
        run = runs.create()
        first = open_shadow(runs, run.run_id, cognition_block=PACK)
        first.receipt("mcp.view", "r1", RECEIPT)
        first.close_step()
        return run, open_shadow(runs, run.run_id, cognition_block=PACK)

    def test_the_constraints_are_there(self, resumed):
        _run, shadow = resumed
        assert [c.name for c in shadow.constraints] == \
            ["share_bounded", "parts_sum"]

    def test_the_pack_is_not_claimed_to_have_loaded(self, resumed):
        """`load_constraints` sets one attribute. Saying a pack loaded here
        would make the console report work this process did not do."""
        _run, shadow = resumed
        assert shadow.pack is None and shadow.loaded == (0, 0, 0)

    def test_it_checks_again_and_notes_nothing_twice(self, resumed):
        _run, shadow = resumed
        shadow.close_step()
        assert len(shadow.violations) == 2
        assert len(notes(shadow.path, VIOLATION_NOTE)) == 2

    def test_a_block_that_will_not_parse_costs_the_checking_only(self, runs):
        run = runs.create()
        first = open_shadow(runs, run.run_id, cognition_block=PACK)
        first.receipt("mcp.view", "r1", RECEIPT)
        first.close_step()
        shadow = open_shadow(runs, run.run_id,
                             cognition_block={"constraints": "nonsense"})
        assert shadow.on and not shadow.checking
        assert notes(shadow.path, UNCHECKED_NOTE)


class TestNothingHereCanCostAMission:
    """Failure isolation, in the idiom the shadow already keeps: four things
    can stop independently and each says which one it was."""

    def test_a_checker_that_raises_stops_the_checking_and_nothing_else(
            self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=PACK)
        with patch("core.runtime.cognition.check_constraints",
                   side_effect=RuntimeError("the solver fell over")):
            shadow.receipt("mcp.view", "r1", RECEIPT)
            shadow.close_step()
        assert not shadow.checking
        assert shadow.on and shadow.watching
        assert shadow.check_failures == 1
        assert shadow.state.propositions()          # the harvest ran
        written = notes(shadow.path, UNCHECKED_NOTE)
        assert written and "the solver fell over" in written[0]["error"]

    def test_it_never_raises_again_after_that(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=PACK)
        with patch("core.runtime.cognition.check_constraints",
                   side_effect=RuntimeError("again")):
            for _ in range(3):
                shadow.receipt("mcp.view", "r1", RECEIPT)
                shadow.close_step()
        assert shadow.check_failures == 1
        assert len(notes(shadow.path, UNCHECKED_NOTE)) == 1

    def test_the_view_still_compiles_after_the_checker_stopped(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=PACK,
                             compiling=True)
        with patch("core.runtime.cognition.check_constraints",
                   side_effect=RuntimeError("no")):
            shadow.receipt("mcp.view", "r1", RECEIPT)
            shadow.close_step()
        assert shadow.compiled_block()
        assert shadow.compile_failures == 0


# ── the manifest door and composition ────────────────────────────────────────


class TestThePackDoorRefusesABadConstraintWithEverythingElse:
    """One message, every problem, in the module's own separator — an author
    with three malformed constraints fixes them once."""

    def test_a_usable_block_is_a_pack(self):
        pack = RulePack.from_mapping(PACK)
        assert [c.name for c in pack.constraints] == \
            ["share_bounded", "parts_sum"]
        assert pack                                  # truthy: it declares

    def test_the_expression_is_refused_at_the_door(self):
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraints": [
                {"name": "c", "over": {"entity": "?e"},
                 "require": "abs(share) <= 1"}]})
        assert "Call" in str(raised.value)

    def test_two_constraints_under_one_name_in_one_file(self):
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraints": [
                {"name": "c", "over": {"entity": "?e"}, "require": "a <= 1"},
                {"name": "c", "over": {"entity": "?e"}, "require": "a <= 2"}]})
        assert "declares 'c' twice in one manifest" in str(raised.value)

    def test_an_unknown_key_in_an_entry_is_refused_by_name(self):
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraints": [
                {"name": "c", "over": {"entity": "?e"}, "require": "a <= 1",
                 "severity": "high"}]})
        assert "unknown key(s): severity" in str(raised.value)

    def test_every_problem_arrives_in_one_message(self):
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraints": [
                {"name": "one", "over": {"entity": "?e"},
                 "require": "1 < a < 2"},
                {"name": "two", "over": {"entity": "e"}, "require": "a <= 1"}]})
        assert "chains 2 comparisons" in str(raised.value)
        assert "names a ?variable" in str(raised.value)

    def test_constraints_is_a_list_of_mappings(self):
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraints": {"name": "c"}})
        assert "`constraints:` holds a dict" in str(raised.value)

    def test_the_key_is_known_to_the_block(self):
        """`constraints` is in COGNITION_KEYS, so it does not arrive as an
        unknown key the way a typo does."""
        with pytest.raises(ValueError) as raised:
            RulePack.from_mapping({"constraint": []})
        assert "unknown key(s): constraint" in str(raised.value)

    def test_a_pack_of_constraints_alone_is_still_a_pack(self):
        assert RulePack.from_mapping(PACK)

    def test_loading_writes_no_kernel_event_for_them(self):
        state = CognitiveState()
        assert RulePack.from_mapping(PACK).load_into(state) == (0, 0, 0)
        assert state.events == ()


class TestConstraintsComposeByNameLikeEverythingElse:
    """Several skills' packs union; a name declared twice with different
    content is refused naming both skills."""

    @staticmethod
    def _skill(tmp_path, name, body):
        """One manifest with *body* indented under ``cognition:``.

        A file a person writes, read by the loader a person's file is read
        by: assembling the mapping by hand would test composition against a
        dict no author ever typed, and the YAML is half of what is being
        composed.
        """
        path = Path(tmp_path) / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = textwrap.dedent(f"""\
            ---
            name: {name}
            skill:
              skill_id: {name}
              when_to_use: Testing composition.
              allowed_tools:
                - governed_view
              output_format: One sentence.
              cognition:
            """)
        path.write_text(
            header + textwrap.indent(textwrap.dedent(body), "    ")
            + f"---\n\n# {name}\n", encoding="utf-8")
        return load_skill(str(path))

    ONE = """\
        constraints:
          - name: share_bounded
            over: {entity: "?e"}
            require: "share <= 100"
        """
    TWO = """\
        constraints:
          - name: parts_sum
            over: {entity: "?e"}
            require: "settled + pending == total"
        """
    SAME = """\
        constraints:
          - name: share_bounded
            over: {entity: '?e'}
            require: "share <= 100"
        """
    OTHER = """\
        constraints:
          - name: share_bounded
            over: {entity: "?e"}
            require: "share <= 50"
        """

    def test_two_skills_bring_both(self, tmp_path):
        composed = compose_manifests([self._skill(tmp_path, "a", self.ONE),
                                      self._skill(tmp_path, "b", self.TWO)])
        assert [entry["name"] for entry in composed.cognition["constraints"]] \
            == ["share_bounded", "parts_sum"]

    def test_the_same_constraint_twice_is_one(self, tmp_path):
        composed = compose_manifests([self._skill(tmp_path, "a", self.ONE),
                                      self._skill(tmp_path, "b", self.SAME)])
        assert len(composed.cognition["constraints"]) == 1

    def test_one_name_over_two_expressions_is_refused(self, tmp_path):
        with pytest.raises(SkillManifestError) as raised:
            compose_manifests([self._skill(tmp_path, "a", self.ONE),
                               self._skill(tmp_path, "b", self.OTHER)])
        assert "One name is one constraint" in str(raised.value)
        assert "'a'" in str(raised.value) and "'b'" in str(raised.value)

    def test_a_declared_empty_list_survives_composition(self, tmp_path):
        """The key-presence invariant (1.1.1): a declared key does not
        vanish between one skill and two."""
        composed = compose_manifests([
            self._skill(tmp_path, "a", "constraints: []\n"),
            self._skill(tmp_path, "b", "constraints: []\n")])
        assert composed.cognition["constraints"] == []

    def test_a_skill_that_never_mentioned_them_has_no_opinion(self, tmp_path):
        composed = compose_manifests([
            self._skill(tmp_path, "a", self.ONE),
            self._skill(tmp_path, "b", "cardinality:\n  blocks: one\n")])
        assert len(composed.cognition["constraints"]) == 1
        assert composed.cognition["cardinality"] == {"blocks": "one"}


# ── the escalation, where the solver is installed ────────────────────────────


class TestTheSolverDecidesWhatTheLinearEngineWillNot:
    """Skipped where ``z3-solver`` is not installed, which is the point of
    the extra: everything above this class runs on a box with nothing."""

    @pytest.fixture(autouse=True)
    def z3(self):
        return pytest.importorskip("z3")

    def test_a_division_is_decided_exactly(self):
        state = store_with(part=1, whole=3)
        found = check_constraints(
            state, [parse_constraint("third", {"entity": "?e"}, None,
                                     "part / whole == 0.3333333333")])
        assert found and "is false where part 1, whole 3" in found[0].detail

    def test_a_third_really_is_a_third(self):
        """The reason the escalation exists: no decimal expansion of 1/3
        makes this true, and the solver works in rationals."""
        state = store_with(part=1, whole=3)
        assert check_constraints(
            state, [parse_constraint("third", {"entity": "?e"}, None,
                                     "3 * (part / whole) == 1")]) == ()

    def test_two_fields_multiplied_is_the_solvers(self):
        state = store_with(rate=3, units=4)
        found = check_constraints(
            state, [parse_constraint("area", {"entity": "?e"}, None,
                                     "rate * units <= 10")])
        assert [v.engine for v in found] == ["z3"]

    def test_a_zero_divisor_is_undecidable_and_never_a_violation(self):
        """z3's division by zero is underspecified — an answer about its own
        semantics rather than about the run — so the binding is dropped."""
        state = store_with(part=1, whole=0)
        assert check_constraints(
            state, [parse_constraint("d", {"entity": "?e"}, None,
                                     "part / whole <= 1")]) == ()

    def test_the_record_says_which_engine_decided_it(self):
        state = store_with(rate=3, units=4)
        found = check_constraints(
            state, [parse_constraint("area", {"entity": "?e"}, None,
                                     "rate * units <= 10")])[0]
        assert found.engine == "z3"
        assert found.require == "rate * units <= 10"
        assert found.bindings == (("rate", 3), ("units", 4))


class TestTheSolverIsNeverRequired:
    """The floor, stated as a test: the built-in language works with nothing
    installed, and it is what a pack gets unless it asks for more."""

    def test_the_probe_answers_without_raising(self):
        assert have_z3() in (True, False)

    def test_the_refusal_names_an_extra_that_fixes_it(self):
        """The rule ``tests/test_packaging.py`` already keeps for pyyaml: a
        refusal that names an extra is worth exactly as much as the extra
        being the one that carries the wheel."""
        import ast

        from tests.test_packaging import _setup_kwargs

        assert "judais-lobi[solver]" in SOLVER_EXTRA
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        assert [item for item in extras["solver"]
                if item.startswith("z3-solver")]

    def test_the_linear_engine_is_the_default(self):
        assert constraint("share <= 100").engine == "linear"

    def test_a_linear_check_never_imports_the_solver(self):
        with patch("core.cognition.constraints.have_z3", return_value=False):
            found = check_constraints(store_with(share=500),
                                      [constraint("share <= 100")])
        assert len(found) == 1
