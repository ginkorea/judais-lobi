# tests/test_grounding_the_critique_names_the_fix.py — a finding is not a fix

"""Two production answers the grounding tier judged and did not repair.

Both were served.  Both were wrong.  Neither failure was a failure of the
*finding* — one was flagged exactly right and the other was invisible — and
that is what this file is about: **a critique that names what is wrong and
not what to do instead gets the same answer back.**

**1 — the arithmetic in prose.**  Asked for the top-five share of a run's
total, with the working shown, the model read a five-row ranking out of a
lookup, summed the five scores in a sentence, took a real field off the same
result that holds the run's *elapsed seconds*, divided one by the other and
asserted a share of 121.2% — with a closing note explaining why a share may
exceed 100%.  The figures check flagged the sum, the quotient and the
percentage, correctly, and spent the run's repair turn saying so.  The
repair turn said *either call a tool that returns them, or rewrite the
answer without them*.  Neither branch exists for a model that believes it
has already done the arithmetic: no tool returns a quotient nobody
computed, and rewriting without the figures deletes the answer.  The
model re-asserted and the run ended ``answered_with_caveat`` with the wrong
figures in it.

What was never said is the branch the platform had already declared:
``figures_from`` names the tools that measure this skill's quantity, which
is to say *the computation plane*.  :class:`TestTheRepairTurnNamesTheFix`
is that sentence, in both of its halves — the scoped one that can name the
tool, and the generic one for a skill that scoped nothing.

**2 — the answer about the tooling.**  Asked to build a small table and
show it — a pure run-the-code objective — the model called nothing and
wrote about the harness: which tools were not invoked, what it therefore had
no evidence to cite, what was not retrieved in this turn.  Every mechanical
check passed it.  The grammars extracted nothing, so both reported *nothing
to check — the answer states no identifiers*, which under a skill with no
``must_cite`` is a legitimate verdict; there was no plane claim to be false,
because the answer claims the opposite.  The run came back ``answered``.
:class:`TestAnAnswerAboutTheToolPlane` is the check that notices, and — as
much of this file — the four answers it must stay silent on.

**3 — the label beside the figure.**  Half of the first failure is not
arithmetic at all: ``154.024 (field `total_s`)`` is a claim about where a
number came from, and a membership check cannot see it, because the number
is in the evidence.  :class:`TestAFigureIsHeldByTheFieldItNames` checks the
pairing.  The recorded one PASSES — ``total_s`` really does hold 154.024 —
and that is an assertion here rather than an omission: this check is for the
invented pairing, and the arithmetic that misuses a real one is the first
mechanism's.

Every payload below is the recorded one with its platform's names taken
out: a run, a ranking, three tools with ordinary names.  The figures, the
shape of the JSON and the sentences the model wrote are as they were.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.grounding import (
    UNCONFIGURED,
    UNSUPPORTED,
    FieldAttributionCheck,
    GroundingConfig,
    GroundingValidator,
    NumericGroundingCheck,
    SubjectGroundingCheck,
)
from core.runtime.results import MissionResultStore
from core.runtime.run import (
    Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.usage import Ledger
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox
from tests.test_mission import ScriptedModel

#: The deployed figure grammar, imported rather than retyped — the same
#: reason `tests/test_grounding_echo.py` imports it.
FIGURES = NumericGroundingCheck.FIGURE.pattern

#: The lookup that answered both recorded turns, and the two other tools
#: that mission was offered.
LOOKUP = "runs_get"
OFFERED = (LOOKUP, "inventory_search", "jobs_list")

#: The ranking result, cut to the fields the answer read.  `total_s` is the
#: run's elapsed seconds and the five scores are impact scores; nothing in
#: the payload says the second is a share of the first, and the answer
#: divided one into the other anyway.
RANKING = json.dumps({
    "data": {
        "runs": [{
            "run_id": "3baa3f3f96e5",
            "stage": "final",
            "nodes": 127,
            "edges": 1080,
            "total_s": 154.024,
        }],
        "ranking": {
            "actor_count": 127,
            "top": 5,
            "actors": [
                {"rank": 1, "actor_id": "1709286740",
                 "impact_score": 54.36487},
                {"rank": 2, "actor_id": "6439298407",
                 "impact_score": 38.65662},
                {"rank": 3, "actor_id": "1733592447",
                 "impact_score": 35.146462},
                {"rank": 4, "actor_id": "5519666559",
                 "impact_score": 31.040223},
                {"rank": 5, "actor_id": "2656274875",
                 "impact_score": 27.493561},
            ],
        },
    },
}, indent=2)

#: The served answer, shortened to the working it showed.  Three figures in
#: it were computed in prose: the sum, the quotient and the percentage.
DERIVED_IN_PROSE = """The newest final run (run_id = 3baa3f3f96e5) reports a
total of **154.024** (field `total_s`). The top-5 actors and their scores:
54.36487, 38.65662, 35.146462, 31.040223, 27.493561.

Summing these five scores gives **186.701736**. Dividing by the run's total
yields a share of **186.701736 / 154.024 = 1.212 or 121.2%**.

*Note:* the sum of all actor scores exceeds `total_s`, so the share exceeds
100%. This is a known artifact of the output format.
"""

#: The served answer to "make a small table and show it".  Not one tool was
#: called; every sentence is about the tools that were not.
ABOUT_THE_TOOLING = (
    "I could not determine whether a corpus exists, whether it has a label "
    "set, or whether a finished run already answers the question, because "
    "no catalog or run-related tool was invoked in this turn. Without a "
    "call to a registered tool such as `inventory_search`, `runs_get`, or "
    "`jobs_list`, I have no evidence to cite. Therefore I cannot specify "
    "which half of the capability is needed or provide any identifiers. I "
    "can only state that the necessary information was not retrieved in "
    "this turn."
)


def store_with(*, tool=LOOKUP, text=RANKING):
    """One result in a store, so the evidence carries its provenance."""
    store = MissionResultStore()
    store.record(tool, {"run_id": "3baa3f3f96e5"}, text=text, exit_code=0)
    return store


def validator(**config):
    made = GroundingValidator.from_config(
        GroundingConfig(**config).offering(OFFERED))
    assert made is not None
    return made


def row(report, name):
    return next(r for r in report.results if r.check == name)


# ── 1. the arithmetic in prose ──────────────────────────────────────────────


class TestTheRepairTurnNamesTheFix:
    """The sentence the 121.2% answer was never sent.

    Both halves of it, because a skill that declared its computation plane
    and a skill that did not are two different things to say and only one
    of them can name a tool.
    """

    def report(self, **config):
        return validator(number_pattern=FIGURES, **config).validate(
            DERIVED_IN_PROSE, store_with().evidence_texts(), calls=1)

    # ── the finding is still the finding ────────────────────────────────

    def test_the_prose_arithmetic_is_flagged_as_it_always_was(self):
        """The three figures nothing measured, and not the five it read."""
        failed = set(row(self.report(), "figures").unsupported)
        assert {"186.701736", "1.212", "121.2"} <= failed
        assert "54.36487" not in failed
        assert "154.024" not in failed

    # ── and now it names the fix ────────────────────────────────────────

    def test_a_skill_that_named_its_computation_plane_gets_the_tool(self):
        prompt = GroundingValidator.repair_prompt(
            self.report(figures_from=("compute",)))
        assert "Do not derive figures in prose." in prompt
        assert ("Call compute to compute them from the tool results' own "
                "fields, and state only what it prints.") in prompt

    def test_two_scoped_tools_are_both_named(self):
        prompt = GroundingValidator.repair_prompt(
            self.report(figures_from=("compute", "tabulate")))
        assert "Call compute or tabulate to compute them" in prompt

    def test_a_skill_that_scoped_nothing_gets_the_generic_half(self):
        prompt = GroundingValidator.repair_prompt(self.report())
        assert "Do not derive figures in prose." in prompt
        assert ("If this catalogue offers a computation tool, compute it "
                "there and cite what it printed; otherwise state only "
                "figures the tools returned.") in prompt
        assert "Call compute" not in prompt

    def test_the_direction_is_said_beside_the_generic_finding(self):
        """Unscoped, the figures check has no words of its own and stays in
        the generic paragraph — which is `test_evidence_scope.py`'s claim
        and is not disturbed. The direction is added, not substituted."""
        prompt = GroundingValidator.repair_prompt(self.report())
        assert "in no tool output you received" in prompt
        assert prompt.index("in no tool output you received") < \
            prompt.index("Do not derive figures in prose.")

    def test_the_direction_is_said_beside_a_scoped_finding_too(self):
        prompt = GroundingValidator.repair_prompt(
            self.report(figures_from=("compute",)))
        assert "These figures are in no compute result" in prompt
        assert "Do not derive figures in prose." in prompt

    def test_a_grounded_answer_is_told_nothing(self):
        """No failed figure, no direction: a repair turn that lectures an
        answer it did not fault is a repair turn its reader skims."""
        report = validator(number_pattern=FIGURES).validate(
            "The run took 154.024 seconds.", store_with().evidence_texts(),
            calls=1)
        assert row(report, "figures").remedy == ""
        assert "Do not derive figures in prose." not in \
            GroundingValidator.repair_prompt(report)

    # ── and the escape hatch no longer invites the other failure ────────

    def test_the_escape_hatch_points_at_the_objective_not_the_tooling(self):
        """"Say plainly what the tools could not establish" is an invitation
        to write the second failure in this file. What a reader is owed is
        what could not be established ABOUT THE OBJECTIVE."""
        prompt = GroundingValidator.repair_prompt(self.report())
        assert ("say plainly what could not be established about the "
                "objective — never by describing this run's tooling in the "
                "answer") in prompt
        assert "what the tools could not establish" not in prompt
        assert "similar-looking" in prompt


# ── 2. the answer about the tooling ─────────────────────────────────────────


class TestAnAnswerAboutTheToolPlane:
    """Zero calls, nothing to check, and every sentence about the harness.

    The three conditions are all required, and the four counterexamples
    below are each one of them removed.
    """

    def report(self, answer=ABOUT_THE_TOOLING, *, calls=0, evidence=(),
               called=(), **config):
        return validator(identifier_pattern=r"\brun-\d+\b",
                         number_pattern=FIGURES, **config).validate(
            answer, list(evidence), called=list(called), calls=calls)

    # ── it fires on the recorded answer ─────────────────────────────────

    def test_the_recorded_answer_is_unsupported(self):
        found = row(self.report(), "subject")
        assert found.verdict == UNSUPPORTED
        assert found.unsupported == (SubjectGroundingCheck.FINDING,)

    def test_the_row_says_why(self):
        detail = row(self.report(), "subject").detail
        assert "the answer's subject is this run's tooling" in detail
        assert "runs_get" in detail

    def test_the_report_is_not_grounded(self):
        assert self.report().grounded is False

    def test_two_markers_alone_are_enough_without_a_tool_name(self):
        """A model that describes the plane without naming anything on it.
        `no tool` and `no evidence to cite` are two of the closed set."""
        found = row(self.report(
            "No tool was available for this, so I have no evidence to cite."
        ), "subject")
        assert found.verdict == UNSUPPORTED

    def test_the_bare_name_of_a_bridged_tool_counts(self):
        """A bridge prefixes a server's tools so one cannot shadow another,
        and a model writes the bare name it reads in the skill's prose.
        Both are the tool, and an answer reciting either is reciting the
        catalogue."""
        made = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=r"\brun-\d+\b").offering(
                ["mcp.inventory_search"]))
        found = row(made.validate(
            "Without a call to inventory_search there is nothing to say.",
            [], calls=0), "subject")
        assert found.verdict == UNSUPPORTED

    def test_a_short_name_is_not_hunted_for_in_prose(self):
        """A two-letter tool name is a substring of ordinary English, and a
        check that searched for it would read a word as a catalogue entry."""
        made = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=r"\brun-\d+\b").offering(
                ["go"]))
        found = row(made.validate(
            "I could not go on: no tool was reachable.", [], calls=0),
            "subject")
        assert found.unsupported == ()

    def test_one_marker_alone_is_not_enough(self):
        """One meta phrase in an answer that is otherwise about the work is
        an aside, and a check that fired on it would flag the honest ones."""
        found = row(self.report(
            "The table has three rows and two columns; no tool was needed."
        ), "subject")
        assert found.unsupported == ()

    # ── the four it must stay silent on ─────────────────────────────────

    def test_the_same_answer_after_one_call_is_never_this_finding(self):
        """The recorded answer exactly, and one dispatch. Nothing else about
        it changes: a mission that called a tool and then wrote about the
        tools it did not call has at least done something, and this check
        is for the answer that did nothing."""
        found = row(self.report(calls=1, called=[LOOKUP]), "subject")
        assert found.unsupported == ()

    def test_a_run_that_called_something_is_never_this_finding(self):
        """The honest caveat after a call that failed — the answer this
        repository most wants — names a tool and a failure in one sentence
        and must never be read as this."""
        found = row(self.report(
            "The fetch returned 404, so no tool was able to read the third "
            "source and the report cannot include it. Without a call to "
            "that page I have no evidence to cite for it.",
            calls=2, called=["fetch"]), "subject")
        assert found.unsupported == ()
        assert "this run called a tool" in found.detail

    def test_an_answer_with_content_is_never_this_finding(self):
        """A figure the other checks considered means the answer grounds
        something, whatever else it mentions in passing."""
        report = self.report(
            "The total is 48750, computed via the code tool. No tool call "
            "was made for the second file and I have no evidence to cite "
            "about it.",
            evidence=["the code printed 48750"])
        assert row(report, "figures").considered == ("48750",)
        assert row(report, "subject").unsupported == ()

    def test_an_answer_about_the_objective_is_never_this_finding(self):
        found = row(self.report(
            "There is no corpus under that name and nothing to summarise."
        ), "subject")
        assert found.unsupported == ()

    def test_a_tool_name_in_passing_is_not_the_finding(self):
        """An offered tool named, no meta phrase, and no call either — so
        the call count is not what is holding this one back. A catalogue
        name is a word the harness itself put in the prompt; the finding is
        the answer being ABOUT it, which takes both halves in one
        sentence."""
        found = row(self.report(
            "The ranking runs_get returns is sorted by score, and the "
            "table below is that order."), "subject")
        assert found.unsupported == ()

    # ── configuration: silence is not zero ──────────────────────────────

    def test_a_caller_that_said_nothing_gets_no_opinion(self):
        """A library caller supplies no call count, and a check that read
        that as "this run called nothing" would report the finding about a
        run whose calls it cannot see."""
        made = validator(identifier_pattern=r"\brun-\d+\b")
        found = row(made.validate(ABOUT_THE_TOOLING, []), "subject")
        assert found.verdict == UNCONFIGURED
        assert "how many tools this run called" in found.detail

    def test_it_is_unconfigured_when_the_validator_is_built(self):
        """So a grounding block that configures nothing else still builds no
        validator: `from_config` counts the checks that could run."""
        assert GroundingValidator.from_config(GroundingConfig()) is None

    def test_a_wildcard_minimum_cannot_require_a_meta_answer(self):
        """`must_cite: true` is a floor on every configured check, and a
        floor here would demand that every answer BE this failure."""
        report = validator(identifier_pattern=r"\brun-\d+\b",
                           must_cite=(("*", 1),)).validate(
            "run-7 is the newest.", ["run-7"], calls=1)
        assert row(report, "subject").minimum == 0
        assert "subject" not in report.uncited

    # ── the words ───────────────────────────────────────────────────────

    def test_the_repair_turn_says_do_the_work(self):
        prompt = GroundingValidator.repair_prompt(self.report())
        assert ("The objective is not about this run's tooling. Do the "
                "work: call the tool that does it, or answer the objective "
                "with what you have and name what is missing — without "
                "describing the tool plane.") in prompt
        assert "runs_get" in prompt, "a repair turn names what is on offer"
        assert "in no tool output you received" not in prompt, (
            "no tool output could support or refute what an answer is "
            "ABOUT, so the generic sentence sends it looking for one")

    def test_the_caveat_says_the_objective_was_not_attempted(self):
        caveat = GroundingValidator.caveat(self.report())
        assert "Unattempted" in caveat
        assert "dispatched none" in caveat
        assert "in no tool result from this mission" not in caveat


class TestTheCallCountReachesTheCheckThroughARun:
    """The wiring, through a real `Run` rather than a hand-built report.

    The check is only as good as the fact it is told, and the fact has one
    owner: the mission's own result store, one entry per dispatch.
    """

    def a_run(self, bus, *replies, grounding=None, records=None):
        store = Store(run_id="run-1")
        return Run(
            Personality(system_message="You are Tai.", grounding=grounding),
            ToolPlane(bus=bus, offered=[LOOKUP], store_tool=""),
            Bounds(),
            store,
            Observer((records if records is not None else []).append,
                     store=store),
            Model(ask=ScriptedModel(*replies), ledger=Ledger()),
        )

    @pytest.fixture
    def bus(self):
        made = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=NoneSandbox())
        made.register(
            ToolDescriptor(tool_name=LOOKUP, description="Read a run."),
            lambda **kw: (0, RANKING, ""))
        return made

    def grounding(self):
        return GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=r"\brun-\d+\b",
                            number_pattern=FIGURES,
                            max_repairs=0).offering(OFFERED))

    def test_a_run_that_called_nothing_reaches_the_check(self, bus):
        run = self.a_run(bus, json.dumps({"answer": ABOUT_THE_TOOLING}),
                         grounding=self.grounding())
        transcript = run.run("make a small table and show it")
        assert transcript.outcome == "answered_with_caveat"
        found = row(transcript.grounding, "subject")
        assert found.verdict == UNSUPPORTED
        assert "Unattempted" in transcript.answer

    def test_a_run_that_called_something_does_not(self, bus):
        run = self.a_run(
            bus,
            json.dumps({"tool": LOOKUP, "arguments": {"run_id": "x"}}),
            json.dumps({"answer": ABOUT_THE_TOOLING}),
            grounding=self.grounding())
        transcript = run.run("make a small table and show it")
        assert row(transcript.grounding, "subject").unsupported == ()
        assert transcript.outcome == "answered"

    def test_the_staged_synthesizer_named_its_own_and_gets_no_opinion(
            self, bus):
        """A staged turn's answer is written over several stores and it
        names its evidence and its called set itself. It says nothing about
        a count, and nothing is not zero — see `Run._ground`."""
        run = self.a_run(bus, grounding=self.grounding())
        report = run._ground(ABOUT_THE_TOOLING, 0, evidence=[RANKING],
                             called=[LOOKUP])
        assert row(report, "subject").verdict == UNCONFIGURED


# ── 3. the label beside the figure ──────────────────────────────────────────


class TestAFigureIsHeldByTheFieldItNames:
    """`154.024 (field `total_s`)` is a claim, and it is checkable.

    Two findings and one deliberate pass. The pass is the recorded answer:
    `total_s` really does hold 154.024, so the attribution is CORRECT and
    the error in that sentence is what the answer then did with it.
    """

    def report(self, answer, evidence=None, **config):
        return validator(number_pattern=FIGURES, **config).validate(
            answer,
            store_with().evidence_texts() if evidence is None else evidence,
            calls=1)

    def found(self, answer, evidence=None, **config):
        return row(self.report(answer, evidence, **config), "attribution")

    # ── the pass that is the boundary between two checks ────────────────

    def test_the_recorded_attribution_passes_because_it_is_true(self):
        found = self.found("The run reports **154.024** (field `total_s`).")
        assert found.considered == ("total_s=154.024",)
        assert found.unsupported == ()
        assert "1/1 figure(s) held by the field" in found.detail

    def test_a_nested_field_read_correctly_passes(self):
        found = self.found("The top actor's `impact_score`: 54.36487.")
        assert found.unsupported == ()

    # ── the field that does not exist ───────────────────────────────────

    def test_a_field_no_result_carries_is_unsupported(self):
        found = self.found(
            "The share is **1.212** (field `influence_share`).")
        assert found.unsupported == ("influence_share=1.212",)

    def test_the_repair_turn_names_real_keys(self):
        report = self.report(
            "The share is **1.212** (field `influence_share`).")
        prompt = GroundingValidator.repair_prompt(report)
        assert ("`influence_share` is not a field in any result of this "
                "mission") in prompt
        assert "Fields the results actually hold include:" in prompt
        assert "actor_count" in prompt

    def test_the_repair_turn_offers_no_more_than_eight(self):
        prompt = GroundingValidator.repair_prompt(self.report(
            "The share is **1.212** (field `influence_share`)."))
        named = prompt.partition("actually hold include: ")[2].partition(".")[0]
        assert len(named.split(", ")) == FieldAttributionCheck.NAMED

    # ── the field that exists and holds something else ──────────────────

    #: A figure the results really do hold — under `impact_score`, not
    #: under `total_s`. Written this way so the figures check PASSES it and
    #: the only finding on the answer is the label, which is the whole
    #: point of this check existing beside that one.
    MISLABELLED = "The run took **54.36487** (field `total_s`)."

    def test_a_real_field_with_the_wrong_figure_is_unsupported(self):
        report = self.report(self.MISLABELLED)
        assert row(report, "figures").unsupported == ()
        assert row(report, "attribution").unsupported == ("total_s=54.36487",)

    def test_the_repair_turn_says_the_field_is_real(self):
        prompt = GroundingValidator.repair_prompt(self.report(self.MISLABELLED))
        assert ("`total_s` is a real field and holds no value 54.36487"
                in prompt)
        assert "not a field in any result" not in prompt
        assert "in no tool output you received" not in prompt, (
            "the figure IS in a tool output; what is wrong is the label, and "
            "the generic sentence sends the model hunting for a "
            "transcription slip that is not there")

    def test_the_caveat_says_the_label_is_wrong_not_the_figure(self):
        caveat = GroundingValidator.caveat(self.report(self.MISLABELLED))
        assert "Misattributed" in caveat
        assert "total_s = 54.36487" in caveat
        assert "in no tool result from this mission" not in caveat

    # ── the three spellings, and what is not one ────────────────────────

    def test_the_aside_may_come_first(self):
        assert self.found("field `nodes` is 128").unsupported == \
            ("nodes=128",)

    def test_a_bare_pairing_needs_its_operator(self):
        assert self.found("`edges` = 1081").unsupported == ("edges=1081",)
        assert self.found("`edges` then 1081").considered == ()

    def test_a_backticked_word_beside_a_number_is_not_a_claim(self):
        """Otherwise every quoted tool name next to a count is a finding."""
        assert self.found("I called `runs_get` 3 times.").considered == ()

    #: A draft inside a fence: the analyst skill tells a model to keep its
    #: figures out of one, and a model that pastes a NUMBERS section in
    #: anyway is quoting a proposal rather than asserting it.
    FENCED = ("Here is the draft I did not use:\n"
              "```\nTotal **154.024** (field `total_s`)\n```\n"
              "The run finished.")

    def test_a_fenced_block_is_not_an_attribution(self):
        """The inline backticks are kept — they are this check's grammar —
        and a fence is still a fence. The second half is what makes the
        first half a claim about the fence and not about the pattern."""
        assert self.found(self.FENCED).considered == ()
        assert self.found(self.FENCED.replace("```\n", "")).considered == \
            ("total_s=154.024",)

    # ── the evidence side ───────────────────────────────────────────────

    def test_evidence_that_is_not_json_teaches_no_field_names(self):
        """And does not raise. A text with no parseable payload contributes
        nothing, so an answer checked against it considers a name it cannot
        confirm — and `supported` is the honest answer only where the name
        was seen."""
        found = self.found("The run took **154.024** (field `total_s`).",
                           evidence=["the run finished in 154.024 seconds"])
        assert found.unsupported == ("total_s=154.024",)

    def test_a_key_seen_only_in_unparseable_text_is_real_enough(self):
        """A truncated payload still shows its keys. The check knows the
        account of provenance is not invented and cannot say more."""
        found = self.found(
            "The run took **99.5** (field `total_s`).",
            evidence=['{"data": {"total_s": 154.024, "run_id": "3b'])
        assert found.unsupported == ()

    def test_a_field_holding_an_object_is_real_and_not_compared(self):
        found = self.found("The ranking is **5** (field `ranking`).",
                           evidence=[RANKING])
        assert found.unsupported == ()

    def test_the_scope_applies_here_too(self):
        """`figures_from` is what a skill says measures its quantity, and a
        field name read off a result outside that scope is a field name this
        skill's figures may not be attributed to."""
        assert self.found(
            "The run took **154.024** (field `total_s`).",
            figures_from=("compute",)).unsupported == ("total_s=154.024",)

    def test_it_runs_only_where_figures_do(self):
        made = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=r"\brun-\d+\b"))
        found = row(made.validate("**154.024** (field `total_s`)", [],
                                  calls=1), "attribution")
        assert found.verdict == UNCONFIGURED
        assert "number_pattern" in found.detail

    def test_a_clean_answer_says_it_pairs_nothing(self):
        found = self.found("The run finished.")
        assert "nothing to check — the answer pairs no figure with a named "\
            "field" in found.detail
