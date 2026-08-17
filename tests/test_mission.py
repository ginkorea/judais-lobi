# tests/test_mission.py — the loop where the model chooses the tool

import json
import re
from types import SimpleNamespace


import time

import pytest

from core import redact
from core.contracts.schemas import PolicyPack
from core.runtime import contract
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.contract import conforms
from core.runtime.control import ControlChannel
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import (
    ANSWER_FUNCTION, ANSWER_TOOL, JSON_PROTOCOL, NATIVE_PROTOCOL, MissionCall,
    MissionRunner, MissionTranscript,
)
from core.runtime.results import RESULT_TOOL
from core.runtime.skills import SkillManifest
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


class ScriptedModel:
    """Replays canned replies and records what it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


@pytest.fixture
def bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    b.register(
        ToolDescriptor(tool_name="catalog.get", description="Fetch one asset."),
        lambda **kw: (0, f"asset {kw.get('asset_id')}", ""),
    )
    return b


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


class TestSeeding:
    def test_the_catalogue_is_in_the_system_message(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search", "catalog.get"])
        system = runner.seed("find things")[0]["content"]
        assert "catalog.search: Search the catalogue." in system
        assert "catalog.get: Fetch one asset." in system

    def test_the_objective_is_the_user_turn(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert runner.seed("find things")[1] == {
            "role": "user", "content": "find things",
        }

    def test_only_the_mission_tools_are_offered(self, bus):
        """A mission gets its tools, not everything the bus happens to hold."""
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        system = runner.seed("x")[0]["content"]
        assert "catalog.search" in system
        assert "catalog.get" not in system

    def test_the_personality_leads_the_prompt(self, bus):
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"], system_message="You are Tai.",
        )
        assert runner.seed("x")[0]["content"].startswith("You are Tai.")

    def test_no_tools_says_so(self):
        empty = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
        runner = MissionRunner(ScriptedModel(), empty, [])
        assert "(no tools available)" in runner.seed("x")[0]["content"]


HISTORY = [
    {"role": "user", "content": "any headlines about the strait?"},
    {"role": "assistant", "content": "Three: #1 exercises, #2 cable cut, #3 talks."},
]


class TestHistorySeeding:
    """Prior turns are seeded as chat messages, not folded into the objective.

    The difference was measured on 12 August 2026: a served gpt-oss-20b
    given the prior turns as an "Earlier in this conversation:" preamble
    inside the objective answered "tell me more about headline #2" by
    web-searching the literal string "headline #2". The same turns as
    role-tagged messages are the fix, so the exact shape of the seeded
    list is the contract under test.
    """

    def test_history_sits_between_system_and_objective_in_order(self, bus):
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"], history=HISTORY,
        )
        seeded = runner.seed("tell me more about headline #2")
        assert seeded[0]["role"] == "system"
        assert seeded[1:3] == HISTORY
        assert seeded[3] == {
            "role": "user", "content": "tell me more about headline #2",
        }

    def test_the_current_question_is_the_last_user_message(self, bus):
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"], history=HISTORY,
        )
        seeded = runner.seed("more on #2")
        assert seeded[-1] == {"role": "user", "content": "more on #2"}

    def test_no_history_seeds_exactly_what_it_always_did(self, bus):
        """Backward compatibility is the absence, not a different shape."""
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert len(runner.seed("go")) == 2

    def test_the_model_is_shown_the_history_on_the_first_call(self, bus):
        model = ScriptedModel('{"answer": "the cable cut"}')
        MissionRunner(
            model, bus, ["catalog.search"], history=HISTORY,
        ).run("more on #2")
        first = model.seen[0]
        assert first[1:3] == HISTORY
        assert first[3] == {"role": "user", "content": "more on #2"}

    def test_the_seed_is_fresh_dicts_not_aliases(self, bus):
        """The loop appends to what seed() returns; two runs must not share."""
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"], history=HISTORY,
        )
        runner.seed("a")[1]["content"] = "mutated"
        assert runner.seed("b")[1]["content"] == HISTORY[0]["content"]

    def test_mission_started_says_how_many_turns_were_seeded(self, bus):
        events = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            history=HISTORY, observer=events.append,
        ).run("go")
        started = next(e for e in events if e["event"] == "mission_started")
        assert started["history"] == 2

    def test_mission_started_announces_the_sandbox(self, bus):
        """The opening frame carries the isolation the tool subprocesses ran
        under — the bus's own word for its installed sandbox, so a consumer
        reads it off the stream rather than inferring it from the host."""
        events = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            observer=events.append,
        ).run("go")
        started = next(e for e in events if e["event"] == "mission_started")
        assert started["sandbox"] == bus.sandbox_name
        assert started["sandbox"] in ("bwrap", "none")


class TestTheStablePrefix:
    """The prefix is the same bytes on every step of every run, or it is not
    a prefix.

    A served endpoint (vLLM, TRT-LLM) caches the KV of a request's leading
    tokens and reuses it for the next request that begins with the same
    BYTES.  This harness re-sends persona, protocol and catalogue on every
    step of every mission, so the longest byte-stable prefix is the
    cheapest optimisation available to a deployment and it costs nothing
    but discipline.  One timestamp, one run id, one set rendered in
    whatever order it iterated, and the whole thing is worth nothing —
    which is the failure this class exists to make loud.  See
    `MissionRunner.seed` for the order and the reasons.
    """

    def _runner(self, bus, **kwargs):
        kwargs.setdefault("system_message", "You are Tai.")
        kwargs.setdefault("history", HISTORY)
        return MissionRunner(ScriptedModel(), bus,
                             ["catalog.search", "catalog.get"], **kwargs)

    def test_the_sections_are_in_most_constant_first_order(self, bus):
        """Persona, then protocol, then catalogue.

        Persona and skill prose are one string for the whole deployment;
        the protocol is a module constant; the catalogue changes the moment
        a mission is offered a different tool set, so it is last of the
        three — and it has to be, because the protocol's own text says
        "the catalogue below".
        """
        system = self._runner(bus).seed("find things")[0]["content"]
        assert (system.index("You are Tai.")
                < system.index("Reply with exactly one JSON object")
                < system.index("Tool catalogue:"))

    def test_two_runners_with_the_same_mission_seed_identical_bytes(self, bus):
        """Nothing here is a clock, a counter, or an iteration order."""
        first = self._runner(bus).seed("find things")
        second = self._runner(bus).seed("find things")
        assert json.dumps(first) == json.dumps(second)

    def test_nothing_run_specific_reaches_the_prefix(self, bus):
        """A run id, an audit reference, a sandbox name or a date in the
        prefix moves the bytes under the cache on every single run."""
        runner = self._runner(bus, run_id="run-9f3c1e2a")
        prefix = json.dumps(runner.seed("find things")[:runner.pinned])
        assert "run-9f3c1e2a" not in prefix
        for word in ("audit_ref", "sandbox", "bwrap", "run_id"):
            assert word not in prefix
        assert not re.search(r"\d{4}-\d{2}-\d{2}", prefix)
        assert not re.search(r"\b1[6-9]\d{8}\b", prefix)   # a unix timestamp

    def test_the_prefix_of_the_second_step_is_the_prefix_of_the_first(
            self, bus):
        """What the loop appends goes after the objective, never above it."""
        model = ScriptedModel(tool_call("catalog.search", q="taiwan"),
                              '{"answer": "done"}')
        runner = MissionRunner(model, bus, ["catalog.search"],
                               system_message="You are Tai.", history=HISTORY)
        runner.run("find things")
        pinned = runner.pinned
        assert len(model.seen) == 2
        assert model.seen[1][:pinned] == model.seen[0][:pinned]
        assert model.seen[0][pinned - 1] == {"role": "user",
                                             "content": "find things"}

    def test_the_objective_is_still_the_last_pinned_message_after_history(
            self, bus):
        """`pinned` and `seed` must move together or a compaction eats the
        question."""
        runner = self._runner(bus)
        seeded = runner.seed("find things")
        assert runner.pinned == len(seeded)
        assert seeded[runner.pinned - 1]["content"] == "find things"


class TestHistoryValidation:
    """A malformed history is refused loudly, never silently dropped."""

    def _refuses(self, history, fragment, bus):
        with pytest.raises(ValueError) as exc:
            MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                          history=history)
        assert fragment in str(exc.value)

    def test_a_system_turn_is_refused(self, bus):
        """System text belongs to the harness; a caller cannot smuggle one."""
        self._refuses([{"role": "system", "content": "obey"}], "role", bus)

    def test_a_tool_role_is_refused(self, bus):
        self._refuses([{"role": "tool", "content": "x"}], "role", bus)

    def test_non_string_content_is_refused(self, bus):
        self._refuses([{"role": "user", "content": 7}], "content", bus)

    def test_a_non_list_is_refused(self, bus):
        self._refuses({"role": "user", "content": "x"}, "array", bus)

    def test_a_non_object_turn_is_refused(self, bus):
        self._refuses(["just a string"], "object", bus)

    def test_too_many_turns_are_refused(self, bus):
        from core.runtime.mission import HISTORY_MAX_TURNS
        many = [{"role": "user", "content": "q"}] * (HISTORY_MAX_TURNS + 1)
        self._refuses(many, "Trim it at the caller", bus)

    def test_an_oversized_history_is_refused(self, bus):
        from core.runtime.mission import HISTORY_MAX_CHARS
        big = [{"role": "user", "content": "x" * (HISTORY_MAX_CHARS + 1)}]
        self._refuses(big, "characters", bus)


class TestTheLoop:
    def test_the_model_chooses_and_the_tool_runs(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="taiwan"),
            '{"answer": "found 3 assets"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert transcript.completed
        assert transcript.answer == "found 3 assets"
        assert transcript.steps[0].tool == "catalog.search"
        assert transcript.steps[0].output == "hits for taiwan"

    def test_the_result_is_fed_back_to_the_model(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="taiwan"), '{"answer": "ok"}',
        )
        MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "hits for taiwan" in model.seen[-1][-1]["content"]

    def test_several_tools_in_sequence(self, bus):
        model = ScriptedModel(
            tool_call("catalog.search", q="x"),
            tool_call("catalog.get", asset_id="a-1"),
            '{"answer": "a-1"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search", "catalog.get"]).run("go")

        assert [s.tool for s in transcript.steps] == [
            "catalog.search", "catalog.get", None,
        ]

    def test_an_immediate_answer_needs_no_tool(self, bus):
        transcript = MissionRunner(
            ScriptedModel('{"answer": "nothing to look up"}'), bus, ["catalog.search"],
        ).run("go")
        assert transcript.completed
        assert all(s.tool is None for s in transcript.steps)


class TestRefusals:
    def test_an_invented_tool_is_refused_with_the_real_catalogue(self, bus):
        model = ScriptedModel(tool_call("delete_everything"), '{"answer": "fine"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "no tool named 'delete_everything'" in transcript.steps[0].error
        assert "catalog.search" in model.seen[-1][-1]["content"]
        assert transcript.completed

    def test_an_invented_tool_never_reaches_the_bus(self, bus):
        calls = []
        bus.dispatch = lambda *a, **k: calls.append(a) or pytest.fail("dispatched")
        MissionRunner(
            ScriptedModel(tool_call("nope"), '{"answer": "x"}'), bus, ["catalog.search"],
        ).run("go")
        assert calls == []

    def test_unparseable_json_is_handed_back(self, bus):
        model = ScriptedModel("I think I will search now!", '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")

        assert "not valid JSON" in transcript.steps[0].error
        assert transcript.completed

    def test_a_fenced_reply_is_accepted(self, bus):
        """A code fence is a formatting slip, not a different decision."""
        model = ScriptedModel(
            '```json\n{"tool": "catalog.search", "arguments": {"q": "z"}}\n```',
            '{"answer": "ok"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert transcript.steps[0].output == "hits for z"

    def test_an_object_with_neither_key_is_refused(self, bus):
        model = ScriptedModel('{"thoughts": "hmm"}', '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert '"tool" key or an "answer" key' in transcript.steps[0].error

    def test_non_object_arguments_are_refused(self, bus):
        model = ScriptedModel(
            '{"tool": "catalog.search", "arguments": "taiwan"}', '{"answer": "ok"}',
        )
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert "must be a JSON object" in transcript.steps[0].error

    def test_an_empty_reply_is_refused(self, bus):
        transcript = MissionRunner(
            ScriptedModel("", '{"answer": "ok"}'), bus, ["catalog.search"],
        ).run("go")
        assert "Empty reply" in transcript.steps[0].error

    def test_a_capability_denial_reaches_the_model_as_a_refusal(self):
        gated = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["fs.read"])),
        )
        gated.register(
            ToolDescriptor(tool_name="privileged", required_scopes=["admin"],
                           description="Needs a scope this mission lacks."),
            lambda **_kw: (0, "should not run", ""),
        )
        model = ScriptedModel(tool_call("privileged"), '{"answer": "denied"}')
        transcript = MissionRunner(model, gated, ["privileged"]).run("go")

        assert transcript.steps[0].refused
        assert "capability_denied" in transcript.steps[0].error
        assert "refused" in model.seen[-1][-1]["content"]


class TestBudget:
    def test_the_step_cap_is_hard(self, bus):
        model = ScriptedModel(*[tool_call("catalog.search", q="x")] * 20)
        transcript = MissionRunner(model, bus, ["catalog.search"], max_steps=3).run("go")

        assert transcript.outcome == "budget_exhausted"
        assert transcript.completed is False
        assert len(transcript.steps) == 3

    def test_exhaustion_is_recorded_not_silent(self, bus):
        transcript = MissionRunner(
            ScriptedModel(*[tool_call("catalog.search", q="x")] * 5),
            bus, ["catalog.search"], max_steps=2,
        ).run("go")
        assert isinstance(transcript, MissionTranscript)
        assert transcript.answer is None
        assert transcript.outcome == "budget_exhausted"

    def test_the_step_case_says_steps_and_the_numbers(self, bus):
        """`budget_exhausted` was one word for one budget for as long as
        there was one budget. Now there are two, and the word alone sends an
        operator to lengthen a step cap that may not be what ran out."""
        transcript = MissionRunner(
            ScriptedModel(*[tool_call("catalog.search", q="x")] * 5),
            bus, ["catalog.search"], max_steps=3,
        ).run("go")
        assert transcript.budget is not None
        assert transcript.budget.which == "steps"
        assert (transcript.budget.limit, transcript.budget.spent) == (3, 3)

    def test_a_mission_that_answered_carries_no_budget(self, bus):
        """Present exactly when it ran out. A consumer branches on the
        outcome and indexes the field, so a stray one on an answered run is
        a consumer telling somebody a good answer hit a limit."""
        transcript = MissionRunner(
            ScriptedModel('{"answer": "done"}'), bus, ["catalog.search"],
        ).run("go")
        assert transcript.budget is None and transcript.reason == ""


# ---------------------------------------------------------------------------
# The wall clock, and the switch somebody outside can throw
# ---------------------------------------------------------------------------


class _R:
    """What a fake bus hands back — the three fields the loop reads."""

    exit_code, stdout, stderr, evidence = 0, "it worked", "", "it worked"


class _Clock:
    """A monotonic that moves only when a test, or a fake model, says so."""

    def __init__(self, start=1_000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class SlowModel(ScriptedModel):
    """A :class:`ScriptedModel` whose every reply costs *seconds* of clock.

    The endpoint is what spends a mission's wall clock — minutes of it, on
    a 20B at 59 tok/s — so the fake that stands in for one has to be what
    spends the fake clock.  Nothing here sleeps: a test that spent its own
    budget to prove a budget is spent would be slow and flaky, and what is
    being asserted is the comparison.
    """

    def __init__(self, clock, seconds, *replies):
        super().__init__(*replies)
        self._clock = clock
        self._seconds = float(seconds)

    def __call__(self, messages):
        self._clock.advance(self._seconds)
        return super().__call__(messages)


class TestTheWallClock:
    def _runner(self, bus, clock, seconds, per_call, *replies, **kwargs):
        from core.budgets import Deadline

        return MissionRunner(
            SlowModel(clock, per_call, *replies), bus, ["catalog.search"],
            deadline=Deadline(seconds, monotonic=clock), **kwargs,
        )

    def test_a_mission_stops_when_its_seconds_run_out(self, bus):
        """Steps bound the work; seconds bound the waiting. A model that
        answers slowly enough burns a budget the step cap never notices."""
        clock = _Clock()
        transcript = self._runner(
            bus, clock, 5.0, 3.0,
            *[tool_call("catalog.search", q="x")] * 20,
            max_steps=20,
        ).run("go")

        assert transcript.outcome == "budget_exhausted"
        assert transcript.budget.which == "seconds"
        assert transcript.budget.limit == 5.0
        assert transcript.budget.spent == 6.0
        # And it was NOT the step cap: two of a stated twenty.
        assert len(transcript.steps) == 2

    def test_the_last_record_says_which_budget_and_by_how_much(self, bus):
        clock = _Clock()
        seen = []
        self._runner(
            bus, clock, 5.0, 3.0,
            *[tool_call("catalog.search", q="x")] * 20,
            max_steps=20, observer=seen.append,
        ).run("go")

        finished = seen[-1]
        assert finished["event"] == "mission_finished"
        assert finished["outcome"] == "budget_exhausted"
        assert finished["budget"] == {"which": "seconds", "limit": 5.0,
                                      "spent": 6.0}

    def test_an_answered_run_carries_no_budget_field(self, bus):
        clock = _Clock()
        seen = []
        self._runner(bus, clock, 60.0, 1.0, '{"answer": "done"}',
                     observer=seen.append).run("go")
        assert seen[-1]["outcome"] == "answered"
        assert "budget" not in seen[-1]

    def test_every_finished_record_says_how_long_the_run_took(self, bus, monkeypatch):
        """`elapsed_s` rides `mission_finished` on every outcome, on the
        harness's own monotonic clock — and OUTSIDE `usage`, whose absence
        is a statement about the provider that elapsed time must not
        disturb."""
        import itertools
        import core.runtime.mission as mission_module
        ticks = itertools.count(100.0, 2.5)          # 100.0, 102.5, 105.0 …
        monkeypatch.setattr(mission_module.time, "monotonic", lambda: next(ticks))
        seen = []
        MissionRunner(ScriptedModel('{"answer": "done"}'), bus,
                      ["catalog.search"], observer=seen.append).run("go")
        finished = seen[-1]
        assert finished["event"] == "mission_finished"
        assert finished["elapsed_s"] == 2.5
        assert "usage" not in finished          # nothing reported → absent
        assert "elapsed_s" in seen[-1] and finished["outcome"] == "answered"

    def test_no_deadline_is_the_loop_as_it_ran_before(self, bus):
        """Unbounded is the default, and unbounded means the clock is not
        consulted at all — including by a fake bus that would choke on a
        keyword it never declared."""
        clock = _Clock()
        transcript = MissionRunner(
            SlowModel(clock, 10_000, *[tool_call("catalog.search", q="x")] * 4),
            bus, ["catalog.search"], max_steps=3,
        ).run("go")
        assert transcript.outcome == "budget_exhausted"
        assert transcript.budget.which == "steps"

    def test_the_clock_is_checked_between_steps_too(self, bus):
        """Not only before a dispatch. Every path that continues — a parse
        error, a refused tool, a grounding repair — comes back through the
        top of the loop, which is the point that stops a run from spending
        a repair turn past its deadline."""
        clock = _Clock()
        transcript = self._runner(
            bus, clock, 5.0, 6.0, "not json at all", "also not json",
            max_steps=6,
        ).run("go")

        assert transcript.outcome == "budget_exhausted"
        assert transcript.budget.which == "seconds"
        # One rejected reply, and the second was never asked for.
        assert len(transcript.steps) == 1

    def test_the_clock_is_checked_before_the_tool_the_model_named(self, bus):
        """The check that costs a dispatch. The model's reply is what spends
        the clock, so a run can be over by the time it says which tool it
        wants — and `tool_call` is emitted BEFORE the call, so a watcher told
        one was coming must not then be told the mission ended without it."""
        clock = _Clock()
        seen = []
        transcript = self._runner(
            bus, clock, 5.0, 6.0, tool_call("catalog.search", q="x"),
            observer=seen.append,
        ).run("go")

        assert transcript.outcome == "budget_exhausted"
        assert [r["event"] for r in seen if r["event"] == "tool_call"] == []
        # Recorded as a step all the same, saying what it was and that it
        # never ran: a proposal with no result beside it reads like a tool
        # that failed silently.
        assert len(transcript.steps) == 1
        assert transcript.steps[0].tool == "catalog.search"
        assert "NOT called" in transcript.steps[0].error
        assert "seconds budget" in transcript.steps[0].error


class TestTheToolCeiling:
    """The remaining clock rides down as a ceiling on the tool call.

    It is a *named parameter of the bus* and not a keyword forwarded to the
    tool, because everything the bus does not name goes to the executor —
    which for an MCP tool is a remote server. A mission that "just passed a
    timeout down" would be inventing an argument for somebody else's schema.
    """

    class _TakesOne:
        sandbox_name = "none"

        def __init__(self):
            self.seen = []

        def describe_tool(self, name):
            return {"description": f"does {name}"}

        def dispatch(self, name, deadline_s=None, **kwargs):
            self.seen.append(deadline_s)
            return _R()

        def register_tool(self, name, tool):
            return name

        def unregister(self, name):
            return None

    class _TakesNone:
        sandbox_name = "none"

        def __init__(self):
            self.seen = []

        def describe_tool(self, name):
            return {"description": f"does {name}"}

        def dispatch(self, name, **kwargs):
            self.seen.append(dict(kwargs))
            return _R()

        def register_tool(self, name, tool):
            return name

        def unregister(self, name):
            return None

    def _run(self, fake, deadline):
        return MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="x"),
                          '{"answer": "done"}'),
            fake, ["catalog.search"], deadline=deadline, store_tool="",
        ).run("go")

    def test_a_bus_that_takes_a_ceiling_is_handed_the_time_left(self):
        from core.budgets import Deadline

        clock = _Clock()
        fake = self._TakesOne()
        self._run(fake, Deadline(30.0, monotonic=clock))
        assert fake.seen == [30.0]

    def test_the_real_bus_takes_one(self, bus):
        """Asserted against the shipped `ToolBus`, not only a stub: the
        probe is a signature check, and a rename there would silently turn
        the ceiling off everywhere."""
        from core.runtime.mission import _takes_deadline

        assert _takes_deadline(bus) is True

    def test_a_bus_that_takes_none_is_handed_none(self):
        """A caller's fake bus must never meet a keyword it did not declare
        just because somebody set a deadline."""
        from core.budgets import Deadline

        fake = self._TakesNone()
        self._run(fake, Deadline(30.0, monotonic=_Clock()))
        assert fake.seen == [{"q": "x"}]

    def test_no_deadline_passes_nothing_at_all(self):
        fake = self._TakesOne()
        self._run(fake, None)
        assert fake.seen == [None]


class TestTheSwitchSomebodyOutsideCanThrow:
    def test_a_cancelled_run_ends_incomplete_saying_why(self, bus):
        """Not a sixth outcome word. A cancelled run stopped without an
        answer, which is what `incomplete` has always meant; what it was
        missing is the reason."""
        from core.budgets import Cancellation

        switch = Cancellation()
        seen = []

        class _CancelsAfterOne(ScriptedModel):
            def __call__(self, messages):
                reply = super().__call__(messages)
                if len(self.seen) >= 1:
                    switch.cancel()
                return reply

        transcript = MissionRunner(
            _CancelsAfterOne(*[tool_call("catalog.search", q="x")] * 6),
            bus, ["catalog.search"], max_steps=6,
            cancel=switch, observer=seen.append,
        ).run("go")

        assert transcript.outcome == "incomplete"
        assert transcript.reason == "cancelled"
        assert transcript.budget is None
        # It ENDED, it was not killed: the transcript kept the step that ran
        # and the stream got the record that says the run is over.
        assert len(transcript.steps) == 1
        assert seen[-1]["event"] == "mission_finished"
        assert seen[-1]["reason"] == "cancelled"
        assert "budget" not in seen[-1]

    def test_a_switch_thrown_before_the_first_step_still_finishes(self, bus):
        """The opening record is owed a closing one whatever happens in
        between — including nothing."""
        from core.budgets import Cancellation

        switch = Cancellation()
        switch.cancel()
        seen = []
        transcript = MissionRunner(
            ScriptedModel('{"answer": "never asked"}'), bus,
            ["catalog.search"], cancel=switch, observer=seen.append,
        ).run("go")

        assert transcript.outcome == "incomplete"
        assert transcript.reason == "cancelled"
        assert [r["event"] for r in seen] == ["mission_started",
                                              "mission_finished"]

    def test_the_switch_stops_a_tool_the_model_had_already_named(self, bus):
        """Cancelled while the endpoint was answering. Nothing new starts."""
        from core.budgets import Cancellation

        switch = Cancellation()
        calls = []
        real_dispatch = bus.dispatch

        def watched(name, **kwargs):
            calls.append(name)
            return real_dispatch(name, **kwargs)

        bus.dispatch = watched

        class _CancelsAtOnce(ScriptedModel):
            def __call__(self, messages):
                reply = super().__call__(messages)
                switch.cancel()
                return reply

        transcript = MissionRunner(
            _CancelsAtOnce(tool_call("catalog.search", q="x")),
            bus, ["catalog.search"], cancel=switch,
        ).run("go")

        assert calls == []
        assert transcript.reason == "cancelled"
        assert "was cancelled" in transcript.steps[0].error

    def test_a_cancellation_outranks_a_clock_that_also_ran_out(self, bus):
        """Both true at the same check. The person who threw the switch is
        the one who will read the sentence, and "somebody stopped this" is
        the truer thing to show them."""
        from core.budgets import Cancellation, Deadline

        clock = _Clock()
        switch = Cancellation()
        switch.cancel()
        deadline = Deadline(1.0, monotonic=clock).start()
        clock.advance(60)

        transcript = MissionRunner(
            ScriptedModel('{"answer": "x"}'), bus, ["catalog.search"],
            deadline=deadline, cancel=switch,
        ).run("go")
        assert (transcript.outcome, transcript.reason) == ("incomplete",
                                                           "cancelled")

    def test_an_answer_already_produced_is_kept(self, bus):
        """The switch stops what has not happened yet; it does not delete
        what has. A model that finished its answer in the same round trip
        somebody threw the switch in did the work, and discarding a real
        answer to report a stop would lose the thing the turn was for."""
        from core.budgets import Cancellation

        switch = Cancellation()

        class _CancelsAtOnce(ScriptedModel):
            def __call__(self, messages):
                reply = super().__call__(messages)
                switch.cancel()
                return reply

        transcript = MissionRunner(
            _CancelsAtOnce('{"answer": "it is 42"}'), bus,
            ["catalog.search"], cancel=switch,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.answer == "it is 42"

    def test_a_bare_threading_event_works_too(self, bus):
        """Duck-typed on `is_set()`: a caller already holding an Event
        should not have to wrap it."""
        import threading

        event = threading.Event()
        event.set()
        transcript = MissionRunner(
            ScriptedModel('{"answer": "never asked"}'), bus,
            ["catalog.search"], cancel=event,
        ).run("go")
        assert transcript.reason == "cancelled"


# ---------------------------------------------------------------------------
# Argument schemas in the catalogue
# ---------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "type": {"type": "string", "enum": ["dataset", "model", "service"]},
        "limit": {"type": "integer"},
        "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["q"],
}


@pytest.fixture
def typed_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(
            tool_name="catalog.search",
            description="Search the catalogue by facet.",
            input_schema=SEARCH_SCHEMA,
        ),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    return b


class TestTheCatalogueCarriesTypes:
    def test_types_and_required_reach_the_prompt(self, typed_bus):
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "q (string, required)" in system
        assert "limit (integer)" in system

    def test_an_enum_is_spelled_out(self, typed_bus):
        """Naming the facet values is the difference between a first
        call that works and three refused ones discovering that `type`
        is not free text."""
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "type (string: dataset|model|service)" in system

    def test_an_optional_argument_still_shows_its_type(self, typed_bus):
        system = MissionRunner(
            ScriptedModel(), typed_bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "owner (string)" in system

    def test_a_tool_without_a_schema_renders_as_before(self, bus):
        system = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"],
        ).seed("x")[0]["content"]
        assert "- catalog.search: Search the catalogue." in system
        assert "arguments:" not in system


# ---------------------------------------------------------------------------
# Bounded results, and the store that keeps the rest
# ---------------------------------------------------------------------------

@pytest.fixture
def big_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="runs.get", description="Read a run view."),
        lambda **_kw: (
            0,
            "HEAD" + ("x" * 5_000) + "TAIL",
            "",
            json.dumps({"run_id": "run.5f21", "totals": {"records": 12481}}),
        ),
    )
    return b


class TestBoundedToolOutput:
    def test_a_large_result_does_not_enter_the_transcript_whole(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert len(shown) < 1_500

    def test_the_cut_is_marked_and_not_silent(self, big_bus):
        """A silently truncated result is worse than an oversized one:
        nothing tells the model a figure was cut off, so the persona rule
        against restating from memory has nothing to bite on."""
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert "truncated" in shown
        assert "must not be guessed at" in shown

    def test_head_and_tail_both_survive(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        shown = model.seen[-1][-1]["content"]
        assert "HEAD" in shown and "TAIL" in shown

    def test_the_marker_names_the_handle_to_read_the_rest_from(self, big_bus):
        model = ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}')
        MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert 'mission_result(handle="r1"' in model.seen[-1][-1]["content"]

    def test_the_step_records_that_it_was_truncated(self, big_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert transcript.steps[0].truncated is True
        assert transcript.steps[0].handle == "r1"

    def test_the_transcript_keeps_the_untruncated_output(self, big_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert len(transcript.steps[0].output) > 5_000

    def test_a_small_result_is_untouched(self, bus):
        model = ScriptedModel(tool_call("catalog.search", q="taiwan"),
                              '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"]).run("go")
        assert transcript.steps[0].truncated is False
        assert "truncated" not in model.seen[-1][-1]["content"]


class TestTheResultStore:
    def test_the_full_result_is_reachable_by_handle(self, big_bus):
        runner = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"], max_result_bytes=500,
        )
        runner.run("go")
        assert len(runner.store.get("r1").text) > 5_000

    def test_the_structured_payload_survives_the_bus(self, big_bus):
        """`as_tuple()` drops it whenever there is text; the bridge and
        the bus carry it in the fourth element so the store keeps it."""
        runner = MissionRunner(
            ScriptedModel(tool_call("runs.get"), '{"answer": "ok"}'),
            big_bus, ["runs.get"],
        )
        runner.run("go")
        assert runner.store.get("r1").structured["totals"]["records"] == 12481

    def test_the_model_can_fetch_one_field(self, big_bus):
        model = ScriptedModel(
            tool_call("runs.get"),
            tool_call(RESULT_TOOL, handle="r1", path="totals.records"),
            '{"answer": "12481"}',
        )
        transcript = MissionRunner(
            model, big_bus, ["runs.get"], max_result_bytes=500,
        ).run("go")
        assert transcript.steps[1].output == "12481"

    def test_the_store_tool_is_in_the_catalogue(self, bus):
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        assert RESULT_TOOL in runner.offered

    def test_the_model_is_told_about_it_during_the_run(self, bus):
        """It is registered inside `run()`, so a catalogue rendered
        before then would silently omit the one tool the truncation
        marker tells the model to call."""
        model = ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"]).run("go")
        system = model.seen[0][0]["content"]
        assert f"- {RESULT_TOOL}:" in system
        assert "handle (string)" in system

    def test_it_is_withdrawn_when_the_mission_ends(self, bus):
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
        ).run("go")
        assert RESULT_TOOL not in bus.list_tools()

    def test_it_is_withdrawn_even_when_the_loop_raises(self, bus):
        def explode(_messages):
            raise RuntimeError("backend fell over")

        with pytest.raises(RuntimeError):
            MissionRunner(explode, bus, ["catalog.search"]).run("go")
        assert RESULT_TOOL not in bus.list_tools()

    def test_a_second_run_does_not_see_the_first_ones_results(self, bus):
        runner = MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"), '{"answer": "ok"}',
                          tool_call("catalog.search", q="b"), '{"answer": "ok"}'),
            bus, ["catalog.search"],
        )
        runner.run("first")
        runner.run("second")
        assert len(runner.store) == 1
        assert runner.store.get("r1").arguments == {"q": "b"}

    def test_a_mission_can_run_without_one(self, bus):
        runner = MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="",
        )
        assert runner.offered == ["catalog.search"]
        assert runner.run("go").completed


# ---------------------------------------------------------------------------
# Grounding: an answer is checked against this run's own tool output
# ---------------------------------------------------------------------------

ID_PATTERN = r"\b(?:asset|labels|run)\.[0-9a-f]{4,}\b"


@pytest.fixture
def asset_bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search."),
        lambda **_kw: (0, "asset.5f21c9 — Taiwan narrative corpus", ""),
    )
    return b


@pytest.fixture
def strict():
    return GroundingValidator.from_config(
        GroundingConfig(identifier_pattern=ID_PATTERN)
    )


class TestGroundingTheAnswer:
    def test_a_cited_answer_is_answered(self, asset_bus, strict):
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "The corpus is asset.5f21c9."}'),
            asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.grounded

    def test_an_invented_identifier_gets_a_repair_turn(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "The label set is labels.7a19c4e2."}',
            '{"answer": "The corpus is asset.5f21c9; no label set was found."}',
        )
        transcript = MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered"
        assert "labels.7a19c4e2" not in transcript.answer

    def test_the_repair_turn_names_the_token(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.7a19c4e2 is the set."}',
            '{"answer": "asset.5f21c9 only."}',
        )
        MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        turns = [m["content"] for m in model.seen[-1] if m["role"] == "user"]
        assert any("labels.7a19c4e2" in t for t in turns)

    def test_a_second_failure_is_caveated_not_suppressed(self, asset_bus, strict):
        """THE test. The answer survives — deleting it hides a finding —
        and says of itself what no tool established."""
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.7a19c4e2 is the set."}',
            '{"answer": "It is definitely labels.7a19c4e2."}',
        )
        transcript = MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"
        assert transcript.completed
        assert "Ungrounded" in transcript.answer
        assert "labels.7a19c4e2" in transcript.answer

    def test_only_one_repair_turn_is_spent(self, asset_bus, strict):
        model = ScriptedModel(
            tool_call("catalog.search"),
            '{"answer": "labels.aaaaaa"}',
            '{"answer": "labels.bbbbbb"}',
            '{"answer": "labels.cccccc"}',
        )
        MissionRunner(
            model, asset_bus, ["catalog.search"], validator=strict,
        ).run("go")
        assert len(model.replies) == 1  # the third answer was never asked for

    def test_zero_repairs_goes_straight_to_the_caveat(self, asset_bus):
        validator = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=ID_PATTERN, max_repairs=0)
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"], validator=validator,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"

    def test_an_id_from_a_refused_call_is_not_grounded(self, strict):
        """A tool that refused established nothing, whatever its error
        message happened to contain."""
        refusing = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        )
        refusing.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **_kw: (1, "", "not found: asset.5f21c9"),
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "asset.5f21c9"}',
                          '{"answer": "asset.5f21c9"}'),
            refusing, ["catalog.search"], validator=strict,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"

    def test_no_validator_leaves_the_loop_exactly_as_it_was(self, asset_bus):
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"],
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding is None

    def test_a_validator_that_could_not_run_does_not_claim_a_pass(self, asset_bus):
        """No grammar means no opinion. It must never read as grounded."""
        from core.runtime.grounding import IdentifierGroundingCheck

        blind = GroundingValidator([IdentifierGroundingCheck(GroundingConfig())])
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "labels.7a19c4e2"}'),
            asset_bus, ["catalog.search"], validator=blind,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.ran is False
        assert transcript.grounding.grounded is False


# ---------------------------------------------------------------------------
# A skill manifest drives the whole thing
# ---------------------------------------------------------------------------

SKILL = """\
---
name: recon
skill:
  skill_id: recon
  allowed_tools:
    - search
    - get
  policy:
    - Never invent an asset id.
  output_format: A table, then a paragraph.
  grounding:
    identifier_pattern: '\\b(?:asset|labels)\\.[0-9a-f]{4,}\\b'
---

# Recon

Start broad, then narrow by facet.
"""


class TestDrivenByAManifest:
    @pytest.fixture
    def manifest(self, tmp_path):
        path = tmp_path / "SKILL.md"
        path.write_text(SKILL, encoding="utf-8")
        return SkillManifest.from_file(path)

    @pytest.fixture
    def server_bus(self):
        b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.search", "mcp.get", "mcp.delete_everything"):
            b.register(
                ToolDescriptor(tool_name=name, description=f"The {name} tool."),
                lambda **_kw: (0, "asset.5f21c9", ""),
            )
        return b

    def test_the_closed_set_narrows_what_is_offered(self, manifest, server_bus):
        names = manifest.resolve(server_bus.list_tools())
        runner = MissionRunner(ScriptedModel(), server_bus, names)
        system = runner.seed("x")[0]["content"]
        assert "mcp.search" in system
        assert "mcp.delete_everything" not in system

    def test_a_tool_outside_the_set_is_refused_even_though_the_bus_has_it(
        self, manifest, server_bus,
    ):
        names = manifest.resolve(server_bus.list_tools())
        transcript = MissionRunner(
            ScriptedModel(tool_call("mcp.delete_everything"), '{"answer": "no"}'),
            server_bus, names,
        ).run("go")
        assert "no tool named 'mcp.delete_everything'" in transcript.steps[0].error

    def test_the_skills_operational_knowledge_reaches_the_model(
        self, manifest, server_bus,
    ):
        names = manifest.resolve(server_bus.list_tools())
        runner = MissionRunner(
            ScriptedModel(), server_bus, names,
            system_message="You are Tai.\n\n" + manifest.prompt,
        )
        system = runner.seed("x")[0]["content"]
        assert system.startswith("You are Tai.")
        assert "Never invent an asset id." in system
        assert "Start broad, then narrow by facet." in system
        assert "A table, then a paragraph." in system

    def test_the_manifests_grammar_is_what_enforces_grounding(
        self, manifest, server_bus,
    ):
        """The pattern is content, from the file. The checking is the
        harness's. Neither works without the other."""
        validator = GroundingValidator.from_config(
            GroundingConfig.from_mapping(manifest.grounding)
        )
        transcript = MissionRunner(
            ScriptedModel(tool_call("mcp.search"),
                          '{"answer": "labels.deadbeef"}',
                          '{"answer": "labels.deadbeef"}'),
            server_bus, manifest.resolve(server_bus.list_tools()),
            validator=validator,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"


class TestAnUnchangedResultIsNotPastedTwice:
    """The Qwen3-30B context death, as a harness behaviour.

    Recorded 10 August 2026: three `runs_get` calls on the same `run_id` at
    turns 1, 2 and 4, three copies of one 33,000-character view in a history
    nothing trims, and a context overflow at turn 5 that was not about
    context. `mission_result` was offered in the truncation marker of every
    one of those turns and never called.

    The call is still made — this platform is submit-and-poll and a repeated
    `compute_job_status` is a mission working correctly. What is collapsed is
    the paste, and only when the bytes are identical.
    """

    @pytest.fixture
    def polling_bus(self):
        """A tool whose answer changes, and one whose answer does not."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(
            ToolDescriptor(tool_name="runs.get", description="One run, whole."),
            lambda **kw: (0, "X" * 5_000, ""),
        )
        polls = {"n": 0}

        def status(**kw):
            polls["n"] += 1
            return 0, f"status poll {polls['n']}", ""

        b.register(
            ToolDescriptor(tool_name="compute.status", description="Job state."),
            status,
        )
        return b

    def shown(self, model):
        """Every tool-result message the model was handed."""
        return [m["content"] for m in model.seen[-1]
                if m["role"] == "user" and m["content"].startswith("Result of")]

    def test_the_second_identical_fetch_is_one_line(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        first, second = self.shown(model)[:2]
        assert len(first) > 4_000
        assert len(second) < 400, (
            f"the unchanged re-fetch was pasted again in full: {len(second)} "
            f"chars")

    def test_it_names_the_handle_and_the_call_that_reads_it(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        second = self.shown(model)[1]
        assert "r1" in second
        assert f'{RESULT_TOOL}(handle="r1"' in second, (
            "a notice that does not spell out the call is a notice the model "
            "has to guess its way past")

    def test_the_call_is_still_dispatched_and_still_recorded(self, polling_bus):
        """Not a refusal. The audit log and the evidence must not lose it."""
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a1"),
            '{"answer": "done"}',
        )
        runner = MissionRunner(model, polling_bus, ["runs.get"], max_steps=5)
        transcript = runner.run("go")
        calls = [s for s in transcript.steps if s.tool == "runs.get"]
        assert len(calls) == 2
        assert [s.exit_code for s in calls] == [0, 0]
        assert len(runner.store) == 2, "the repeat was not recorded"

    def test_a_poll_that_changed_is_shown_in_full(self, polling_bus):
        """The behaviour a blanket repeat-refusal would have broken."""
        model = ScriptedModel(
            tool_call("compute.status", job="j1"),
            tool_call("compute.status", job="j1"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["compute.status"],
                      max_steps=5).run("go")
        first, second = self.shown(model)[:2]
        assert "status poll 1" in first
        assert "status poll 2" in second, (
            "a poll whose answer changed was collapsed as a duplicate")
        assert "identical" not in second

    def test_a_different_argument_is_not_a_duplicate(self, polling_bus):
        model = ScriptedModel(
            tool_call("runs.get", run_id="a1"),
            tool_call("runs.get", run_id="a2"),
            '{"answer": "done"}',
        )
        MissionRunner(model, polling_bus, ["runs.get"], max_steps=5).run("go")
        second = self.shown(model)[1]
        assert "identical" not in second, (
            "runs.get(a2) returned the same bytes as runs.get(a1) only "
            "because this stub ignores its arguments; the check must compare "
            "the call as well")


class TestTheRefusalNamesTheNearMiss:
    """Three spellings of one tool in one prompt, and the turns they cost.

    Measured 10 August 2026. `mcp.catalog_search_assets` is the dispatch
    name; the catalogue prose says `catalog.search_assets`; the skill prose
    says bare `catalog_search_assets`. A mission emitted the bare form, burnt
    a turn on `reply_rejected`, then burnt a second on a repair that guessed
    wrong — because the refusal listed the whole catalogue and never said
    which entry the model had nearly typed.

    The set is derived from the bus at runtime, so a tool TAIPAN adds is
    matchable here without a judais-lobi release.
    """

    @pytest.fixture
    def namespaced_bus(self):
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.catalog_search_assets", "mcp.catalog_get_asset",
                     "mcp.runs_list"):
            b.register(ToolDescriptor(tool_name=name, description="A tool."),
                       lambda **kw: (0, "ok", ""))
        return b

    def refusal_for(self, bus, spelling):
        model = ScriptedModel(tool_call(spelling), '{"answer": "done"}')
        offered = ["mcp.catalog_search_assets", "mcp.catalog_get_asset",
                   "mcp.runs_list"]
        transcript = MissionRunner(model, bus, offered, max_steps=4).run("go")
        return transcript.steps[0].error

    @pytest.mark.parametrize("spelling", [
        "catalog_search_assets",            # the skill prose spelling
        "catalog.search_assets",            # the catalogue prose spelling
        "CATALOG_SEARCH_ASSETS",            # case
    ])
    def test_every_recorded_spelling_gets_the_dispatch_name(
            self, namespaced_bus, spelling):
        refusal = self.refusal_for(namespaced_bus, spelling)
        assert "mcp.catalog_search_assets" in refusal
        assert "almost certainly mean" in refusal, (
            f"{spelling!r} was refused with a bare catalogue dump; that is "
            f"the refusal that cost two turns on 10 August")

    def test_the_catalogue_still_follows_it(self, namespaced_bus):
        """A model that meant a different tool must still see the set."""
        refusal = self.refusal_for(namespaced_bus, "catalog_search_assets")
        assert "mcp.runs_list" in refusal

    def test_a_genuinely_unknown_tool_gets_no_suggestion(self, namespaced_bus):
        """A confident wrong suggestion is worse than none."""
        refusal = self.refusal_for(namespaced_bus, "run_inspection")
        assert "almost certainly mean" not in refusal
        assert "Choose one of" in refusal

    def test_an_ambiguous_name_proposes_neither(self):
        """Two tools normalising the same way is a coin flip the model
        cannot see it is taking."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        for name in ("mcp.runs_list", "local.runs_list"):
            b.register(ToolDescriptor(tool_name=name, description="A tool."),
                       lambda **kw: (0, "ok", ""))
        model = ScriptedModel(tool_call("runs_list"), '{"answer": "done"}')
        transcript = MissionRunner(
            model, b, ["mcp.runs_list", "local.runs_list"],
            max_steps=4).run("go")
        assert "almost certainly mean" not in transcript.steps[0].error


# ---------------------------------------------------------------------------
# The conversation is bounded against the model's real context window
# ---------------------------------------------------------------------------


@pytest.fixture
def paged_bus():
    """One tool that returns a fresh, sizeable page every time.

    Fresh on purpose: a byte-identical re-fetch is collapsed to one line by
    the store (see `TestAnUnchangedResultIsNotPastedTwice`), and a mission
    whose every result is the same never grows the conversation these tests
    are about.
    """
    b = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    pages = {"n": 0}

    def page(**_kw):
        pages["n"] += 1
        return (0, f"page {pages['n']} — asset.{pages['n']:06x} "
                   + "z" * 800, "")

    b.register(ToolDescriptor(tool_name="catalog.page",
                              description="One page of the catalogue."), page)
    return b


def _paging_model(rounds, answer='{"answer": "ok"}'):
    return ScriptedModel(*([tool_call("catalog.page")] * rounds), answer)


def _small_window(**kwargs):
    """A window a handful of 800-byte results does not fit inside."""
    return MissionWindow(
        config=ContextConfig(max_context_tokens=1200, max_output_tokens=200),
        **kwargs,
    )


class TestTheConversationIsBounded:
    """A mission's message list grew across every step of the budget and was
    handed to the backend whole. Each result is bounded and no single one is
    large; the sum is, and against a served model with a real
    ``max_model_len`` the end of it is a 400 or a silent eviction — the
    second being the dangerous one, because the model then answers from a
    conversation it can no longer fully see and the answer does not say so.
    """

    def test_every_request_stays_inside_the_window(self, paged_bus):
        window = _small_window()
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=window).run("go")
        assert max(window.estimate(sent) for sent in model.seen) \
            <= window.limit_tokens

    def test_without_a_window_it_still_grows_past_the_same_limit(
            self, paged_bus):
        """The behaviour the parameter changes, stated as the thing it was.

        ``None`` is not a smaller bound — it is no bound, which is what the
        loop did before and what a caller passing nothing still gets."""
        window = _small_window()
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"],
                      max_steps=8).run("go")
        assert max(window.estimate(sent) for sent in model.seen) \
            > window.limit_tokens

    def test_the_catalogue_survives(self, paged_bus):
        """An agent that has forgotten which tools exist is a worse failure
        than the one being fixed."""
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=_small_window()).run("go")
        system = model.seen[-1][0]
        assert system["role"] == "system"
        assert "catalog.page: One page of the catalogue." in system["content"]

    def test_the_seeded_history_and_the_objective_survive(self, paged_bus):
        """The analyst's prior turns are the conversation being continued,
        and the objective is the question. Neither is compactable."""
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      history=HISTORY, window=_small_window()).run("go")
        sent = model.seen[-1]
        assert sent[1:3] == HISTORY
        assert sent[3] == {"role": "user", "content": "go"}

    def test_the_newest_result_survives(self, paged_bus):
        """It is what the next reply is made out of."""
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=_small_window()).run("go")
        assert "page 6" in model.seen[-1][-1]["content"]

    def test_the_oldest_round_trips_are_the_ones_that_go(self, paged_bus):
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=_small_window()).run("go")
        assert "page 1" not in "".join(m["content"] for m in model.seen[-1])

    def test_the_model_is_told_the_conversation_was_shortened(self,
                                                              paged_bus):
        """A silently shortened conversation is worse than a short one: the
        model cannot see anything is missing, so it re-runs a call it already
        made and spends a step of eight rediscovering it."""
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=_small_window()).run("go")
        notice = next(m["content"] for m in model.seen[-1]
                      if "[context]" in m["content"])
        assert "Do not repeat a call" in notice
        assert f'{RESULT_TOOL}(handle=' in notice

    def test_the_notice_lands_after_the_objective_and_never_above_it(
            self, paged_bus):
        """Per-step material below the prefix, always.

        A notice inserted above the objective would move the bytes of
        every request from the step it first appeared on, which is the one
        way to make a byte-stable prefix worth nothing — and it would put
        a sentence about bookkeeping between the persona and the question.
        """
        model = _paging_model(6)
        runner = MissionRunner(model, paged_bus, ["catalog.page"],
                               max_steps=8, history=HISTORY,
                               window=_small_window())
        runner.run("go")
        sent = model.seen[-1]
        pinned = runner.pinned
        assert sent[:pinned] == model.seen[0][:pinned]
        assert sent[pinned - 1] == {"role": "user", "content": "go"}
        assert "[context]" in sent[pinned]["content"]

    def test_the_notice_names_the_tool_results_and_points_at_the_store(
            self, paged_bus):
        """What was dropped, and where it still is.

        The pointer is the store's own index and not a handle range: a
        refused reply is a round trip that stored nothing, so counting
        round trips from outside would slide every later handle by one and
        hand the model a confident, wrong `r5`.
        """
        model = _paging_model(6)
        MissionRunner(model, paged_bus, ["catalog.page"], max_steps=8,
                      window=_small_window()).run("go")
        notice = next(m["content"] for m in model.seen[-1]
                      if "[context]" in m["content"])
        assert "tool result(s)" in notice
        assert f"call {RESULT_TOOL}() with no handle" in notice

    def test_a_mission_that_fits_is_never_compacted(self, bus):
        model = ScriptedModel(tool_call("catalog.search", q="taiwan"),
                              '{"answer": "ok"}')
        events = []
        MissionRunner(model, bus, ["catalog.search"], window=_small_window(),
                      observer=events.append).run("go")
        assert all("compacted" not in e for e in events)
        assert "[context]" not in "".join(m["content"] for m in model.seen[-1])


class TestTheCompactionIsVisible:
    def test_the_step_it_happened_on_says_so(self, paged_bus):
        events = []
        MissionRunner(_paging_model(6), paged_bus, ["catalog.page"],
                      max_steps=8, window=_small_window(),
                      observer=events.append).run("go")
        compacted = [e for e in events
                     if e["event"] == "step_started" and "compacted" in e]
        assert compacted
        first = compacted[0]["compacted"]
        assert first["dropped_turns"] >= 1
        assert first["freed_chars"] > 0
        assert first["tokens_before"] > first["tokens_after"]
        assert first["limit_tokens"] == _small_window().limit_tokens

    def test_the_record_says_how_many_of_them_were_tool_results(
            self, paged_bus):
        """"Eleven turns went" and "eleven governed listings went" are
        different sentences to somebody reading a shortened mission."""
        events = []
        MissionRunner(_paging_model(6), paged_bus, ["catalog.page"],
                      max_steps=8, window=_small_window(),
                      observer=events.append).run("go")
        first = next(e["compacted"] for e in events
                     if e["event"] == "step_started" and "compacted" in e)
        assert first["dropped_results"] >= 1
        assert first["dropped_results"] <= first["dropped_turns"]

    def test_the_record_still_conforms_to_the_contract(self, paged_bus):
        """An optional field is a minor change, and the check a consumer
        runs must still pass over the whole stream."""
        events = []
        MissionRunner(_paging_model(6), paged_bus, ["catalog.page"],
                      max_steps=8, window=_small_window(),
                      observer=events.append).run("go")
        assert [p for e in events for p in conforms(e)] == []
        assert "compacted" in contract.OPTIONAL[contract.STEP_STARTED]

    def test_the_steps_that_dropped_nothing_are_silent(self, paged_bus):
        """Absent, not zero: a consumer reads the field with a default and a
        run that never compacted must look like the run it is."""
        events = []
        MissionRunner(_paging_model(6), paged_bus, ["catalog.page"],
                      max_steps=8, window=_small_window(),
                      observer=events.append).run("go")
        steps = [e for e in events if e["event"] == "step_started"]
        assert "compacted" not in steps[0]


class TestGroundingStillSeesEveryResult:
    """Compaction removes a *paste*, never evidence.

    The validator reads the mission's result store, and the store is
    written on dispatch, so an answer citing a page whose text left the
    conversation is still an answer with a tool result behind it. The
    opposite would be the worst outcome available here: a truthful answer
    refused, a repair turn spent, and a true sentence deleted — which is
    exactly what the three-spellings defect did on 10 August.
    """

    def test_an_identifier_from_a_dropped_result_is_still_grounded(
            self, paged_bus):
        model = ScriptedModel(*([tool_call("catalog.page")] * 6),
                              '{"answer": "The first page is asset.000001."}')
        transcript = MissionRunner(
            model, paged_bus, ["catalog.page"], max_steps=8,
            window=_small_window(),
            validator=GroundingValidator.from_config(
                GroundingConfig(identifier_pattern=ID_PATTERN)),
        ).run("go")
        assert "asset.000001" not in "".join(
            m["content"] for m in model.seen[-1])
        assert transcript.grounding.grounded
        assert transcript.grounding.repairs == 0
        assert transcript.outcome == "answered"

    def test_the_store_keeps_every_result_the_conversation_lost(
            self, paged_bus):
        runner = MissionRunner(
            _paging_model(6), paged_bus, ["catalog.page"], max_steps=8,
            window=_small_window(),
        )
        runner.run("go")
        assert len(runner.store.evidence_texts()) == 6


# ---------------------------------------------------------------------------
# What a mission says about the host it ran on
# ---------------------------------------------------------------------------

LEAK_PATH = "/home/testuser/data/mission.log"
LEAK_TOKEN = "hunter2-hunter2-hunter2"


@pytest.fixture
def leaky_env(monkeypatch):
    """A credential this process holds, so the redactor can name it."""
    monkeypatch.setenv("MISSION_API_KEY", LEAK_TOKEN)
    return "MISSION_API_KEY"


@pytest.fixture
def leaky_bus():
    """A tool that succeeds, cites an identifier, and warns in a leaky way.

    Both halves on one result on purpose: the warning is the free text that
    must be scrubbed and the output is the evidence that must not be, and a
    fixture that separated them could not show that the two are decided
    differently on the same record.
    """
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search."),
        lambda **_kw: (0, "asset.5f21c9 — Taiwan narrative corpus",
                       f"warn: cache {LEAK_PATH} unreadable, key {LEAK_TOKEN}"),
    )
    return b


@pytest.fixture
def raising_bus():
    """A tool that throws.  ``ToolBus.dispatch`` renders the exception into
    ``stderr`` and the loop puts that on ``tool_result.error`` — the shortest
    path there is from an exception to somebody's browser."""
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))

    def explode(**_kw):
        raise RuntimeError(f"cannot open {LEAK_PATH} with key {LEAK_TOKEN}")

    b.register(ToolDescriptor(tool_name="catalog.search", description="Search."),
               explode)
    return b


class TestTheStreamDoesNotNameTheHost:
    """``EXIT_CONTRACT["diagnostic"]`` used to warn a consumer that what this
    harness writes carries absolute paths from this host, and TAIPAN's
    location sweep was deferred on the strength of that sentence.  The
    redactor at ``_emit`` is what makes it false.
    """

    def test_a_tools_error_reaches_the_stream_scrubbed(self, leaky_bus, leaky_env):
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "The corpus is asset.5f21c9."}'),
            leaky_bus, ["catalog.search"], observer=events.append,
        ).run("go")
        error = next(r for r in events if r["event"] == "tool_result")["error"]
        assert "<home>/data/mission.log" in error
        assert f"<redacted:{leaky_env}>" in error

    def test_neither_raw_value_appears_anywhere_on_the_stream(
            self, leaky_bus, leaky_env):
        """Anywhere: the point of scrubbing at the emitter rather than at the
        one field somebody remembered is that there is no second copy."""
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "The corpus is asset.5f21c9."}'),
            leaky_bus, ["catalog.search"], observer=events.append,
        ).run("go")
        whole = json.dumps(events)
        assert LEAK_PATH not in whole
        assert LEAK_TOKEN not in whole

    def test_the_evidence_on_the_stream_is_still_the_evidence(
            self, leaky_bus, leaky_env, strict):
        """``output`` is what the grounding validator checked the answer
        against, out of the store.  A scrubbed stream copy would put a pane
        and the store into disagreement about the bytes a mission was given,
        so the answer's identifier survives on the record a watcher reads.
        """
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"),
                          '{"answer": "The corpus is asset.5f21c9."}'),
            leaky_bus, ["catalog.search"], validator=strict,
            observer=events.append,
        ).run("go")
        assert transcript.outcome == "answered"
        assert transcript.grounding.grounded
        result = next(r for r in events if r["event"] == "tool_result")
        assert result["output"] == "asset.5f21c9 — Taiwan narrative corpus"
        assert "asset.5f21c9" in next(
            r for r in events if r["event"] == "answer")["text"]

    def test_an_exception_rendered_into_a_result_is_scrubbed_too(
            self, raising_bus, leaky_env):
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search"), '{"answer": "gave up"}'),
            raising_bus, ["catalog.search"], observer=events.append,
        ).run("go")
        error = next(r for r in events if r["event"] == "tool_result")["error"]
        assert error.startswith("Tool execution error: RuntimeError:")
        assert "<home>/data/mission.log" in error
        assert LEAK_TOKEN not in error

    def test_an_answer_that_is_really_an_error_is_scrubbed(self, bus, leaky_env):
        """Nothing stops a model putting what it was shown into ``answer``,
        and on the failure path what it was shown is an error."""
        events = []
        MissionRunner(
            ScriptedModel(json.dumps(
                {"answer": f"the run failed: {LEAK_PATH} ({LEAK_TOKEN})"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        text = next(r for r in events if r["event"] == "answer")["text"]
        assert text == (
            f"the run failed: <home>/data/mission.log (<redacted:{leaky_env}>)")

    def test_a_refusal_quoting_the_model_is_scrubbed(self, bus, leaky_env):
        """``reply_rejected`` quotes back the tool name the model wrote, and
        the name a model writes is model prose — a path-shaped one goes
        straight onto the stream on both ``problem`` and ``tool``.  That is
        why ``tool`` is scrubbed as well: on every other event it is a name
        the bus resolved and scrubbing is a no-op, and on this one it was
        never validated at all."""
        events = []
        MissionRunner(
            ScriptedModel(tool_call(LEAK_PATH), '{"answer": "sorry"}'),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        rejected = next(r for r in events if r["event"] == "reply_rejected")
        assert "<home>/data/mission.log" in rejected["problem"]
        assert rejected["tool"] == "<home>/data/mission.log"
        assert LEAK_PATH not in json.dumps(events)

    def test_a_resolved_tool_name_is_unchanged_by_being_scrubbed(self, bus):
        """The other side of that decision: a real catalogue name has no path,
        no host and no credential in it, so a consumer still matches ``tool``
        against ``catalogue``."""
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search"), '{"answer": "done"}'),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert next(r for r in events
                    if r["event"] == "tool_call")["tool"] == "catalog.search"
        assert "catalog.search" in next(
            r for r in events if r["event"] == "mission_started")["catalogue"]

    def test_the_transcript_the_caller_holds_is_not_rewritten(
            self, leaky_bus, leaky_env):
        """Redaction is about what leaves the process, not about what the
        mission knows.  A library caller in the same trust domain as the
        harness still gets the real message off ``MissionStep.error``."""
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"), '{"answer": "done"}'),
            leaky_bus, ["catalog.search"],
        ).run("go")
        assert LEAK_PATH in transcript.steps[0].error


class TestEveryStringOnTheStreamIsClassified:
    """The scrubbed/verbatim split is a decision per field, and a field on
    neither list is scrubbed by nobody — silently, and only until somebody
    puts an exception in it.  Read off a real run rather than off the two
    frozensets, so a field added to an emitter and to neither list fails here.
    """

    #: The one string a record carries that is neither error text nor
    #: evidence: the record type itself, which is the contract's vocabulary.
    ALLOWED = {"event"}

    def _stream(self, leaky_bus, strict):
        """Two runs, because one cannot reach every record: the gate ends the
        mission where it fires, so a run that is gated never answers and a run
        that answers was never gated."""
        events = []
        MissionRunner(
            ScriptedModel("not json",
                          tool_call("catalog.search"),
                          tool_call("nosuchtool"),
                          '{"answer": "asset.5f21c9 is unsupported by 3.14159"}'),
            leaky_bus, ["catalog.search"], validator=strict,
            observer=events.append, max_steps=6,
        ).run("go")
        MissionRunner(
            ScriptedModel(tool_call("catalog.gated")),
            leaky_bus, ["catalog.search", "catalog.gated"],
            gated=["catalog.gated"], observer=events.append, max_steps=6,
        ).run("go")
        return events

    def _unclassified(self, value, key=None):
        if isinstance(value, str):
            if key in redact.SCRUBBED_FIELDS or key in redact.VERBATIM_FIELDS:
                return []
            return [] if key in self.ALLOWED else [key]
        if isinstance(value, dict):
            found = []
            for name, item in value.items():
                if name in redact.VERBATIM_FIELDS:
                    continue
                found += self._unclassified(item, name)
            return found
        if isinstance(value, list):
            found = []
            for item in value:
                found += self._unclassified(item, key)
            return found
        return []

    def test_a_rich_run_carries_no_unclassified_string(self, leaky_bus, strict):
        events = self._stream(leaky_bus, strict)
        kinds = {r["event"] for r in events}
        # The run has to actually reach the interesting records, or this
        # passes by not looking at anything.
        assert {"reply_rejected", "tool_result", "gate_requested",
                "grounding"} <= kinds
        unclassified = sorted(set(sum(
            (self._unclassified(r) for r in events), [])))
        assert unclassified == [], unclassified


class TestTheStreamNamesTheAuditFile:
    """``mission_started.audit_ref`` — where this run's dispatches are recorded.

    Optional on the contract and therefore read with a default, but always
    emitted, and ``None`` when auditing was turned off in as many words. That
    null is the point: a consumer that simply finds no audit file cannot tell
    a harness that failed to open one from a harness that was told not to,
    and only one of those is a decision somebody made.
    """

    def _audited_bus(self, tmp_path):
        from core.policy.audit import AuditLogger

        b = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            audit=AuditLogger(path=tmp_path / "audit.jsonl"),
        )
        b.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **kw: (0, f"hits for {kw.get('q')}", ""))
        return b

    def _started(self, runner_bus, **kw):
        events = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), runner_bus, ["catalog.search"],
            observer=events.append, **kw,
        ).run("go")
        return next(e for e in events if e["event"] == "mission_started")

    def test_it_names_the_file(self, tmp_path):
        started = self._started(self._audited_bus(tmp_path))
        assert started["audit_ref"] == str(tmp_path / "audit.jsonl")

    def test_it_is_null_when_there_is_no_audit(self, bus):
        assert self._started(bus)["audit_ref"] is None

    def test_it_is_always_present(self, bus):
        """Present-and-null rather than absent: an absent field and a field
        saying "no record was kept" are different sentences."""
        assert "audit_ref" in self._started(bus)

    def test_the_record_still_conforms(self, tmp_path):
        assert conforms(self._started(self._audited_bus(tmp_path))) == []

    def test_it_is_declared_optional_on_the_contract(self):
        assert "audit_ref" in contract.OPTIONAL[contract.MISSION_STARTED]

    def test_a_bus_that_never_heard_of_auditing_does_not_stop_the_mission(self):
        """Either runner takes any object with ``dispatch`` and
        ``describe_tool``. A fake bus in somebody's test suite is not obliged
        to know what an audit is, and nothing here is a reason for a mission
        not to start."""
        class Minimal:
            def describe_tool(self, name):
                return {"name": name, "description": "d"}

            def dispatch(self, name, **kw):
                raise AssertionError("not reached")

            def register(self, *a, **kw):
                return None

            def unregister(self, name):
                return None

        assert self._started(Minimal(), store_tool="")["audit_ref"] is None


class TestTheAuditKnowsWhichStepCalled:
    """The bus has no idea what a step is, and must not learn one.

    The mission leaves its index in ``bus.audit_context`` before each
    dispatch and the bus copies it onto the entry — one settable dict
    against a mission-shaped parameter on a module that serves chat turns
    and kernel roles too.
    """

    def _run_two_calls(self, tmp_path):
        from core.policy.audit import AuditLogger

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        b = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            audit=logger,
        )
        b.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **kw: (0, "hits", ""))
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          tool_call("catalog.search", q="b"),
                          '{"answer": "ok"}'),
            b, ["catalog.search"], store_tool="",
        ).run("go")
        return logger

    def test_each_entry_carries_the_step_it_belongs_to(self, tmp_path):
        logger = self._run_two_calls(tmp_path)
        steps = [json.loads(e["detail"])["step"] for e in logger.tail(10)]
        assert steps == [0, 1]

    def test_the_arguments_are_there_too(self, tmp_path):
        logger = self._run_two_calls(tmp_path)
        detail = json.loads(logger.tail(10)[0]["detail"])
        assert '"q": "a"' in detail["arguments"]

    def test_the_step_is_withdrawn_when_the_mission_ends(self, tmp_path):
        """The bus outlives the run. A step left behind would stamp the next
        chat turn with the last mission's index — a column that is wrong
        rather than absent, which is the worse of the two."""
        from core.policy.audit import AuditLogger

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        b = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            audit=logger,
        )
        b.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **kw: (0, "hits", ""))
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          '{"answer": "ok"}'),
            b, ["catalog.search"], store_tool="",
        ).run("go")
        b.dispatch("catalog.search", q="later")
        assert "step" not in json.loads(logger.tail(1)[0]["detail"])

    def test_a_mission_that_raised_still_withdraws_it(self, tmp_path):
        from core.policy.audit import AuditLogger

        def explode(messages):
            raise RuntimeError("the model server went away")

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        b = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            audit=logger,
        )
        b.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **kw: (0, "hits", ""))
        b.audit_context["step"] = 9
        with pytest.raises(RuntimeError):
            MissionRunner(explode, b, ["catalog.search"], store_tool="").run("go")
        assert "step" not in b.audit_context


# ── the durable transcript ───────────────────────────────────────────────────


class TestTheRunIsRecorded:
    """The sink is a client of the log, not a second copy of it.

    A pane holds a mission until the socket carrying it drops; a directory
    holds it afterwards. Both have to hold the same thing, and they do
    because there is one choke point — ``_emit`` — and it writes the record
    down before it hands it out.
    """

    def _store(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def test_the_stream_and_the_log_hold_the_same_records(self, bus, tmp_path):
        store = self._store(tmp_path)
        run_id = store.create().run_id
        seen = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          '{"answer": "found it"}'),
            bus, ["catalog.search"], store_tool="", observer=seen.append,
            run_store=store, run_id=run_id,
        ).run("go")
        assert store.records(run_id) == seen

    def test_every_record_is_numbered_once_and_in_order(self, bus, tmp_path):
        store = self._store(tmp_path)
        run_id = store.create().run_id
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          '{"answer": "found it"}'),
            bus, ["catalog.search"], store_tool="",
            run_store=store, run_id=run_id,
        ).run("go")
        seqs = [e["seq"] for e in store.since(run_id)]
        assert seqs == sorted(set(seqs)) == list(range(1, len(seqs) + 1))

    def test_the_opening_frame_names_the_run(self, bus, tmp_path):
        store = self._store(tmp_path)
        run_id = store.create().run_id
        seen = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", observer=seen.append,
            run_store=store, run_id=run_id,
        ).run("go")
        opening = seen[0]
        assert opening["run_id"] == run_id
        assert conforms(opening) == []

    def test_a_loop_with_no_store_says_nothing_about_a_run(self, bus):
        """Absent, not null: a consumer must be able to tell "no transcript"
        from "a transcript whose id I was not told"."""
        seen = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", observer=seen.append,
        ).run("go")
        assert "run_id" not in seen[0]

    def test_it_records_with_nobody_watching(self, bus, tmp_path):
        """The disk is a watcher. A mission spawned with no ``--events`` sink
        still has to leave a transcript behind."""
        store = self._store(tmp_path)
        run_id = store.create().run_id
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", run_store=store, run_id=run_id,
        ).run("go")
        assert [r["event"] for r in store.records(run_id)] == \
            ["mission_started", "step_started", "answer", "mission_finished"]

    def test_a_finished_run_says_so_in_its_own_log(self, bus, tmp_path):
        """``mission_finished`` in the log is the record of a run that closed.
        A later lane reads its absence as an orphan; this is the half that
        makes the reading true."""
        store = self._store(tmp_path)
        run_id = store.create().run_id
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", run_store=store, run_id=run_id,
        ).run("go")
        assert store.records(run_id)[-1]["event"] == "mission_finished"

    def test_a_mission_that_raised_still_closed_its_log(self, bus, tmp_path):
        """For the reason the record is emitted from a ``finally``: a log that
        simply stops is indistinguishable from a mission still thinking."""
        store = self._store(tmp_path)
        run_id = store.create().run_id

        def explode(messages):
            raise RuntimeError("the model server went away")

        with pytest.raises(RuntimeError):
            MissionRunner(explode, bus, ["catalog.search"], store_tool="",
                          run_store=store, run_id=run_id).run("go")
        assert store.records(run_id)[-1]["event"] == "mission_finished"

    def test_what_is_written_is_the_scrubbed_record(self, bus, tmp_path,
                                                   monkeypatch):
        """The redactor is at the choke point, and the file is downstream of
        it: a credential that must not reach a pane must not reach a disk."""
        monkeypatch.setenv("MCP_TOKEN", "shhh-a-very-secret-token")
        store = self._store(tmp_path)
        run_id = store.create().run_id
        MissionRunner(
            ScriptedModel('{"answer": "the token is shhh-a-very-secret-token"}'),
            bus, ["catalog.search"], store_tool="",
            run_store=store, run_id=run_id,
        ).run("go")
        written = store.log_path(run_id).read_text(encoding="utf-8")
        assert "shhh-a-very-secret-token" not in written

    def test_a_store_that_cannot_write_does_not_fail_the_mission(self, bus,
                                                                 tmp_path):
        """The same promise ``_emit`` makes about an observer. An 11,000-second
        submission lost to a full disk is worse than a hole in a transcript."""
        class Broken:
            def append(self, run_id, record):
                raise OSError("no space left on device")

        transcript = MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", run_store=Broken(), run_id="run_abcd1234",
        ).run("go")
        assert transcript.answer == "ok"

    def test_the_id_is_readable_off_the_runner(self, bus, tmp_path):
        store = self._store(tmp_path)
        run_id = store.create().run_id
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                               run_store=store, run_id=run_id)
        assert runner.run_id == run_id


# ── what the run cost ────────────────────────────────────────────────────────


class Meter:
    """A usage source that hands back one report per model call.

    Shaped like the real side channel: a nullary callable, read once after
    each ``chat_fn`` returns.  ``None`` in the script is a call the
    provider said nothing about, which is the case a zero would silently
    replace.
    """

    def __init__(self, *reports):
        self.reports = list(reports)
        self.reads = 0

    def __call__(self):
        self.reads += 1
        if not self.reports:
            return None
        return self.reports.pop(0)


def usage(prompt, completion, **extra):
    from core.runtime.backends.base import Usage

    return Usage(prompt_tokens=prompt, completion_tokens=completion,
                 total_tokens=prompt + completion, extra=extra)


def _metered(bus, *replies, meter=None, rate=None, max_steps=8):
    """A mission with a usage source, and everything it emitted."""
    events = []
    runner = MissionRunner(
        ScriptedModel(*replies), bus, ["catalog.search"],
        max_steps=max_steps, observer=events.append,
        usage_fn=meter, rate=rate,
    )
    return runner.run("find things"), events


def _of(events, name):
    return [r for r in events if r["event"] == name]


class TestThePerCallUsageRidesTheRecordItPaidFor:
    def test_the_tool_call_carries_the_call_that_chose_the_tool(self, bus):
        _, events = _metered(
            bus, tool_call("catalog.search", q="x"), '{"answer": "done"}',
            meter=Meter(usage(100, 10), usage(200, 20)),
        )
        assert _of(events, "tool_call")[0]["usage"] == {
            "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}

    def test_the_answer_carries_the_call_that_wrote_it(self, bus):
        _, events = _metered(
            bus, tool_call("catalog.search", q="x"), '{"answer": "done"}',
            meter=Meter(usage(100, 10), usage(200, 20)),
        )
        assert _of(events, "answer")[0]["usage"] == {
            "prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}

    def test_a_rejected_reply_is_still_a_billed_reply(self, bus):
        """A ledger that counted only the calls that worked would
        under-report exactly the runs that went badly."""
        _, events = _metered(
            bus, "not json at all", '{"answer": "done"}',
            meter=Meter(usage(50, 5), usage(60, 6)),
        )
        assert _of(events, "reply_rejected")[0]["usage"]["prompt_tokens"] == 50

    def test_a_provider_extra_reaches_the_stream_verbatim(self, bus):
        _, events = _metered(
            bus, '{"answer": "done"}',
            meter=Meter(usage(10, 1, prompt_tokens_details={"cached_tokens": 8})),
        )
        assert _of(events, "answer")[0]["usage"]["prompt_tokens_details"] == {
            "cached_tokens": 8}

    def test_nothing_reported_means_no_field_at_all(self, bus):
        """Absent, not zero. Three zeros are a claim about a call."""
        _, events = _metered(bus, '{"answer": "done"}', meter=Meter(None))
        assert "usage" not in _of(events, "answer")[0]
        assert "usage" not in _of(events, "mission_finished")[0]

    def test_no_usage_source_leaves_the_stream_exactly_as_it_was(self, bus):
        """The default. Every record this loop emitted before there was a
        ledger is byte-identical."""
        _, events = _metered(bus, tool_call("catalog.search", q="x"),
                             '{"answer": "done"}')
        assert all("usage" not in record for record in events)

    def test_a_usage_source_that_throws_does_not_end_the_mission(self, bus):
        def boom():
            raise RuntimeError("the meter broke")

        transcript, events = _metered(bus, '{"answer": "done"}', meter=boom)
        assert transcript.outcome == "answered"
        assert "usage" not in _of(events, "answer")[0]

    def test_it_is_read_once_per_model_call(self, bus):
        """`last_usage` is a side channel the NEXT call clears, so reading
        it twice for one call would count it twice."""
        meter = Meter(usage(1, 1), usage(1, 1), usage(1, 1))
        _metered(bus, tool_call("catalog.search", q="x"), '{"answer": "done"}',
                 meter=meter)
        assert meter.reads == 2

    def test_every_record_still_conforms(self, bus):
        _, events = _metered(
            bus, "not json", tool_call("catalog.search", q="x"),
            '{"answer": "done"}',
            meter=Meter(usage(1, 1), usage(2, 2), usage(3, 3)),
        )
        for record in events:
            assert conforms(record) == [], record

    def test_usage_is_declared_optional_on_every_record_that_carries_it(self):
        for event in ("tool_call", "answer", "reply_rejected",
                      "mission_finished"):
            assert "usage" in contract.OPTIONAL[event], event


class TestTheRunsTotalsRideTheLastRecord:
    def test_the_totals_are_the_sum_of_the_calls(self, bus):
        _, events = _metered(
            bus, tool_call("catalog.search", q="x"), '{"answer": "done"}',
            meter=Meter(usage(100, 10), usage(200, 20)),
        )
        assert _of(events, "mission_finished")[0]["usage"] == {
            "prompt_tokens": 300, "completion_tokens": 30,
            "total_tokens": 330, "calls": 2}

    def test_calls_counts_the_ones_that_REPORTED(self, bus):
        """Not the calls that were made. A run against a provider that
        answers sometimes must not be reported as a run of fewer calls
        with made-up totals."""
        _, events = _metered(
            bus, tool_call("catalog.search", q="x"), '{"answer": "done"}',
            meter=Meter(usage(100, 10), None),
        )
        assert _of(events, "mission_finished")[0]["usage"]["calls"] == 1

    def test_the_transcript_holds_the_same_ledger(self, bus):
        transcript, events = _metered(
            bus, '{"answer": "done"}', meter=Meter(usage(7, 3)))
        assert (transcript.usage.prompt, transcript.usage.completion,
                transcript.usage.calls) == (7, 3, 1)

    def test_a_second_run_does_not_report_the_first_ones_tokens(self, bus):
        runner = MissionRunner(
            ScriptedModel('{"answer": "one"}', '{"answer": "two"}'),
            bus, ["catalog.search"], usage_fn=Meter(usage(5, 5), usage(9, 9)),
        )
        runner.run("first")
        second = runner.run("second")
        assert second.usage.calls == 1
        assert second.usage.prompt == 9

    def test_a_mission_that_raised_still_reports_what_it_spent(self):
        """`mission_finished` comes out of a `finally`, and so does this."""
        class _Exploding:
            def dispatch(self, *a, **kw):
                raise RuntimeError("the bus died")

            def register(self, *a, **kw):
                return None

            def unregister(self, *a, **kw):
                return None

            def describe_tool(self, name):
                return {"name": name, "description": "A tool."}

            def list_tools(self):
                return ["catalog.search"]

        events = []
        runner = MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="x")), _Exploding(),
            ["catalog.search"], observer=events.append, store_tool="",
            usage_fn=Meter(usage(11, 1)),
        )
        with pytest.raises(RuntimeError):
            runner.run("x")
        finished = _of(events, "mission_finished")[0]
        assert finished["usage"]["total_tokens"] == 12


class TestCostIsConfigurationAndNeverAConstant:
    def _rate(self, **kw):
        from core.runtime.usage import Rate

        return Rate(**kw)

    def test_a_configured_rate_puts_a_cost_beside_the_tokens(self, bus):
        _, events = _metered(
            bus, '{"answer": "done"}', meter=Meter(usage(1000, 500)),
            rate=self._rate(prompt_per_1k=0.5, completion_per_1k=1.5),
        )
        assert _of(events, "mission_finished")[0]["usage"]["cost"] == {
            "amount": 1.25, "currency": "USD"}

    def test_the_currency_is_carried_and_never_assumed(self, bus):
        _, events = _metered(
            bus, '{"answer": "done"}', meter=Meter(usage(1000, 0)),
            rate=self._rate(prompt_per_1k=2.0, currency="EUR"),
        )
        assert _of(events, "mission_finished")[0]["usage"]["cost"][
            "currency"] == "EUR"

    def test_no_rate_means_no_cost_key(self, bus):
        _, events = _metered(bus, '{"answer": "done"}',
                             meter=Meter(usage(1000, 500)))
        assert "cost" not in _of(events, "mission_finished")[0]["usage"]

    def test_a_rate_with_nothing_to_price_writes_nothing(self, bus):
        """No provider reported, so there is no usage field to hang a cost
        off — and inventing one would be billing for a run nobody counted."""
        _, events = _metered(
            bus, '{"answer": "done"}', meter=Meter(None),
            rate=self._rate(prompt_per_1k=1.0),
        )
        assert "usage" not in _of(events, "mission_finished")[0]

    def test_a_small_run_does_not_round_to_free(self, bus):
        """Cents would make every cheap call cost nothing at the point of
        measurement, which is the point at which it still can be summed."""
        _, events = _metered(
            bus, '{"answer": "done"}', meter=Meter(usage(30, 0)),
            rate=self._rate(prompt_per_1k=0.001),
        )
        assert _of(events, "mission_finished")[0]["usage"]["cost"][
            "amount"] == 3e-05


# ── the gate writes the request down, and a decision widens one run ──────────


class TestTheGateWritesADurableRequest:
    """`AWAITING_APPROVAL` used to be the end of the story.

    The mission stopped, the process exited, and the request lived in whatever
    the consumer happened to keep — a socket, a tab, the memory of the program
    that spawned us. An approval that dies with a socket gets re-asked, or
    worse, defaulted. So the ask half writes a file, and its id rides the
    record a watcher already reads.
    """

    def _gated_run(self, bus, store, **kw):
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.search", "catalog.get"],
            gated=["catalog.get"], approvals=store, observer=events.append,
            **kw,
        ).run("fetch a1")
        return transcript, events

    def test_the_request_is_on_disk_when_the_record_goes_out(self, bus, tmp_path):
        from core.runtime.approvals import PENDING, ApprovalStore

        store = ApprovalStore(tmp_path / "approvals")
        transcript, events = self._gated_run(bus, store, run_id="r-7")

        gate = [r for r in events if r["event"] == "gate_requested"][0]
        approval_id = gate["approval_id"]
        recorded = store.get(approval_id)
        assert recorded.state == PENDING
        assert recorded.tool == "catalog.get"
        assert recorded.arguments == {"asset_id": "a1"}
        assert recorded.objective == "fetch a1"
        assert recorded.run_id == "r-7"
        assert transcript.awaiting["approval_id"] == approval_id

    def test_the_id_conforms_as_an_optional_field(self, bus, tmp_path):
        from core.runtime.approvals import ApprovalStore

        _t, events = self._gated_run(bus, ApprovalStore(tmp_path / "a"))
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert conforms(gate) == []
        assert "approval_id" in contract.OPTIONAL[contract.GATE_REQUESTED]

    def test_the_call_is_still_not_made(self, bus, tmp_path):
        """Writing the request down is bookkeeping, not permission."""
        from core.runtime.approvals import ApprovalStore
        from core.runtime.mission import AWAITING_APPROVAL

        transcript, events = self._gated_run(bus, ApprovalStore(tmp_path / "a"))
        assert transcript.outcome == AWAITING_APPROVAL
        assert [r for r in events if r["event"] == "tool_result"] == []

    def test_without_a_store_the_loop_is_what_it_was(self, bus):
        """`None` is the old behaviour, whole: no id, no key on `awaiting`,
        and a library caller holding its own gate machinery is untouched."""
        transcript, events = self._gated_run(bus, None)
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "approval_id" not in gate
        assert transcript.awaiting == {"tool": "catalog.get",
                                       "arguments": {"asset_id": "a1"}}

    def test_a_store_that_cannot_write_says_so_instead_of_shrugging(
            self, bus, tmp_path):
        """A request with no record is one nobody can ever answer, and an
        operator who is never told that waits on a decision that cannot be
        made. Same lesson as the audit log's failed write."""
        from core.runtime.approvals import ApprovalStore

        blocked = tmp_path / "blocked"
        blocked.write_text("I am a file, not a directory", encoding="utf-8")

        transcript, events = self._gated_run(bus, ApprovalStore(blocked))
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "approval_id" not in gate
        assert "NO DURABLE RECORD" in gate["reason"]
        assert "NO DURABLE RECORD" in transcript.steps[0].error


class TestAnApprovalWidensOneRunByOneTool:
    def _approved(self, tmp_path, tool="catalog.get"):
        from core.runtime.approvals import ApprovalStore, resolve

        store = ApprovalStore(tmp_path / "approvals")
        approval_id = store.request(tool=tool, arguments={"asset_id": "a1"})
        store.decide(approval_id, approve=True, decided_by="dana")
        return store, approval_id, resolve(store, approval_id)

    def test_the_approved_tool_leaves_the_gated_set_on_the_opening_frame(
            self, bus, tmp_path):
        _store, _id, ticket = self._approved(tmp_path)
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "ok"}'),
            bus, ["catalog.search", "catalog.get"],
            gated=["catalog.search", "catalog.get"], approval=ticket,
            observer=events.append,
        ).run("fetch a1")

        opened = [r for r in events if r["event"] == "mission_started"][0]
        # The widening IS the absence. There is no second field announcing it.
        assert opened["gated"] == ["catalog.search"]
        assert "catalog.get" in opened["catalogue"]

    def test_exactly_that_tool_and_no_other(self, bus, tmp_path):
        _store, _id, ticket = self._approved(tmp_path, tool="catalog.search")
        runner = MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus,
            ["catalog.search", "catalog.get"],
            gated=["catalog.search", "catalog.get"], approval=ticket)
        assert runner.gated == ["catalog.get"]

    def test_the_approved_tool_is_dispatched_and_the_approval_is_spent(
            self, bus, tmp_path):
        from core.runtime.approvals import SPENT

        store, approval_id, ticket = self._approved(tmp_path)
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "asset a1"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approval=ticket,
            observer=events.append,
        ).run("fetch a1")

        assert transcript.outcome == "answered"
        assert [r["tool"] for r in events
                if r["event"] == "tool_result"] == ["catalog.get"]
        assert store.get(approval_id).state == SPENT

    def test_a_run_that_never_calls_it_leaves_the_decision_unspent(
            self, bus, tmp_path):
        """Spend-on-dispatch, and this is the case it is for: a yes burned on
        a run where nothing happened teaches an operator to approve twice."""
        from core.runtime.approvals import APPROVED

        store, approval_id, ticket = self._approved(tmp_path)
        MissionRunner(
            ScriptedModel('{"answer": "I did not need it"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approval=ticket,
        ).run("fetch a1")

        assert store.get(approval_id).state == APPROVED

    def test_dispatching_a_different_tool_does_not_spend_it(
            self, bus, tmp_path):
        """The spend is attached to the ONE tool the decision was about. A
        run that used something else has used nobody's yes."""
        from core.runtime.approvals import APPROVED

        store, approval_id, ticket = self._approved(tmp_path)
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="x"),
                          '{"answer": "found it another way"}'),
            bus, ["catalog.search", "catalog.get"], gated=["catalog.get"],
            approval=ticket,
        ).run("fetch a1")

        assert store.get(approval_id).state == APPROVED

    def test_calling_it_twice_in_one_run_spends_one_decision(
            self, bus, tmp_path):
        from core.runtime.approvals import SPENT

        store, approval_id, ticket = self._approved(tmp_path)
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          tool_call("catalog.get", asset_id="a2"),
                          '{"answer": "both"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approval=ticket,
        ).run("fetch both")

        assert store.get(approval_id).state == SPENT
        assert store.get(approval_id).spent_at

    def test_the_next_run_without_the_approval_gates_it_again(
            self, bus, tmp_path):
        """One tool, one run. There is no state anywhere saying this operator
        approves fetches."""
        from core.runtime.mission import AWAITING_APPROVAL

        _store, _id, ticket = self._approved(tmp_path)
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "ok"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approval=ticket,
        ).run("fetch a1")

        second = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"],
        ).run("fetch a1 again")
        assert second.outcome == AWAITING_APPROVAL

    def test_a_spent_record_cannot_be_resolved_into_a_second_run(
            self, bus, tmp_path):
        from core.runtime.approvals import NotApproved, resolve

        store, approval_id, ticket = self._approved(tmp_path)
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "ok"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approval=ticket,
        ).run("fetch a1")

        with pytest.raises(NotApproved) as exc:
            resolve(store, approval_id)
        assert "spent" in str(exc.value)


class TestTheRunnerCannotAnswerItsOwnGate:
    """The rule, as a grep.

    A framework that could approve its own proposal has a gate that is a
    formality, and the cheapest guarantee is written against the source
    because that is the property — not "it does not happen on this path"
    but "there is no path".

    The rule used to be "the loop never calls ``decide``", and it stopped
    being spellable that way when the control channel arrived: a gate
    answered while the run stands at it has to be **recorded**, through the
    same store the ``--approval`` path reads, or an in-turn yes would be a
    permission with no record — the exact defect
    :mod:`core.runtime.approvals` exists to prevent. So the property is
    stated as what it always meant: the loop may *carry* somebody's
    decision, and it may not *make* one.

    Which is greppable, and sharper than the old form. There is no literal
    verdict in the loop — no ``approve=True``, no ``approve=False`` — and no
    literal decider, so every argument the store is handed came off a
    command that arrived from outside this process. The word ``APPROVED``
    still does not appear at all, so no branch here can recognise the state
    it must not produce, and the staged runner still shares no call with the
    answering code whatsoever.
    """

    SOURCES = ("core/runtime/mission.py", "core/runtime/swarm.py")

    def _source(self, name):
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / name).read_text()

    def test_the_staged_runner_never_goes_near_a_decision(self):
        """The swarm keeps the original rule whole: it gates, and the gate
        is answered by the sub-mission's loop or by nobody."""
        source = self._source("core/runtime/swarm.py")
        assert ".decide(" not in source
        assert "decided_by" not in source

    @pytest.mark.parametrize("name", SOURCES)
    def test_no_verdict_is_written_anywhere_in_the_loop(self, name):
        """`approve=` is only ever handed a value that arrived from
        outside. A literal here would be the loop deciding."""
        source = self._source(name)
        assert re.findall(r"approve\s*=\s*(?:True|False)\b", source) == [], \
            f"{name} states a verdict of its own"

    @pytest.mark.parametrize("name", SOURCES)
    def test_no_decider_is_named_anywhere_in_the_loop(self, name):
        """A decision names who made it, and this harness never knows who
        that is — it has no identity layer and will not invent one."""
        source = self._source(name)
        assert re.findall(r"decided_by\s*=\s*[\"\']", source) == [], \
            f"{name} names a decider"

    def test_the_one_call_that_records_a_decision_is_the_only_one(self):
        """One site, and it is the bookkeeping for a command somebody sent.
        A second would be a second owner of what a yes means."""
        source = self._source("core/runtime/mission.py")
        assert source.count(".decide(") == 1
        assert "def _record_decision" in source

    @pytest.mark.parametrize("name", SOURCES)
    def test_the_loop_never_names_the_approved_state(self, name):
        """It cannot write `state = APPROVED` if it never says the word."""
        assert "APPROVED" not in self._source(name), \
            f"{name} knows what approved is"

    def test_only_the_store_reaches_the_approved_state(self):
        """One owner, across the whole of `core/`."""
        from pathlib import Path

        core = Path(__file__).resolve().parent.parent / "core"
        writers = sorted(
            path.relative_to(core).as_posix()
            for path in core.rglob("*.py")
            if "state = APPROVED" in path.read_text())
        assert writers == ["runtime/approvals.py"]


class TestTheRunIsResumed:
    """What ``run(objective, resumption)`` changes, and what it must not.

    The replay itself lives in ``tests/test_resume.py``; this is the loop's
    own half of the seam — that a resumed run is the SAME mission on the
    stream, that the step budget is a total for the run rather than a fresh
    allowance for this process, and that with no resumption every line of it
    behaves exactly as it did before any of this existed.
    """

    def _resumption(self, *, next_index=1, tail=(), steps=(), from_seq=3):
        """A resumption built by hand.

        By hand rather than through ``rebuild``, deliberately: this class is
        about what the LOOP does with one, and a fixture that had to record
        a real run first would fail for reasons belonging to the replay.
        """
        from core.runtime.resume import Resumption

        made = Resumption(run_id="run_abcd1234", objective="go",
                          from_seq=from_seq, next_index=next_index)
        made.tail.extend(dict(turn) for turn in tail)
        made.steps.extend(steps)
        return made

    def _store(self, tmp_path):
        from core.durable import RunStore
        return RunStore(tmp_path / "runs")

    def test_a_resumed_run_emits_no_second_opening(self, bus):
        seen = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", observer=seen.append,
        ).run("go", self._resumption())
        assert [r["event"] for r in seen] == \
            ["step_started", "answer", "mission_finished"]

    def test_the_first_step_carries_resumed_and_the_rest_do_not(self, bus):
        seen = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          '{"answer": "ok"}'),
            bus, ["catalog.search"], store_tool="", observer=seen.append,
            max_steps=4,
        ).run("go", self._resumption(from_seq=7))
        started = [r for r in seen if r["event"] == "step_started"]
        assert len(started) == 2
        assert started[0]["resumed"] == {"from_seq": 7, "steps_replayed": 0}
        assert "resumed" not in started[1]

    def test_a_cold_run_says_nothing_about_being_resumed(self, bus):
        """Absent, not false: a consumer must be able to tell "this stream
        continues an earlier one" from "this one does not"."""
        seen = []
        MissionRunner(ScriptedModel('{"answer": "ok"}'), bus,
                      ["catalog.search"], store_tool="",
                      observer=seen.append).run("go")
        assert "resumed" not in seen[1]

    def test_the_tail_is_appended_after_the_seed(self, bus):
        model = ScriptedModel('{"answer": "ok"}')
        tail = [{"role": "assistant", "content": "earlier"},
                {"role": "user", "content": "Result of catalog.search (ok):"}]
        MissionRunner(model, bus, ["catalog.search"], store_tool="",
                      ).run("go", self._resumption(tail=tail))
        shown = model.seen[0]
        assert shown[0]["role"] == "system"
        assert shown[1] == {"role": "user", "content": "go"}
        assert shown[2:] == tail

    def test_the_index_starts_where_the_recorded_stretch_left_off(self, bus):
        seen = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", observer=seen.append, max_steps=6,
        ).run("go", self._resumption(next_index=4))
        assert seen[0]["index"] == 4

    def test_max_steps_is_the_total_for_the_run_and_not_a_fresh_allowance(
            self, bus):
        """A cap a resume resets is a cap anybody can widen by killing the
        run. Three recorded steps against a total of three leaves none."""
        model = ScriptedModel('{"answer": "ok"}')
        transcript = MissionRunner(
            model, bus, ["catalog.search"], store_tool="", max_steps=3,
        ).run("go", self._resumption(next_index=3))
        assert transcript.outcome == "budget_exhausted"
        assert model.seen == []

    def test_a_run_with_nothing_left_still_closes_its_stream(self, bus):
        """And says nothing about being resumed, because it never reached a
        ``step_started`` to say it on."""
        seen = []
        MissionRunner(ScriptedModel(), bus, ["catalog.search"], store_tool="",
                      observer=seen.append, max_steps=2,
                      ).run("go", self._resumption(next_index=2))
        assert [r["event"] for r in seen] == ["mission_finished"]
        assert seen[0]["outcome"] == "budget_exhausted"

    def test_the_replayed_steps_are_on_the_transcript(self, bus):
        from core.runtime.mission import MissionStep

        earlier = MissionStep(index=0, raw_reply="x", tool="catalog.search")
        transcript = MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", max_steps=4,
        ).run("go", self._resumption(steps=[earlier]))
        assert transcript.steps[0] is earlier
        assert len(transcript.steps) == 2

    def test_the_finishing_counts_are_totals_for_the_run(self, bus):
        """``steps`` and ``max_steps`` stay comparable across a resume, which
        they only do if both count the whole run."""
        from core.runtime.mission import MissionStep

        seen = []
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", observer=seen.append, max_steps=5,
        ).run("go", self._resumption(
            next_index=2, steps=[MissionStep(index=0, raw_reply="a"),
                                 MissionStep(index=1, raw_reply="b")]))
        assert (seen[-1]["steps"], seen[-1]["max_steps"]) == (3, 5)

    def test_the_runner_adopts_the_replayed_result_store(self, bus):
        """Adopted rather than copied into: the handles the model was given
        have to keep addressing the same results, and two stores would mean
        ``mission_result`` read one and the grounding validator the other."""
        resumption = self._resumption()
        resumption.store.record("catalog.search", {"q": "a"},
                                text="hits for a")
        runner = MissionRunner(ScriptedModel('{"answer": "ok"}'), bus,
                               ["catalog.search"], store_tool="", max_steps=4)
        runner.run("go", resumption)
        assert runner.store is resumption.store
        assert runner.store.get("r1").text == "hits for a"

    def test_a_cold_run_still_clears_the_store_between_runs(self, bus):
        """The line the resumption branch had to step around. A runner used
        twice must not offer the second run a handle into the first."""
        runner = MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="a"),
                          '{"answer": "ok"}', '{"answer": "ok"}'),
            bus, ["catalog.search"], store_tool="")
        runner.run("go")
        assert len(runner.store) == 1
        runner.run("again")
        assert len(runner.store) == 0

    def test_the_resumed_records_go_to_the_same_log(self, bus, tmp_path):
        store = self._store(tmp_path)
        run_id = store.create().run_id
        store.append(run_id, {"event": "mission_started"})
        MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            store_tool="", run_store=store, run_id=run_id, max_steps=4,
        ).run("go", self._resumption())
        assert [r["event"] for r in store.records(run_id)] == \
            ["mission_started", "step_started", "answer", "mission_finished"]


# ---------------------------------------------------------------------------
# The native protocol: the model calls a function instead of writing one
# ---------------------------------------------------------------------------
#
# Everything above this line is the JSON protocol and stays exactly as it
# was — which is itself asserted, near the bottom, because "byte for byte
# the loop that has always run" is the promise `--protocol` is allowed to
# exist on.


def native_call(name, _id=None, **arguments):
    """One entry of the side channel a backend fills, as it fills it."""
    return {"id": _id or f"c_{name}", "name": name, "arguments": arguments}


def answer_call(text, _id=None):
    return native_call(ANSWER_TOOL, _id, text=text)


class NativeModel:
    """A server whose decoder was constrained: the reply IS the call.

    Two channels, like the real one — ``chat`` returns whatever ``content``
    the model wrote (usually nothing) and the calls arrive on the side
    channel the backend clears per request.  Scripted as ``(content,
    [calls])`` turns, or as one call, so a test says what a turn *was*
    rather than what a string happened to parse into.
    """

    def __init__(self, *turns):
        self.turns = [self._turn(turn) for turn in turns]
        self.seen = []
        self.last_tool_calls = []

    @staticmethod
    def _turn(turn):
        if isinstance(turn, tuple):
            return turn
        if isinstance(turn, list):
            return "", turn
        return "", [turn]

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        content, calls = (self.turns.pop(0) if self.turns
                          else ("", [answer_call("done")]))
        self.last_tool_calls = list(calls)
        return content

    def tool_calls(self):
        return list(self.last_tool_calls)


def native_runner(bus, model, tools=("catalog.search", "catalog.get"),
                  events=None, **kw):
    kw.setdefault("store_tool", "")
    return MissionRunner(
        model, bus, list(tools), protocol=NATIVE_PROTOCOL,
        tool_calls_fn=model.tool_calls,
        observer=(events.append if events is not None else None), **kw)


class TestTheNativeProtocolIsRefusedBeforeItCanMisbehave:
    def test_a_word_that_is_neither_protocol_is_refused_at_construction(
            self, bus):
        with pytest.raises(ValueError) as exc:
            MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                          protocol="functions")
        assert "json" in str(exc.value) and "native" in str(exc.value)

    def test_a_bus_tool_named_like_the_answer_function_is_refused(self):
        """Under `tool_choice=required` finishing IS a call, so a tool of
        that name would make finishing and calling it the same act."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(ToolDescriptor(tool_name=ANSWER_TOOL, description="x"),
                   lambda **kw: (0, "", ""))
        with pytest.raises(ValueError) as exc:
            MissionRunner(ScriptedModel(), b, [ANSWER_TOOL],
                          protocol=NATIVE_PROTOCOL)
        assert ANSWER_TOOL in str(exc.value)
        assert f"--protocol {JSON_PROTOCOL}" in str(exc.value)

    def test_the_same_tool_name_is_fine_under_the_json_protocol(self):
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(ToolDescriptor(tool_name=ANSWER_TOOL, description="x"),
                   lambda **kw: (0, "", ""))
        assert MissionRunner(ScriptedModel(), b, [ANSWER_TOOL],
                             store_tool="").offered == [ANSWER_TOOL]


class TestTheNativeProtocolAnswers:
    def test_one_answer_call_alone_is_the_answer(self, bus):
        events = []
        model = NativeModel(answer_call("the cable was cut"))
        transcript = native_runner(bus, model, events=events).run("what?")
        assert transcript.answer == "the cable was cut"
        assert transcript.outcome == "answered"
        assert [r["text"] for r in events if r["event"] == "answer"] == \
            ["the cable was cut"]

    def test_the_answer_goes_through_the_same_grounding_as_the_json_one(
            self, asset_bus, strict):
        """One owner for what an answer is worth. A native run whose caveat
        path drifted from the JSON one would be two agents in one name."""
        model = NativeModel(
            native_call("catalog.get", asset_id="asset.5f21"),
            answer_call("the asset is asset.9999"),
            answer_call("the asset is asset.9999"))
        transcript = native_runner(
            asset_bus, model, tools=("catalog.get",), validator=strict,
        ).run("go")
        assert transcript.outcome == "answered_with_caveat"
        assert transcript.grounding.repairs == 1

    def test_a_repair_prompt_goes_back_as_a_tool_message(self, asset_bus,
                                                         strict):
        """An assistant turn that declared tool_calls followed by a `user`
        message is a 400. Every declared call is answered — including the
        answer call the validator refused."""
        model = NativeModel(
            native_call("catalog.get", asset_id="asset.5f21"),
            answer_call("the asset is asset.9999", "ans-1"),
            answer_call("the asset is asset.5f21"))
        native_runner(asset_bus, model, tools=("catalog.get",),
                      validator=strict).run("go")
        repaired = model.seen[-1]
        assert repaired[-1]["role"] == "tool"
        assert repaired[-1]["tool_call_id"] == "ans-1"

    def test_an_answer_call_with_no_text_is_rejected_naming_the_field(
            self, bus):
        events = []
        model = NativeModel(native_call(ANSWER_TOOL, "a1"),
                            answer_call("done"))
        transcript = native_runner(bus, model, events=events).run("go")
        rejected = [r for r in events if r["event"] == "reply_rejected"]
        assert len(rejected) == 1
        assert "'text'" in rejected[0]["problem"]
        assert rejected[0]["tool"] == ANSWER_TOOL
        assert transcript.answer == "done"

    def test_two_answer_calls_are_refused_rather_than_the_first_one_taken(
            self, bus):
        events = []
        model = NativeModel([answer_call("a", "x"), answer_call("b", "y")],
                            answer_call("the real one"))
        transcript = native_runner(bus, model, events=events).run("go")
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "once, alone" in problem["problem"]
        assert transcript.answer == "the real one"

    def test_content_with_no_calls_at_all_is_read_as_the_answer(self, bus):
        """Some servers answer in prose despite `required`, and prose that
        says something is an answer: asking again spends a turn on text
        already written."""
        model = NativeModel(("the strait is quiet", []))
        transcript = native_runner(bus, model).run("go")
        assert transcript.answer == "the strait is quiet"
        assert transcript.outcome == "answered"

    def test_neither_calls_nor_content_is_a_rejection_that_says_what_to_do(
            self, bus):
        events = []
        model = NativeModel(("", []), answer_call("ok"))
        native_runner(bus, model, events=events).run("go")
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert ANSWER_TOOL in problem["problem"]
        assert conforms(problem) == []


class TestSeveralCallsInOneTurn:
    def _two(self, bus, events, **kw):
        model = NativeModel(
            [native_call("catalog.search", "c0", q="cables"),
             native_call("catalog.get", "c1", asset_id="a1")],
            answer_call("both"))
        return native_runner(bus, model, events=events, **kw).run("go"), model

    def test_both_calls_are_dispatched_in_the_order_the_model_gave_them(
            self, bus):
        events = []
        self._two(bus, events)
        assert [r["tool"] for r in events if r["event"] == "tool_result"] == \
            ["catalog.search", "catalog.get"]

    def test_each_call_gets_its_own_pair_of_records(self, bus):
        events = []
        self._two(bus, events)
        assert len([r for r in events if r["event"] == "tool_call"]) == 2
        assert len([r for r in events if r["event"] == "tool_result"]) == 2

    def test_the_ordinal_is_absent_on_the_first_and_present_after_it(self, bus):
        """Absent on the first so a consumer written before this reads the
        stream it always read."""
        events = []
        self._two(bus, events)
        for event in ("tool_call", "tool_result"):
            records = [r for r in events if r["event"] == event]
            assert "call" not in records[0]
            assert records[1]["call"] == 1

    def test_both_pairs_carry_the_same_index_because_a_step_is_a_model_turn(
            self, bus):
        events = []
        self._two(bus, events)
        assert {r["index"] for r in events
                if r["event"] in ("tool_call", "tool_result")} == {0}

    def test_two_calls_are_one_step_and_the_budget_counts_model_turns(
            self, bus):
        events = []
        transcript, _model = self._two(bus, events)
        assert len(transcript.steps) == 2          # the calls, then the answer
        assert len([r for r in events if r["event"] == "step_started"]) == 2
        assert transcript.steps[0].index == 0
        assert [c.tool for c in transcript.steps[0].calls] == \
            ["catalog.search", "catalog.get"]

    def test_the_ordinals_on_the_transcript_number_from_zero(self, bus):
        transcript, _model = self._two(bus, [])
        assert [c.ordinal for c in transcript.steps[0].calls] == [0, 1]
        assert isinstance(transcript.steps[0].calls[0], MissionCall)

    def test_every_record_of_a_multi_call_turn_conforms(self, bus):
        events = []
        self._two(bus, events)
        assert [p for r in events for p in conforms(r)] == []
        for record in events:
            declared = (set(contract.FIELDS.get(record["event"], ()))
                        | set(contract.OPTIONAL.get(record["event"], ())))
            assert set(record) - {"event"} <= declared, record

    def test_the_usage_of_the_turn_rides_the_first_record_only(self, bus):
        """One model call, one cost. A consumer summing the per-record field
        over a turn that dispatched twice must not be told it paid twice."""
        events = []
        self._two(bus, events, usage_fn=Meter(usage(11, 5)))
        calls = [r for r in events if r["event"] == "tool_call"]
        assert "usage" in calls[0] and "usage" not in calls[1]
        assert calls[0]["usage"]["total_tokens"] == 16


class TestTheWireShapeOfANativeTurn:
    def _ran(self, bus):
        model = NativeModel(
            [native_call("catalog.search", "c0", q="x"),
             native_call("catalog.get", "c1", asset_id="a1")],
            answer_call("done"))
        native_runner(bus, model).run("go")
        return model

    def test_the_model_reads_its_own_turn_back_as_tool_calls(self, bus):
        assistant = self._ran(bus).seen[1][2]
        assert assistant["role"] == "assistant"
        assert [c["id"] for c in assistant["tool_calls"]] == ["c0", "c1"]
        assert assistant["tool_calls"][0]["type"] == "function"
        assert assistant["tool_calls"][0]["function"]["name"] == \
            "catalog.search"
        assert json.loads(
            assistant["tool_calls"][0]["function"]["arguments"]) == {"q": "x"}

    def test_every_result_comes_back_quoting_the_call_it_answers(self, bus):
        results = [m for m in self._ran(bus).seen[1] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in results] == ["c0", "c1"]
        assert "Result of catalog.search (ok)" in results[0]["content"]

    def test_a_reply_with_no_calls_carries_no_tool_calls_key(self, bus):
        """An empty list is a different thing to some servers, and a reply
        with no calls in it is the shape it always was.

        Read off the turn AFTER a rejected empty reply, because that is the
        only way a call-less turn survives into a request: a call-less
        reply with text in it is an answer and the mission ends there.
        """
        model = NativeModel(("", []), answer_call("ok"))
        native_runner(bus, model).run("go")
        assistant = [m for m in model.seen[-1] if m["role"] == "assistant"]
        assert assistant and "tool_calls" not in assistant[0]

    def test_the_arguments_go_back_verbatim_when_the_backend_kept_them(
            self, bus):
        """A re-serialization is a paraphrase of the model to itself."""
        raw = '{"q":   "x"}'
        call = native_call("catalog.search", "c0", q="x")
        call["arguments_raw"] = raw
        model = NativeModel([call], answer_call("done"))
        native_runner(bus, model).run("go")
        assert model.seen[1][2]["tool_calls"][0]["function"]["arguments"] == raw

    def test_a_provider_that_gave_no_id_still_produces_a_matched_pair(
            self, bus):
        model = NativeModel(
            [{"name": "catalog.search", "arguments": {"q": "x"}}],
            answer_call("done"))
        native_runner(bus, model).run("go")
        minted = model.seen[1][2]["tool_calls"][0]["id"]
        assert minted
        results = [m for m in model.seen[1] if m["role"] == "tool"]
        assert results[0]["tool_call_id"] == minted

    def test_the_system_message_tells_the_model_how_to_finish(self, bus):
        system = native_runner(bus, NativeModel()).seed("x")[0]["content"]
        assert f"{ANSWER_TOOL}(text=" in system
        assert "one JSON object" not in system


class TestTheAnswerCountsOnlyWhenItIsAlone:
    def _mixed(self, bus, events):
        model = NativeModel(
            [native_call("catalog.search", "c0", q="x"),
             answer_call("I am done already", "ans")],
            answer_call("the real answer"))
        return native_runner(bus, model, events=events).run("go"), model

    def test_the_tools_run(self, bus):
        events = []
        self._mixed(bus, events)
        assert [r["tool"] for r in events if r["event"] == "tool_result"] == \
            ["catalog.search"]

    def test_the_answer_beside_them_is_not_the_missions_answer(self, bus):
        events = []
        transcript, _model = self._mixed(bus, events)
        assert transcript.answer == "the real answer"
        assert [r["text"] for r in events if r["event"] == "answer"] == \
            ["the real answer"]

    def test_the_model_is_told_the_answer_was_ignored_and_why(self, bus):
        events = []
        _transcript, model = self._mixed(bus, events)
        note = [m for m in model.seen[1] if m.get("tool_call_id") == "ans"][0]
        assert "IGNORED" in note["content"]
        assert "alone" in note["content"]

    def test_the_note_arrives_after_the_results_it_is_about(self, bus):
        events = []
        _transcript, model = self._mixed(bus, events)
        assert [m["tool_call_id"] for m in model.seen[1]
                if m["role"] == "tool"] == ["c0", "ans"]


class TestAGateStopsOnItsOwnCall:
    def _gated(self, bus, events, **kw):
        model = NativeModel([
            native_call("catalog.search", "c0", q="x"),
            native_call("catalog.get", "c1", asset_id="a1"),
            native_call("catalog.search", "c2", q="later"),
        ])
        return native_runner(bus, model, events=events,
                             gated=["catalog.get"], **kw).run("go"), model

    def test_the_call_before_it_ran(self, bus):
        events = []
        self._gated(bus, events)
        assert [r["tool"] for r in events if r["event"] == "tool_result"] == \
            ["catalog.search"]

    def test_the_mission_ends_awaiting_approval_on_that_call(self, bus):
        from core.runtime.mission import AWAITING_APPROVAL

        events = []
        transcript, _model = self._gated(bus, events)
        assert transcript.outcome == AWAITING_APPROVAL
        assert transcript.awaiting["tool"] == "catalog.get"
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert gate["arguments"] == {"asset_id": "a1"}

    def test_the_calls_after_it_are_not_dispatched(self, bus):
        events = []
        self._gated(bus, events)
        assert {"q": "later"} not in [r["arguments"] for r in events
                                      if r["event"] == "tool_call"]

    def test_and_the_reason_says_how_many_were_dropped_with_it(self, bus):
        events = []
        self._gated(bus, events)
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "1 later call" in gate["reason"]
        assert "NOT dispatched" in gate["reason"]

    def test_a_gate_on_the_only_call_says_what_it_always_said(self, bus):
        events = []
        model = NativeModel([native_call("catalog.get", "c0", asset_id="a1")])
        native_runner(bus, model, events=events,
                      gated=["catalog.get"]).run("go")
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "later call" not in gate["reason"]

    def test_the_turn_is_still_one_step(self, bus):
        transcript, _model = self._gated(bus, [])
        assert len(transcript.steps) == 1
        assert [c.tool for c in transcript.steps[0].calls] == \
            ["catalog.search", "catalog.get"]


class TestTheArgumentsAreCheckedAgainstTheToolsOwnSchema:
    """The half of the failure class constrained decoding does not close.

    A decoder held to the declared namespace cannot emit a name nobody
    offers nor JSON that does not parse.  What it can still emit is a
    well-formed object with the wrong contents, and the tool already said
    what it takes.
    """

    def _run(self, bus, arguments, events, protocol=NATIVE_PROTOCOL, **kw):
        if protocol == NATIVE_PROTOCOL:
            model = NativeModel(
                [native_call("catalog.search", "c0", **arguments)],
                answer_call("done"))
            return (native_runner(bus, model, tools=("catalog.search",),
                                  events=events, **kw).run("go"), model)
        model = ScriptedModel(tool_call("catalog.search", **arguments),
                              '{"answer": "done"}')
        return (MissionRunner(model, bus, ["catalog.search"], store_tool="",
                              observer=events.append, **kw).run("go"), model)

    def test_a_missing_required_argument_is_refused_naming_the_field(
            self, typed_bus):
        events = []
        self._run(typed_bus, {"limit": 3}, events)
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "'q'" in problem["problem"]
        assert problem["tool"] == "catalog.search"

    def test_a_wrong_type_is_refused_naming_the_rule(self, typed_bus):
        events = []
        self._run(typed_bus, {"q": "x", "limit": "three"}, events)
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "'limit'" in problem["problem"]
        assert "integer" in problem["problem"]

    def test_a_value_outside_an_enum_is_refused_listing_the_values(
            self, typed_bus):
        events = []
        self._run(typed_bus, {"q": "x", "type": "corpus"}, events)
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "dataset|model|service" in problem["problem"]

    def test_the_call_is_not_made(self, typed_bus):
        events = []
        self._run(typed_bus, {"limit": 3}, events)
        assert [r for r in events if r["event"] == "tool_call"] == []

    def test_the_refusal_names_the_schema_so_the_next_call_can_be_right(
            self, typed_bus):
        events = []
        self._run(typed_bus, {"limit": 3}, events)
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "q (string, required)" in problem["problem"]

    def test_it_goes_back_as_a_tool_message_under_the_native_protocol(
            self, typed_bus):
        events = []
        _transcript, model = self._run(typed_bus, {"limit": 3}, events)
        answered = [m for m in model.seen[1] if m["role"] == "tool"]
        assert answered[0]["tool_call_id"] == "c0"
        assert "'q'" in answered[0]["content"]

    def test_the_json_protocol_gets_the_same_check_and_the_same_sentence(
            self, typed_bus):
        """It costs nothing there and catches the same class."""
        events = []
        self._run(typed_bus, {"limit": 3}, events, protocol=JSON_PROTOCOL)
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "'q'" in problem["problem"]
        assert [r for r in events if r["event"] == "tool_call"] == []

    def test_a_gated_call_is_proposed_verbatim_even_if_it_would_not_pass(
            self, typed_bus):
        """What a person approves has to be the bytes the model wrote,
        whatever the schema would have said about them."""
        events = []
        self._run(typed_bus, {"limit": 3}, events, gated=["catalog.search"])
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert gate["arguments"] == {"limit": 3}

    def test_a_tool_that_published_no_schema_is_dispatched_as_before(
            self, bus):
        events = []
        model = NativeModel([native_call("catalog.search", "c0", whatever=1)],
                            answer_call("done"))
        native_runner(bus, model, events=events).run("go")
        assert [r["tool"] for r in events if r["event"] == "tool_result"] == \
            ["catalog.search"]

    def test_a_name_nobody_offers_is_still_refused_if_a_server_emits_one(
            self, bus):
        """Unrepresentable through a decoder that kept its promise — and the
        promise is the server's, so a mission must not crash on a broken
        one."""
        events = []
        model = NativeModel([native_call("catalog.invent", "c0", q="x")],
                            answer_call("done"))
        native_runner(bus, model, events=events).run("go")
        problem = [r for r in events if r["event"] == "reply_rejected"][0]
        assert "no tool named 'catalog.invent'" in problem["problem"]
        assert [r for r in events if r["event"] == "tool_call"] == []


class TestTheOpeningFrameSaysWhichProtocolRan:
    def _started(self, runner, events):
        runner.run("go")
        return next(r for r in events if r["event"] == "mission_started")

    def test_a_native_run_announces_it(self, bus):
        events = []
        started = self._started(
            native_runner(bus, NativeModel(), events=events), events)
        assert started["protocol"] == NATIVE_PROTOCOL
        assert conforms(started) == []

    def test_a_json_run_says_nothing_at_all(self, bus):
        """Absent, not "json": that is what keeps every stream recorded
        before this field existed byte-identical."""
        events = []
        started = self._started(MissionRunner(
            ScriptedModel('{"answer": "ok"}'), bus, ["catalog.search"],
            observer=events.append), events)
        assert "protocol" not in started

    def test_the_new_fields_are_declared_optional_on_the_contract(self):
        assert "protocol" in contract.OPTIONAL[contract.MISSION_STARTED]
        assert "call" in contract.OPTIONAL[contract.TOOL_CALL]
        assert "call" in contract.OPTIONAL[contract.TOOL_RESULT]

    def test_the_answer_function_is_declared_where_the_caller_can_find_it(
            self):
        """The loop reads a call to it and the caller declares it; two
        copies of one function's schema is how an emitter drifts."""
        assert ANSWER_FUNCTION["function"]["name"] == ANSWER_TOOL
        assert ANSWER_FUNCTION["function"]["parameters"]["required"] == ["text"]


class TestTheJsonProtocolIsUntouched:
    """The promise the flag is allowed to exist on.

    A default that changed one field of one record would break the consumer
    this repo is pinned by, and break it silently: an added key is not an
    error, it is a key nobody reads.
    """

    def _stream(self, bus, **kw):
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="cables"),
                          '{"answer": "two"}'),
            bus, ["catalog.search"], store_tool="", observer=events.append,
            **kw).run("go")
        return events

    def test_the_records_are_the_same_records_in_the_same_order(self, bus):
        assert [r["event"] for r in self._stream(bus)] == [
            "mission_started", "step_started", "tool_call", "tool_result",
            "step_started", "answer", "mission_finished"]

    def test_no_record_grew_a_field(self, bus):
        for record in self._stream(bus):
            assert "protocol" not in record
            assert "call" not in record

    def test_the_conversation_is_still_plain_turns_and_nothing_else(self, bus):
        model = ScriptedModel(tool_call("catalog.search", q="cables"),
                              '{"answer": "two"}')
        MissionRunner(model, bus, ["catalog.search"], store_tool="").run("go")
        assert {m["role"] for m in model.seen[-1]} == {"system", "user",
                                                       "assistant"}
        assert all("tool_calls" not in m for m in model.seen[-1])

    def test_the_step_carries_its_call_on_the_fields_it_always_did(self, bus):
        model = ScriptedModel(tool_call("catalog.search", q="cables"),
                              '{"answer": "two"}')
        transcript = MissionRunner(model, bus, ["catalog.search"],
                                   store_tool="").run("go")
        assert transcript.steps[0].tool == "catalog.search"
        assert transcript.steps[0].calls == []


class TestACompactedNativeConversationIsStillSendable:
    """A `tool` message answering no call is a 400, not an oddity.

    The window drops oldest-first and already refuses to leave a tail
    starting with anything but the model's own turn; this is the last edge
    of that rule, where the tail has been cut to its floor.
    """

    def test_an_orphaned_result_is_dropped(self):
        healed = MissionRunner._heal_native([
            {"role": "system", "content": "s"},
            {"role": "user", "content": "objective"},
            {"role": "tool", "tool_call_id": "gone", "content": "orphan"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "kept"},
        ])
        assert [m.get("tool_call_id") for m in healed
                if m["role"] == "tool"] == ["c1"]
        assert len(healed) == 4

    def test_a_conversation_with_nothing_to_heal_is_unchanged(self):
        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "content": "o"},
                    {"role": "assistant", "content": "a"},
                    {"role": "user", "content": "r"}]
        assert MissionRunner._heal_native(messages) == messages

    def test_a_user_turn_closes_the_calls_that_preceded_it(self):
        """A compaction note lands between the two halves of a round trip,
        and the result on the far side of it answers nothing the model can
        still see."""
        healed = MissionRunner._heal_native([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "user", "content": "…older turns were dropped…"},
            {"role": "tool", "tool_call_id": "c1", "content": "stranded"},
        ])
        assert [m["role"] for m in healed] == ["assistant", "user"]


# ── the answer, while it is still being written ──────────────────────────────
#
# `chat_fn` may hand the loop a string, which is what every test above does
# and what every library caller does, or an iterator of delta frames, which
# is what a streaming backend hands `core.cli`. The loop takes either. What
# follows asserts both halves of that promise: the fragments a streamed call
# produces, and the fact that a string-returning one still produces exactly
# the stream it always produced.


class StreamingModel:
    """Replays canned replies as frames, the way a backend yields them.

    Each scripted reply is cut into fixed-size pieces, and the split is
    the point: a server's frame boundary lands wherever its buffer filled
    and never where a JSON token ends.
    """

    def __init__(self, *replies, piece=5):
        self.replies = list(replies)
        self.piece = piece
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else '{"answer": "done"}'
        return self._frames(reply)

    def _frames(self, reply):
        for at in range(0, len(reply), self.piece):
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content=reply[at:at + self.piece],
                                      tool_calls=None))])


class NativeStreamingModel(NativeModel):
    """A constrained decoder, streaming: the call arrives as fragments.

    Subclasses the scripted native model so the side channel — which is
    what the loop actually dispatches from — is filled exactly as it is
    for a non-streamed native turn, and only the frames are new.
    """

    def __init__(self, *turns, piece=6):
        super().__init__(*turns)
        self.piece = piece

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        content, calls = (self.turns.pop(0) if self.turns
                          else ("", [answer_call("done")]))
        self.last_tool_calls = list(calls)
        return self._frames(content, calls)

    def _frames(self, content, calls):
        if content:
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None))])
        for index, call in enumerate(calls):
            raw = json.dumps(call["arguments"])
            yield self._fragment(index, call["id"], call["name"], raw[:1])
            for at in range(1, len(raw), self.piece):
                yield self._fragment(index, None, None,
                                     raw[at:at + self.piece])

    @staticmethod
    def _fragment(index, call_id, name, arguments):
        function = {"arguments": arguments}
        if name is not None:
            function["name"] = name
        entry = {"index": index, "function": function}
        if call_id is not None:
            entry["id"] = call_id
        return SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, tool_calls=[entry]))])


def deltas(events):
    return [r for r in events if r["event"] == contract.ANSWER_DELTA]


class TestTheAnswerArrivesWhileItIsBeingWritten:
    def test_the_fragments_concatenate_to_the_answer(self, bus):
        events = []
        answer = "Three assets, and the newest is from August."
        MissionRunner(
            StreamingModel(json.dumps({"answer": answer})),
            bus, ["catalog.search"], observer=events.append,
        ).run("what do we hold")
        assert "".join(r["text"] for r in deltas(events)) == answer

    def test_the_answer_record_still_follows_and_carries_the_whole_text(
            self, bus):
        """Always emitted, never suppressed because the fragments already
        added up to it: the deltas are decoded out of a half-written reply
        and the answer is read out of the finished one."""
        events = []
        answer = "The cable was cut."
        MissionRunner(
            StreamingModel(json.dumps({"answer": answer})),
            bus, ["catalog.search"], observer=events.append,
        ).run("what happened")
        names = [r["event"] for r in events]
        assert names.index(contract.ANSWER) > names.index(contract.ANSWER_DELTA)
        assert [r["text"] for r in events
                if r["event"] == contract.ANSWER] == [answer]

    def test_the_ordinals_run_from_zero_without_a_gap(self, bus):
        events = []
        MissionRunner(
            StreamingModel(json.dumps({"answer": "x" * 300})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert len(deltas(events)) > 1, "300 characters is several fragments"
        assert [r["part"] for r in deltas(events)] == \
            list(range(len(deltas(events))))

    def test_the_index_is_the_step_that_produced_them(self, bus):
        events = []
        MissionRunner(
            StreamingModel(tool_call("catalog.search", q="x"),
                           json.dumps({"answer": "found it"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert {r["index"] for r in deltas(events)} == {1}

    def test_every_record_conforms(self, bus):
        events = []
        MissionRunner(
            StreamingModel(json.dumps({"answer": "conformant"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert deltas(events)
        for record in events:
            assert conforms(record) == [], record

    def test_a_turn_that_called_a_tool_streamed_no_answer(self, bus):
        """Nothing is provisional about a tool call, and the reply has no
        top-level `answer` key for the decoder to find."""
        events = []
        MissionRunner(
            StreamingModel(tool_call("catalog.search", q="x"),
                           json.dumps({"answer": "done"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert [r["index"] for r in deltas(events)] == [1] * len(deltas(events))
        assert [r["event"] for r in events][:3] == [
            contract.MISSION_STARTED, contract.STEP_STARTED,
            contract.TOOL_CALL]

    def test_a_rejected_reply_streams_nothing_and_still_rejects(self, bus):
        events = []
        MissionRunner(
            StreamingModel("not json at all",
                           json.dumps({"answer": "second time lucky"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        rejected = [r for r in events if r["event"] == contract.REPLY_REJECTED]
        assert len(rejected) == 1
        assert {r["index"] for r in deltas(events)} == {1}

    def test_the_loop_is_told_the_whole_reply(self, bus):
        """What the model is handed back as its own turn is the assembled
        reply and not the fragments — a paraphrase of the model to itself
        is how a conversation stops making sense."""
        model = StreamingModel(tool_call("catalog.search", q="x"),
                               json.dumps({"answer": "done"}))
        MissionRunner(model, bus, ["catalog.search"]).run("go")
        assistant = [m for m in model.seen[-1] if m["role"] == "assistant"]
        assert assistant[-1]["content"] == tool_call("catalog.search", q="x")

    def test_a_repair_turn_streams_again_from_part_zero(self, asset_bus,
                                                        strict):
        """One model call, one `part` sequence. The consumer replaces its
        provisional text when the `answer` arrives, so the last one wins."""
        events = []
        MissionRunner(
            StreamingModel(
                tool_call("catalog.search"),
                json.dumps({"answer": "The label set is labels.7a19c4e2."}),
                json.dumps({"answer": "The corpus is asset.5f21c9."})),
            asset_bus, ["catalog.search"], validator=strict,
            observer=events.append,
        ).run("go")
        by_step = {}
        for record in deltas(events):
            by_step.setdefault(record["index"], []).append(record["part"])
        assert sorted(by_step) == [1, 2], "the draft, then the repair"
        assert all(parts[0] == 0 for parts in by_step.values())

    def test_the_fragments_are_scrubbed_like_every_other_text(self, bus,
                                                              monkeypatch):
        monkeypatch.setattr(redact, "_home", lambda: "/home/someone")
        events = []
        MissionRunner(
            StreamingModel(json.dumps(
                {"answer": "it is under /home/someone/x and nowhere else"}),
                piece=200),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        streamed = "".join(r["text"] for r in deltas(events))
        assert "/home/someone" not in streamed
        assert redact.HOME in streamed


class TestAStringReplyIsTheStreamItAlwaysWas:
    """The other half of the promise, and the more important half."""

    def test_a_string_returning_chat_fn_emits_no_deltas(self, bus):
        events = []
        MissionRunner(
            ScriptedModel(json.dumps({"answer": "done"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert deltas(events) == []

    def test_the_two_streams_differ_by_the_deltas_and_nothing_else(self, bus):
        """Byte for byte the stream a consumer read before this existed,
        once the new records are dropped — which is exactly what a
        consumer that has never heard of them does."""
        reply = json.dumps({"answer": "the same answer either way"})
        whole, pieces = [], []
        MissionRunner(ScriptedModel(reply), bus, ["catalog.search"],
                      observer=whole.append).run("go")
        MissionRunner(StreamingModel(reply), bus, ["catalog.search"],
                      observer=pieces.append).run("go")

        def comparable(records):
            # `elapsed_s` is a wall clock and differs between any two runs;
            # everything else on these records is a fact about the loop.
            return [{k: v for k, v in r.items() if k != "elapsed_s"}
                    for r in records if r["event"] != contract.ANSWER_DELTA]

        assert deltas(pieces)
        assert comparable(pieces) == comparable(whole)


class TestANativeTurnStreamsItsAnswerToo:
    def test_the_answer_functions_argument_streams(self, bus):
        events = []
        model = NativeStreamingModel(answer_call("the cable was cut"))
        transcript = native_runner(bus, model, events=events).run("what?")
        assert "".join(r["text"] for r in deltas(events)) == "the cable was cut"
        assert transcript.answer == "the cable was cut"

    def test_a_dispatching_turn_streams_nothing(self, bus):
        events = []
        model = NativeStreamingModel(
            native_call("catalog.search", q="x"),
            answer_call("found"))
        native_runner(bus, model, events=events).run("go")
        assert {r["index"] for r in deltas(events)} == {1}

    def test_the_side_channel_is_still_what_gets_dispatched(self, bus):
        """The fragments are a rendering; the decision is the calls the
        backend published when the iterator was exhausted."""
        events = []
        model = NativeStreamingModel(native_call("catalog.search", q="x"),
                                     answer_call("done"))
        native_runner(bus, model, events=events).run("go")
        called = [r for r in events if r["event"] == contract.TOOL_CALL]
        assert [r["arguments"] for r in called] == [{"q": "x"}]

    def test_every_record_of_a_streamed_native_run_conforms(self, bus):
        events = []
        model = NativeStreamingModel(answer_call("conformant"))
        native_runner(bus, model, events=events).run("go")
        assert deltas(events)
        for record in events:
            assert conforms(record) == [], record


class TestADecoderThatGivesUpCostsTheMissionNothing:
    def test_a_decoder_that_raises_never_reaches_the_loop(self, bus,
                                                          monkeypatch):
        """The error policy, exercised where it matters. The reply is
        accumulated whatever the decoder does, and the answer is read out
        of the finished reply by the parser that has always read it — so
        a decoder that gave up costs a pane its live rendering and costs
        the mission nothing."""
        from core.runtime import answer_stream

        def boom(_self, _text):
            raise RuntimeError("the decoder is confused")

        monkeypatch.setattr(answer_stream._TopLevelString, "feed", boom)
        events = []
        transcript = MissionRunner(
            StreamingModel(json.dumps({"answer": "still here"})),
            bus, ["catalog.search"], observer=events.append,
        ).run("go")
        assert transcript.answer == "still here"
        assert deltas(events) == []

    def test_frames_of_a_shape_no_backend_sends_do_not_end_the_mission(
            self, bus):
        def odd(_messages):
            yield object()
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content='{"answer": "fine"}',
                                      tool_calls=None))])

        assert MissionRunner(odd, bus, ["catalog.search"]).run("go").answer \
            == "fine"


# ---------------------------------------------------------------------------
# Being steered from outside: `--control`
# ---------------------------------------------------------------------------


class Steering:
    """A real control channel over a real pipe, plus a `send` for the test.

    The real object, over a real descriptor, read by the real daemon
    thread. A fake queue would prove the loop drains something; it would
    prove nothing about the thing a platform actually writes to.

    `send` does not return until the command has crossed the thread, so a
    test can say "the operator spoke here" and mean it. A `cancel` never
    reaches the queue — it is applied in the reader — so that one waits on
    the switch instead.
    """

    def __init__(self, cancel=None):
        import os

        read_fd, write_fd = os.pipe()
        self.cancel = cancel
        self.channel = ControlChannel.open(f"fd:{read_fd}", cancel=cancel)
        self.writer = os.fdopen(write_fd, "w", encoding="utf-8")

    def send(self, **payload):
        import time

        word = payload.get("control")
        before = self.channel.waiting
        self.writer.write(json.dumps(payload) + "\n")
        self.writer.flush()
        if word == "gate_decision":
            # Nothing to wait for: the run is already inside `wait_for`,
            # draining as fast as this writes, so watching the queue would
            # be watching for a moment that has already passed.
            return
        until = time.monotonic() + 2.0
        while time.monotonic() < until:
            if word == "cancel":
                if self.cancel is not None and self.cancel.is_set():
                    return
            elif self.channel.waiting > before:
                return
            time.sleep(0.002)
        raise AssertionError(f"the channel never took {payload}")

    def close(self):
        try:
            self.writer.close()
        except OSError:                         # pragma: no cover - defensive
            pass
        self.channel.close()


@pytest.fixture
def steering():
    """A channel the test writes to, closed however the test ends."""
    made = []

    def build(cancel=None):
        made.append(Steering(cancel=cancel))
        return made[-1]

    yield build
    for one in made:
        one.close()


class SpeakingModel(ScriptedModel):
    """A model that lets the operator speak at a chosen turn.

    `at` is which reply this model is about to give when the command goes
    out — so `at=0` is "the operator sent it while the first model call was
    in flight", which is the only interesting timing there is.
    """

    def __init__(self, steer, at, payloads, *replies):
        super().__init__(*replies)
        self._steer, self._at, self._payloads = steer, at, payloads

    def __call__(self, messages):
        reply = super().__call__(messages)
        if len(self.seen) - 1 == self._at:
            for payload in self._payloads:
                self._steer.send(**payload)
        return reply


class TestAnInjectionLandsBeforeTheNextModelCall:
    """The one moment an operator's instruction is a message in a
    conversation rather than an edit to a decision already taken."""

    def test_it_is_the_last_thing_the_model_is_shown(self, bus, steering):
        steer = steering()
        steer.send(control="inject", text="the SECOND corpus, not the first")
        model = ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"],
                      control=steer.channel).run("go")
        assert model.seen[0][-1] == {
            "role": "user", "content": "the SECOND corpus, not the first"}

    def test_the_objective_is_still_above_it(self, bus, steering):
        """Appended, never substituted: the question the run was started
        with does not stop being the question."""
        steer = steering()
        steer.send(control="inject", text="and check the dates")
        model = ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"],
                      control=steer.channel).run("survey the corpus")
        roles = [(m["role"], m["content"]) for m in model.seen[0]]
        assert ("user", "survey the corpus") in roles
        assert roles[-1] == ("user", "and check the dates")

    def test_the_step_that_carried_it_says_so_on_the_stream(
            self, bus, steering):
        """`injected` is the ONLY trace a control command leaves: commands
        coming in are not events going out, and an agent whose conversation
        gained a turn nobody can see looks, from outside, exactly like an
        agent that changed its mind."""
        steer = steering()
        steer.send(control="inject", text="the second corpus")
        events = []
        MissionRunner(ScriptedModel('{"answer": "ok"}'), bus,
                      ["catalog.search"], control=steer.channel,
                      observer=events.append).run("go")
        started = [r for r in events if r["event"] == "step_started"]
        assert started[0]["injected"] == ["the second corpus"]
        assert conforms(started[0]) == []
        assert "injected" in contract.OPTIONAL[contract.STEP_STARTED]

    def test_a_step_nobody_spoke_into_carries_no_field_at_all(
            self, bus, steering):
        """Absent, not empty. A consumer that has never heard of it reads
        exactly the stream it always read."""
        steer = steering()
        steer.send(control="inject", text="once")
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="x"),
                          '{"answer": "ok"}'),
            bus, ["catalog.search"], control=steer.channel,
            observer=events.append).run("go")
        started = [r for r in events if r["event"] == "step_started"]
        assert "injected" in started[0] and "injected" not in started[1]

    def test_a_run_with_no_channel_says_nothing_either(self, bus):
        events = []
        MissionRunner(ScriptedModel('{"answer": "ok"}'), bus,
                      ["catalog.search"], observer=events.append).run("go")
        assert all("injected" not in r for r in events)

    def test_two_injections_ride_one_step_in_the_order_they_were_sent(
            self, bus, steering):
        steer = steering()
        steer.send(control="inject", text="first")
        steer.send(control="inject", text="second")
        events = []
        model = ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"], control=steer.channel,
                      observer=events.append).run("go")
        started = [r for r in events if r["event"] == "step_started"][0]
        assert started["injected"] == ["first", "second"]
        assert [m["content"] for m in model.seen[0][-2:]] == ["first",
                                                              "second"]

    def test_an_injection_sent_mid_step_waits_for_the_next_one(
            self, bus, steering):
        """It does NOT arrive between the model choosing a tool and the tool
        being called: that would be an instruction landing inside a decision
        the model had already made."""
        steer = steering()
        model = SpeakingModel(
            steer, 0, [{"control": "inject", "text": "stop searching"}],
            tool_call("catalog.search", q="x"), '{"answer": "ok"}')
        events = []
        MissionRunner(model, bus, ["catalog.search"], control=steer.channel,
                      observer=events.append).run("go")
        # The first step's call still happened, and the instruction reached
        # the SECOND step.
        assert [r["tool"] for r in events if r["event"] == "tool_call"] == \
            ["catalog.search"]
        started = [r for r in events if r["event"] == "step_started"]
        assert "injected" not in started[0]
        assert started[1]["injected"] == ["stop searching"]

    def test_the_operators_words_are_scrubbed_on_the_wire(
            self, bus, steering, monkeypatch):
        """Free text an operator typed, and an operator quotes paths. The
        MODEL is told exactly what was sent; the stream states it scrubbed,
        the same split every other prose field takes."""
        monkeypatch.setenv("HOME", "/home/someone")
        steer = steering()
        steer.send(control="inject", text="read /home/someone/notes.txt")
        events, model = [], ScriptedModel('{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"], control=steer.channel,
                      observer=events.append).run("go")
        started = [r for r in events if r["event"] == "step_started"][0]
        assert started["injected"] == ["read <home>/notes.txt"]
        assert model.seen[0][-1]["content"] == "read /home/someone/notes.txt"

    def test_injected_is_classified_rather_than_scrubbed_by_nobody(self):
        assert "injected" in redact.SCRUBBED_FIELDS
        assert "injected" not in redact.VERBATIM_FIELDS


class TestCancelOnTheChannelIsTheSameLeverAsSigterm:
    def test_the_run_winds_up_incomplete_saying_why(self, bus, steering):
        from core.budgets import Cancellation

        switch = Cancellation()
        steer = steering(cancel=switch)
        model = SpeakingModel(steer, 0, [{"control": "cancel"}],
                              *[tool_call("catalog.search", q="x")] * 4)
        events = []
        transcript = MissionRunner(
            model, bus, ["catalog.search"], max_steps=4, cancel=switch,
            control=steer.channel, observer=events.append).run("go")

        assert (transcript.outcome, transcript.reason) == ("incomplete",
                                                           "cancelled")
        assert events[-1]["event"] == "mission_finished"
        assert events[-1]["reason"] == "cancelled"

    def test_it_stops_a_tool_the_model_had_already_named(self, bus, steering):
        from core.budgets import Cancellation

        switch = Cancellation()
        steer = steering(cancel=switch)
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]
        model = SpeakingModel(steer, 0, [{"control": "cancel"}],
                              tool_call("catalog.search", q="x"))
        transcript = MissionRunner(
            model, bus, ["catalog.search"], cancel=switch,
            control=steer.channel).run("go")
        assert calls == []
        assert transcript.reason == "cancelled"

    def test_the_cause_is_control_and_not_sigterm(self, bus, steering):
        """`exit_as_signalled` must not fire: a platform asked the MISSION
        to stop, not the process to die of a signal nobody sent."""
        from core.budgets import Cancellation
        from core.runtime.mission_stream import SIGTERM_CAUSE

        switch = Cancellation()
        steer = steering(cancel=switch)
        steer.send(control="cancel")
        MissionRunner(ScriptedModel('{"answer": "x"}'), bus,
                      ["catalog.search"], cancel=switch,
                      control=steer.channel).run("go")
        assert switch.cause != SIGTERM_CAUSE


class TestCancelStepDropsWhatHasNotGoneOut:
    def test_the_json_call_is_not_dispatched_and_the_model_is_asked_again(
            self, bus, steering):
        steer = steering()
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]
        model = SpeakingModel(steer, 0, [{"control": "cancel_step"}],
                              tool_call("catalog.search", q="x"),
                              '{"answer": "ok without it"}')
        transcript = MissionRunner(model, bus, ["catalog.search"],
                                   control=steer.channel).run("go")
        assert calls == []
        # Re-asked, not ended: the model gets to decide from what it has.
        assert transcript.outcome == "answered"
        assert transcript.answer == "ok without it"

    def test_the_model_is_told_in_as_many_words(self, bus, steering):
        """A turn whose calls silently produced no results reads, from
        inside the conversation, exactly like a tool plane that broke."""
        from core.runtime.mission import CANCEL_STEP_NOTE

        steer = steering()
        model = SpeakingModel(steer, 0, [{"control": "cancel_step"}],
                              tool_call("catalog.search", q="x"),
                              '{"answer": "ok"}')
        transcript = MissionRunner(model, bus, ["catalog.search"],
                                   control=steer.channel).run("go")
        assert model.seen[1][-1] == {"role": "user",
                                     "content": CANCEL_STEP_NOTE}
        assert transcript.steps[0].error == CANCEL_STEP_NOTE

    def test_two_asks_are_one_answer(self, bus, steering):
        """An operator clicking twice wanted the step stopped, not two
        steps."""
        steer = steering()
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]
        model = SpeakingModel(
            steer, 0, [{"control": "cancel_step"}, {"control": "cancel_step"}],
            tool_call("catalog.search", q="a"),
            tool_call("catalog.search", q="b"), '{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"], max_steps=4,
                      control=steer.channel).run("go")
        assert calls == ["catalog.search"]

    def test_one_that_arrives_too_late_is_a_note_and_not_a_skip(
            self, bus, steering):
        """It missed its step. The ask becomes a sentence rather than
        silently cancelling a step nobody asked about."""
        from core.runtime.mission import CANCEL_STEP_LATE

        steer = steering()
        calls = []
        real = bus.dispatch

        def watched(name, **kw):
            # Sent from INSIDE the dispatch, which is the one window where
            # the call is already gone and the step is not over: the ask
            # cannot reach it, and pretending otherwise would cancel a step
            # nobody asked about.
            result = real(name, **kw)
            calls.append(name)
            if len(calls) == 1:
                steer.send(control="cancel_step")
            return result

        bus.dispatch = watched
        model = ScriptedModel(tool_call("catalog.search", q="a"),
                              tool_call("catalog.search", q="b"),
                              '{"answer": "ok"}')
        MissionRunner(model, bus, ["catalog.search"], max_steps=4,
                      control=steer.channel).run("go")
        assert calls == ["catalog.search", "catalog.search"]
        assert any(m == {"role": "user", "content": CANCEL_STEP_LATE}
                   for m in model.seen[1])

    def test_it_does_not_swallow_an_injection_sent_beside_it(
            self, bus, steering):
        """The mid-step drain takes `cancel_step` and leaves the rest. An
        injection eaten there would be an instruction the model was never
        shown, with nothing saying so."""
        steer = steering()
        model = SpeakingModel(
            steer, 0,
            [{"control": "inject", "text": "try the other corpus"},
             {"control": "cancel_step"}],
            tool_call("catalog.search", q="x"), '{"answer": "ok"}')
        events = []
        MissionRunner(model, bus, ["catalog.search"], control=steer.channel,
                      observer=events.append).run("go")
        started = [r for r in events if r["event"] == "step_started"]
        assert started[1]["injected"] == ["try the other corpus"]

    def test_a_native_turn_drops_the_calls_that_had_not_gone_out(
            self, bus, steering):
        """The boundary this protocol has and the JSON one does not: one
        turn, several calls, and the operator gets to stop the rest."""
        from core.runtime.mission import CANCEL_STEP_NOTE

        steer = steering()
        calls = []
        real = bus.dispatch

        def watched(name, **kw):
            calls.append(name)
            if len(calls) == 1:
                steer.send(control="cancel_step")
            return real(name, **kw)

        bus.dispatch = watched
        model = NativeModel(
            [native_call("catalog.search", "c0", q="a"),
             native_call("catalog.get", "c1", asset_id="a1"),
             native_call("catalog.search", "c2", q="c")],
            answer_call("done"))
        transcript = native_runner(bus, model,
                                   control=steer.channel).run("go")
        assert calls == ["catalog.search"]
        skipped = transcript.steps[0].calls[1:]
        assert [c.tool for c in skipped] == ["catalog.get", "catalog.search"]
        assert all(c.error == CANCEL_STEP_NOTE for c in skipped)

    def test_every_skipped_native_call_is_still_answered(self, bus, steering):
        """An assistant turn that declared `tool_calls` and left one
        unanswered is a 400 from an OpenAI-shaped server. A cancelled call
        is still a declared one."""
        steer = steering()
        real = bus.dispatch
        seen = []

        def watched(name, **kw):
            seen.append(name)
            if len(seen) == 1:
                steer.send(control="cancel_step")
            return real(name, **kw)

        bus.dispatch = watched
        model = NativeModel(
            [native_call("catalog.search", "c0", q="a"),
             native_call("catalog.get", "c1", asset_id="a1")],
            answer_call("done"))
        native_runner(bus, model, control=steer.channel).run("go")
        answered = {m.get("tool_call_id") for m in model.seen[-1]
                    if m.get("role") == "tool"}
        assert answered == {"c0", "c1"}


class TestAGateAnsweredWhileTheRunStandsAtIt:
    """Today a gated tool ends the turn and somebody decides tomorrow. With
    a channel open the run waits — and what arrives is still a decision
    somebody *sent*, recorded in the same store, signed by the name they
    put on it. Nothing here times out into a yes."""

    def _store(self, tmp_path):
        from core.runtime.approvals import ApprovalStore

        return ApprovalStore(tmp_path / "approvals")

    def _answering(self, steer, approve=True, who="dana", note="",
                   delay=0.0):
        """A channel that answers whatever gate the run opens, once."""
        import threading

        def answer():
            import time

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                pending = self._pending
                if pending:
                    steer.send(control="gate_decision",
                               approval_id=pending[0], approve=approve,
                               decided_by=who, note=note)
                    return
                time.sleep(0.005)

        self._pending = []
        threading.Timer(delay, answer).start()

    def _watch(self, events):
        """Feed `_pending` from the stream, which is how a platform learns
        the id in the first place."""
        def observe(record):
            events.append(record)
            if record["event"] == "gate_requested" and record.get(
                    "approval_id"):
                self._pending.append(record["approval_id"])
        return observe

    def test_an_approval_dispatches_the_call_in_the_same_step(
            self, bus, tmp_path, steering):
        from core.runtime.approvals import SPENT

        store = self._store(tmp_path)
        steer = steering()
        events = []
        self._answering(steer)
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "asset a1"}'),
            bus, ["catalog.search", "catalog.get"], gated=["catalog.get"],
            approvals=store, control=steer.channel, gate_wait_s=5.0,
            observer=self._watch(events)).run("fetch a1")

        assert transcript.outcome == "answered"
        # The call it asked about follows the request, under the same index.
        kinds = [(r["event"], r.get("index")) for r in events
                 if r["event"] in ("gate_requested", "tool_call",
                                   "tool_result")]
        assert kinds[:3] == [("gate_requested", 0), ("tool_call", 0),
                             ("tool_result", 0)]
        recorded = store.get(self._pending[0])
        assert recorded.state == SPENT
        assert recorded.decided_by == "dana"

    def test_a_zero_window_ends_the_turn_at_the_gate_at_once(
            self, bus, tmp_path, steering, monkeypatch):
        """`--gate-wait 0` with a channel open is the 0.11 behaviour: the run
        ends at `awaiting_approval` immediately, the record stays pending,
        and the decision arrives on a later turn. The reference deployment
        measured a 300 s hang on an unattended gate without this — an eval
        driver is not going to click an approval card."""
        import time

        from core.runtime.approvals import PENDING

        store = self._store(tmp_path)
        steer = steering()
        self._pending = []                      # nobody answers this gate
        # A wait that WOULD have taken time: nobody answers, and a fake clock
        # would let a bug wait 300 s of wall time without the test noticing,
        # so this one is on the real clock with a real budget.
        started = time.monotonic()
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "unreached"}'),
            bus, ["catalog.search", "catalog.get"], gated=["catalog.get"],
            approvals=store, control=steer.channel, gate_wait_s=0,
            observer=self._watch([])).run("fetch a1")
        assert transcript.outcome == "awaiting_approval"
        assert time.monotonic() - started < 2.0
        assert store.get(self._pending[0]).state == PENDING

    def test_the_record_names_the_person_the_platform_sent(
            self, bus, tmp_path, steering):
        store = self._store(tmp_path)
        steer = steering()
        self._answering(steer, who="ravi", note="fine by me")
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "ok"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=5.0,
            observer=self._watch([])).run("fetch a1")
        recorded = store.get(self._pending[0])
        assert (recorded.decided_by, recorded.note) == ("ravi", "fine by me")

    def test_a_refusal_is_recorded_and_the_model_is_told(
            self, bus, tmp_path, steering):
        from core.runtime.approvals import REFUSED

        store = self._store(tmp_path)
        steer = steering()
        self._answering(steer, approve=False, who="dana",
                        note="not on prod")
        model = ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                              '{"answer": "could not fetch it"}')
        transcript = MissionRunner(
            model, bus, ["catalog.search", "catalog.get"],
            gated=["catalog.get"], approvals=store, control=steer.channel,
            gate_wait_s=5.0, observer=self._watch([])).run("fetch a1")

        assert transcript.outcome == "answered"
        assert store.get(self._pending[0]).state == REFUSED
        told = model.seen[-1][-1]["content"]
        assert "REFUSED by dana" in told and "not on prod" in told

    def test_nothing_is_dispatched_on_a_refusal(self, bus, tmp_path,
                                                steering):
        store = self._store(tmp_path)
        steer = steering()
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]
        self._answering(steer, approve=False)
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1"),
                          '{"answer": "no"}'),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=5.0,
            observer=self._watch([])).run("fetch a1")
        assert calls == []

    def test_a_wait_that_runs_out_ends_exactly_where_it_always_did(
            self, bus, tmp_path, steering):
        """Nothing times out into a yes. The record stays pending and
        `--approval` on a later turn still works."""
        from core.runtime.approvals import PENDING
        from core.runtime.mission import AWAITING_APPROVAL

        store = self._store(tmp_path)
        steer = steering()
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=0.15,
            observer=events.append).run("fetch a1")

        assert transcript.outcome == AWAITING_APPROVAL
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert store.get(gate["approval_id"]).state == PENDING
        assert transcript.awaiting["approval_id"] == gate["approval_id"]

    def test_a_decision_signed_by_nobody_is_dropped_and_the_wait_goes_on(
            self, bus, tmp_path, steering):
        """The command never reaches the loop, so the gate is still open
        when the wait runs out — which is the difference between refusing
        a bad command and answering with it."""
        from core.runtime.approvals import PENDING
        from core.runtime.mission import AWAITING_APPROVAL

        store = self._store(tmp_path)
        steer = steering()
        events = []
        self._answering(steer, who="")
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=0.4,
            observer=self._watch(events)).run("fetch a1")

        assert transcript.outcome == AWAITING_APPROVAL
        assert store.get(self._pending[0]).state == PENDING

    def test_a_decision_for_another_gate_is_not_this_gates_answer(
            self, bus, tmp_path, steering):
        from core.runtime.mission import AWAITING_APPROVAL

        store = self._store(tmp_path)
        steer = steering()
        steer.send(control="gate_decision", approval_id="ap_somebody_else",
                   approve=True, decided_by="dana")
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=0.2).run("fetch a1")
        assert transcript.outcome == AWAITING_APPROVAL

    def test_without_an_approval_store_there_is_nothing_to_wait_for(
            self, bus, steering):
        """No store is no id, and an unrecorded yes is the standing
        permission the approvals module exists not to have."""
        from core.runtime.mission import AWAITING_APPROVAL

        steer = steering()
        events = []
        started = time.monotonic()
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=None,
            control=steer.channel, gate_wait_s=30.0,
            observer=events.append).run("fetch a1")
        assert transcript.outcome == AWAITING_APPROVAL
        assert time.monotonic() - started < 5.0

    def test_a_run_with_no_channel_does_not_wait_at_all(self, bus, tmp_path):
        from core.runtime.mission import AWAITING_APPROVAL

        started = time.monotonic()
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"],
            approvals=self._store(tmp_path), gate_wait_s=30.0,
        ).run("fetch a1")
        assert transcript.outcome == AWAITING_APPROVAL
        assert time.monotonic() - started < 5.0

    def test_the_wait_never_outlasts_the_runs_own_deadline(
            self, bus, tmp_path, steering):
        """A run that waited five minutes for a person and then reported
        that it had run out of seconds would have spent the operator's whole
        budget standing still."""
        from core.budgets import Deadline

        clock = _Clock()
        deadline = Deadline(0.0, monotonic=clock).start()
        steer = steering()
        runner = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"],
            approvals=self._store(tmp_path), control=steer.channel,
            deadline=deadline, gate_wait_s=300.0)
        assert runner._gate_window() == 0.0

    def test_the_reason_says_a_decision_can_arrive_in_turn(
            self, bus, tmp_path, steering):
        """The request is what the platform reads, so it has to say what
        answering it will do."""
        steer = steering()
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"],
            approvals=self._store(tmp_path), control=steer.channel,
            gate_wait_s=0.1, observer=events.append).run("fetch a1")
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "control channel" in gate["reason"]

    def test_that_sentence_is_absent_where_nobody_can_answer(
            self, bus, tmp_path):
        events = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"],
            approvals=self._store(tmp_path), observer=events.append,
        ).run("fetch a1")
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "control channel" not in gate["reason"]

    def test_a_native_turns_later_calls_run_after_an_approval(
            self, bus, tmp_path, steering):
        """The gate held them rather than dropping them, which is what the
        reason says when a decision can arrive."""
        store = self._store(tmp_path)
        steer = steering()
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]
        self._answering(steer)
        model = NativeModel(
            [native_call("catalog.get", "c0", asset_id="a1"),
             native_call("catalog.search", "c1", q="after")],
            answer_call("done"))
        # Built directly rather than through `native_runner`, which owns
        # the observer keyword and this test needs the one that learns the
        # `approval_id` off the stream — which is how a platform learns it.
        transcript = MissionRunner(
            model, bus, ["catalog.search", "catalog.get"],
            protocol=NATIVE_PROTOCOL, tool_calls_fn=model.tool_calls,
            store_tool="", gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=5.0,
            observer=self._watch([])).run("go")
        assert calls == ["catalog.get", "catalog.search"]
        assert transcript.outcome == "answered"

    def test_the_native_reason_says_held_rather_than_dropped(
            self, bus, tmp_path, steering):
        steer = steering()
        events = []
        model = NativeModel(
            [native_call("catalog.get", "c0", asset_id="a1"),
             native_call("catalog.search", "c1", q="after")],
            answer_call("done"))
        native_runner(bus, model, gated=["catalog.get"],
                      approvals=self._store(tmp_path), control=steer.channel,
                      gate_wait_s=0.1, events=events).run("go")
        gate = [r for r in events if r["event"] == "gate_requested"][0]
        assert "HELD" in gate["reason"]
        assert "NOT dispatched" not in gate["reason"]

    def test_a_decision_that_cannot_be_recorded_fails_closed(
            self, bus, tmp_path, steering):
        """Somebody answered the record out of band. The call is not made:
        failing closed is the only direction a gate may fail in."""
        from core.runtime.mission import AWAITING_APPROVAL

        store = self._store(tmp_path)
        steer = steering()
        calls = []
        real = bus.dispatch
        bus.dispatch = lambda name, **kw: (calls.append(name),
                                           real(name, **kw))[1]

        def answer():
            import time

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if self._pending:
                    # Resolved underneath the run, by somebody else.
                    store.decide(self._pending[0], approve=False,
                                 decided_by="somebody else")
                    steer.send(control="gate_decision",
                               approval_id=self._pending[0], approve=True,
                               decided_by="dana")
                    return
                time.sleep(0.005)

        import threading

        self._pending = []
        threading.Timer(0.0, answer).start()
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.get", asset_id="a1")),
            bus, ["catalog.get"], gated=["catalog.get"], approvals=store,
            control=steer.channel, gate_wait_s=3.0,
            observer=self._watch(events)).run("fetch a1")

        assert calls == []
        assert transcript.outcome == AWAITING_APPROVAL
        assert "could NOT be recorded" in transcript.steps[0].error


class TestTheSecondOpinionRidesTheGroundingRecord:
    """A critic's verdict is surfaced beside `grounded` and never inside it.

    `grounded` is a mechanical fact anybody holding the transcript can
    recompute. A critic's verdict varies with sampling, with which provider
    had a key today, and with a prompt somebody may edit next month —
    latching one onto the other would make a governance field
    unreproducible while the record went on looking exactly the same.
    """

    class Critic:
        """A stand-in for `core.critic.mission.MissionCritic`.

        Duck-typed here for the reason the runner duck-types it: `core.critic`
        pulls in pydantic and a transport, and a mission not using a critic
        must not pay for either.
        """

        def __init__(self, row=None, boom=False):
            self.row = row
            self.boom = boom
            self.seen = []

        def review(self, answer, evidence, **kw):
            if self.boom:
                raise RuntimeError("the far end went away")
            self.seen.append({"answer": answer, "evidence": list(evidence),
                              **kw})
            if not kw.get("answered_with_caveat"):
                return None
            return _Opinion(self.row or {
                "check": "critic", "advisory": True, "configured": True,
                "grounded": False, "verdict": "fail", "considered": 1,
                "minimum": 0, "unsupported": ["the SDK never ran"],
                "detail": "stub disputes this answer"})

    def run(self, asset_bus, strict, critic, answers):
        events = []
        transcript = MissionRunner(
            ScriptedModel(tool_call("catalog.search"), *answers),
            asset_bus, ["catalog.search"], validator=strict,
            critic=critic, observer=events.append,
        ).run("go")
        return transcript, [r for r in events if r["event"] == "grounding"]

    #: Two drafts that both fail the grammar, so the run ends
    #: `answered_with_caveat` after its one repair turn.
    UNGROUNDED = ('{"answer": "The label set is labels.7a19c4e2."}',
                  '{"answer": "The label set is labels.7a19c4e2."}')

    def test_no_critic_means_no_row_and_the_stream_is_unchanged(
            self, asset_bus, strict):
        transcript, records = self.run(asset_bus, strict, None, self.UNGROUNDED)
        assert transcript.outcome == "answered_with_caveat"
        assert all(row["check"] != "critic"
                   for record in records for row in record["checks"])

    def test_the_verdict_arrives_on_the_final_record(self, asset_bus, strict):
        critic = self.Critic()
        transcript, records = self.run(asset_bus, strict, critic,
                                       self.UNGROUNDED)
        assert transcript.outcome == "answered_with_caveat"
        final = records[-1]
        assert final["repairing"] is False
        row = next(r for r in final["checks"] if r["check"] == "critic")
        assert row["verdict"] == "fail"
        assert row["detail"] == "stub disputes this answer"

    def test_it_does_not_ride_the_interim_repairing_record(
            self, asset_bus, strict):
        """A repair turn is work in progress and a consumer is told not to
        latch it. Paying for a second opinion on a draft about to be
        rewritten would buy an opinion about text nobody keeps."""
        _t, records = self.run(asset_bus, strict, self.Critic(),
                               self.UNGROUNDED)
        interim = [r for r in records if r["repairing"]]
        assert interim, "this run has to spend a repair turn or it proves nothing"
        assert all(row["check"] != "critic"
                   for record in interim for row in record["checks"])

    def test_a_failing_critic_does_not_move_grounded(self, asset_bus, strict):
        """The whole rule, in one assertion. The row says `fail`; the
        mechanical verdict is whatever the arithmetic said."""
        _t, records = self.run(asset_bus, strict, self.Critic(),
                               self.UNGROUNDED)
        final = records[-1]
        mechanical = [r for r in final["checks"] if not r["advisory"]]
        assert final["grounded"] == all(
            r["grounded"] for r in mechanical if r["configured"])

    def test_a_failing_critic_on_a_clean_answer_cannot_break_it(
            self, asset_bus, strict):
        """It is not even asked: no rule in `core.critic.triggers` fires on
        a clean answer, and the stub returns `None` accordingly."""
        critic = self.Critic()
        transcript, records = self.run(
            asset_bus, strict, critic,
            ('{"answer": "The corpus is asset.5f21c9."}',))
        assert transcript.outcome == "answered"
        assert records[-1]["grounded"] is True
        assert all(row["check"] != "critic" for row in records[-1]["checks"])
        assert critic.seen[-1]["answered_with_caveat"] is False, (
            "the trigger decision has one owner and the loop still asks it")

    def test_every_mechanical_row_says_it_is_not_advisory(
            self, asset_bus, strict):
        """Stated on both kinds so a consumer never infers it from a name."""
        _t, records = self.run(asset_bus, strict, self.Critic(),
                               self.UNGROUNDED)
        rows = records[-1]["checks"]
        assert [r["advisory"] for r in rows] == \
            [False] * (len(rows) - 1) + [True]

    def test_the_critic_is_shown_the_store_and_the_findings(
            self, asset_bus, strict):
        critic = self.Critic()
        self.run(asset_bus, strict, critic, self.UNGROUNDED)
        asked = critic.seen[-1]
        assert asked["objective"] == "go"
        assert "labels.7a19c4e2" in asked["unsupported"]
        assert asked["evidence"], "the critic judged an answer with no evidence"

    def test_a_critic_that_explodes_does_not_take_the_mission_with_it(
            self, asset_bus, strict):
        """A second opinion that could take a run down would be strictly
        worse than not having one: the draft exists, the mechanical verdict
        is computed, and the only thing missing is an opinion."""
        transcript, records = self.run(asset_bus, strict,
                                       self.Critic(boom=True), self.UNGROUNDED)
        assert transcript.outcome == "answered_with_caveat"
        row = next(r for r in records[-1]["checks"] if r["check"] == "critic")
        assert row["verdict"] == "skipped"
        assert "the far end went away" in row["detail"]

    def test_the_records_still_conform(self, asset_bus, strict):
        _t, records = self.run(asset_bus, strict, self.Critic(),
                               self.UNGROUNDED)
        assert [conforms(record) for record in records] == \
            [[] for _ in records]


class _Opinion:
    """The one method `MissionRunner` calls on a critic's answer."""

    def __init__(self, row):
        self.row = row

    def as_check(self):
        return dict(self.row)
