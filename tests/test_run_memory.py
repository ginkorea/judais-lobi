# tests/test_run_memory.py — where the three tiers meet the loop

"""What a bank changes about a run, and — first — what it does not.

The load-bearing assertion in this file is the **negative** one: a run with
no bank produces the messages it produced before this module existed, byte
for byte.  ``tests/test_run_corpus.py`` is the other half of that claim and
the stronger one — it replays four recorded runs through this code and
compares them record for record with an empty drift record, which means the
prompts are the recorded prompts.  What is here is the reason it holds:
:meth:`~core.runtime.run.Run.system_turn` stacks ``""`` and
:func:`~core.runtime.mission.stacked` drops it, and
:meth:`~core.runtime.run.Run.seed`'s objective turn is the objective alone.

With a bank there are exactly four visible differences, and each has a
class below: a fourth section in the system turn AFTER the catalogue, a
titles-only hint in the USER turn beside the objective, two more names in
the catalogue, and — after a run that answered — a reflection that writes
notes and spends tokens on the run's own ledger.  Nothing on the wire is
new: a recall is a ``tool_call``/``tool_result`` pair like any other.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.memory.bank import MEMORY_POLICY, MemoryBank
from core.runtime.mission import PROTOCOL, MissionRunner, stacked
from core.runtime.mission_stream import TOOL_CALL, TOOL_RESULT
from core.runtime.run import (
    Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.usage import Ledger
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import (
    MEMORY_RECALL_TOOL, MEMORY_WRITE_TOOL, ToolDescriptor,
)
from core.tools.sandbox import NoneSandbox
from tests.test_mission import ScriptedModel


@pytest.fixture
def bus():
    made = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox())
    made.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    return made


@pytest.fixture
def bank(tmp_path):
    return MemoryBank(tmp_path / "bank", principal="alice")


def a_run(bus, *replies, memory=None, records=None, plain=None,
          usage_fn=None, history=()):
    store = Store(run_id="run-1")
    return Run(
        Personality(system_message="You are Tai.", memory=memory,
                    history=history),
        ToolPlane(bus=bus, offered=["catalog.search"], store_tool=""),
        Bounds(),
        store,
        Observer((records if records is not None else []).append, store=store),
        Model(ask=ScriptedModel(*replies), plain=plain, usage_fn=usage_fn,
              ledger=Ledger()),
    )


def answer(text="done"):
    return json.dumps({"answer": text})


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


# ── the negative claim ──────────────────────────────────────────────────────


class TestWithNoBankNothingMoved:
    def test_the_system_turn_is_the_three_sections_and_no_more(self, bus):
        run = a_run(bus)
        assert run.system_turn() == {"role": "system", "content": stacked(
            "You are Tai.", PROTOCOL.strip(),
            "Tool catalogue:\n" + run.catalogue())}

    def test_the_objective_turn_is_the_objective(self, bus):
        assert a_run(bus).seed("find things")[-1] == {
            "role": "user", "content": "find things"}

    def test_the_seed_is_two_messages_and_a_history(self, bus):
        run = a_run(bus, history=[{"role": "user", "content": "hi"},
                                  {"role": "assistant", "content": "hello"}])
        assert [turn["role"] for turn in run.seed("go")] == [
            "system", "user", "assistant", "user"]
        assert run.pinned == 4

    def test_the_catalogue_holds_no_memory_tool(self, bus):
        run = a_run(bus)
        assert run.offered == ["catalog.search"]
        assert MEMORY_RECALL_TOOL not in run.catalogue()

    def test_a_run_with_no_bank_asks_nobody_anything_extra(self, bus):
        asked = []
        run = a_run(bus, answer("done"), plain=lambda m: asked.append(m))
        assert run.run("go").outcome == "answered"
        assert asked == []


# ── the core block, and where it sits ───────────────────────────────────────


class TestTheCoreBlockIsTheFourthSection:
    def test_it_is_in_the_system_turn(self, bus, bank):
        bank.write("add", label="style", kind="preference",
                   body="Answers are short.", reason="asked twice",
                   source="operator")
        content = a_run(bus, memory=bank).system_turn()["content"]
        assert "- [preference] style: Answers are short." in content

    def test_it_comes_after_the_catalogue(self, bus, bank):
        content = a_run(bus, memory=bank).system_turn()["content"]
        assert content.index("Tool catalogue:") < content.index(MEMORY_POLICY)

    def test_and_after_the_persona_and_the_protocol(self, bus, bank):
        content = a_run(bus, memory=bank).system_turn()["content"]
        assert content.index("You are Tai.") < content.index(MEMORY_POLICY)
        assert content.index(PROTOCOL.strip()[:40]) < content.index(
            MEMORY_POLICY)

    def test_and_before_the_history_and_the_objective(self, bus, bank):
        run = a_run(bus, memory=bank,
                    history=[{"role": "user", "content": "earlier"}])
        seeded = run.seed("go")
        assert MEMORY_POLICY in seeded[0]["content"]
        assert [turn["role"] for turn in seeded] == ["system", "user", "user"]
        assert seeded[1]["content"] == "earlier"
        assert seeded[2]["content"] == "go"

    def test_the_policy_sentence_is_there_with_nothing_pinned(self, bus,
                                                              bank):
        assert MEMORY_POLICY in a_run(bus, memory=bank
                                      ).system_turn()["content"]

    def test_the_run_is_the_bank_rendering_and_not_a_second_one(self, bus,
                                                                bank):
        bank.write("add", label="k", kind="fact", body="b", reason="r",
                   source="s")
        content = a_run(bus, memory=bank).system_turn()["content"]
        assert content.endswith(bank.core())

    def test_a_bank_that_raises_costs_the_run_nothing(self, bus):
        class Broken:
            def core(self):
                raise RuntimeError("locked")

            def hint(self, _objective):
                raise RuntimeError("locked")

            def tool_names(self):
                return []

            def register_on(self, _bus, **_kw):
                return []

        run = a_run(bus, answer("done"), memory=Broken())
        assert run.seed("go")[-1]["content"] == "go"
        assert run.run("go").outcome == "answered"


# ── the hint, and where it does NOT sit ─────────────────────────────────────


class TestTheHintRidesWithTheObjective:
    def test_a_scoring_note_puts_a_hint_in_the_user_turn(self, bus, bank):
        bank.add_note("Widget calibration is manual", "Do it by hand.")
        seeded = a_run(bus, memory=bank).seed("calibrate the widget")
        assert "Widget calibration is manual" in seeded[-1]["content"]
        assert seeded[-1]["content"].startswith("calibrate the widget")

    def test_and_never_in_the_system_turn(self, bus, bank):
        bank.add_note("Widget calibration is manual", "Do it by hand.")
        run = a_run(bus, memory=bank)
        assert "Widget calibration is manual" not in run.system_turn()[
            "content"]

    def test_nothing_scoring_leaves_the_objective_alone(self, bus, bank):
        bank.add_note("Widget calibration is manual", "Do it by hand.")
        assert a_run(bus, memory=bank).seed("unrelated request")[-1] == {
            "role": "user", "content": "unrelated request"}

    def test_the_hint_is_titles_and_not_bodies(self, bus, bank):
        bank.add_note("Widget calibration is manual", "Do it by hand.")
        seeded = a_run(bus, memory=bank).seed("calibrate the widget")
        assert "Do it by hand." not in seeded[-1]["content"]

    def test_the_hint_does_not_change_what_a_compaction_may_drop(self, bus,
                                                                 bank):
        """It rides *in* the objective turn rather than as a message of its
        own, so ``pinned`` — which is how many leading messages a
        compaction may never drop — is what it always was."""
        bank.add_note("Widget calibration is manual", "Do it by hand.")
        assert a_run(bus, memory=bank).pinned == 2


# ── the plane ───────────────────────────────────────────────────────────────


class TestTheToolsAreOfferedForTheLengthOfTheRun:
    def test_both_names_are_offered(self, bus, bank):
        run = a_run(bus, memory=bank)
        assert run.offered == ["catalog.search", MEMORY_RECALL_TOOL,
                               MEMORY_WRITE_TOOL]

    def test_they_are_registered_while_the_run_is_running(self, bus, bank):
        seen = {}

        def peek(**kwargs):
            seen["offered"] = list(bus.list_tools())
            return (0, "hits", "")

        bus.register(ToolDescriptor(tool_name="peek", description="Peek."),
                     peek)
        run = a_run(bus, tool_call("peek"), answer("done"), memory=bank)
        run.plane.offered.append("peek")
        run.run("go")
        assert MEMORY_RECALL_TOOL in seen["offered"]
        assert MEMORY_WRITE_TOOL in seen["offered"]

    def test_and_withdrawn_afterwards(self, bus, bank):
        a_run(bus, answer("done"), memory=bank).run("go")
        assert bus.get_descriptor(MEMORY_RECALL_TOOL) is None
        assert bus.get_descriptor(MEMORY_WRITE_TOOL) is None

    def test_they_are_in_the_catalogue_the_model_is_shown(self, bus, bank):
        """Read off the running loop and not off ``catalogue()`` before it:
        the catalogue renders the BUS's own descriptions, and — exactly as
        for ``mission_result`` — these are on the bus for the length of the
        run and not before it."""
        run = a_run(bus, answer("done"), memory=bank)
        run.run("go")
        system = run.model.ask.seen[0][0]["content"]
        assert f"- {MEMORY_RECALL_TOOL}:" in system
        assert f"- {MEMORY_WRITE_TOOL}:" in system
        # And the core block still follows them, in the turn actually sent.
        assert system.index(f"- {MEMORY_WRITE_TOOL}:") < system.index(
            MEMORY_POLICY)

    def test_arriving_memory_tools_are_never_read_as_a_plane_that_grew(
            self, bus, bank):
        """They are registered before the baseline is taken, so the model
        is never told ``+memory_recall`` mid-run."""
        records = []
        run = a_run(bus, answer("done"), memory=bank, records=records)
        run.run("go")
        started = [r for r in records if r["event"] == "step_started"]
        assert all("catalogue" not in record for record in started)


class TestARecallIsAnOrdinaryToolResult:
    def test_the_model_calls_it_and_is_shown_what_came_back(self, bus, bank):
        bank.add_note("Widget calibration is manual",
                      "The rig has no autocalibration.")
        records = []
        run = a_run(bus, tool_call(MEMORY_RECALL_TOOL, query="widget"),
                    answer("It is manual."), memory=bank, records=records)
        transcript = run.run("how is the widget calibrated")
        assert transcript.outcome == "answered"
        called = [r for r in records if r["event"] == TOOL_CALL]
        results = [r for r in records if r["event"] == TOOL_RESULT]
        assert [r["tool"] for r in called] == [MEMORY_RECALL_TOOL]
        assert results[0]["ok"] is True
        assert "Widget calibration is manual" in results[0]["output"]

    def test_no_new_record_type_appears(self, bus, bank):
        bank.add_note("alpha", "beta")
        records = []
        a_run(bus, tool_call(MEMORY_RECALL_TOOL, query="alpha"),
              answer("done"), memory=bank, records=records).run("go")
        assert {record["event"] for record in records} <= {
            "mission_started", "step_started", TOOL_CALL, TOOL_RESULT,
            "answer", "mission_finished"}

    def test_a_write_the_model_makes_is_read_back_next_run(self, bus, bank):
        a_run(bus, tool_call(MEMORY_WRITE_TOOL, action="add",
                             label="house-style", kind="lesson",
                             body="Never quote a figure without its unit.",
                             reason="was corrected", source="r1"),
              answer("noted"), memory=bank).run("go")
        assert "Never quote a figure without its unit." in \
            a_run(bus, memory=bank).system_turn()["content"]


# ── the reflection ──────────────────────────────────────────────────────────


class ReflectingModel:
    """A ``plain`` that returns one note and counts how often it was asked."""

    def __init__(self, reply=None):
        self.reply = reply if reply is not None else json.dumps(
            {"notes": [{"title": "Cold starts are slow",
                        "body": "Retry once.", "importance": 4}]})
        self.calls = 0

    def __call__(self, messages, **_extra):
        self.calls += 1
        return self.reply


class TestTheReflectionRunsOnceAndCannotFailTheRun:
    def test_a_run_that_answered_writes_notes(self, bus, bank):
        plain = ReflectingModel()
        a_run(bus, answer("done"), memory=bank, plain=plain).run("go")
        assert plain.calls == 1
        assert [note.title for note in bank.notes()] == [
            "Cold starts are slow"]

    def test_the_note_carries_the_run_it_came_from(self, bus, bank):
        a_run(bus, tool_call("catalog.search", q="x"), answer("done"),
              memory=bank, plain=ReflectingModel()).run("go")
        note, = bank.notes()
        assert note.run_id == "run-1"
        assert note.sources == ["run-1/0"]

    def test_at_most_three_notes(self, bus, bank):
        plain = ReflectingModel(json.dumps({"notes": [
            {"title": f"t{i}", "body": f"b{i}"} for i in range(7)]}))
        a_run(bus, answer("done"), memory=bank, plain=plain).run("go")
        assert len(bank.notes()) == 3

    def test_a_run_that_did_not_answer_reflects_on_nothing(self, bus, bank):
        plain = ReflectingModel()
        run = a_run(bus, tool_call("catalog.search", q="x"), memory=bank,
                    plain=plain)
        run.bounds = type(run.bounds)(max_steps=1)
        transcript = run.run("go")
        assert transcript.outcome == "budget_exhausted"
        assert plain.calls == 0 and bank.notes() == []

    def test_a_reflection_that_raises_does_not_fail_the_run(self, bus, bank):
        def explode(_messages, **_extra):
            raise RuntimeError("endpoint down")

        transcript = a_run(bus, answer("done"), memory=bank,
                           plain=explode).run("go")
        assert transcript.outcome == "answered"
        assert transcript.answer == "done"
        assert bank.notes() == []

    def test_a_run_with_no_bank_never_reflects(self, bus):
        plain = ReflectingModel()
        a_run(bus, answer("done"), plain=plain).run("go")
        assert plain.calls == 0

    def test_the_reflection_emits_no_record(self, bus, bank):
        records = []
        a_run(bus, answer("done"), memory=bank, plain=ReflectingModel(),
              records=records).run("go")
        assert [r["event"] for r in records] == [
            "mission_started", "step_started", "answer", "mission_finished"]

    def test_what_it_cost_is_on_the_run_s_ledger(self, bus, bank):
        from core.runtime.backends.base import Usage

        run = a_run(bus, answer("done"), memory=bank,
                    plain=ReflectingModel(),
                    usage_fn=lambda: Usage(prompt_tokens=10,
                                           completion_tokens=2,
                                           total_tokens=12))
        transcript = run.run("go")
        # Two calls: the step and the reflection. A reflection whose tokens
        # were never read would leave 12 here.
        assert transcript.usage.as_record()["total_tokens"] == 24

    def test_the_reflection_is_asked_the_answer_and_the_evidence(self, bus,
                                                                 bank):
        seen = {}

        def plain(messages, **_extra):
            seen["text"] = messages[0]["content"]
            return "{}"

        a_run(bus, tool_call("catalog.search", q="widgets"),
              answer("There are four."), memory=bank, plain=plain).run(
                  "count the widgets")
        assert "count the widgets" in seen["text"]
        assert "There are four." in seen["text"]
        assert "hits for widgets" in seen["text"]


# ── the adapter carries it ──────────────────────────────────────────────────


class TestTheAdapterHandsTheBankToThePersonality:
    def test_memory_lands_on_the_personality(self, bus, bank):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                               memory=bank)
        assert runner._run.personality.memory is bank

    def test_the_plain_model_lands_on_the_model(self, bus):
        plain = ScriptedModel()
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                               plain_chat_fn=plain)
        assert runner._run.model.plain is plain

    def test_a_caller_that_built_no_plain_model_gets_the_one_it_did_build(
            self, bus):
        asking = ScriptedModel()
        runner = MissionRunner(asking, bus, ["catalog.search"])
        assert runner._run.model.plain is asking

    def test_a_runner_with_no_bank_seeds_what_it_always_did(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert runner.seed("go")[-1] == {"role": "user", "content": "go"}


class TestAStagedTurnKeepsTheBankAndAStepDoesNot:
    """A step's summary is not an answer, so a reflection over one would
    put "what a stage concluded" in a bank that holds what a *mission*
    learned.  The swarm strikes ``memory`` out of a plan step's personality
    beside ``grounding`` and ``critic``, for the same sentence."""

    def test_the_turn_carries_it(self, bus, bank):
        from core.runtime.swarm import SwarmRunner

        runner = SwarmRunner(ScriptedModel(), bus, ["catalog.search"],
                             memory=bank)
        assert runner._run.personality.memory is bank

    def test_a_plan_step_does_not(self, bus, bank, monkeypatch):
        """Driven, not asserted about the source: a real two-step staged
        turn, with every child's personality captured as it is built."""
        from core.runtime.run import Run
        from core.runtime.swarm import SwarmRunner

        seen = []
        original = Run.child

        def spy(self, *, personality=None, **kwargs):
            child = original(self, personality=personality, **kwargs)
            seen.append(child.personality)
            return child

        monkeypatch.setattr(Run, "child", spy)
        plain = ScriptedModel(
            json.dumps({"route": "staged"}),
            json.dumps({"steps": [
                {"id": "s1", "goal": "search", "rung": "tool"},
                {"id": "s2", "goal": "search again", "rung": "tool",
                 "needs": ["s1"]}]}),
            "the synthesized answer")
        executor = ScriptedModel(
            tool_call("catalog.search", q="a"), answer("first"),
            tool_call("catalog.search", q="b"), answer("second"))
        SwarmRunner(executor, bus, ["catalog.search"], memory=bank,
                    plain_chat_fn=plain,
                    system_message="You are Tai.").run("do two things")
        assert seen, "no child was built"
        assert all(personality.memory is None for personality in seen)
        assert all(personality.grounding is None for personality in seen)

    def test_the_direct_route_inherits_it(self, bus, bank):
        """``_direct`` overrides nothing, so a staged turn that routes
        direct is a whole mission with the bank on it."""
        from core.runtime.swarm import SwarmRunner

        runner = SwarmRunner(ScriptedModel(), bus, ["catalog.search"],
                             memory=bank)
        assert runner._run.child().personality.memory is bank
