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
* **it needs nothing installed, and it never makes a manifest unloadable.**
  ``require:`` is **exact rational** arithmetic over a deliberately small
  language — no precision to exceed, no ambient ``decimal`` context to
  inherit, so a very large sum is decided rather than rounded into a
  violation that is not there.  ``require_z3:`` is an opt-in spelled in the
  manifest, and on a box without the extra it loads exactly as it does
  everywhere else and simply goes **unchecked**, with one note naming the
  extra;
* **it is a record, not a diary.**  One line per ``(constraint, entity)``
  pair for the life of the run, resumes included, while the view shows what
  is true *now*; and what the budget drops, it drops **honestly** — a
  dropped violation is never sent to a result store that does not hold one.

The refusals are checked one expression at a time and by message, because a
refusal an author cannot act on is a refusal that costs them an afternoon.
"""

import decimal
import json
import textwrap
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition import (CognitiveState, EvidenceAuthority, EvidenceRef,
                            PropositionStatus)
from core.cognition.compile import (CONFLICTS_HEADING, OMITTED, SIDE_SEP,
                                    VIOLATIONS_OMITTED, compile_view,
                                    violation_line)
from core.cognition.constraints import (MAX_EXPRESSION, SOLVER_EXTRA,
                                        VIOLATION_KIND, Constraint,
                                        ConstraintMalformed, Violation,
                                        SOLVER_TIMEOUT_MS,
                                        _show_number, check_constraints,
                                        have_z3, needs_solver,
                                        parse_constraint, solver_names)
from core.durable import RunStore
from core.runtime.cognition import (NOTE_KEY, UNCHECKED_NOTE, UNSOLVED_NOTE,
                                    VIOLATION_NOTE, RulePack, open_shadow,
                                    read_reasoning)
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

    def test_the_z3_form_reads_what_the_linear_one_refuses(self):
        parsed = parse_constraint("c", {"entity": "?e"}, None,
                                  "share / total <= 1")
        assert parsed.engine == "z3"
        assert parsed.fields == ("share", "total")

    def test_a_z3_form_parses_with_no_solver_on_the_box(self):
        """THE DOOR DOES NOT ASK THE BOX, and this is the review's
        correction. A manifest's validity is a property of the manifest: the
        grammar is an `ast` walk that reads the same with or without the
        wheel, and refusing here made an optional extra mandatory to LOAD a
        skill — and therefore to start a mission, with cognition OFF, on a
        layer that may never block an answer."""
        with patch("core.cognition.constraints.have_z3", return_value=False):
            parsed = parse_constraint("c", {"entity": "?e"}, None,
                                      "share * rate <= cap")
        assert parsed.engine == "z3"
        assert parsed.fields == ("share", "rate", "cap")

    def test_a_pack_of_them_loads_with_no_solver_on_the_box(self):
        """The same claim one level up, where it bites: the manifest door."""
        with patch("core.cognition.constraints.have_z3", return_value=False):
            pack = RulePack.from_mapping({"constraints": [
                {"name": "ratio", "over": {"entity": "?e"},
                 "require_z3": "part / whole <= 1"}]})
        assert [c.engine for c in pack.constraints] == ["z3"]

    def test_a_z3_form_is_still_refused_for_a_fault_of_its_own(self):
        """Not asking the box is not the same as not reading the line."""
        with pytest.raises(ConstraintMalformed) as raised:
            parse_constraint("c", {"entity": "?e"}, None, "abs(share) <= 1")
        assert "Call" in str(raised.value)


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

    def test_a_negative_literal_is_not_restated_as_its_own_value(self):
        """m1: `-5 = -5` is a block saying one thing twice and inviting a
        reader to look for the difference. A sign in front of a bare term is
        still a bare term."""
        state = store_with(share=5)
        assert check_constraints(
            state, [constraint("share <= -5")])[0].detail == "share 5 > -5"

    def test_two_signs_do_not_run_together(self):
        """n6: `--5` reads as an operator nobody has. The parentheses the
        file wrote are the parentheses the line keeps."""
        state = store_with(share=5)
        assert check_constraints(
            state, [constraint("share <= -(-4)")])[0].detail == \
            "share 5 > -(-4)"

    def test_the_sentence_and_the_verdict_are_one_arithmetic(self):
        """MAJOR 3: the numbers in the sentence are the numbers that decided
        it, because there is only one evaluation to disagree with."""
        state = store_with(a=0.1, b=0.2, c=0.4)
        found = check_constraints(state, [constraint("a + b == c")])[0]
        assert found.detail == "a 0.1 + b 0.2 = 0.3 != c 0.4"

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

    def test_exact_arithmetic_and_not_float(self):
        """`0.1 + 0.2 == 0.3` is false in floats and true in the arithmetic
        a run is judged by. A checker that reported this store would be
        reporting Python's rounding as the run's fault."""
        state = store_with(a=0.1, b=0.2, c=0.3)
        assert check_constraints(state, [constraint("a + b == c")]) == ()


class TestTheArithmeticHasNoBoundAndNoAmbientState:
    """The review's MAJOR 2, as the tests that would have caught it.

    The first version computed in decimals under ``localcontext()`` at fifty
    digits. Fifty digits is exact for every figure a receipt plausibly
    carries and **silently rounds** above it, and ``localcontext()`` inherits
    whatever the host process has done to :mod:`decimal` — so a consistent
    store could be reported as violating its own constraint, and a host that
    had set its own precision could flip a verdict without touching a
    manifest. A fabricated violation is a line in the model's prompt saying a
    store disagrees with itself. :class:`~fractions.Fraction` has neither
    failure mode: no precision to exceed, no context to inherit.
    """

    #: Big enough that fifty significant digits cannot hold the sum: the
    #: rounding puts `settled + pending` back onto `total`.
    BIG = 10 ** 60

    def test_a_sum_above_any_precision_bound_is_decided_correctly(self):
        """`10**60 + 1 > 10**60` is TRUE, so this store violates nothing —
        and under a rounding arithmetic it was reported as a violation."""
        state = store_with(settled=self.BIG, pending=1, total=self.BIG)
        assert check_constraints(
            state, [constraint("settled + pending > total")]) == ()

    def test_the_mirror_case_is_not_missed(self):
        """The same rounding hid a REAL violation: `10**60 + 1 == 10**60` is
        false, and an arithmetic that rounded the sum called it true."""
        state = store_with(settled=self.BIG, pending=1, total=self.BIG)
        found = check_constraints(
            state, [constraint("settled + pending == total")])
        assert [v.constraint for v in found] == ["c"]

    def test_the_sentence_carries_the_exact_figure(self):
        state = store_with(settled=self.BIG, pending=1, total=self.BIG)
        found = check_constraints(
            state, [constraint("settled + pending == total")])
        assert f"= {self.BIG + 1} !=" in found[0].detail

    def test_a_hosts_decimal_context_cannot_move_a_verdict(self):
        """We ship behind an SDK front door, so ambient process state is
        real: a host that narrowed `decimal`'s precision used to change what
        a mission reported about a store it never touched."""
        state = store_with(settled=204.5, pending=631.25, total=835.75)
        expression = "settled + pending == total"
        before = check_constraints(state, [constraint(expression)])
        with decimal.localcontext() as context:
            context.prec = 3
            during = check_constraints(state, [constraint(expression)])
        assert before == during == ()

    def test_a_hosts_context_cannot_move_the_rendered_bytes_either(self):
        """`compile_view`'s promise is the same state, the same bytes, in any
        process — and the sentence is part of those bytes."""
        state = store_with(settled=100.125, pending=1, total=2)
        found = check_constraints(
            state, [constraint("settled + pending == total")])
        with decimal.localcontext() as context:
            context.prec = 2
            under = check_constraints(
                state, [constraint("settled + pending == total")])
        assert found[0].detail == under[0].detail
        assert "= 101.125 !=" in found[0].detail

    def test_a_figure_too_big_to_spell_does_not_raise_mid_render(self):
        """m2. CPython refuses to turn an integer of more than ~4,300 digits
        into a string, and the harvest takes whatever figure a receipt
        carried — so a line of model input can be built around one. The limit
        is described rather than hit: a rendering that raised would be an
        advisory check costing a step."""
        huge = 10 ** 6000
        state = store_with(total=huge, part=1)
        found = check_constraints(state, [constraint("part >= total")])
        assert len(found) == 1
        # The COUNT is pinned, because the escape is a claim about the number
        # in a line the model reads: `bit_length()` under the word "digit"
        # would say 19,932 here and be wrong by a factor of 3.32.
        # `10 ** 6000` has 6,001 digits by construction — and `len(str())`
        # is not how to check it, because spelling it is the very thing
        # CPython refuses.
        assert "a 6001-digit integer" in found[0].detail

    def test_a_fraction_that_is_not_a_decimal_still_renders(self):
        """Only the solver's division can make one, and a rendering nobody
        recognises beats a number that is not the one that decided it."""
        assert _show_number(Fraction(1, 3)) == "1/3"
        assert _show_number(Fraction(-1, 8)) == "-0.125"
        assert _show_number(Fraction(835)) == "835"


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

    @pytest.fixture
    def crowded(self):
        """A store whose CONFLICTS section can lose lines one at a time.

        Twelve entities, one constraint, twelve violations — and the size is
        the point rather than decoration. Dropping the FIRST line of a
        section adds an omission clause longer than the line it saved, so a
        section of one line is all-or-nothing: the budget that would drop it
        cannot fit the sentence explaining the drop, and the whole view goes
        empty instead. A section of twelve has a band of budgets where lines
        come off one by one, which is where the sentence can be read.
        """
        state = CognitiveState()
        for index in range(12):
            state.assert_observation(
                (f"tool#r{index}", "share", 200 + index),
                evidence=(EvidenceRef(kind="receipt",
                                      locator=f"run/r{index}/tool"),),
                authority=EvidenceAuthority.DETERMINISTIC)
        return state, check_constraints(state, [constraint("share <= 100")])

    def test_a_dropped_violation_is_not_sent_to_the_result_store(self, crowded):
        """MAJOR 4. The CONFLICTS section's escape sentence says *ask the
        mission's result store, every receipt is still in it, whole* — which
        is true of a dropped fact and false of a violation: a violation is
        computed from the pack against the store, it is in no receipt and no
        tool's output, and a model that spent a call asking for one would
        learn only that the runtime was wrong about itself."""
        state, found = crowded
        wide = compile_view(state, violations=found)
        for budget in range(len(wide.text), 0, -1):
            view = compile_view(state, budget_chars=budget, violations=found)
            if min(view.conflicts_omitted, len(found)):
                assert VIOLATIONS_OMITTED.split("{what}")[1][:40] in view.text
                assert "constraint violation" in view.text
                return
        pytest.fail("no budget dropped the violation")

    def test_each_clause_names_only_what_it_is_true_of(self, crowded):
        """A budget that loses both kinds writes both clauses, and each one
        counts only its own: the store clause is about the twelve facts, the
        violation clause about the violations, and neither sentence claims
        the other's lines."""
        state, found = crowded
        view = compile_view(state, budget_chars=707, violations=found)
        assert (view.facts_omitted,
                min(view.conflicts_omitted, len(found))) == (12, 8)
        assert "+12 facts not shown at this budget; ask the mission's " \
            "result store" in view.text
        assert "+8 constraint violations not shown at this budget — " \
            "nothing to ask for" in view.text

    def test_a_dropped_fact_still_points_at_the_store(self, crowded):
        """The other clause still says what it always said: three losses,
        three truths, and neither one swallowed the other."""
        state, found = crowded
        wide = compile_view(state, violations=found)
        for budget in range(len(wide.text), 0, -1):
            view = compile_view(state, budget_chars=budget, violations=found)
            if view.facts_omitted and not view.conflicts_omitted:
                assert OMITTED.split("{what}")[1][:40] in view.text
                assert "constraint violation" not in view.text
                return
        pytest.fail("no budget dropped a fact and kept the violation")

    def test_the_counters_tell_violations_from_contradictions(self):
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
        assert (view.conflicts, view.conflicts_omitted) == (2, 0)
        assert view.text.count(f"{VIOLATION_KIND}: ") == 1

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

    def test_the_line_says_only_what_loaded(self):
        """m6. The console sentence is what an operator is told a pack DID,
        and a pack of constraints alone derives nothing and owes nothing —
        so a fixed sentence about clauses and goals would be the harness
        reporting work it did not do."""
        from core.cli import pack_line

        only = pack_line((0, 0, 0), 2, "packed")
        assert "0 rule(s), 0 goal(s), 2 constraint(s)" in only
        assert "DERIVE" not in only and "still owed" not in only
        assert "recorded and shown, never enforced" in only
        assert only.endswith("None of it gates anything")
        # n5: the clauses are assembled, and a sentence assembled after a
        # full stop starts like one.
        assert ". A constraint that does not hold" in only

        whole = pack_line((1, 2, 1), 1, "packed")
        assert "DERIVE" in whole and "still owed" in whole
        assert "promoted to SKILL authority" in whole

        bare = pack_line((1, 0, 0), 0, "packed")
        assert "never enforced" not in bare and "still owed" not in bare

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


class TestAMissingSolverCostsTheCheckingAndSaysSo:
    """The other half of the review's MAJOR 1.

    The manifest loads, the mission runs, the linear constraints are checked
    and the solver's are not — with one note in the log naming the extra, so
    a reader never has to work out why half a pack was silent.
    """

    PACK = {"constraints": [
        {"name": "bounded", "over": {"entity": "?e"},
         "require": "share <= 100"},
        {"name": "ratio", "over": {"entity": "?e"},
         "require_z3": "settled / total <= 1"},
    ]}

    @pytest.fixture
    def shadow(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=self.PACK)
        with patch("core.runtime.cognition.have_z3", return_value=False):
            shadow.receipt("mcp.view", "r1", RECEIPT)
            shadow.close_step()
            shadow.close_step()
        return shadow

    def test_the_pack_loaded_whole(self, shadow):
        assert [c.name for c in shadow.constraints] == ["bounded", "ratio"]
        assert shadow.on and shadow.checking

    def test_the_linear_half_is_checked(self, shadow):
        assert [v.constraint for v in shadow.violations] == ["bounded"]

    def test_the_note_is_written_once_and_names_the_extra(self, shadow):
        with patch("core.runtime.cognition.have_z3", return_value=False):
            for _ in range(2):
                shadow.close_step()
        written = notes(shadow.path, UNSOLVED_NOTE)
        assert len(written) == 1
        assert written[0]["extra"] == SOLVER_EXTRA
        assert written[0]["constraints"] == ["ratio"]

    def test_a_resume_does_not_say_it_again(self, runs, shadow):
        """ONCE PER RUN, and a run outlives a process. `_said_unsolved` is
        seeded from the log exactly as the violation dedup is: an attribute
        that started fresh every time would state the same fact about the
        same box once per resume, and a reader counting notes would read four
        resumes as four findings."""
        again = open_shadow(runs, shadow.run_id,
                            cognition_block=self.PACK)
        with patch("core.runtime.cognition.have_z3", return_value=False):
            again.receipt("mcp.view", "r2", RECEIPT)
            again.close_step()
        assert len(notes(again.path, UNSOLVED_NOTE)) == 1

    def test_a_resume_that_finds_no_note_writes_the_first_one(self, runs):
        """The other half, or the seeding would be a switch that can only
        ever silence: a run whose first process had the solver, resumed on a
        box that does not, has never said this and says it now."""
        run = runs.create()
        first = open_shadow(runs, run.run_id, cognition_block=self.PACK)
        with patch("core.runtime.cognition.have_z3", return_value=True):
            first.receipt("mcp.view", "r1", RECEIPT)
            first.close_step()
        assert notes(first.path, UNSOLVED_NOTE) == []

        again = open_shadow(runs, run.run_id, cognition_block=self.PACK)
        with patch("core.runtime.cognition.have_z3", return_value=False):
            again.close_step()
            again.close_step()
        assert len(notes(again.path, UNSOLVED_NOTE)) == 1

    def test_a_pack_with_no_solver_constraints_says_nothing(self, runs):
        run = runs.create()
        shadow = open_shadow(runs, run.run_id, cognition_block=PACK)
        with patch("core.runtime.cognition.have_z3", return_value=False):
            shadow.receipt("mcp.view", "r1", RECEIPT)
            shadow.close_step()
        assert notes(shadow.path, UNSOLVED_NOTE) == []

    def test_the_names_come_from_one_owner(self):
        pack = RulePack.from_mapping(self.PACK)
        assert solver_names(pack.constraints) == ("ratio",)
        assert needs_solver(pack.constraints)
        assert not needs_solver(RulePack.from_mapping(PACK).constraints)


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

    def test_the_solver_is_given_a_wall_clock_bound(self, z3):
        """m4. It runs on the mission's own thread inside `close_step`, so
        the one thing it may never do is not come back. Every value is bound
        before it is asked, so this can only fire on something pathological —
        and `unknown` is already the undecidable answer that yields nothing.
        """
        seen = {}
        real = z3.Solver

        class Timed(real):
            def set(self, *args, **kwargs):
                if args[:1] == ("timeout",):
                    seen["timeout"] = args[1]
                return real.set(self, *args, **kwargs)

        with patch.object(z3, "Solver", Timed):
            check_constraints(store_with(rate=3, units=4), [
                parse_constraint("area", {"entity": "?e"}, None,
                                 "rate * units <= 10")])
        assert seen.get("timeout") == SOLVER_TIMEOUT_MS

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
    installed, it is what a pack gets unless it asks for more, and asking for
    more costs a deployment **checking** and never a mission."""

    def test_the_probe_answers_without_raising(self):
        assert have_z3() in (True, False)

    def test_the_sentence_names_an_extra_that_exists_and_carries_the_wheel(
            self):
        """m3, and the rule ``tests/test_server.py`` already keeps for
        ``[server]``: a sentence that names an extra is worth exactly as much
        as the extra being real and being the one with the wheel in it. The
        name is READ OUT of the sentence rather than typed here, so a rename
        in either place has to be a rename in both."""
        import ast
        import re

        from tests.test_packaging import _setup_kwargs

        named = re.search(r"judais-lobi\[([a-z0-9_-]+)]", SOLVER_EXTRA)
        assert named, SOLVER_EXTRA
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        assert named.group(1) in extras
        assert [item for item in extras[named.group(1)]
                if item.startswith("z3-solver")]

    def test_the_linear_engine_is_the_default(self):
        assert constraint("share <= 100").engine == "linear"

    def test_a_linear_check_never_imports_the_solver(self):
        with patch("core.cognition.constraints.have_z3", return_value=False):
            found = check_constraints(store_with(share=500),
                                      [constraint("share <= 100")])
        assert len(found) == 1
