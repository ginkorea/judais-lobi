# tests/test_agui.py — the mission stream, spoken as AG-UI

"""Every stream under test here is a **real one**.

The fixtures run a `MissionRunner` with a scripted model and collect what its
observer was handed, so the translator is fed the records the harness actually
writes rather than the records somebody remembered it writing. That is the
whole reason this file is longer than it would be with hand-built dicts: a
translator tested against a fixture the test author invented passes for as long
as the author's memory holds, which on the evidence of the reference deployment
is about one release.

`ScriptedModel` is copied rather than imported from `tests/test_mission.py` —
it is eight lines, and importing a fixture out of another test module ties two
suites together at exactly the point where one of them is free to change.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime import agui, contract
from core.runtime.agui import Translator, translate
from core.runtime.contract import conforms
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionRunner
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


ID_PATTERN = r"\b(?:asset|labels|run)\.[0-9a-f]{4,}\b"

#: A result long enough that a translator inclined to bound it would have to.
LONG_OUTPUT = "asset.5f21c9 — Taiwan narrative corpus\n" + ("detail line\n" * 400)


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


@pytest.fixture
def bus():
    b = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search", description="Search."),
        lambda **_kw: (0, LONG_OUTPUT, ""),
    )
    b.register(
        ToolDescriptor(tool_name="catalog.publish", description="Publish."),
        lambda **_kw: (0, "published", ""),
    )
    return b


@pytest.fixture
def strict():
    return GroundingValidator.from_config(
        GroundingConfig(identifier_pattern=ID_PATTERN))


@pytest.fixture
def answered(bus, strict):
    """One real run that reaches eight of the nine events.

    A reply the loop cannot act on, a tool call and its result, a draft answer
    the validator catches (the interim `grounding`), the repair turn, the
    second failure that gets caveated rather than deleted (the verdict
    `grounding`), the `answer`, and the finish.
    """
    records = []
    MissionRunner(
        ScriptedModel(
            "not json",
            tool_call("catalog.search", q="taiwan"),
            '{"answer": "labels.7a19c4e2 is the set."}',
            '{"answer": "It is definitely labels.7a19c4e2."}'),
        bus, ["catalog.search"], validator=strict,
        observer=records.append, max_steps=8, run_id="run-7",
    ).run("go")
    return records


@pytest.fixture
def gated(bus):
    """The ninth event. A gate ends the mission where it fires, so a run that
    is gated never answers and a run that answers was never gated."""
    records = []
    MissionRunner(
        ScriptedModel(tool_call("catalog.publish", body="x")),
        bus, ["catalog.search", "catalog.publish"],
        gated=["catalog.publish"], observer=records.append, max_steps=4,
    ).run("go")
    return records


def frames_of(records, **kw):
    return list(translate(records, **kw))


def types_of(frames):
    return [f["type"] for f in frames]


def customs(frames, name):
    return [f["value"] for f in frames
            if f["type"] == agui.CUSTOM and f["name"] == name]


# ---------------------------------------------------------------------------
# The contract is what this module is written against
# ---------------------------------------------------------------------------

#: A value of the right shape per field name, for building one conforming
#: record of every event the contract declares. The empty-string default is
#: deliberate: a field this table has never heard of is exactly what an event
#: added tomorrow will carry, and the translator must survive it.
_PLACEHOLDER = {
    "schema_version": contract.SCHEMA_VERSION, "objective": "go",
    "catalogue": ["catalog.search"], "gated": [], "max_steps": 4,
    "history": 0, "index": 0, "call": 0, "problem": "not json",
    "tool": "catalog.search", "arguments": {"q": "x"}, "ok": True,
    "exit_code": 0, "output": "hits", "error": "", "handle": "r1",
    "truncated": False, "reason": "because", "text": "the answer",
    "outcome": "answered", "ran": True, "grounded": True, "verified": True,
    "repairs": 0, "repairing": False, "caveat": "", "unsupported": [],
    "silent": [], "uncited": [], "checks": [], "steps": 1, "part": 0,
}


def conforming(event):
    record = {"event": event}
    for name in contract.FIELDS.get(event, ()):
        record[name] = _PLACEHOLDER.get(name, "")
    assert conforms(record) == []
    return record


class TestTheContractIsCovered:
    """`HANDLED` is computed from the contract and then held equal to it.

    That is the load-bearing test of this file. A tenth event added to
    `core.runtime.contract` fails here, and it goes on failing until somebody
    decides what a browser should see for it — which is a decision, rather
    than a frame nobody noticed going missing.
    """

    def test_every_event_the_contract_declares_has_a_mapping(self):
        assert agui.HANDLED == frozenset(contract.EVENTS)

    @pytest.mark.parametrize("event", contract.EVENTS)
    def test_a_conforming_record_of_every_event_produces_frames(self, event):
        frames = Translator(thread_id="t").feed(conforming(event))
        assert frames, f"{event} produced nothing"
        assert all(f["type"] in agui.AG_UI_TYPES for f in frames)

    def test_a_record_type_this_module_does_not_know_is_dropped(self):
        """The contract's own rule for a consumer: a turn must not fail over
        an event the harness grew and this pane has no opinion about."""
        translator = Translator()
        assert translator.feed({"event": "telemetry", "index": 0}) == []

    def test_an_event_the_contract_has_not_declared_does_not_fire_its_handler(
            self, monkeypatch):
        """The gate is the contract's vocabulary and not this class's method
        names. A handler for an event the contract does not declare — which is
        what an unmerged half of a release looks like from here — must stay
        silent rather than emit frames for a record type nobody has agreed
        exists."""
        monkeypatch.setattr(
            contract, "EVENTS",
            tuple(e for e in contract.EVENTS if e != contract.GROUNDING))
        record = conforming(contract.GROUNDING)
        assert Translator()._on_grounding(record), "the handler is still there"
        assert Translator().feed(record) == []

    def test_something_that_is_not_a_record_at_all_is_dropped(self):
        assert Translator().feed("mission_started") == []


# ---------------------------------------------------------------------------
# A real run, frame by frame
# ---------------------------------------------------------------------------

class TestARealRunTranslates:
    def test_the_stream_opens_with_a_run_and_closes_with_one(self, answered):
        frames = frames_of(answered, thread_id="t1")
        assert frames[0]["type"] == agui.RUN_STARTED
        assert frames[-1]["type"] == agui.RUN_FINISHED
        assert frames[0]["threadId"] == "t1"

    def test_the_run_id_defaults_to_the_one_the_harness_announced(self, answered):
        assert frames_of(answered)[0]["runId"] == "run-7"

    def test_the_caller_s_run_id_wins(self, answered):
        assert frames_of(answered, run_id="mine")[0]["runId"] == "mine"

    def test_the_opening_frame_carries_the_posture_the_harness_stated(
            self, answered):
        opening = customs(frames_of(answered), agui.CUSTOM_OPENING)[0]
        assert "catalog.search" in opening["catalogue"]
        assert opening["gated"] == []
        assert opening["max_steps"] == 8
        assert opening["sandbox"] in ("bwrap", "none")
        assert opening["run_id"] == "run-7"

    def test_a_field_the_harness_did_not_state_is_not_invented(self, answered):
        """Absence travels as absence. A `profile: safe` conjured for a run
        that never mentioned one is the translator asserting the safest
        possible thing about a run it knows nothing about."""
        started = next(r for r in answered if r["event"] == "mission_started")
        opening = customs(frames_of(answered), agui.CUSTOM_OPENING)[0]
        assert set(opening) == set(started) - {"event"}

    def test_a_step_is_started_and_finished(self, answered):
        kinds = types_of(frames_of(answered))
        assert kinds.count(agui.STEP_STARTED) == kinds.count(agui.STEP_FINISHED)
        assert kinds.count(agui.STEP_STARTED) == len(
            [r for r in answered if r["event"] == "step_started"])

    def test_what_the_harness_said_about_a_step_gets_its_own_custom(self, bus):
        """A real compaction: the conversation had to be shortened to fit the
        model's window, and an agent whose earlier evidence quietly left its
        prompt looks from outside exactly like an agent that had it all along.

        Its own frame rather than a field of `STEP_STARTED`, because a
        frontend with an opinion about compaction should not have to unpack a
        frame about steps to find it.
        """
        from core.runtime.context_window import ContextConfig, MissionWindow

        records = []
        MissionRunner(
            ScriptedModel(*([tool_call("catalog.search", q="x")] * 5),
                          '{"answer": "ok"}'),
            bus, ["catalog.search"], max_steps=8, observer=records.append,
            window=MissionWindow(config=ContextConfig(
                max_context_tokens=1200, max_output_tokens=200)),
        ).run("go")
        compacted = [r for r in records
                     if r["event"] == "step_started" and "compacted" in r]
        assert compacted, "the fixture is supposed to compact"
        frames = customs(frames_of(records), agui.CUSTOM_PREFIX + "compacted")
        assert len(frames) == len(compacted)
        assert frames[0]["compacted"] == compacted[0]["compacted"]
        assert frames[0]["index"] == compacted[0]["index"]

    def test_a_field_the_harness_adds_later_gets_one_too(self):
        """Read off the record rather than off a list here, so `resumed`,
        `injected` and whatever comes after them arrive without an edit."""
        record = dict(conforming(contract.STEP_STARTED), whatever={"a": 1})
        names = [f["name"] for f in Translator().feed(record)
                 if f["type"] == agui.CUSTOM]
        assert names == ["mission.whatever"]

    def test_the_step_is_named_for_its_index(self, answered):
        names = [f["stepName"] for f in frames_of(answered)
                 if f["type"] == agui.STEP_STARTED]
        assert names[0] == "step-0"
        assert names == [f"step-{r['index']}" for r in answered
                         if r["event"] == "step_started"]


class TestAToolCall:
    def test_it_becomes_start_args_end_result_in_that_order(self, answered):
        kinds = [k for k in types_of(frames_of(answered))
                 if k.startswith("TOOL_CALL")]
        assert kinds == [agui.TOOL_CALL_START, agui.TOOL_CALL_ARGS,
                         agui.TOOL_CALL_END, agui.TOOL_CALL_RESULT]

    def test_the_call_and_its_result_share_a_minted_id(self, answered):
        frames = [f for f in frames_of(answered) if f["type"].startswith("TOOL_CALL")]
        assert {f["toolCallId"] for f in frames} == {"call-1-0"}

    def test_the_arguments_go_out_as_json_with_sorted_keys(self, bus):
        records = []
        MissionRunner(
            ScriptedModel(tool_call("catalog.search", q="x", limit=2, a="b"),
                          '{"answer": "ok"}'),
            bus, ["catalog.search"], observer=records.append,
        ).run("go")
        args = next(f for f in frames_of(records)
                    if f["type"] == agui.TOOL_CALL_ARGS)
        assert args["delta"] == '{"a": "b", "limit": 2, "q": "x"}'

    def test_the_output_travels_verbatim_and_is_never_truncated(self, answered):
        """Bounding is the caller's, made where the socket is. `truncated`
        describes what the MODEL was shown."""
        result = next(f for f in frames_of(answered)
                      if f["type"] == agui.TOOL_CALL_RESULT)
        assert result["content"] == LONG_OUTPUT
        assert len(result["content"]) > agui.ANSWER_DELTA_LIMIT

    def test_the_mechanics_of_the_result_ride_the_frame(self, answered):
        result = next(f for f in frames_of(answered)
                      if f["type"] == agui.TOOL_CALL_RESULT)
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["handle"]
        assert result["truncated"] is False
        assert result["toolName"] == "catalog.search"

    def test_a_result_whose_call_this_stream_never_carried_still_opens_one(self):
        """A follower that joined between the two halves. The result has to be
        attributable or nothing downstream can tie it to a tool."""
        frames = Translator().feed(conforming(contract.TOOL_RESULT))
        assert types_of(frames)[:2] == [agui.RUN_STARTED, agui.TOOL_CALL_START]

    def test_a_call_with_no_result_is_closed_at_the_end(self, bus):
        """A gated tool is never dispatched and a dead harness never reports.
        Left open, it is an argument stream a frontend waits on forever."""
        records = [conforming(contract.TOOL_CALL)]
        kinds = types_of(frames_of(records))
        assert kinds.count(agui.TOOL_CALL_END) == 1
        assert kinds.index(agui.TOOL_CALL_END) < kinds.index(agui.RUN_ERROR)


# ---------------------------------------------------------------------------
# A rejected reply is mechanics
# ---------------------------------------------------------------------------

class TestARejectedReplyIsMechanics:
    """The loop's correction prompt is the harness talking to the model about
    shape. Rendered as content it reads as the agent saying something
    incoherent to the analyst, which is what the reference deployment shipped
    first and then had to undo."""

    def test_it_never_becomes_a_text_message(self, answered):
        rejected = [r for r in answered if r["event"] == "reply_rejected"]
        assert rejected, "the fixture is supposed to contain one"
        frames = frames_of(answered)
        problems = [r["problem"] for r in rejected]
        for frame in frames:
            if frame["type"].startswith("TEXT_MESSAGE"):
                assert frame.get("delta", "") not in problems
                assert not any(p and p in frame.get("delta", "")
                               for p in problems)

    def test_the_problem_reaches_the_consumer_as_a_custom(self, answered):
        held = customs(frames_of(answered), agui.CUSTOM_REPLY_REJECTED)
        assert len(held) == 1
        assert held[0]["problem"]

    def test_the_frame_says_it_is_mechanics(self, answered):
        """Marked so a consumer can branch on it — hold the rejections and
        flush them only for a turn that ended without an answer — rather than
        having to know the convention."""
        assert customs(frames_of(answered),
                       agui.CUSTOM_REPLY_REJECTED)[0]["mechanics"] is True


# ---------------------------------------------------------------------------
# The verdict rides the answer's own frames
# ---------------------------------------------------------------------------

class TestTheGroundingVerdict:
    def test_the_report_names_the_message_it_judges(self, answered):
        """The lesson. A report delivered as a sibling of the answer is one a
        renderer has to guess the subject of, and it will guess wrong."""
        frames = frames_of(answered)
        reports = customs(frames, agui.CUSTOM_GROUNDING)
        answer = customs(frames, agui.CUSTOM_ANSWER)[0]
        verdict = [r for r in reports if not r["repairing"]][-1]
        assert verdict["messageId"] == answer["messageId"]
        assert answer["messageId"] in {f.get("messageId")
                                       for f in frames
                                       if f["type"] == agui.TEXT_MESSAGE_START}

    def test_the_whole_report_travels(self, answered):
        record = [r for r in answered
                  if r["event"] == "grounding" and not r["repairing"]][-1]
        report = [r for r in customs(frames_of(answered), agui.CUSTOM_GROUNDING)
                  if not r["repairing"]][-1]
        assert set(report) == set(record) - {"event"} | {"messageId"}
        assert report["verified"] == record["verified"]
        assert report["checks"] == record["checks"]

    def test_an_interim_report_does_not_close_the_message(self, answered):
        """A repair turn is a whole extra round-trip and looks like a stall,
        so it is emitted — and it must not end anything."""
        interim = [r for r in answered
                   if r["event"] == "grounding" and r["repairing"]]
        assert interim, "the fixture is supposed to spend a repair turn"
        frames = Translator().feed(interim[0])
        assert agui.TEXT_MESSAGE_END not in types_of(frames)
        assert types_of(frames) == [agui.RUN_STARTED, agui.CUSTOM]

    def test_an_interim_report_is_not_latched_as_the_verdict(self, answered):
        """`repairing: true` is work in progress. A consumer that latched it
        would badge the answer with the finding that was then repaired.

        The stream that proves it is the one where an interim report is the
        ONLY report: nothing may be marked from it, because the loop had not
        finished deciding. In a run that goes on to produce a verdict the
        second report simply wins, which is the same rule seen from the other
        side.
        """
        interim = next(r for r in answered
                       if r["event"] == "grounding" and r["repairing"])
        alone = [interim, {"event": "answer", "text": "draft",
                           "outcome": "answered"}]
        frames = frames_of(alone)
        assert customs(frames, agui.CUSTOM_ANSWER)[0].get("grounding") is None
        assert all("grounding" not in f for f in frames
                   if f["type"] == agui.TEXT_MESSAGE_CONTENT)

    def test_the_second_report_is_the_verdict(self, answered):
        frames = frames_of(answered)
        final = [r for r in answered
                 if r["event"] == "grounding" and not r["repairing"]][-1]
        carried = customs(frames, agui.CUSTOM_ANSWER)[0]["grounding"]
        assert carried["repairing"] is False
        assert carried["repairs"] == final["repairs"]
        assert carried["caveat"] == final["caveat"]

    def test_every_frame_of_the_answer_carries_it(self, answered):
        """Not one frame beside them. A reconnect resuming from a cursor
        between two frames must not be able to separate an ungrounded answer
        from the fact that it is one."""
        deltas = [f for f in frames_of(answered)
                  if f["type"] == agui.TEXT_MESSAGE_CONTENT]
        assert deltas
        assert all("grounding" in f for f in deltas)
        assert all(f["grounding"]["grounded"] is False for f in deltas)

    def test_the_bulky_half_stays_off_the_answer_s_frames(self, answered):
        """`checks` is the per-check detail and a badge does not need it; it
        is on the report in full. Stated as what is OMITTED, so a field the
        contract adds to `grounding` reaches the frames it qualifies without
        this module being edited."""
        delta = next(f for f in frames_of(answered)
                     if f["type"] == agui.TEXT_MESSAGE_CONTENT)
        assert "checks" not in delta["grounding"]
        assert agui.VERDICT_OMITS == ("checks",)
        assert set(delta["grounding"]) == set(
            contract.FIELDS[contract.GROUNDING]) - {"checks"}

    def test_an_ungrounded_run_that_never_checked_carries_no_verdict(self, bus):
        """No validator, no report, no marking. An absent report and a clean
        one are different facts."""
        records = []
        MissionRunner(ScriptedModel('{"answer": "ok"}'), bus,
                      ["catalog.search"], observer=records.append).run("go")
        frames = frames_of(records)
        assert customs(frames, agui.CUSTOM_GROUNDING) == []
        assert all("grounding" not in f for f in frames
                   if f["type"] == agui.TEXT_MESSAGE_CONTENT)


# ---------------------------------------------------------------------------
# The answer, in frames
# ---------------------------------------------------------------------------

class TestTheAnswerArrivesInFrames:
    def test_it_is_fanned_out_when_the_harness_emitted_no_deltas(self, answered):
        record = next(r for r in answered if r["event"] == "answer")
        frames = frames_of(answered)
        kinds = [k for k in types_of(frames) if k.startswith("TEXT_MESSAGE")]
        assert kinds[0] == agui.TEXT_MESSAGE_START
        assert kinds[-1] == agui.TEXT_MESSAGE_END
        joined = "".join(f["delta"] for f in frames
                         if f["type"] == agui.TEXT_MESSAGE_CONTENT)
        assert joined == record["text"]

    def test_the_custom_states_the_authoritative_text_and_outcome(self, answered):
        record = next(r for r in answered if r["event"] == "answer")
        answer = customs(frames_of(answered), agui.CUSTOM_ANSWER)[0]
        assert answer["text"] == record["text"]
        assert answer["outcome"] == record["outcome"] == "answered_with_caveat"

    def test_the_message_is_named_for_the_step_it_was_written_on(self, answered):
        last_step = [r["index"] for r in answered
                     if r["event"] == "step_started"][-1]
        answer = customs(frames_of(answered), agui.CUSTOM_ANSWER)[0]
        assert answer["messageId"] == f"msg-{last_step}"

    def test_a_long_answer_is_split_into_bounded_frames(self, bus):
        long_answer = "\n".join(f"paragraph {n}" for n in range(900))
        records = []
        MissionRunner(
            ScriptedModel(json.dumps({"answer": long_answer})), bus,
            ["catalog.search"], observer=records.append).run("go")
        deltas = [f["delta"] for f in frames_of(records)
                  if f["type"] == agui.TEXT_MESSAGE_CONTENT]
        assert len(deltas) > 1
        assert "".join(deltas) == long_answer

    def test_the_ceiling_is_the_caller_s(self, answered):
        record = next(r for r in answered if r["event"] == "answer")
        deltas = [f["delta"] for f in frames_of(answered, delta_limit=8)
                  if f["type"] == agui.TEXT_MESSAGE_CONTENT]
        assert len(deltas) > 1
        assert "".join(deltas) == record["text"]


class TestAnswerDeltasTheFunction:
    def test_the_frames_concatenate_to_the_answer(self):
        text = "\n".join(f"line {n}" for n in range(2000))
        assert "".join(agui.answer_deltas(text)) == text

    def test_a_short_answer_is_one_frame(self):
        assert agui.answer_deltas("short") == ["short"]

    def test_a_fenced_block_is_never_split(self):
        fence = "```python\n" + "x = 1\n" * 600 + "```"
        text = "before\n" + fence + "\nafter\n"
        deltas = agui.answer_deltas(text, limit=200)
        assert "".join(deltas) == text
        assert any(fence in d for d in deltas), "the fence was split"

    def test_one_over_long_line_ships_whole(self):
        """A bounded frame is hygiene and a broken token is a correctness
        failure, so when the two conflict the limit loses."""
        line = "x" * 5000
        deltas = agui.answer_deltas(line, limit=100)
        assert deltas == [line]


class TestWhenTheHarnessEmitsRealDeltas:
    """Lane X adds `answer_delta` to the contract. This module translates it
    the moment the contract declares it, which is what these tests establish —
    by declaring it the way the contract will, so the path is exercised on
    either side of that merge rather than skipped on one of them.
    """

    @pytest.fixture
    def declared(self, monkeypatch):
        if "answer_delta" in contract.EVENTS:
            return "answer_delta"
        monkeypatch.setattr(contract, "EVENTS",
                            tuple(contract.EVENTS) + ("answer_delta",))
        return "answer_delta"

    def stream(self, declared, parts=("the ", "answer")):
        return ([{"event": "step_started", "index": 3}]
                + [{"event": declared, "index": 3, "part": n, "text": t}
                   for n, t in enumerate(parts)]
                + [{"event": "answer", "text": "the answer",
                    "outcome": "answered"}])

    def test_the_deltas_are_relayed_as_they_arrive(self, declared):
        frames = frames_of(self.stream(declared))
        deltas = [f["delta"] for f in frames
                  if f["type"] == agui.TEXT_MESSAGE_CONTENT]
        assert deltas == ["the ", "answer"]

    def test_the_message_opens_once_for_the_step(self, declared):
        kinds = types_of(frames_of(self.stream(declared, ("a", "b", "c"))))
        assert kinds.count(agui.TEXT_MESSAGE_START) == 1
        assert kinds.count(agui.TEXT_MESSAGE_END) == 1

    def test_the_answer_record_closes_the_message_and_does_not_fan_out(
            self, declared):
        """The record always follows and is authoritative; fanning it out on
        top of the deltas would deliver the answer twice."""
        frames = frames_of(self.stream(declared))
        deltas = [f["delta"] for f in frames
                  if f["type"] == agui.TEXT_MESSAGE_CONTENT]
        assert deltas == ["the ", "answer"]
        assert types_of(frames).count(agui.TEXT_MESSAGE_END) == 1

    def test_the_authoritative_text_replaces_the_provisional_one(self, declared):
        """The harness may have appended a caveat or spent a repair turn since
        the first delta went out, so the accumulated fragments are not the
        answer — the record is."""
        stream = self.stream(declared, ("the ", "draft"))
        answer = customs(frames_of(stream), agui.CUSTOM_ANSWER)[0]
        assert answer["text"] == "the answer"
        assert answer["messageId"] == "msg-3"

    def test_an_interim_report_leaves_an_open_message_open(self, declared,
                                                           answered):
        """The case the fan-out cannot reach: prose is already streaming when
        the validator catches something and the loop spends a repair turn. The
        report is emitted — it is the thing that looks like a stall — and the
        message it interrupts must still be open afterwards, or the consumer
        ends a message the harness has not finished writing.
        """
        interim = next(r for r in answered
                       if r["event"] == "grounding" and r["repairing"])
        stream = [{"event": "step_started", "index": 3},
                  {"event": declared, "index": 3, "part": 0, "text": "draft"},
                  interim,
                  {"event": declared, "index": 3, "part": 1, "text": " more"},
                  {"event": "answer", "text": "final", "outcome": "answered"}]
        kinds = types_of(frames_of(stream))
        assert kinds.count(agui.TEXT_MESSAGE_START) == 1
        assert kinds.count(agui.TEXT_MESSAGE_END) == 1
        last_delta = max(n for n, k in enumerate(kinds)
                         if k == agui.TEXT_MESSAGE_CONTENT)
        assert kinds.index(agui.TEXT_MESSAGE_END) > last_delta

    def test_the_deltas_are_hung_on_the_step_they_name(self, declared):
        start = next(f for f in frames_of(self.stream(declared))
                     if f["type"] == agui.TEXT_MESSAGE_START)
        assert start["messageId"] == "msg-3"
        assert start["role"] == "assistant"


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class TestAGate:
    def test_it_is_a_custom_and_not_a_tool_call(self, gated):
        """Nothing was dispatched. A frontend shown `TOOL_CALL_START` for a
        call that will never run shows work in progress for a mission that has
        stopped."""
        frames = frames_of(gated)
        assert customs(frames, agui.CUSTOM_GATE_REQUESTED)
        assert not [f for f in frames if f["type"].startswith("TOOL_CALL")]

    def test_the_arguments_travel_verbatim(self, gated):
        """What a person approves has to be the bytes that would run."""
        record = next(r for r in gated if r["event"] == "gate_requested")
        proposed = customs(frames_of(gated), agui.CUSTOM_GATE_REQUESTED)[0]
        assert proposed["arguments"] == record["arguments"] == {"body": "x"}
        assert proposed["tool"] == "catalog.publish"
        assert proposed["reason"] == record["reason"]

    def test_the_run_still_finishes(self, gated):
        frames = frames_of(gated)
        assert frames[-1]["type"] == agui.RUN_FINISHED
        assert frames[-1]["outcome"] == "awaiting_approval"


# ---------------------------------------------------------------------------
# How a run ends
# ---------------------------------------------------------------------------

class TestHowARunEnds:
    def test_an_answered_run_finishes(self, answered):
        last = frames_of(answered)[-1]
        assert last["type"] == agui.RUN_FINISHED
        assert last["outcome"] == "answered_with_caveat"
        assert last["steps"] == 4
        assert last["max_steps"] == 8
        assert "cancelled" not in last

    def test_the_ledger_rides_the_finish_when_the_harness_stated_it(
            self, answered):
        last = frames_of(answered)[-1]
        assert isinstance(last["elapsed_s"], float)

    def test_budget_exhausted_is_a_finish_and_names_the_budget(self, bus):
        """A run that hit a hard bound did what it was told."""
        records = []
        MissionRunner(
            ScriptedModel(*[tool_call("catalog.search", q="x")] * 4),
            bus, ["catalog.search"], max_steps=2, observer=records.append,
        ).run("go")
        last = frames_of(records)[-1]
        assert last["type"] == agui.RUN_FINISHED
        assert last["outcome"] == "budget_exhausted"
        assert last["budget"]["which"] == "steps"

    def test_a_cancelled_run_finishes_and_says_so(self, bus):
        """`incomplete` with a reason. Rendering somebody's own decision as a
        failure tells them something went wrong with the thing they asked
        for."""
        from core.budgets import Cancellation

        switch = Cancellation()

        class _CancelsAfterOne(ScriptedModel):
            def __call__(self, messages):
                reply = super().__call__(messages)
                switch.cancel()
                return reply

        records = []
        MissionRunner(
            _CancelsAfterOne(*[tool_call("catalog.search", q="x")] * 4),
            bus, ["catalog.search"], max_steps=6, cancel=switch,
            observer=records.append,
        ).run("go")
        last = frames_of(records)[-1]
        assert last["type"] == agui.RUN_FINISHED
        assert last["outcome"] == "incomplete"
        assert last["reason"] == "cancelled"
        assert last["cancelled"] is True

    def test_incomplete_with_no_reason_is_an_error(self, bus):
        """The word a mission ends on when it ended by RAISING: the record is
        written from a `finally`, so a crash still closes the stream and closes
        it holding the outcome nothing got round to setting."""
        class Cold:
            def __call__(self, messages):
                raise RuntimeError("connection refused")

        records = []
        with pytest.raises(RuntimeError):
            MissionRunner(Cold(), bus, ["catalog.search"],
                          observer=records.append).run("go")
        last = frames_of(records)[-1]
        assert last["type"] == agui.RUN_ERROR
        assert last["code"] == "incomplete"
        assert last["outcome"] == "incomplete"
        assert "stderr" in last["message"]

    def test_a_stream_that_stops_without_a_terminal_record_is_an_error(
            self, answered):
        """A stream that simply stops is indistinguishable from an agent that
        is thinking, and a pane showing a spinner forever is the state an
        analyst cannot leave."""
        truncated = [r for r in answered if r["event"] != "mission_finished"]
        last = frames_of(truncated)[-1]
        assert last["type"] == agui.RUN_ERROR
        assert last["code"] == agui.UNFINISHED

    def test_a_mission_that_said_nothing_at_all_is_an_error_too(self):
        """The silence clause. An empty stream is never an empty answer, and a
        consumer must report it as a failure rather than render a blank."""
        frames = frames_of([])
        assert types_of(frames) == [agui.RUN_STARTED, agui.RUN_ERROR]
        assert frames[-1]["code"] == agui.SILENCE

    def test_closing_after_a_finish_says_nothing(self, answered):
        translator = Translator()
        for record in answered:
            translator.feed(record)
        assert translator.close() == []

    def test_a_stopped_stream_closes_whatever_was_open(self):
        translator = Translator()
        translator.feed(conforming(contract.STEP_STARTED))
        translator.feed(conforming(contract.TOOL_CALL))
        kinds = types_of(translator.close())
        assert kinds == [agui.TOOL_CALL_END, agui.STEP_FINISHED,
                         agui.RUN_ERROR]


# ---------------------------------------------------------------------------
# What it will be fed
# ---------------------------------------------------------------------------

class TestTheInput:
    def test_store_envelopes_are_unwrapped(self, answered):
        """A run read back out of `RunStore.since` is `{seq, at, record}`, and
        a replay must translate to what the live stream translated to."""
        envelopes = [{"seq": n, "at": "2026-08-16T00:00:00Z", "record": r}
                     for n, r in enumerate(answered, start=1)]
        assert frames_of(envelopes) == frames_of(answered)

    def test_the_two_shapes_can_be_mixed(self, answered):
        mixed = [{"seq": 1, "at": "z", "record": answered[0]}] + answered[1:]
        assert frames_of(mixed) == frames_of(answered)

    def test_an_envelope_around_an_unknown_record_is_dropped(self):
        assert Translator().feed(
            {"seq": 1, "at": "z", "record": {"event": "telemetry"}}) == []


class TestItIsDeterministic:
    def test_the_same_stream_translates_twice_to_the_same_frames(self, answered):
        """What lets a consumer replay a transcript and get the pane it had.
        No clock is read and no id is random."""
        assert frames_of(answered) == frames_of(answered)

    def test_a_follower_and_a_replay_agree(self, answered):
        translator = Translator(thread_id="t")
        live = []
        for record in answered:
            live += translator.feed(record)
        live += translator.close()
        assert live == frames_of(answered, thread_id="t")

    def test_the_frames_are_json(self, answered, gated):
        """Dicts only, no SDK — so what a driver writes down a socket is what
        this returned."""
        for records in (answered, gated):
            for frame in frames_of(records):
                assert json.loads(json.dumps(frame)) == frame
