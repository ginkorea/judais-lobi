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
                                    DISPUTED, DROP_ORDER, FACTS_HEADING,
                                    FRONTIER_CAPPED, HYPOTHESES_HEADING,
                                    OMITTED, OWED_HEADING, SECTIONS,
                                    TITLE, UNGRADED, CompiledView, band,
                                    owed_line)
from core.cognition.state import ENV_CAP
from core.cognition.types import RuleAuthority


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


class TestAConclusionDoesNotLookLikeAReceipt:
    """The 19a review's finding: the first lane in which derived facts
    reached a model found them rendering **identically to observations**.

    Same shape, same band, same line — and a model asked to quote a figure
    with where it came from will quote the entity handle on a derived line,
    where no such receipt exists.  The band is already honest about a chain
    (a conclusion carries its weakest premise's authority); what it cannot
    say is that nothing was read to produce this one.
    """

    @pytest.fixture
    def concluded(self) -> CognitiveState:
        state = CognitiveState()
        state.add_rule("owner_known", ("alice", "owner_known", True),
                       [("alice", "payment_link", "?c")],
                       authority=RuleAuthority.SKILL)
        observe(state, "alice", "payment_link", "acct-9")
        return state

    def test_a_derived_line_says_so(self, concluded):
        assert "alice · owner_known = true  [verified · derived]" in \
            section(compile_view(concluded), FACTS_HEADING)

    def test_an_observed_line_does_not(self, concluded):
        line = [row for row in section(compile_view(concluded), FACTS_HEADING)
                if "payment_link" in row][0]
        assert line.endswith("[verified]")

    def test_the_band_is_still_the_weakest_premise(self):
        """The mark is beside the grade and not instead of it: a
        conclusion over a model's extraction is `model-extracted` AND
        derived, and a reader needs both halves."""
        state = CognitiveState()
        state.add_rule("owner_known", ("alice", "owner_known", True),
                       [("alice", "payment_link", "?c")],
                       authority=RuleAuthority.SKILL)
        observe(state, "alice", "payment_link", "acct-9",
                authority=EvidenceAuthority.SOURCE)
        assert "owner_known = true  [sourced · derived]" in \
            compile_view(state).text

    def test_a_contested_conclusion_carries_both_marks(self):
        """Band, then where it came from, then who disagrees."""
        state = CognitiveState()
        state.declare_field("owner_known", "one")
        state.add_rule("owner_known", ("alice", "owner_known", True),
                       [("alice", "payment_link", "?c")],
                       authority=RuleAuthority.SKILL)
        observe(state, "alice", "payment_link", "acct-9")
        guess(state, "alice", "owner_known", False)
        line = [row for row in section(compile_view(state), FACTS_HEADING)
                if "owner_known = true" in row][0]
        assert line.endswith("[verified · derived · disputed]")

    def test_the_heading_does_not_promise_a_receipt_for_it(self, concluded):
        """The heading's claim — "with the receipt each came from" — is
        false of a derived line, and a heading that is false of a line
        under it is worse than no heading."""
        assert "derived" in FACTS_HEADING

    def test_the_mark_is_in_the_digest(self):
        """The same claim read and the same claim concluded are two
        different blocks, and a digest that called them one would be a
        cache key that served the wrong view."""
        read, concluded = CognitiveState(), CognitiveState()
        observe(read, "alice", "owner_known", True)
        concluded.add_rule("owner_known", ("alice", "owner_known", True),
                           [("alice", "payment_link", "?c")],
                           authority=RuleAuthority.SKILL)
        observe(concluded, "alice", "payment_link", "acct-9")
        assert "owner_known = true  [verified]" in compile_view(read).text
        assert compile_view(read).digest() != compile_view(concluded).digest()


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


def owes(state: CognitiveState, premises, *, goal: str = "owner_known",
         entity: str = "alice", authority=RuleAuthority.SKILL) -> str:
    """One goal and one rule whose *premises* nothing satisfies.

    Obligations are **computed, never authored** — the kernel's own rule —
    so a state with a frontier in it is a state with a goal and a rule in
    it, and this file builds one the only way there is.  Each premise the
    store cannot satisfy is one owed line; premises that share a variable
    with an earlier unsatisfied one are ``BLOCKED`` on it, which is how
    this file makes a blocked line without asking for one.
    """
    state.add_rule(goal, (entity, goal, True), list(premises),
                   authority=authority)
    return state.add_goal((entity, goal, True))


def chain(count: int, entity: str = "alice"):
    """*count* premises about *entity*, none of them sharing a variable."""
    return [(entity, f"p{index}", f"?v{index}") for index in range(count)]


class TestTheFrontierIsInTheBlock:
    """``ROADMAP.md`` §2.9.6: the frontier drives, so the model reads it.

    Every line here is **state** and none of them is an instruction. The
    layer is shadow and additive by the owner's ruling of 13 September
    2026 — it says what is owed, it never says what to call, and a model
    that ignores the whole section answers exactly as it would have.
    """

    @pytest.fixture
    def owed(self) -> CognitiveState:
        """A goal, a rule, and two premises the store cannot satisfy —
        the second blocked on the first, because it cannot even be stated
        until the first binds the account it is about."""
        state = CognitiveState()
        state.add_rule("owner_known", ("?a", "owner_known", True),
                       [("?a", "payment_link", "?c"), ("?c", "holder", "?h")],
                       authority=RuleAuthority.SKILL)
        state.add_goal(("alice", "owner_known", True))
        return state

    def test_an_open_obligation_names_the_pattern_and_its_goal(self, owed):
        assert section(compile_view(owed), OWED_HEADING)[0] == \
            "owed: (alice, payment_link, ?c) — for goal g1, open"

    def test_a_blocked_one_says_what_it_waits_on(self, owed):
        assert section(compile_view(owed), OWED_HEADING)[1] == \
            "owed: (?c, holder, ?h) — for goal g1, blocked on 1"

    def test_a_variable_does_not_read_like_a_string(self, owed):
        """``'?c'`` in quotes is a variable dressed as a literal value, in
        the one position where the difference is the whole meaning of the
        line: what is missing, against what is known."""
        for line in section(compile_view(owed), OWED_HEADING):
            assert "'?" not in line, line

    def test_the_workable_one_comes_first(self, owed):
        """The kernel's own ranking — fewest unresolved dependencies, then
        computation order — and not a second sort written here. A reader's
        eye lands on the cheapest true thing to do next."""
        lines = section(compile_view(owed), OWED_HEADING)
        assert lines == [owed_line(item) for item in owed.ranked_frontier()]
        assert owed_line(owed.next_obligation()) == lines[0]

    def test_and_the_ranking_is_not_the_order_it_was_computed_in(self):
        """The case where the two orders differ, written out in full.

        The assertion above says the block renders what
        `ranked_frontier()` returns, which is true of an unsorted
        `ranked_frontier()` as well — both sides would move together. So
        here is a state whose computation order and whose ranking are
        *different lists*: two goals, one rule, and a second premise that
        cannot be stated until the first binds the account it is about.
        Walked, it is alice-open, alice-blocked, bob-open, bob-blocked —
        goal by goal. Ranked, every workable line comes first and the
        blocked ones follow in the order they were found, which is what a
        reader working from the top of the section is owed.
        """
        state = CognitiveState()
        state.add_rule("owner_known", ("?a", "owner_known", True),
                       [("?a", "payment_link", "?c"), ("?c", "holder", "?h")],
                       authority=RuleAuthority.SKILL)
        state.add_goal(("alice", "owner_known", True))
        state.add_goal(("bob", "owner_known", True))
        assert section(compile_view(state), OWED_HEADING) == [
            "owed: (alice, payment_link, ?c) — for goal g1, open",
            "owed: (bob, payment_link, ?c) — for goal g2, open",
            "owed: (?c, holder, ?h) — for goal g1, blocked on 1",
            "owed: (?c, holder, ?h) — for goal g2, blocked on 1",
        ]
        assert [owed_line(item) for item in state.frontier()] != \
            [owed_line(item) for item in state.ranked_frontier()]

    def test_the_section_sits_after_the_conflicts(self, owed):
        state = owed
        state.declare_field("units", "one")
        observe(state, "t#r1", "units", 120)
        guess(state, "t#r1", "units", 999)
        guess(state, "t#g1", "route", "north")
        text = compile_view(state).text
        assert text.index(CONFLICTS_HEADING) < text.index(OWED_HEADING) \
            < text.index(HYPOTHESES_HEADING)

    def test_a_run_with_no_goals_has_no_heading_at_all(self, ledger):
        """The no-empty-headings rule. A mission that was given no pack is
        not told that nothing is owed — it is told nothing, which is what
        every other empty section in this block does."""
        assert OWED_HEADING not in compile_view(ledger).text

    def test_a_satisfied_goal_owes_nothing(self):
        """The kernel drops a goal the store already satisfies, and the
        section goes with it: a finished goal on an owed ledger is a
        runtime asking for what it has."""
        state = CognitiveState()
        state.add_rule("owner_known", ("?a", "owner_known", True),
                       [("?a", "payment_link", "?c")],
                       authority=RuleAuthority.SKILL)
        state.add_goal(("alice", "owner_known", True))
        assert OWED_HEADING in compile_view(state).text
        observe(state, "alice", "payment_link", "acct-9")
        assert OWED_HEADING not in compile_view(state).text

    def test_a_goal_alone_is_a_block_of_nothing_but_owed(self):
        """A run that knows what it wants and has established none of it
        still has something to be shown, and it is the frontier."""
        state = CognitiveState()
        owes(state, chain(2))
        view = compile_view(state)
        assert view.owed == 2
        assert view.facts == 0 and FACTS_HEADING not in view.text

    def test_nothing_in_the_section_is_an_instruction(self, owed):
        """The constitution, read off the words. A verb in the imperative
        would be the shadow layer steering with a mouth rather than
        reporting with a page."""
        text = "\n".join(section(compile_view(owed), OWED_HEADING)).lower()
        for word in ("call ", "you should", "must ", "try ", "next, ",
                     "do not"):
            assert word not in text, word

    def test_the_header_does_not_count_the_frontier(self, owed):
        """Receipts, facts and conflicts are one population — the evidence
        — and the frontier is not evidence. A fourth number in that
        sentence would be a count of something else entirely, with nothing
        on the line to say so."""
        observe(owed, "t#r1", "units", 120)
        assert lines_of(compile_view(owed))[0] == \
            f"{TITLE} — compiled from 1 receipt, 1 fact, 0 conflicts."


class TestTheFrontierSaysWhenItStoppedShort:
    """:attr:`~core.cognition.types.Frontier.truncated` is the kernel's own
    cap, not this module's budget, and the two say so differently.

    A walk that stopped at :data:`~core.cognition.state.ENV_CAP` and a walk
    that finished look identical from outside — both hand back obligations
    and neither says anything — and this repository's rule is that a budget
    exhausted is a recorded outcome naming the budget.
    """

    @pytest.fixture
    def capped(self) -> CognitiveState:
        state = CognitiveState()
        state.add_rule("owner_known", ("?a", "owner_known", True),
                       [("?a", "payment_link", "?c"), ("?c", "holder", "?h")],
                       authority=RuleAuthority.SKILL)
        state.add_goal(("alice", "owner_known", True))
        for index in range(ENV_CAP + 4):
            state.assert_observation(("alice", "payment_link", f"acct-{index}"),
                                     evidence=(receipt(f"r{index}"),),
                                     authority=EvidenceAuthority.SOURCE)
        assert state.ranked_frontier().truncated, "this fixture must cap"
        return state

    def test_the_section_says_the_walk_stopped(self, capped):
        assert section(compile_view(capped, budget_chars=1_000_000),
                       OWED_HEADING)[0] == FRONTIER_CAPPED

    def test_it_is_first_so_it_is_the_last_line_to_go(self, capped):
        """Lines are dropped from the end, so a flag at the end is a flag
        the budget silences. This one survives every owed line it stands
        in front of."""
        view = compile_view(capped, budget_chars=1_000_000)
        tight = compile_view(capped, budget_chars=len(view.text) // 4)
        assert tight.owed_omitted
        assert FRONTIER_CAPPED in tight.text

    def test_and_when_even_it_goes_the_block_still_says_so(self, capped):
        """The floor under the flag: the block's one omission sentence
        counts the owed lines it lost, the cap note among them, so there
        is no budget at which owed material disappears in silence."""
        tight = compile_view(capped, budget_chars=500)
        assert FRONTIER_CAPPED not in tight.text
        assert f"+{tight.owed_omitted} owed lines" in tight.text

    def test_an_uncapped_frontier_says_nothing_about_it(self):
        state = CognitiveState()
        owes(state, chain(3))
        assert FRONTIER_CAPPED not in compile_view(state).text

    def test_and_a_capped_walk_owing_nothing_renders_no_section(self,
                                                                monkeypatch):
        """The note says there is more than what is shown, so it needs
        something to be more *than*. A walk that stopped at the cap having
        resolved everything it reached leaves an empty frontier, and the
        note alone under the heading would be a section announcing itself
        over no rows — the no-empty-headings rule, broken by the one line
        that is exempt from being dropped.

        Asked of the renderer directly because the kernel is not known to
        produce this state today: the flag and the emptiness are two
        properties of one object, and what this pins is what the block does
        when it is handed both.
        """
        from core.cognition.types import Frontier

        state = CognitiveState()
        observe(state, "mcp.ledger_entry#r1", "units", 120)
        monkeypatch.setattr(type(state), "ranked_frontier",
                            lambda self: Frontier((), truncated=True))
        view = compile_view(state)
        assert view.owed == 0 and view.owed_omitted == 0
        assert OWED_HEADING not in view.text
        assert FRONTIER_CAPPED not in view.text


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


class TestTheSectionsAreOneList:
    """Five structures, four names, and nothing but this keeps them in step.

    :data:`SECTIONS` is the order the block renders in; :data:`HEADINGS` is
    parallel to it; :data:`DROP_ORDER` is the same four names in another
    order; and both ``_Cut`` and :class:`CompiledView` carry a field per
    name and a second field per name for what was lost. The module says
    the reason out loud — *four parallel tuples whose order is a
    convention is the shape where a heading ends up over the wrong lines*
    — and a fifth section, or a rename, is the edit that would prove it.
    """

    def _fields(self, cls):
        import dataclasses

        return [field.name for field in dataclasses.fields(cls)]

    def test_the_headings_are_parallel_to_the_sections(self):
        assert len(set(SECTIONS)) == len(SECTIONS)
        assert len(mod.HEADINGS) == len(SECTIONS)

    def test_the_drop_order_is_the_same_four_names(self):
        assert sorted(DROP_ORDER) == sorted(SECTIONS)

    def test_the_cut_carries_one_field_per_section_and_one_per_loss(self):
        assert self._fields(mod._Cut) == \
            list(SECTIONS) + [f"{name}_out" for name in SECTIONS]

    def test_and_the_view_carries_the_same_four_twice_over(self):
        section_fields = [name for name in self._fields(CompiledView)
                          if name in set(SECTIONS)
                          or name.endswith("_omitted")]
        assert section_fields == \
            list(SECTIONS) + [f"{name}_omitted" for name in SECTIONS]

    def test_and_the_kept_and_out_tuples_read_in_section_order(self):
        cut = mod._cut_at(0, (4, 3, 2, 1))
        assert cut.kept == (4, 3, 2, 1)
        assert cut.kept == tuple(getattr(cut, name) for name in SECTIONS)
        assert cut.out == tuple(getattr(cut, f"{name}_out")
                                for name in SECTIONS)


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

    def test_an_owed_line_outlives_a_fact(self):
        """The drop-order decision, stated as the thing it buys.

        A dropped fact is recoverable: its line printed the handle and the
        mission's result store holds that receipt whole, which is what the
        omission sentence tells the model in as many words. A dropped owed
        line is recoverable from nowhere — it is not in the transcript, not
        in the store, and no deployment has an interface that serves it.
        """
        state = CognitiveState()
        for index in range(30):
            observe(state, f"mcp.ledger_entry#r{index}", "units", index)
        owes(state, chain(3))
        whole = compile_view(state)
        tight = compile_view(state, budget_chars=len(whole.text) - 300)
        assert tight.facts_omitted
        assert tight.owed_omitted == 0
        assert tight.owed == whole.owed

    def test_but_a_guess_still_goes_before_an_owed_line(self):
        """Owed is kept longer than a receipt and a guess is kept shorter
        than everything: the frontier is guidance, and guidance a model
        wrote is the cheapest thing in the block."""
        state = CognitiveState()
        owes(state, chain(4))
        for index in range(10):
            guess(state, f"t#g{index}", "route", f"road-{index}")
        whole = compile_view(state)
        tight = compile_view(state, budget_chars=len(whole.text) - 100)
        assert tight.hypotheses_omitted
        assert tight.owed_omitted == 0

    def test_and_a_conflict_still_outlives_an_owed_line(self):
        """Conflicts stay last to go. What is owed is a question; a
        disagreement the model cannot see is an answer that is wrong."""
        state = CognitiveState()
        state.declare_field("units", "one")
        observe(state, "led.a41", "units", 120)
        guess(state, "led.a41", "units", 98)
        owes(state, chain(12))
        tight = compile_view(state, budget_chars=600)
        assert tight.conflicts == 1
        assert tight.owed_omitted

    def test_what_the_frontier_lost_is_counted_in_the_block(self):
        state = CognitiveState()
        owes(state, chain(20))
        view = compile_view(state, budget_chars=600)
        assert view.owed_omitted
        assert view.truncated
        assert f"+{view.owed_omitted} owed lines" in view.text

    def test_one_owed_line_lost_is_singular(self):
        """Asked of the sentence's one owner, because the budget at which
        exactly one line goes is not a number this file should have to
        know — the omission sentence is itself a line, so a block often
        loses two to afford saying it lost any."""
        assert "+1 owed line " in mod._omission((0, 0, 1, 0))
        assert "+2 owed lines " in mod._omission((0, 0, 2, 0))

    def test_the_sentence_names_its_losses_in_render_order(self):
        """Facts, conflicts, hypotheses — the order the block reads in, not
        the order the budget took them in. A reader matching the sentence
        against the block should not have to know the drop order.

        The owed lines are named in a clause of their own and therefore
        last; render order is kept inside the clause that has a store to
        point at, which is the clause it is a promise about."""
        said = mod._omission((1, 1, 1, 1))
        assert said.index("+1 fact") < said.index("+1 conflict") \
            < said.index("+1 hypothesis") < said.index("+1 owed line")

    def test_a_dropped_owed_line_is_not_promised_in_the_store(self):
        """The escape is true of three sections and false of this one. An
        owed line is computed from the goals against the store; it is in no
        store, and a model sent to look for one has spent a tool call
        learning the runtime was wrong about itself."""
        state = CognitiveState()
        owes(state, chain(20))
        view = compile_view(state, budget_chars=600)
        assert view.owed_omitted and view.facts_omitted == 0
        assert f"+{view.owed_omitted} owed lines" in view.text
        assert "result store" not in view.text
        assert "ask the mission" not in view.text

    def test_and_what_it_says_instead_is_what_is_true_of_a_frontier(self):
        """Nothing was lost when an owed line went: the frontier is
        recomputed from the goals at every step, and the rest of it renders
        as soon as the lines above it are resolved or there is room."""
        state = CognitiveState()
        owes(state, chain(20))
        text = compile_view(state, budget_chars=600).text
        assert "nothing to ask for" in text
        assert "recomputed from the goals at every step" in text

    def test_a_block_that_lost_only_receipts_says_only_that(self):
        """And the other direction: the clause appears where it is true and
        nowhere else, so a block that dropped no owed line reads exactly as
        it did before this clause existed."""
        state = CognitiveState()
        for index in range(40):
            observe(state, f"mcp.ledger_entry#r{index}", "units", index)
        owes(state, chain(2))
        view = compile_view(state, budget_chars=900)
        assert view.facts_omitted and view.owed_omitted == 0
        assert "result store" in view.text
        assert "nothing to ask for" not in view.text

    def test_and_a_block_that_lost_both_says_both(self):
        state = CognitiveState()
        for index in range(40):
            observe(state, f"mcp.ledger_entry#r{index}", "units", index)
        owes(state, chain(20))
        view = compile_view(state, budget_chars=500)
        assert view.facts_omitted and view.owed_omitted
        assert "result store" in view.text
        assert "nothing to ask for" in view.text

    def test_a_budget_too_small_to_explain_itself_compiles_nothing(self,
                                                                   wide):
        """A cap that is exceeded to apologise for itself is not a cap, and
        a block that is all apology is not worth a step."""
        assert compile_view(wide, budget_chars=80).text == ""


#: The shapes the oracle below is run over, as ``(facts, conflicts, owed,
#: hypotheses)``.  Small on purpose — the oracle renders every cut of every
#: shape at every budget, and a few hundred pairs settle the question that
#: a thousand would settle no better.  Each shape reaches a different
#: branch: nothing to drop but facts; a section that empties; a store whose
#: conflicts have to outlive its facts; a frontier with no receipts under
#: it at all; and a block in which every one of the four sections has to
#: give something up.
_SHAPES = {(12, 0, 0, 0), (20, 0, 0, 4), (8, 2, 0, 3), (30, 1, 0, 0),
           (5, 3, 0, 5), (0, 0, 6, 0), (10, 1, 4, 3), (6, 2, 9, 2)}

#: The budgets each shape is measured at: a stride across the whole range
#: from "not even the header" to "everything fits", chosen with a stride
#: that is not a multiple of a line length so the cuts land unevenly.
_BUDGETS = tuple(range(120, 1400, 17))


def _shaped(shape) -> CognitiveState:
    """A store of exactly *shape*, one receipt per fact.

    One receipt per fact is what lets the oracle know the header's receipt
    count without re-deriving it: it is the number of facts shown.  The
    conflicts are model-against-receipt disagreements, which is the kind a
    shadow run actually produces, and the owed lines are one goal's worth
    of premises nothing satisfies.
    """
    facts, conflicts, owed, hypotheses = shape
    state = CognitiveState()
    state.declare_field("units", "one")
    for index in range(facts):
        observe(state, f"mcp.ledger_entry#r{index}", "units", index)
    for index in range(conflicts):
        guess(state, f"mcp.ledger_entry#r{index}", "units", 900 + index)
    for index in range(hypotheses):
        guess(state, f"mcp.guess#g{index}", "route", f"road-{index}")
    if owed:
        owes(state, chain(owed))
    return state


def _brute_force(state: CognitiveState, budget: int) -> str:
    """What a renderer alone would choose: the first cut in order that fits.

    No arithmetic, no prefix sums, no reserved lengths — every cut in the
    documented drop order, rendered through the production renderer, and
    the first one that measures inside the budget.  That is the definition
    :func:`~core.cognition.compile.compile_view`'s size model is an
    optimisation of, so it is the thing the optimisation has to agree with.

    The drop order is **spelled out here** rather than imported from
    :data:`~core.cognition.compile.DROP_ORDER`, which is the whole point of
    an oracle: a second statement of the property, written by hand, that
    disagrees when the first one moves.  Hypotheses, then facts, then owed,
    then conflicts — and the interesting one is owed above facts, because a
    dropped fact is still in the result store under the handle its line
    printed and a dropped obligation is nowhere at all.
    """
    whole = compile_view(state, budget_chars=1_000_000)
    held = (whole.facts, whole.conflicts, whole.owed, whole.hypotheses)
    headings = (FACTS_HEADING, CONFLICTS_HEADING, OWED_HEADING,
                HYPOTHESES_HEADING)
    lines = [section(whole, heading) if count else []
             for heading, count in zip(headings, held)]
    facts, clashes, owed, guesses = (len(rows) for rows in lines)
    for dropped in range(facts + clashes + owed + guesses + 1):
        out_guesses = min(dropped, guesses)
        out_facts = min(dropped - out_guesses, facts)
        out_owed = min(dropped - out_guesses - out_facts, owed)
        out_clashes = min(dropped - out_guesses - out_facts - out_owed,
                          clashes)
        kept = (facts - out_facts, clashes - out_clashes, owed - out_owed,
                guesses - out_guesses)
        text = mod._render([rows[:keep] for rows, keep in zip(lines, kept)],
                           # one receipt per fact — see `_shaped`
                           kept[0],
                           (out_facts, out_clashes, out_owed, out_guesses))
        if len(text) <= budget:
            return text
    return ""


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
    def test_one_render_whatever_the_store_holds(self, monkeypatch, facts):
        state = CognitiveState()
        for index in range(facts):
            observe(state, f"t#r{index}", "units", index)
        calls = self._spy(monkeypatch)
        assert compile_view(state).text
        assert len(calls) == 1, len(calls)

    @pytest.mark.parametrize("facts", [10, 100, 1000])
    def test_one_render_when_the_budget_bites_as_well(self, monkeypatch,
                                                      facts):
        """The path that used to be the quadratic one: the tighter the
        budget, the more lines the old loop dropped and the more whole
        blocks it built to find that out."""
        state = CognitiveState()
        for index in range(facts):
            observe(state, f"t#r{index}", "units", index)
        calls = self._spy(monkeypatch)
        assert compile_view(state, budget_chars=800).text
        assert len(calls) == 1, len(calls)

    def test_a_budget_that_fits_nothing_renders_nothing(self, monkeypatch):
        state = CognitiveState()
        observe(state, "t#r1", "units", 120)
        calls = self._spy(monkeypatch)
        assert compile_view(state, budget_chars=30).text == ""
        assert calls == []

    @pytest.mark.parametrize("shape", sorted(_SHAPES))
    def test_the_cut_is_what_brute_force_would_have_chosen(self, shape):
        """The oracle, and it is the only honest form of this claim.

        Safe is not enough: a cut that dropped everything would satisfy
        every cap assertion in this file.  So the block is compared,
        budget by budget, against **rendering every cut in drop order and
        taking the first that fits** — which is the definition the
        arithmetic is an optimisation of, and which cannot be wrong
        because it does not compute anything.

        The review found what a weaker check missed: reserving the widest
        header any cut could need is two characters wide of the truth for
        a typical one, and over 1,941 measured pairs that cost 44 of them
        a line they had room for and two of them a block entirely.  A test
        that only asked "does one more line fit at a slightly larger
        budget" passed through all of it.
        """
        state = _shaped(shape)
        for budget in _BUDGETS:
            assert compile_view(state, budget_chars=budget).text == \
                _brute_force(state, budget), (shape, budget)

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

    def test_the_frontier_is_in_the_digest(self):
        """The digest is what the supervisor's stall signal and any cache
        key are read through, so a block whose OWED section changed and
        whose facts did not has to digest differently. A view that dropped
        the frontier from what it hashes would call two different problems
        the same problem."""
        first, second = CognitiveState(), CognitiveState()
        for state, premises in ((first, chain(2)), (second, chain(3))):
            observe(state, "t#r1", "units", 120)
            owes(state, premises)
        assert compile_view(first).digest() != compile_view(second).digest()

    def test_an_obligation_resolving_changes_the_block(self):
        """The frontier moving is the event Phase 19 is about, and the
        block is where a reader sees it."""
        state = CognitiveState()
        owes(state, chain(2))
        before = compile_view(state).digest()
        observe(state, "alice", "p0", "acct-9")
        assert compile_view(state).digest() != before

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
