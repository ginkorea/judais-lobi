# tests/test_grounding_echo.py — figures that arrived without being measured

"""Three ways a figure reached the evidence set without any tool having
measured it.  The file is named for the first of them.

1. **The echo.**  A model told a figure is unsupported runs
   ``print('30,000')`` and re-submits.
2. **The clock.**  A timestamped tool result donates its minute and its
   second to the evidence set, and an invented "52 hours" comes back
   grounded.  Nobody has to try: it happens on its own.
3. **A call that failed.**  Its arguments are now evidence, so that "I
   could not read that page — it answered 404" can ground the URL and the
   status.  What the model SENT must not thereby ground the model's own
   arithmetic.

The first is below in full; the other two follow it.

**The echo.**  Stated as an analyst lane found it: *a model told a figure is
unsupported can run* ``print('30,000')`` *and re-submit, and the record
then says* ``grounded: true``.  Nothing about the shape of the evidence
distinguished a computed figure from an echoed one — it is a tool's
stdout either way — so the only thing standing between the harness and a
laundered number was skill content telling the model not to, which is a
property that holds for exactly as long as the model cooperates.

What closes it is mechanical and lives in one place
(:class:`~core.runtime.grounding.NumericGroundingCheck`): **a code-plane
call whose output holds no figure it was not already given grounds
nothing.**  The two halves of that sentence are the two halves of this
file.

* :class:`TestAnEchoIsNotEvidence` — the hazard, in the spellings a model
  reaches for: printing a quoted figure, printing a bare one, echoing it
  from a shell, and doing it again after the repair turn has said so.
* :class:`TestWhatTheRuleMustNotTouch` — the far more common case, and the
  one this repository has already paid for once.  A check that flags
  working code is a check its reader learns to skip, which un-catches the
  fabrications it exists for (``tests/test_grounding_code_is_not_a_claim
  .py``).  A computed figure grounds; a literal that merely collides with
  a computed result grounds; a non-code tool handed a figure and echoing
  it back is untouched, because that is what a lookup by id does.

The collision case is not hypothetical and is why the rule asks whether
the CALL computed rather than docking each figure: the committed analyst
stream ``errors_by_hour`` increments its counter with ``+ 1`` and its
program then computes that one hour has exactly ``1`` error.  Same digit,
one a step and one a result.  Excluding every figure the arguments
happened to contain took that correct answer apart and spent a repair
turn on it, and ``tests/test_pack_analyst.py`` went red on two cells.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.grounding import (
    GroundingConfig,
    GroundingValidator,
    NumericGroundingCheck,
)
from core.runtime.mission import MissionRunner
from core.runtime.results import MissionResultStore, SourcedEvidence
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor

#: The deployed grammar, imported rather than retyped: the analyst pack's
#: manifest asks for figures with exactly the pattern the check's own
#: :data:`~core.runtime.grounding.NumericGroundingCheck.FIGURE` uses, and a
#: copy here would let this file pass against a grammar nobody ships.
FIGURES = NumericGroundingCheck.FIGURE.pattern

#: The tool a code plane is reached through in the analyst pack.  Named as
#: a constant so the tests read as one hazard rather than eight, and so
#: the one test that deliberately uses a DIFFERENT name is visible.
PYTHON = "run_python_code"

#: The recorded `errors_by_hour` mission's script, cut to the lines that
#: make the collision: the counter's `+ 1` is a literal in the arguments,
#: and one of the hours the program counts really does have 1 error.
COLLIDING = (
    'counts[hour] = counts.get(hour, 0) + 1\n'
    'print("errors:", sum(counts.values()))\n'
    'for hour in sorted(counts):\n'
    '    print("hour", hour, "errors", counts[hour])\n'
)

#: What that program printed.
COLLIDING_OUTPUT = "errors: 28\nhour 09 errors 1\nhour 13 errors 17\n"


@pytest.fixture
def validator():
    return GroundingValidator.from_config(
        GroundingConfig(number_pattern=FIGURES))


def unsupported(validator, answer, store):
    return validator.validate(answer, store.evidence_texts()).unsupported


class TestAnEchoIsNotEvidence:
    """The hazard, in the spellings a model reaches for."""

    def test_printing_the_figure_back_grounds_nothing(self, validator):
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print('30,000')"},
                     text="30,000\n", exit_code=0)
        assert unsupported(
            validator, "Revenue was 30,000.", store) == ("30,000",)

    def test_a_bare_literal_is_the_same_echo(self, validator):
        """`print(30000)` is the likelier attempt of the two, and a rule
        that only saw quoted text would miss it."""
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(30000)"},
                     text="30000\n", exit_code=0)
        assert unsupported(validator, "Revenue was 30,000.", store) \
            == ("30,000",)

    def test_a_shell_echo_is_the_same_hazard(self, validator):
        store = MissionResultStore()
        store.record("run_shell_command", {"command": "echo 42"},
                     text="42\n", exit_code=0)
        assert unsupported(validator, "There were 42.", store) == ("42",)

    def test_a_bridged_code_plane_tool_is_covered(self, validator):
        """The sandbox gate deliberately lets a bridged shell past — the
        question there is who runs the subprocess.  The question here is
        who WROTE the program, and that is the model whichever end runs
        it, so this one matches on `same_tool`."""
        store = MissionResultStore()
        store.record("mcp.run_python_code", {"code": "print(30000)"},
                     text="30000\n", exit_code=0)
        assert unsupported(validator, "Revenue was 30,000.", store) \
            == ("30,000",)

    def test_the_typed_payload_of_an_echo_grounds_nothing_either(
            self, validator):
        """A call contributes up to two evidence texts and each is asked
        the same question: crediting the structured rendering of an echo
        would be the same laundering through the other door."""
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(30000)"}, text="30000\n",
                     evidence=json.dumps({"stdout": "30000"}), exit_code=0)
        assert unsupported(validator, "Revenue was 30,000.", store) \
            == ("30,000",)


class TestWhatTheRuleMustNotTouch:
    """The common case: code that ran and computed something."""

    def test_a_computed_figure_grounds(self, validator):
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(df.amount.max())"},
                     text="48750.0\n", exit_code=0)
        assert unsupported(validator, "The largest is 48750.0.", store) == ()

    def test_a_threshold_the_script_was_given_does_not_dock_the_result(
            self, validator):
        """`df[df.amount > 30000]` prints rows containing 48750.  The
        threshold was an input; the row is a result, and the call grounds
        what it printed."""
        store = MissionResultStore()
        store.record(PYTHON,
                     {"code": "print(df[df.amount > 30000].amount.max())"},
                     text="48750.0\n", exit_code=0)
        assert unsupported(validator, "The largest is 48750.0.", store) == ()

    def test_a_literal_that_collides_with_a_computed_result_still_grounds(
            self, validator):
        """The committed `errors_by_hour` stream, cut to its collision.

        The script increments a counter with `+ 1`; the program then
        computes that one hour has exactly 1 error.  Same digit, one a
        step and one a result.  Excluding every figure the arguments
        happened to contain took that correct answer apart and spent a
        repair turn on it — the run ends `answered_with_caveat` with the
        answer replaced.  Judging whether the CALL computed keeps it
        whole, because the call also printed 28, which nobody gave it.
        """
        store = MissionResultStore()
        store.record(PYTHON, {"code": COLLIDING}, text=COLLIDING_OUTPUT,
                     exit_code=0)
        assert unsupported(
            validator, "28 errors in all, and one hour has just 1.",
            store) == ()

    def test_a_figure_echoed_by_one_call_and_computed_by_another(
            self, validator):
        """Evidence is a union and only the echoing call is docked."""
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(42)"}, text="42\n", exit_code=0)
        store.record(PYTHON, {"code": "print(len(rows))"}, text="42\n",
                     exit_code=0)
        assert unsupported(validator, "There were 42.", store) == ()

    def test_a_non_code_tool_echoing_its_argument_is_unaffected(
            self, validator):
        """A `run_id` handed to a lookup comes back in the record it
        fetches, and every submit-and-poll platform this check was written
        for works that way.  Docking it would make the check unusable."""
        store = MissionResultStore()
        store.record("runs_get", {"run_id": 30000},
                     text="run 30000: finished\n", exit_code=0)
        assert unsupported(validator, "Run 30000 finished.", store) == ()

    def test_evidence_with_no_provenance_is_unaffected(self, validator):
        """A library caller hands the validator plain strings, and the
        staged path hands it the union of five sub-missions' stores.
        Nothing known is not the same as nothing echoed."""
        report = validator.validate("Revenue was 30,000.", ["30,000\n"])
        assert report.unsupported == ()


class TestTheClockIsNotAMeasurement:
    """Hazard 2, and the one that needs no model cooperation.

    Measured 18 August 2026 on the research pack: a tool result stamped
    ``2026-08-18T01:52:07+00:00`` put 2026, 8, 18, 1, 52, 7 and 0 into the
    evidence set, because a two-digit run after a colon satisfies
    ``FIGURE``'s boundaries.  An answer inventing "52 hours" was reported
    grounded roughly one run in six — by the clock on an unrelated record.
    The pack worked round it by stamping ISO basic, which is content
    standing in for a harness property: the next tool to stamp a result
    reopens it.
    """

    #: One result carrying the shape that caused it.  `items` is the only
    #: figure anything measured.
    STAMPED = json.dumps({"fetched_at": "2026-08-18T01:52:07+00:00",
                          "items": 3})

    def test_the_seconds_of_a_timestamp_ground_nothing(self, validator):
        store = MissionResultStore()
        store.record("fetch", {"url": "u"}, text=self.STAMPED, exit_code=0)
        assert unsupported(validator, "The outage lasted 52 hours.", store)             == ("52",)

    def test_the_figure_beside_the_timestamp_still_grounds(self, validator):
        store = MissionResultStore()
        store.record("fetch", {"url": "u"}, text=self.STAMPED, exit_code=0)
        assert unsupported(validator, "It found 3 items.", store) == ()

    def test_an_answer_quoting_the_timestamp_claims_nothing(self, validator):
        """Masked on BOTH sides.  Masking only the evidence would turn a
        model that correctly quoted the time it read into an answer with
        six unsupported figures in it — a false positive invented by the
        fix for a false negative."""
        store = MissionResultStore()
        store.record("fetch", {"url": "u"}, text=self.STAMPED, exit_code=0)
        report = validator.validate(
            "Fetched at 2026-08-18T01:52:07+00:00; 3 items.",
            store.evidence_texts())
        assert report.unsupported == ()
        assert report.grounded

    @pytest.mark.parametrize("stamp,donated", [
        ("2026-08-18T01:52:07+00:00", "52"),
        ("2026-08-18T01:52:07Z", "52"),
        ("2026-08-18 01:52:07", "52"),
        ("2026-08-18", "18"),
        ("01:52:07", "52"),
        ("01:52", "52"),
    ])
    def test_every_shape_a_stamp_arrives_in(self, validator, stamp, donated):
        """Each pair is a stamp and the figure it used to donate.  ISO
        basic (`20260818T015207Z`) is absent because it donates nothing to
        begin with — a digit run touching a letter is not a figure — which
        is exactly why the research pack could work round this by writing
        it, and exactly why that workaround is content and not a fix."""
        store = MissionResultStore()
        store.record("fetch", {"url": "u"}, text=f"read at {stamp}",
                     exit_code=0)
        assert unsupported(
            validator, f"It took {donated} minutes.", store) == (donated,)

    def test_an_epoch_is_deliberately_left_alone(self, validator):
        """A ten-digit epoch is ONE token under `FIGURE`, so it can only
        support an answer claiming that exact number — there is nothing to
        launder.  Masking it would hide a genuine claim and buy nothing,
        so the mask is about separators, not about times."""
        store = MissionResultStore()
        store.record("fetch", {"url": "u"}, text="ts=1755481927",
                     exit_code=0)
        assert unsupported(validator, "The stamp was 1755481927.", store) \
            == ()


class TestACallThatFailedStillHappened:
    """Hazard 3, and the finding underneath it: a refusal is a fact.

    ``evidence_texts`` used to drop a failed result whole, so *"I could not
    read that page — it answered 404"* could not ground either the page or
    the status, though the very call that failed demonstrates both.  It
    now contributes its typed error payload and its arguments — and its
    arguments are marked ``sent``, because they are what the MODEL wrote.
    """

    def failed(self):
        store = MissionResultStore()
        store.record("perform_web_search",
                     {"url": "https://example.org/report"},
                     text="HTTPError: the server said no",
                     evidence=json.dumps({"status": 404}), exit_code=1)
        return store

    def test_the_status_in_the_typed_payload_grounds(self, validator):
        assert unsupported(
            validator, "It answered 404.", self.failed()) == ()

    def test_the_url_the_call_was_given_grounds(self):
        """The identifier half of the same claim: the run addressed that
        page, and the store is what knows it did."""
        report = GroundingValidator.from_config(GroundingConfig(
            identifier_pattern=r"https?://[\w.\-/]*[\w/]"
        )).validate(
            "I could not read https://example.org/report.",
            self.failed().evidence_texts())
        assert report.unsupported == ()

    def test_a_figure_typed_into_a_failing_call_grounds_nothing(
            self, validator):
        """The way in that had to stay shut, and deliberately through a
        tool the echo rule does NOT cover: a non-code call's arguments are
        evidence for what the run ADDRESSED and never for what it
        measured, and only the `sent` mark says so."""
        store = MissionResultStore()
        store.record("runs_get", {"run_id": "r-7", "limit": 30000},
                     text="502 Bad Gateway", exit_code=1)
        assert unsupported(validator, "Revenue was 30,000.", store) \
            == ("30,000",)

    def test_the_same_holds_for_a_failing_code_plane_call(self, validator):
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(30000)"}, text="Traceback",
                     exit_code=1)
        assert unsupported(validator, "Revenue was 30,000.", store) \
            == ("30,000",)

    def test_the_free_text_of_a_failure_is_still_not_evidence(self):
        """An error message is prose written by whatever was on the other
        end.  An identifier appearing only inside one has been established
        by nothing, and that is the rule `test_mission_results.py` has
        pinned since the store was written."""
        store = MissionResultStore()
        store.record("t", {}, text="asset.1234 not found", exit_code=1)
        assert store.evidence_texts() == []


class TestTheProvenanceHasOneOwner:
    """The store makes the pairing, because the store is what has it."""

    def test_evidence_texts_carry_the_call_that_made_them(self):
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(1)"}, text="1\n",
                     evidence='{"stdout": "1"}', exit_code=0)
        texts = store.evidence_texts()
        assert len(texts) == 2
        for text in texts:
            assert isinstance(text, SourcedEvidence)
            assert text.tool == PYTHON
            assert "print(1)" in text.arguments
            assert text.sent is False

    def test_an_evidence_text_is_still_a_string(self):
        """Every other consumer — the identifier check, the critic, the
        report — reads evidence as text and must not have to learn a new
        type."""
        store = MissionResultStore()
        store.record(PYTHON, {"code": "print(1)"}, text="1\n", exit_code=0)
        assert store.evidence_texts() == ["1\n"]
        assert "".join(store.evidence_texts()) == "1\n"


# ---------------------------------------------------------------------------
# The loop, end to end: the repair turn is not a way in
# ---------------------------------------------------------------------------

class ScriptedModel:
    """Replays canned replies.  The same shape `tests/test_mission.py` uses."""

    def __init__(self, *replies):
        self.replies = list(replies)

    def __call__(self, messages):
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def answer(text):
    return json.dumps({"answer": text})


@pytest.fixture
def python_bus():
    """A bus serving the code plane, with the program's output scripted.

    The executor is a lambda rather than the real tool because what is
    under test is the loop's verdict, not the interpreter: the mission
    still dispatches, the store still records the arguments the model
    wrote, and the descriptor is the registered one — which is what makes
    it a code plane.
    """
    bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    bus.register(
        ToolDescriptor(tool_name=PYTHON, description="Runs Python code."),
        lambda **kw: (0, "30,000\n", ""),
    )
    return bus


class TestTheRepairTurnIsNotAWayIn:
    def test_running_the_echo_after_being_told_does_not_ground_the_answer(
            self, python_bus):
        """The whole hazard, played out: the model answers with a figure
        no tool produced, is told so, runs a program that prints the
        figure, and answers again.  The run ends `answered_with_caveat`
        with the figure still unsupported."""
        runner = MissionRunner(
            ScriptedModel(
                answer("Revenue was 30,000."),
                tool_call(PYTHON, code="print('30,000')"),
                answer("Revenue was 30,000."),
            ),
            python_bus, [PYTHON],
            validator=GroundingValidator.from_config(
                GroundingConfig(number_pattern=FIGURES, max_repairs=1)),
        )
        transcript = runner.run("what was revenue?")
        assert transcript.grounding.grounded is False
        assert "30,000" in transcript.grounding.unsupported
        assert transcript.outcome == "answered_with_caveat"

    def test_the_same_loop_with_a_computed_figure_is_answered(
            self, python_bus):
        """The green cell beside the red one.  Identical script, identical
        validator; the only difference is that the program was not handed
        the figure it printed."""
        runner = MissionRunner(
            ScriptedModel(
                answer("Revenue was 30,000."),
                tool_call(PYTHON, code="print(total())"),
                answer("Revenue was 30,000."),
            ),
            python_bus, [PYTHON],
            validator=GroundingValidator.from_config(
                GroundingConfig(number_pattern=FIGURES, max_repairs=1)),
        )
        transcript = runner.run("what was revenue?")
        assert transcript.grounding.grounded is True
        assert transcript.outcome == "answered"
