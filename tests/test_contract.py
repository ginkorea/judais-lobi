"""The seam, asserted against the code that has to honour it.

:mod:`core.runtime.contract` is the whole of what a consumer may rely on, and
a consumer is now a separate program on a separate release cycle: TAIPAN pins
a version of this repo and reads its NDJSON off an inherited descriptor.  That
only works if the contract is *checked against the emitters* rather than
written down beside them, because a docstring and an ``_emit`` call drift the
moment nobody is reading both — which is how ``repairing`` came to be a field
TAIPAN indexes and this repo never mentioned, and how the swarm's ``grounding``
record came to carry six of the ten fields the direct path's does.

So every test here is the same test in a different place: *what the contract
says is what actually happens.*  The events a real loop emits pass
:func:`~core.runtime.contract.conforms`; the flags it publishes are flags the
parser takes; the environment it publishes is environment something reads; and
``CONTRACT.md``, which is the version a person reads, says the same words as
the module a program imports.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import signal
from pathlib import Path

import pytest

from core.runtime import contract as c
from core.runtime import mission_stream as ms
from core.runtime.mission import AWAITING_APPROVAL, MissionRunner

REPO = Path(__file__).resolve().parent.parent
CONTRACT_MD = REPO / "CONTRACT.md"


class _Result:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code
        self.evidence = stdout


class _Bus:
    #: The runners read this off the bus to announce `sandbox` on
    #: `mission_started`; the stub answers `"none"` so the field is present
    #: and conformant without this test taking a dependency on the host's
    #: bubblewrap.
    sandbox_name = "none"

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def describe_tool(self, name):
        return {"description": f"does {name}", "input_schema": {
            "type": "object", "properties": {"q": {"type": "string"}}}}

    def dispatch(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self.answers.get(name, _Result(stdout=f"{name} said so"))

    def register_tool(self, name, tool):
        return name

    def unregister(self, name):
        return None


def _replies(*texts):
    queue = list(texts)

    def chat(messages):
        return queue.pop(0) if queue else json.dumps({"answer": "done"})
    return chat


class _FakeClock:
    """A monotonic that moves only when a fake model answers."""

    def __init__(self, start=1_000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


def _slow(clock, seconds, *texts):
    """A model whose every reply costs *seconds* of fake clock.

    Nothing sleeps.  What the wall-clock budget is asserted against is the
    comparison, not the sleeping, and a test that spent its own budget to
    prove one is spent would be slow and flaky both.
    """
    chat = _replies(*texts)

    def slow_chat(messages):
        clock.advance(seconds)
        return chat(messages)
    return slow_chat


def _run(replies, *, gated=(), tools=("catalog_search_assets",), max_steps=4,
         validator=None, store=None, run_id="", usage_fn=None):
    seen = []
    runner = MissionRunner(
        _replies(*replies), _Bus(), list(tools), max_steps=max_steps,
        gated=gated, validator=validator, observer=seen.append, store_tool="",
        run_store=store, run_id=run_id,
        usage_fn=usage_fn,
    )
    return runner.run("what do we hold"), seen


def _faults(records):
    """Every problem across a whole stream, said with the record that had it.

    Two checks, and the second is deliberately stricter than the first.
    :func:`~core.runtime.contract.conforms` is what a *consumer* runs, and
    it tolerates a key it has never heard of on purpose: an added optional
    field is a minor change by the rule at the top of that module, and a
    checker that failed on one would make every additive release breaking.

    This repo's own emitters are held tighter than its consumers, in both
    directions.  ``FIELDS`` is the floor — ``conforms`` covers that half —
    and ``FIELDS | OPTIONAL`` is the ceiling, which is the half nothing
    checked.  A field an event does not declare is a field a consumer will
    meet and have no sentence for, and it is also what a *removal* from
    ``FIELDS`` looks like from here: drop ``reason`` from
    ``GATE_REQUESTED`` and the record that still carries it fails on this
    line, rather than only where ``CONTRACT.md`` is compared with the
    module.
    """
    problems = []
    for record in records:
        event = record.get("event")
        problems += [f"{event}: {problem}" for problem in c.conforms(record)]
        if event not in c.FIELDS:
            continue
        declared = set(c.FIELDS[event]) | set(c.OPTIONAL.get(event, ()))
        for name in sorted(set(record) - {"event"} - declared):
            problems.append(f"{event}: undeclared field {name!r}")
    return problems


def _staged(validator=None,
            syntheses=("the synthesized answer, which names abc123",),
            store=None, run_id=""):
    """A two-step staged mission over a real bus, and what it emitted.

    Factored out because the staged path is a second emitter and drifted
    once already, so it is exercised three times from here: once as it runs
    for a caller with no grounding grammar, once with one — the branch that
    emits a ``grounding`` record at all, and therefore the only branch in
    which its shape is a fact rather than a hope — and once with a synthesis
    the validator refuses, which is the repair turn.

    ``syntheses`` is what the synthesizer says, in order: one reply for an
    answer nobody argues with, and a second for the repair turn a validator
    that refused the first will ask for.
    """
    from core.contracts.schemas import PolicyPack
    from core.runtime.swarm import SwarmRunner
    from core.tools.bus import ToolBus
    from core.tools.capability import CapabilityEngine
    from core.tools.descriptors import ToolDescriptor

    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    bus.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="search tool. Second sentence."),
        lambda **kw: (0, "corpus abc123", ""))

    seen = []
    plain = _replies(
        json.dumps({"route": "staged"}),
        json.dumps({"steps": [
            {"id": "s1", "goal": "search", "rung": "tool"},
            {"id": "s2", "goal": "search again", "rung": "tool",
             "needs": ["s1"]}]}),
        *syntheses)
    executor = _replies(
        json.dumps({"tool": "catalog.search", "arguments": {"q": "x"}}),
        json.dumps({"answer": "abc123"}),
        json.dumps({"tool": "catalog.search", "arguments": {"q": "y"}}),
        json.dumps({"answer": "abc123 again"}))
    SwarmRunner(executor, bus, ["catalog.search"],
                system_message="You are Tai.", plain_chat_fn=plain,
                validator=validator, observer=seen.append,
                run_store=store, run_id=run_id).run("search twice")
    return seen


# ── the events a real loop emits are the events the contract declares ────────


class TestAMissionConformsToItsOwnContract:
    def test_an_ordinary_mission_end_to_end(self):
        """Tool call, result, answer, finish — the shape a consumer sees on
        nearly every turn, checked field by field rather than by name."""
        _, seen = _run([
            json.dumps({"tool": "catalog_search_assets", "arguments": {"q": "x"}}),
            json.dumps({"answer": "three assets"}),
        ])
        assert seen
        assert _faults(seen) == []

    def test_a_mission_that_was_rejected_reprompted_and_gated(self):
        """The awkward paths, because they are the ones a pane renders least
        often and therefore the ones that rot."""
        _, seen = _run(
            ["not json at all",
             json.dumps({"tool": "catalog_delete_everything", "arguments": {}}),
             json.dumps({"tool": "compute_cancel_job",
                         "arguments": {"job_id": "job_7f3"}})],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        assert _faults(seen) == []
        assert ms.GATE_REQUESTED in [r["event"] for r in seen]

    def test_a_mission_that_ran_out_of_steps(self):
        transcript, seen = _run(
            [json.dumps({"tool": "catalog_search_assets", "arguments": {}})] * 3,
            max_steps=2)
        assert transcript.outcome == "budget_exhausted"
        assert _faults(seen) == []

    def test_a_mission_that_ran_out_of_seconds(self):
        """The second budget. It reaches a consumer as the same outcome word
        with a different ``budget.which``, which is the whole reason the
        field exists — narrowing the question fixes one of these and not the
        other."""
        from core.budgets import Deadline

        clock = _FakeClock()
        seen = []
        runner = MissionRunner(
            _slow(clock, 6.0, *[json.dumps(
                {"tool": "catalog_search_assets", "arguments": {}})] * 4),
            _Bus(), ["catalog_search_assets"], max_steps=4,
            observer=seen.append, store_tool="",
            deadline=Deadline(5.0, monotonic=clock))
        transcript = runner.run("go")

        assert transcript.outcome == "budget_exhausted"
        assert _faults(seen) == []
        assert seen[-1]["budget"] == {"which": "seconds", "limit": 5.0,
                                      "spent": 6.0}

    def test_a_mission_somebody_cancelled(self):
        """``incomplete`` with a ``reason``, and no new outcome word for a
        consumer's closed set to have to grow."""
        from core.budgets import Cancellation

        switch = Cancellation()
        switch.cancel()
        seen = []
        transcript = MissionRunner(
            _replies(json.dumps({"answer": "never reached"})), _Bus(),
            ["catalog_search_assets"], observer=seen.append, store_tool="",
            cancel=switch).run("go")

        assert transcript.outcome == "incomplete"
        assert _faults(seen) == []
        assert seen[-1]["reason"] == "cancelled"
        assert seen[-1]["outcome"] in c.OUTCOMES

    def test_a_mission_that_repaired_and_then_caveated(self):
        """Both grounding records — the interim one carrying ``repairing`` and
        the verdict that follows it — are full records, not the subset the
        repair path happened to need."""
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        validator = GroundingValidator.from_config(GroundingConfig.from_mapping(
            {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 1}))
        transcript, seen = _run(
            [json.dumps({"answer": "the score is 80.847"}),
             json.dumps({"answer": "the score is 80.848"})],
            validator=validator)
        assert transcript.outcome == "answered_with_caveat"
        grounding = [r for r in seen if r["event"] == ms.GROUNDING]
        assert [r["repairing"] for r in grounding] == [True, False]
        assert _faults(seen) == []

    def test_a_mission_that_crashed_still_ends_conformantly(self):
        """``mission_finished`` comes out of a ``finally``. A record emitted on
        the way out of an exception is still a record somebody has to parse."""
        seen = []

        def explode(messages):
            raise RuntimeError("the model server went away")

        runner = MissionRunner(explode, _Bus(), ["catalog_search_assets"],
                               observer=seen.append, store_tool="")
        with pytest.raises(RuntimeError):
            runner.run("go")
        assert _faults(seen) == []
        assert seen[-1]["outcome"] == "incomplete"

    def test_a_staged_swarm_speaks_the_same_vocabulary(self):
        """The staged path is a second emitter and drifted once already. Same
        contract or it is not one contract."""
        seen = _staged()
        assert [r["event"] for r in seen][0] == ms.MISSION_STARTED
        assert _faults(seen) == []

    def test_both_emitters_open_with_an_audit_ref(self):
        """``audit_ref`` is optional and therefore the kind of field that ends
        up on one emitter and not the other — nothing in ``conforms`` would
        object, and a consumer would meet a reference on direct turns and
        nothing on staged ones. Both, or it is not one contract.

        Its *value* is ``None`` here because neither of these buses is
        audited; where it comes from is tested against a real logger in
        ``tests/test_mission.py`` and ``tests/test_swarm.py``.
        """
        _, direct = _run([json.dumps({"answer": "done"})])
        staged = _staged()
        for stream in (direct, staged):
            opening = next(r for r in stream if r["event"] == ms.MISSION_STARTED)
            assert "audit_ref" in opening

    def test_both_emitters_name_the_run_they_are_recorded_in(self, tmp_path):
        """``run_id`` is optional, which makes it exactly the kind of field
        that lands on one emitter and not the other — and a consumer that
        found a transcript for direct turns and none for staged ones would
        have no way to tell a swarm that kept no record from a swarm whose
        record it was never told the name of.

        Both, and absent on both when nothing is being recorded, which is the
        half that makes the presence of the field mean something.
        """
        from core.durable import RunStore

        store = RunStore(tmp_path / "runs")
        direct_id = store.create().run_id
        staged_id = store.create().run_id
        streams = {
            direct_id: _run([json.dumps({"answer": "done"})],
                            store=store, run_id=direct_id)[1],
            staged_id: _staged(store=store, run_id=staged_id),
        }
        for run_id, stream in streams.items():
            opening = next(r for r in stream
                           if r["event"] == ms.MISSION_STARTED)
            assert opening["run_id"] == run_id
            assert _faults(stream) == []
            # The sink is a client of the log: same records, same order.
            assert store.records(run_id) == stream

    def test_neither_emitter_invents_a_run_that_is_not_being_recorded(self):
        _, direct = _run([json.dumps({"answer": "done"})])
        for stream in (direct, _staged()):
            opening = next(r for r in stream
                           if r["event"] == ms.MISSION_STARTED)
            assert "run_id" not in opening

    def test_a_swarm_opens_its_stream_before_the_router_is_asked(self):
        """The silence clause is a promise about the FIRST call to the model,
        and under ``--swarm`` that is the router's own — not the first step's.

        A router that fails in an ordinary way falls open to the direct path,
        which announces the mission itself, so the failure that reaches this
        line is one nothing catches. Before the announcement was moved ahead
        of triage it produced a stream with NOTHING in it, and a consumer
        reading that stream is instructed by this very contract to report a
        harness that never started — about a harness that had run, asked, and
        died waiting for an answer.
        """
        from core.runtime.swarm import SwarmRunner

        def killed(messages):
            raise KeyboardInterrupt("the endpoint went away mid-call")

        seen = []
        runner = SwarmRunner(_replies(), _Bus(), ["catalog_search_assets"],
                             plain_chat_fn=killed, observer=seen.append)
        with pytest.raises(KeyboardInterrupt):
            runner.run("what do we hold")
        assert [r["event"] for r in seen] == [ms.MISSION_STARTED,
                                              ms.MISSION_FINISHED]
        assert seen[-1]["outcome"] == "incomplete"
        assert _faults(seen) == []

    def test_a_staged_swarm_that_repaired_said_so_while_it_was_repairing(self):
        """``repairing`` was written down as a fact about this harness and was
        true of one of its two loops.

        The staged path spent its repair turns without a word and emitted only
        the verdict, which from outside is a stall followed by an answer. Both
        records here, both whole, and both out of the renderer the direct path
        uses rather than a second hand-listing beside the emit — the mistake
        that made this record six fields long the last time.
        """
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        validator = GroundingValidator.from_config(GroundingConfig.from_mapping(
            {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 1}))
        seen = _staged(validator, syntheses=("the score is 80.847",
                                             "the score is 80.848"))
        assert _faults(seen) == []
        grounding = [r for r in seen if r["event"] == ms.GROUNDING]
        assert [r["repairing"] for r in grounding] == [True, False]
        for record in grounding:
            assert set(record) - {"event"} == (
                set(c.FIELDS[ms.GROUNDING])
                | set(c.OPTIONAL.get(ms.GROUNDING, ())))

    def test_a_staged_swarms_plan_travels_as_a_declared_field(self):
        """It rode ``mission_started`` until that record moved ahead of
        triage. A plan cannot travel on a record written before anything asked
        for one, so it rides the first ``step_started`` the plan produces —
        and ``_faults`` above is what holds it to being *declared* there
        rather than merely present."""
        seen = _staged()
        carrying = [r for r in seen
                    if r["event"] == ms.STEP_STARTED and "plan" in r]
        assert len(carrying) == 1
        assert [s["id"] for s in carrying[0]["plan"]] == ["s1", "s2"]
        assert "plan" not in seen[0]

    def test_a_resumed_stretch_says_so_on_a_declared_field(self, tmp_path):
        """``resumed`` rides the first ``step_started`` after a resume and no
        other record — and ``_faults`` above is what holds it to being
        *declared* there rather than merely present.

        The other half is the absence: there is no second
        ``mission_started``. A resumed run is the same mission, and a
        consumer reading the whole log of one resumed twice would otherwise
        find three openings for one mission and render three.
        """
        from core.durable import RunStore
        from core.runtime.resume import open_for_resume, rebuild

        store = RunStore(tmp_path / "runs")
        run_id = store.create(meta={"objective": "what do we hold"}).run_id
        # One step, then the model server goes away. The crash still closes
        # the log from its `finally`, which is why `incomplete` is a word a
        # resume is allowed to pick up from.
        first = [json.dumps({"tool": "catalog_search_assets", "arguments": {}})]

        def dies(messages):
            if first:
                return first.pop(0)
            raise RuntimeError("the model server went away")

        killed = MissionRunner(dies, _Bus(), ["catalog_search_assets"],
                               max_steps=4, store_tool="",
                               run_store=store, run_id=run_id)
        with pytest.raises(RuntimeError):
            killed.run("what do we hold")

        seen = []
        recorded = open_for_resume(store, run_id)
        runner = MissionRunner(
            _replies(json.dumps({"answer": "three assets"})), _Bus(),
            ["catalog_search_assets"], max_steps=recorded.total_steps(None),
            observer=seen.append, store_tool="",
            run_store=store, run_id=run_id)
        runner.run(recorded.objective, rebuild(runner, recorded))

        assert _faults(seen) == []
        assert [r["event"] for r in seen].count(ms.MISSION_STARTED) == 0
        carrying = [r for r in seen
                    if r["event"] == ms.STEP_STARTED and "resumed" in r]
        assert len(carrying) == 1
        assert set(carrying[0]["resumed"]) == {"from_seq", "steps_replayed"}
        assert [r["event"] for r in store.records(run_id)].count(
            ms.MISSION_STARTED) == 1

    def test_a_staged_swarms_grounding_record_is_the_whole_record(self):
        """The drift itself, pinned where it happened.

        A staged mission emits ``grounding`` only when a validator was
        configured, so until one was configured here the shape of that
        record was never exercised on this path — which is exactly how it
        came to carry six of the ten fields the direct path's does, hand
        listed at the emit. Ten fields through the same renderer, checked
        as a key SET rather than by picking out the ones somebody
        remembered: a consumer switching on ``event`` gets one shape per
        event, or it does not have a vocabulary.
        """
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        seen = _staged(GroundingValidator.from_config(
            GroundingConfig.from_mapping(
                {"identifier_pattern": r"\babc[0-9a-z]{3,}\b"})))
        assert _faults(seen) == []
        grounding = [r for r in seen if r["event"] == ms.GROUNDING]
        assert len(grounding) == 1, "a validator ran and said nothing"
        assert set(grounding[0]) - {"event"} == (
            set(c.FIELDS[ms.GROUNDING])
            | set(c.OPTIONAL.get(ms.GROUNDING, ())))


class _NativeReplies:
    """A constrained decoder's two channels, for the contract's purposes.

    ``chat`` returns the content (usually nothing) and the calls arrive on
    the side channel, which is what :class:`MissionRunner` reads under the
    native protocol.  Scripted as a list of call-lists, one per turn.
    """

    def __init__(self, *turns):
        self.turns = list(turns)
        self.last = []

    def __call__(self, messages):
        self.last = list(self.turns.pop(0)) if self.turns else [
            {"id": "z", "name": "mission_answer",
             "arguments": {"text": "done"}}]
        return ""

    def calls(self):
        return list(self.last)


def _run_native(turns, *, gated=(), tools=("catalog_search_assets",),
                max_steps=4):
    """A native-protocol mission over the same stub bus, and what it emitted."""
    from core.runtime.mission import NATIVE_PROTOCOL

    seen = []
    model = _NativeReplies(*turns)
    runner = MissionRunner(
        model, _Bus(), list(tools), max_steps=max_steps, gated=gated,
        observer=seen.append, store_tool="",
        protocol=NATIVE_PROTOCOL, tool_calls_fn=model.calls)
    return runner.run("what do we hold"), seen


class TestANativeMissionSpeaksTheSameVocabulary:
    """The second protocol is not a second contract.

    A consumer pinned to ``SCHEMA_VERSION == 1`` reads a native run with
    the vocabulary it already has: the same nine events, the same required
    fields, and two optional ones it may ignore.  That is the whole reason
    the protocol could be added without bumping the version, so it is
    asserted rather than asserted about.
    """

    def test_a_turn_that_dispatched_twice_conforms_field_by_field(self):
        _t, seen = _run_native([
            [{"id": "c0", "name": "catalog_search_assets",
              "arguments": {"q": "x"}},
             {"id": "c1", "name": "catalog_search_assets",
              "arguments": {"q": "y"}}],
            [{"id": "a", "name": "mission_answer",
              "arguments": {"text": "two"}}],
        ])
        assert _faults(seen) == []
        assert [r.get("call") for r in seen if r["event"] == ms.TOOL_CALL] == \
            [None, 1]

    def test_a_native_gate_conforms(self):
        _t, seen = _run_native(
            [[{"id": "c0", "name": "compute_cancel_job",
               "arguments": {"job_id": "job_7f3"}}]],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        assert _faults(seen) == []
        assert ms.GATE_REQUESTED in [r["event"] for r in seen]

    def test_a_native_rejection_conforms(self):
        _t, seen = _run_native([
            [{"id": "c0", "name": "catalog_invented", "arguments": {}}],
            [{"id": "a", "name": "mission_answer",
              "arguments": {"text": "done"}}],
        ])
        assert _faults(seen) == []
        assert ms.REPLY_REJECTED in [r["event"] for r in seen]

    def test_the_opening_frame_names_the_protocol(self):
        _t, seen = _run_native([])
        assert seen[0]["protocol"] == "native"
        assert c.conforms(seen[0]) == []

    def test_the_vocabulary_did_not_grow(self):
        """A tenth event is the one additive change a consumer cannot
        absorb quietly — the reference consumer asserts the whole set."""
        _t, seen = _run_native([
            [{"id": "c0", "name": "catalog_search_assets",
              "arguments": {"q": "x"}}],
            [{"id": "a", "name": "mission_answer",
              "arguments": {"text": "one"}}],
        ])
        assert {r["event"] for r in seen} <= set(c.EVENTS)

    def test_the_json_protocol_carries_neither_new_field(self):
        _t, seen = _run([
            json.dumps({"tool": "catalog_search_assets",
                        "arguments": {"q": "x"}}),
            json.dumps({"answer": "three assets"}),
        ])
        assert all("call" not in r and "protocol" not in r for r in seen)


class TestTheTwoAdditiveFields:
    def test_the_first_record_carries_the_schema_version(self):
        """On the FIRST record, so a consumer that is going to refuse the
        stream refuses it before it has rendered anything from it."""
        _, seen = _run([json.dumps({"answer": "done"})])
        assert seen[0]["event"] == ms.MISSION_STARTED
        assert seen[0]["schema_version"] == c.SCHEMA_VERSION

    def test_the_last_record_carries_the_budget_beside_the_spend(self):
        """Six steps of a stated twenty-four is not an agent that ran out of
        room, and a consumer holding only the six cannot say so."""
        _, seen = _run([json.dumps({"answer": "done"})], max_steps=24)
        finished = seen[-1]
        assert finished["event"] == ms.MISSION_FINISHED
        assert (finished["steps"], finished["max_steps"]) == (1, 24)


# ── the contract is internally whole ─────────────────────────────────────────


class TestTheLedgerIsAFieldAndNotATenthEvent:
    """The decision, written where the decision is enforced.

    A run's token spend wants a record type of its own — it is a fact
    about the run rather than about any one step — and it does not get
    one. A new event is the single additive change a consumer cannot
    absorb quietly: the reference consumer asserts its read-set EQUALS
    `EVENTS`, so a tenth name is a lockstep release on both sides for a
    number that fits in frames that already exist. An optional field is
    read with a default by a consumer that meters and ignored by one that
    does not, which is the route `compacted` and `plan` took.
    """

    def _usage(self, prompt, completion):
        from core.runtime.backends.base import Usage

        return lambda: Usage(prompt_tokens=prompt, completion_tokens=completion,
                             total_tokens=prompt + completion)

    def test_the_ledger_is_still_not_one_of_them(self):
        """The count is stated so that a tenth name is a decision somebody
        made rather than a line somebody added.

        It went from nine to ten once, for `answer_delta`, and that is the
        shape of the argument this class exists to record: a new event is
        the additive change a consumer cannot absorb quietly, so it is
        paid for when there is something to say that no existing frame can
        carry — a fragment of an answer that has not been written yet —
        and not when there is a number that fits in frames that already
        exist.
        """
        assert len(c.EVENTS) == 10
        assert not any("usage" in event or "ledger" in event
                       for event in c.EVENTS)

    def test_it_is_declared_optional_on_the_four_records_that_carry_it(self):
        for event in (ms.TOOL_CALL, ms.ANSWER, ms.REPLY_REJECTED,
                      ms.MISSION_FINISHED):
            assert "usage" in c.OPTIONAL[event], event

    def test_it_is_optional_and_never_required(self):
        for event in c.EVENTS:
            assert "usage" not in c.FIELDS[event], event

    def test_a_metered_stream_declares_every_field_it_carries(self):
        """`_faults` is the ceiling check: a field an event does not
        declare is a field a consumer meets with no sentence for it."""
        _, seen = _run([json.dumps({"tool": "catalog_search_assets",
                                    "arguments": {"q": "x"}}),
                        "not json at all",
                        json.dumps({"answer": "done"})],
                       usage_fn=self._usage(50, 5))
        assert _faults(seen) == []
        carrying = {r["event"] for r in seen if "usage" in r}
        assert carrying == {ms.TOOL_CALL, ms.REPLY_REJECTED, ms.ANSWER,
                            ms.MISSION_FINISHED}

    def test_an_unmetered_stream_carries_none_of_it(self):
        """Absent, not zero — and absent for every record when no provider
        reported. A consumer from before this field must read the stream
        unchanged."""
        _, seen = _run([json.dumps({"answer": "done"})])
        assert _faults(seen) == []
        assert all("usage" not in record for record in seen)

    def test_the_last_record_carries_totals_and_the_others_carry_one_call(self):
        _, seen = _run([json.dumps({"tool": "catalog_search_assets",
                                    "arguments": {"q": "x"}}),
                        json.dumps({"answer": "done"})],
                       usage_fn=self._usage(50, 5))
        per_call = [r for r in seen if r["event"] == ms.TOOL_CALL][0]["usage"]
        totals = [r for r in seen
                  if r["event"] == ms.MISSION_FINISHED][0]["usage"]
        assert "calls" not in per_call
        assert totals["calls"] == 2
        assert totals["total_tokens"] == 110


class TestTheTenthEventIsSafeToNotKnowAbout:
    """`answer_delta` is the one additive change a consumer *does* have to
    notice, so what it costs one is written down as assertions.

    The reference consumer asserts its read-set EQUALS `EVENTS`, which is
    why a tenth name was paid for rather than assumed: it buys the one
    thing no existing frame could carry, an answer that has not been
    finished yet. What it must not cost is the rest of the stream.
    """

    def _streamed(self, reply, piece=6):
        def chat(_messages):
            for at in range(0, len(reply), piece):
                yield {"choices": [
                    {"delta": {"content": reply[at:at + piece]}}]}
        return chat

    def _run_streamed(self, reply):
        seen = []
        MissionRunner(self._streamed(reply), _Bus(),
                      ["catalog_search_assets"], observer=seen.append,
                      store_tool="").run("what do we hold")
        return seen

    def test_a_streamed_mission_conforms_field_by_field(self):
        seen = self._run_streamed(json.dumps({"answer": "three assets"}))
        assert [r for r in seen if r["event"] == ms.ANSWER_DELTA]
        assert _faults(seen) == []

    def test_dropping_the_new_records_leaves_the_stream_a_consumer_read(self):
        """What a consumer that has never heard of it does, done here: the
        records it knows are the records it always got."""
        seen = self._run_streamed(json.dumps({"answer": "three assets"}))
        known = [r for r in seen if r["event"] != ms.ANSWER_DELTA]
        assert [r["event"] for r in known] == [
            ms.MISSION_STARTED, ms.STEP_STARTED, ms.ANSWER,
            ms.MISSION_FINISHED]

    def test_the_answer_is_emitted_even_though_the_deltas_said_it_all(self):
        """Never suppressed. A consumer replaces provisional text when the
        `answer` arrives, and one that never arrived would leave a pane
        holding a decode of a half-written reply forever."""
        seen = self._run_streamed(json.dumps({"answer": "the whole thing"}))
        fragments = "".join(r["text"] for r in seen
                            if r["event"] == ms.ANSWER_DELTA)
        answered = [r for r in seen if r["event"] == ms.ANSWER]
        assert fragments == "the whole thing"
        assert [r["text"] for r in answered] == ["the whole thing"]

    def test_zero_of_them_is_the_ordinary_case(self):
        """A backend that does not stream, `--no-stream`, a library caller
        with a string-returning `chat_fn` — all of them, and all of them
        normal."""
        _, seen = _run([json.dumps({"answer": "done"})])
        assert not [r for r in seen if r["event"] == ms.ANSWER_DELTA]
        assert _faults(seen) == []

    def test_it_carries_no_optional_field_at_all(self):
        """Deliberately: `usage` is the cost of a CALL and would be
        restated on every fragment of it."""
        assert ms.ANSWER_DELTA not in c.OPTIONAL

    def test_the_event_sits_beside_the_answer_it_precedes(self):
        assert c.EVENTS.index(c.ANSWER_DELTA) == c.EVENTS.index(c.ANSWER) - 1


class TestTheContractIsWhole:
    def test_every_event_declares_its_fields(self):
        assert set(c.FIELDS) == set(c.EVENTS)

    def test_the_stream_module_re_exports_rather_than_redeclares(self):
        """One owner. A second copy of a vocabulary is its own defect, and an
        importer that has always said ``mission_stream.EVENTS`` keeps working."""
        assert ms.EVENTS is c.EVENTS
        for name in c.EVENTS:
            assert getattr(ms, name.upper()) == name

    def test_no_field_is_both_required_and_optional(self):
        for event, optional in c.OPTIONAL.items():
            assert not set(optional) & set(c.FIELDS[event]), event

    def test_optional_fields_are_declared_for_real_events(self):
        assert set(c.OPTIONAL) <= set(c.EVENTS)

    def test_the_outcome_words_are_the_ones_the_code_can_say(self):
        """Read off the source rather than off memory: an outcome assigned in
        the loop and missing here is a word a consumer will meet and have no
        sentence for."""
        source = (REPO / "core" / "runtime" / "mission.py").read_text()
        source += (REPO / "core" / "runtime" / "swarm.py").read_text()
        assigned = set(re.findall(r'\.outcome = "([a-z_]+)"', source))
        assigned |= set(re.findall(r'outcome: str = "([a-z_]+)"', source))
        # `_stop` returns its verdict as a tuple that is unpacked onto the
        # transcript, so the outcome word never appears beside `.outcome =`.
        # Without this pattern a new word introduced there — `cancelled`,
        # say, which was very nearly one — would reach a consumer with
        # nothing here noticing.
        assigned |= set(re.findall(r'return "([a-z_]+)", ', source))
        assigned.add(AWAITING_APPROVAL)
        assert assigned <= set(c.OUTCOMES), assigned - set(c.OUTCOMES)

    def test_the_budget_words_are_the_ones_the_shared_module_declares(self):
        """``mission_finished.budget.which`` is a closed set, and it is
        `core.budgets`'s to close. A word the mission could emit and that
        module does not list is a word this contract documents nowhere.

        The document is held to the *list* and not merely to mentioning
        each word somewhere, because every one of these words appears in
        the Events section for other reasons — ``steps`` is a required
        field, ``tokens`` is in the compaction record — so a presence
        check would pass over a `which` vocabulary the page had quietly
        stopped stating. Anchored on "``which`` is one of", which is the
        contract's own phrase and not somebody's prose.
        """
        from core.budgets import WHICH

        assert WHICH == ("steps", "seconds", "bytes", "tokens")
        section = _md_section("Events")
        listed = re.search(r"`which` is one of ([^;]+);", section, re.S)
        assert listed, "CONTRACT.md no longer states the `which` vocabulary"
        assert re.findall(r"`([a-z]+)`", listed.group(1)) == list(WHICH)

    def test_cancellation_did_not_become_a_sixth_outcome(self):
        """A consumer's closed set of outcome words is the thing this tuple
        exists to let it assert, and widening it is a cost every consumer
        pays. TAIPAN's bridge keys a sentence per word and falls through to a
        fallback that states the raw one; adding `cancelled` would have been
        *safe* there and still wrong, because a cancelled run genuinely IS a
        run that stopped without an answer."""
        from core.runtime.mission import CANCELLED

        assert CANCELLED not in c.OUTCOMES
        assert "reason" in c.OPTIONAL[ms.MISSION_FINISHED]
        assert "incomplete" in c.OUTCOMES

    def test_the_exit_contract_names_the_clauses_a_consumer_builds_on(self):
        assert set(c.EXIT_CONTRACT) == {
            "stdout", "events", "control", "silence", "finished", "sigterm",
            "diagnostic"}
        with pytest.raises(TypeError):
            c.EXIT_CONTRACT["stdout"] = "something else"


# ── what `conforms` is for: naming what is wrong ─────────────────────────────


class TestConformsNamesTheProblem:
    def _record(self):
        return {"event": ms.MISSION_FINISHED, "outcome": "answered",
                "steps": 3, "max_steps": 24}

    def test_a_good_record_has_nothing_to_say_about_it(self):
        assert c.conforms(self._record()) == []

    @pytest.mark.parametrize("field", ("outcome", "steps", "max_steps"))
    def test_a_missing_required_field_is_named(self, field):
        """The mutation check. A checker that passes a broken record is worse
        than no checker, because somebody stops looking."""
        record = self._record()
        del record[field]
        problems = c.conforms(record)
        assert problems, f"{field} was removed and nothing complained"
        assert any(repr(field) in problem for problem in problems)

    def test_an_unknown_event_is_named_and_its_fields_are_not_guessed_at(self):
        problems = c.conforms({"event": "mission_paused"})
        assert problems == ["unknown event 'mission_paused'"]

    def test_a_record_with_no_event_at_all(self):
        assert c.conforms({"steps": 1}) == ["no 'event' field"]

    def test_a_stream_from_a_future_version_says_so(self):
        problems = c.conforms({"event": ms.MISSION_STARTED,
                               "schema_version": c.SCHEMA_VERSION + 1,
                               "objective": "x", "catalogue": [], "gated": [],
                               "max_steps": 4, "history": 0})
        assert any("schema_version" in problem for problem in problems)

    def test_an_extra_field_is_not_a_problem(self):
        """Adding an optional field is a minor change by the rule at the top of
        the module. A checker that failed on one would make every additive
        release a breaking one."""
        record = self._record()
        record["something_new"] = "later"
        assert c.conforms(record) == []

    def test_something_that_is_not_a_record_at_all(self):
        assert c.conforms(["mission_finished"]) == ["not a record: list"]


# ── the surface a consumer spawns us by ──────────────────────────────────────


def _mission_parser() -> argparse.ArgumentParser:
    """The parser ``core.cli._main`` actually builds, caught on its way to use.

    Intercepted rather than rebuilt: a copy of the flag declarations in a test
    would pass forever after somebody renamed one.
    """
    from core import cli

    class _Caught(Exception):
        pass

    caught = {}
    real = argparse.ArgumentParser.parse_args

    def _capture(self, *args, **kwargs):
        caught["parser"] = self
        raise _Caught

    argparse.ArgumentParser.parse_args = _capture
    try:
        stub = type("Tai", (), {})
        with pytest.raises(_Caught):
            cli._main(stub)
    finally:
        argparse.ArgumentParser.parse_args = real
    return caught["parser"]


#: One usable value per flag that takes one, so the flag is *parsed* rather
#: than merely spelled the same as something in the source.
_FLAG_VALUES = {
    "--mcp-url": "http://127.0.0.1:8000/mcp",
    "--mission-steps": "6",
    "--mission-seconds": "90",
    "--model": "gpt-oss-20b",
    "--profile": "dev",
    "--skill": "skill.yaml",
    "--events": "-",
    "--history": "thread.json",
    "--gate-tool": "compute_cancel_job",
    "--approval": "ap_0f3c9d2b1a4e5f60",
    "--temperature": "0.2",
    "--top-p": "0.9",
    "--seed": "7",
    "--resume": "run_20260815T131102-9f3a1c04",
    "--replay": "run_20260815T131102-9f3a1c04",
    "--protocol": "native",
    "--control": "fd:9",
    "--gate-wait": "45",
}


class TestTheSpawningSurface:
    def test_every_published_flag_is_one_the_parser_takes(self):
        from core.cli import PROVIDERS

        parser = _mission_parser()
        values = dict(_FLAG_VALUES, **{"--provider": list(PROVIDERS)[0]})
        for flag in c.CLI_FLAGS:
            argv = ["go", flag]
            if flag in values:
                argv.append(values[flag])
            args = parser.parse_args(argv)
            assert getattr(args, flag.lstrip("-").replace("-", "_")) is not None

    def test_every_published_env_var_is_one_something_reads(self):
        """Not a substring grep. That version passed on a name that appeared
        only in a comment, or only in the tuple two screens up that publishes
        it — a claim satisfying itself.

        So: the name has to be a string literal *whose whole value is the
        name*, parsed out of the syntax tree, in a module that reads the
        environment at all. A comment never becomes a node; a docstring or
        a ``help=`` sentence that mentions the name becomes one node
        holding the whole sentence, not the name. And ``contract.py``
        itself is excluded by construction — it publishes the list and
        imports nothing outside the standard library, so it can no longer
        satisfy its own claim.

        It deliberately does not insist on ``os.getenv("NAME")``
        adjacency. This repo reads an env var through ``_env_path(name)``
        and through ``os.environ.get(CLIENT_NAME_ENV)`` as often as
        directly, and a rule that recognised only one spelling would push
        the next author towards the spelling the test likes rather than
        the one the code wants.
        """
        readers = {}
        for path in sorted((REPO / "core").rglob("*.py")):
            source = path.read_text()
            if "os.getenv" not in source and "os.environ" not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    readers.setdefault(node.value, set()).add(path.name)

        for name in c.ENV_VARS:
            assert name in readers, (
                f"{name} is published and nothing under core/ reads it")


# ── the human rendering says the same thing as the machine one ───────────────


def _md_section(heading: str) -> str:
    """The body under one ``##`` heading, up to the next one."""
    text = CONTRACT_MD.read_text()
    body = text.split(f"\n## {heading}\n", 1)
    assert len(body) == 2, f"CONTRACT.md has no '## {heading}' section"
    return body[1].split("\n## ", 1)[0]


def _md_names(heading: str) -> set:
    """The first backticked token of every table row or bullet in a section."""
    return set(re.findall(r"^(?:\| |- )`([^`]+)`",
                          _md_section(heading), re.MULTILINE))


class TestTheDocumentAndTheModuleAgree:
    """``CONTRACT.md`` is written by hand, which is the only reason it reads
    well and the whole reason it drifts.  Equality both ways: a name the module
    grew and the document did not is as much a defect as the reverse.
    """

    def test_the_events(self):
        assert _md_names("Events") == set(c.EVENTS)

    def test_the_outcomes(self):
        assert _md_names("Outcomes") == set(c.OUTCOMES)

    def test_the_flags(self):
        assert _md_names("Command line") == set(c.CLI_FLAGS)

    def test_the_environment(self):
        assert _md_names("Environment") == set(c.ENV_VARS)

    def test_the_required_fields_of_every_event(self):
        """The table's second column, against ``FIELDS``. The fields are the
        half of the contract somebody actually indexes."""
        rows = re.findall(r"^\| `([^`]+)` \| ([^|]*)\|",
                          _md_section("Events"), re.MULTILINE)
        assert rows
        for event, cell in rows:
            assert set(re.findall(r"`([^`]+)`", cell)) == set(c.FIELDS[event]), \
                event

    def test_the_optional_fields_of_every_event(self):
        """The other half of the fields, and the half that is prose.

        An optional field is the only kind this repo may add without
        bumping the schema, which makes it the kind most likely to be
        added to the module and not to the page a consumer is sent to —
        and a field nobody documented is a field nobody reads with a
        default. Named in the Events section, wherever in it the sentence
        reads best; only the name is asserted.
        """
        section = _md_section("Events")
        for event, optional in c.OPTIONAL.items():
            for name in optional:
                assert f"`{name}`" in section, \
                    f"{event}.{name} is optional and undocumented"

    def test_the_stated_version(self):
        assert f"SCHEMA_VERSION == {c.SCHEMA_VERSION}" in CONTRACT_MD.read_text()

    def test_the_delta_bound_the_page_quotes_is_the_one_the_code_uses(self):
        """A number in prose is a number that drifts.

        `BOUND_CHARS` is a display tuning knob rather than a protocol
        value — a consumer must never read meaning into where a fragment
        ends — but the page tells one how many records to expect, and a
        page saying 64 over code doing 8 would be describing a stream
        nobody receives.
        """
        from core.runtime.answer_stream import BOUND_CHARS

        assert f"{BOUND_CHARS} characters, or a newline" in \
            _md_section("Events")


# ── being asked to stop is not the same as stopping ──────────────────────────


class _SpySink:
    def __init__(self):
        self.flushed = self.closed = 0

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed += 1


def _Switch():
    """The mission's cancellation, spelled out where a test reads it."""
    from core.budgets import Cancellation

    return Cancellation()


@pytest.fixture
def sigterm_restored():
    previous = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, previous)


class TestSigtermClosesTheStream:
    def test_no_sink_installs_nothing(self, sigterm_restored):
        before = signal.getsignal(signal.SIGTERM)
        ms.close_on_sigterm(None)
        assert signal.getsignal(signal.SIGTERM) is before

    def test_the_sink_is_flushed_and_closed_and_the_signal_re_raised(
            self, monkeypatch, sigterm_restored):
        """TAIPAN sends SIGTERM rather than SIGKILL *so that* the harness gets
        to close its stream. Nothing made that true until there was a handler,
        and swallowing the signal afterwards would report a killed turn as a
        clean exit."""
        import os

        sink = _SpySink()
        ms.close_on_sigterm(sink)
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)

        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        handler(signal.SIGTERM, None)

        assert (sink.flushed, sink.closed) == (1, 1)
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert killed == [(os.getpid(), signal.SIGTERM)]

    def test_a_flush_on_a_dead_stream_does_not_raise(self):
        """The handler runs while something is already going wrong. It is the
        last thing that should add a traceback to it."""
        import io

        stream = io.StringIO()
        stream.close()
        ms.NdjsonSink(stream).flush()

    def test_the_first_signal_cancels_instead_of_closing(
            self, monkeypatch, sigterm_restored):
        """Closing the stream ON the signal saved every record except the one
        that says the run is over — which is the record a pane needs to stop
        spinning. So the first ask is cooperative: throw the switch, return,
        and let the loop finish and close in its own `finally`."""
        import os

        sink, switch = _SpySink(), _Switch()
        ms.close_on_sigterm(sink, switch)
        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))

        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        assert switch.is_set() is True
        assert switch.cause == ms.SIGTERM_CAUSE
        # Nothing closed, nothing died: the mission is still running and
        # still has a record to write.
        assert (sink.flushed, sink.closed, killed) == (0, 0, [])

    def test_a_second_signal_does_not_wait(self, monkeypatch, sigterm_restored):
        """Somebody asked twice, which means the first ask is not being
        honoured fast enough — a model call in flight, a tool mid-subprocess.
        The honest answer is the old behaviour."""
        import os

        sink, switch = _SpySink(), _Switch()
        ms.close_on_sigterm(sink, switch)
        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))

        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
        handler(signal.SIGTERM, None)

        assert (sink.flushed, sink.closed) == (1, 1)
        assert killed == [signal.SIGTERM]

    def test_the_whole_ordering_a_stopped_run_gets(self, monkeypatch,
                                                   sigterm_restored):
        """Cancel → the loop ends → `mission_finished` → the sink closes →
        the process dies of the signal. Asserted as one sequence, because
        every one of those steps is only worth having in that order."""
        import os

        from core.runtime.mission import MissionRunner

        events, order = [], []

        class _Sink:
            def __call__(self, record):
                events.append(dict(record))

            def flush(self):
                order.append("flush")

            def close(self):
                order.append("close")

        sink, switch = _Sink(), _Switch()
        ms.close_on_sigterm(sink, switch)
        handler = signal.getsignal(signal.SIGTERM)

        def signalled(messages):
            handler(signal.SIGTERM, None)
            return json.dumps({"tool": "catalog_search_assets",
                               "arguments": {}})

        transcript = MissionRunner(
            signalled, _Bus(), ["catalog_search_assets"], observer=sink,
            store_tool="", cancel=switch).run("go")
        sink.close()

        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))
        ms.exit_as_signalled(switch)

        assert transcript.outcome == "incomplete"
        assert events[-1]["event"] == ms.MISSION_FINISHED
        assert events[-1]["reason"] == "cancelled"
        assert order == ["close"]
        # And the exit status is still the signal's: a turn that was stopped
        # and reports success is a turn a consumer will believe finished.
        assert killed == [signal.SIGTERM]
        assert _faults(events) == []

    def test_a_library_cancellation_does_not_kill_the_process(
            self, monkeypatch):
        """`exit_as_signalled` is for the run a SIGTERM asked to stop. A
        caller that threw the switch itself wants its process back."""
        import os

        from core.budgets import Cancellation

        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append(sig))
        switch = Cancellation()
        switch.cancel()
        ms.exit_as_signalled(switch)
        ms.exit_as_signalled(None)
        assert killed == []


# ── the diagnostic clause, which used to be a warning ────────────────────────


class TestTheDiagnosticIsScrubbedBeforeItIsWritten:
    """``EXIT_CONTRACT["diagnostic"]`` told a consumer that stderr carries
    absolute paths from this host and that it had to scrub them itself.  It
    was the sentence TAIPAN's location sweep was deferred on.  Mission mode's
    outermost frame is what makes it false: the traceback is rendered through
    the same redactor the stream uses and written by the harness, not by the
    interpreter's default handler.
    """

    LEAK = "/home/testuser/data/mission.log"

    def _blow_up(self, monkeypatch):
        from core import cli

        def explode(*_args, **_kwargs):
            raise RuntimeError(f"cannot open {self.LEAK}")

        monkeypatch.setattr(cli, "_mission", explode)
        return cli

    def test_the_traceback_reaches_stderr_scrubbed(self, monkeypatch, capsys):
        cli = self._blow_up(monkeypatch)
        with pytest.raises(SystemExit) as exit_info:
            cli._run_mission(object(), object(), "Tai", "cyan")
        assert exit_info.value.code == 1
        err = capsys.readouterr().err
        assert "RuntimeError: cannot open <home>/data/mission.log" in err
        assert self.LEAK not in err
        # Still a traceback: a scrubbed location is no use if the frame it
        # belonged to went with it.
        assert "Traceback (most recent call last):" in err
        assert "_run_mission" in err

    def test_a_refusal_is_not_turned_into_a_traceback(self, monkeypatch, capsys):
        """``SystemExit`` is how this CLI refuses — ``--skill: no such tool``
        and the rest. Catching it here would bury a sentence somebody wrote
        for an operator under a stack this code produced."""
        from core import cli

        def refuse(*_args, **_kwargs):
            raise SystemExit("--events: fd: needs a number")

        monkeypatch.setattr(cli, "_mission", refuse)
        with pytest.raises(SystemExit) as exit_info:
            cli._run_mission(object(), object(), "Tai", "cyan")
        assert exit_info.value.code == "--events: fd: needs a number"
        assert "Traceback" not in capsys.readouterr().err

    def test_a_person_pressing_control_c_is_not_a_defect(self, monkeypatch, capsys):
        from core import cli

        def interrupt(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(cli, "_mission", interrupt)
        with pytest.raises(KeyboardInterrupt):
            cli._run_mission(object(), object(), "Tai", "cyan")
        assert capsys.readouterr().err == ""

    def test_the_clause_no_longer_tells_a_consumer_to_scrub_it_itself(self):
        """The contract is data, and this is the datum that changed."""
        clause = c.EXIT_CONTRACT["diagnostic"]
        assert "SCRUBBED BEFORE IT IS WRITTEN" in clause
        assert "<home>" in clause and "<redacted:NAME>" in clause
        assert "CARRIES ABSOLUTE PATHS" not in clause

    def test_the_page_a_person_reads_says_the_same(self):
        text = CONTRACT_MD.read_text()
        assert "scrubbed before it is written" in text
        assert "carries absolute paths from this host" not in text
