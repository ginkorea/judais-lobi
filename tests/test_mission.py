# tests/test_mission.py — the loop where the model chooses the tool

import json

import pytest

from core import redact
from core.contracts.schemas import PolicyPack
from core.runtime import contract
from core.runtime.context_window import ContextConfig, MissionWindow
from core.runtime.contract import conforms
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionRunner, MissionTranscript
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
