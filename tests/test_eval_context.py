# tests/test_eval_context.py — what the context costs, from the recordings

"""`python -m core.eval context`, over recordings and nothing else.

The owner's commissioning sentence for the whole cognitive arc was *"one
thing we need to ensure. is that all of this we add, does not make the
context bloated and the agent less capable"*.  `ablation` already answers
the second half.  :mod:`core.eval.context` answers the first, and this file
is the argument that its answers are arithmetic rather than impressions.

Four things are load-bearing and each has its section:

* **the attribution adds up** — `pinned + block-outside-the-pinned-prefix +
  rest == chars`, on every call of every fixture and on a constructed run
  where the block lies *inside* the prefix, which is the one case a tally
  that double-counts gets wrong;
* **the pinned prefix is computed, never assumed** — the longest common
  prefix of a conversation's requests, grouped by the recorded `kind` so a
  swarm's router and its children are not averaged into one false head;
* **a moved head is caught, with the call it moved at** — the regression
  detector for the caching claim;
* **nothing recorded is refused by name** — a run that was never recorded
  and a run that was cheap are two facts, and only one of them is a
  measurement.

Nothing here spawns anything.  The recordings are either the corpus
fixtures this repository ships or ones written through
:class:`core.runtime.replay.Recorder` — the real writer, so what this
module reads is what the runtime writes and not a test's idea of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cognition import (CognitiveState, EvidenceAuthority, EvidenceRef,
                            compile_view)
from core.cognition.compile import TITLE
from core.durable import RunStore
from core.eval import ablation as ablation_mod
from core.eval import context as mod
from core.eval.ablation import (ARMS, Ablation, Arm, ArmResult, bloat)
from core.eval.context import (MODEL_LOG, CallCost, ContextSummary,
                               common_prefix, cost_of_run, head_of, is_block,
                               profile, render_request, run_shaped,
                               sections_in, summarise_runs)
from core.eval.run import main as eval_main
from core.eval.score import Half, Report, Totals, Verdict
from core.runtime.replay import Recorder

#: The corpus fixtures this file pins numbers against, by name.  **By name
#: and never by the directory listing**: a lane that drops one more recorded
#: run into `tests/fixtures/runs/` must not move a number asserted here.
FIXTURES = Path(__file__).parent / "fixtures" / "runs"
JSON_RUN = FIXTURES / "run_corpusjson-0001"
SWARM_RUN = FIXTURES / "run_corpusswarm-0001"


# ── the tools for building a recording ───────────────────────────────────────

def view_block() -> str:
    """A real compiled view, out of the real compiler.

    Not a hand-written paragraph that begins with the right words: the
    block this module has to recognise is whatever
    :func:`core.cognition.compile.compile_view` renders, and a fixture
    spelled here by hand would keep passing the day the renderer changed.
    """
    state = CognitiveState()
    state.assert_observation(
        ("job#1", "status", "done"),
        evidence=(EvidenceRef(kind="receipt", locator="run-1/r1/mcp.tool"),),
        authority=EvidenceAuthority.DETERMINISTIC)
    return compile_view(state).text


def record(root: Path, calls, run_id: str = None) -> Path:
    """Write *calls* through the real recorder; return the run directory.

    *calls* is a sequence of ``(kind, request)``.  Going through
    :class:`~core.runtime.replay.Recorder` rather than writing JSONL by
    hand is the point: the line this module parses is the line the runtime
    writes, and a change to either side shows up here.
    """
    store = RunStore(root)
    run = store.create(run_id)
    recorder = Recorder(store, run.run_id)
    for kind, request in calls:
        recorder.model_call(kind, request, "ok")
    return store.directory(run.run_id)


def request(*messages, tools=None) -> dict:
    """One recorded request, in the shape the recorder writes."""
    out = {"messages": [{"role": role, "content": text}
                        for role, text in messages]}
    if tools is not None:
        out["extra"] = {"tools": tools, "stream": False}
    return out


# ── what one request is measured as ──────────────────────────────────────────

class TestWhatARequestIsMeasuredAs:
    def test_the_parts_are_the_tools_and_then_the_messages(self):
        """Tool declarations first, because that is where a chat template
        renders them and therefore where a prefix cache meets them."""
        text, parts = render_request(
            request(("system", "S"), ("user", "U"), tools=[{"name": "t"}]))
        assert [part.label for part in parts] == ["tools", "system", "user"]
        assert text.endswith("\nS\nU")

    def test_every_span_is_where_the_string_says_it_is(self):
        text, parts = render_request(request(("system", "alpha"),
                                             ("user", "beta")))
        for part in parts:
            assert text[part.start:part.end] == part.text

    def test_the_rendering_is_the_parts_and_the_separators(self):
        text, parts = render_request(request(("system", "alpha"),
                                             ("user", "beta")))
        assert text == "alpha\nbeta"
        assert len(text) == sum(len(part.text) for part in parts) + 1

    def test_a_request_with_no_messages_renders_to_nothing(self):
        text, parts = render_request({})
        assert (text, parts) == ("", ())


class TestTheBlockIsRecognisedExactly:
    def test_the_real_compiled_view_is_a_block(self):
        block = view_block()
        assert block.startswith(TITLE)
        assert is_block(block)

    def test_its_sections_are_read_off_the_compiler_s_own_headings(self):
        assert sections_in(view_block()) == ("facts",)

    def test_a_paragraph_that_is_not_the_view_is_not_charged_to_it(self):
        """An operator's own prose about the runtime's view of the problem
        is not a compiled block, and a substring match would have charged
        it to a lane that never emitted it."""
        assert not is_block("Here is the runtime's view of this problem: …")
        assert not is_block("")

    def test_the_block_is_found_in_a_rendered_request(self):
        block = view_block()
        _text, parts = render_request(
            request(("system", "S"), ("user", "U"), ("user", block)))
        found = [part for part in parts if part.block]
        assert len(found) == 1
        assert found[0].sections == ("facts",)


# ── the pinned prefix ────────────────────────────────────────────────────────

class TestThePinnedPrefixIsComputed:
    def test_the_longest_common_prefix_is_what_it_says(self):
        assert common_prefix(["abcdef", "abcxyz", "abcq"]) == 3
        assert common_prefix(["abc", "xyz"]) == 0

    def test_one_request_pins_nothing(self):
        """A single call is trivially its own prefix, and reporting a
        one-call run as 100% pinned would be the most flattering figure in
        the report and the least true: nothing was reused because nothing
        was repeated."""
        assert common_prefix(["anything at all"]) == 0
        assert common_prefix([]) == 0

    def test_the_head_stops_at_the_first_message_that_is_not_system(self):
        _text, parts = render_request(
            request(("system", "S"), ("user", "U"), ("system", "late"),
                    tools=[{"name": "t"}]))
        head = head_of(parts)
        assert head.endswith("S")
        assert "late" not in head

    def test_a_stable_head_reads_yes_with_no_divergence(self, tmp_path):
        directory = record(tmp_path, [
            ("mission", request(("system", "S" * 50), ("user", "go"))),
            ("mission", request(("system", "S" * 50), ("user", "go"),
                                ("assistant", "a"), ("user", "b"))),
        ])
        cost = cost_of_run(directory)
        assert cost.stable is True
        assert cost.diverged_at is None
        assert cost.conversations[0].prefix_chars == 50 + 1 + len("go")

    def test_a_moved_head_is_flagged_with_the_call_it_moved_at(self,
                                                               tmp_path):
        """The regression detector. An inserted timestamp, a shuffled tool
        catalogue or a per-step rewrite of the system prompt all land
        here, and all of them are a prefix cache that misses from that
        call on."""
        directory = record(tmp_path, [
            ("mission", request(("system", "S" * 50), ("user", "go"))),
            ("mission", request(("system", "S" * 50), ("user", "go"),
                                ("assistant", "a"))),
            ("mission", request(("system", "MOVED" + "S" * 50),
                                ("user", "go"))),
        ])
        cost = cost_of_run(directory)
        assert cost.stable is False
        assert cost.diverged_at == 3
        assert cost.conversations[0].stable is False

    def test_the_conversations_are_grouped_by_the_recorded_kind(self,
                                                               tmp_path):
        """A swarm's router and its children share a `model.jsonl` and
        share no system prompt. One prefix over both would be the few
        words two unrelated prompts happen to start with, reported as the
        thing a cache keeps."""
        directory = record(tmp_path, [
            ("plain", request(("system", "ROUTER"), ("user", "pick"))),
            ("mission", request(("system", "AGENT" * 20), ("user", "go"))),
            ("mission", request(("system", "AGENT" * 20), ("user", "go"),
                                ("assistant", "a"))),
        ])
        cost = cost_of_run(directory)
        kinds = {c.kind: c for c in cost.conversations}
        assert set(kinds) == {"plain", "mission"}
        assert kinds["plain"].measured is False
        assert kinds["plain"].prefix_chars == 0
        assert kinds["mission"].measured is True
        assert kinds["mission"].prefix_chars == len("AGENT" * 20) + 1 + 2

    def test_a_conversation_of_one_call_pins_nothing_and_says_so(self,
                                                                 tmp_path):
        directory = record(tmp_path, [
            ("mission", request(("system", "S" * 40), ("user", "go"))),
        ])
        cost = cost_of_run(directory)
        assert cost.conversations[0].measured is False
        assert cost.calls[0].prefix_chars == 0
        assert "no prefix measurable" in mod._prefix_line(cost)


# ── the attribution ──────────────────────────────────────────────────────────

class TestTheAttributionAddsUp:
    """`pinned + block-outside-the-prefix + rest == chars`, every call.

    The three are three readings of one string and two of them overlap, so
    they are computed from one interval algebra over the same spans rather
    than from three tallies that agree by convention. A tally that counted
    a pinned block twice reports a request larger than the request.
    """

    def _check(self, call: CallCost) -> None:
        assert (call.prefix_chars + call.block_unpinned_chars
                + call.rest_chars) == call.chars
        assert 0 <= call.block_unpinned_chars <= call.block_chars
        assert 0 <= call.prefix_chars <= call.chars

    def test_it_holds_on_every_call_of_the_shipped_fixtures(self):
        for directory in sorted(FIXTURES.iterdir()):
            if not (directory / MODEL_LOG).exists():
                continue
            cost = cost_of_run(directory)
            assert cost.calls
            for call in cost.calls:
                self._check(call)

    def test_a_block_that_did_not_change_lies_inside_the_pinned_prefix(
            self, tmp_path):
        """The case a double-counting tally gets wrong. A view that is
        byte-identical between two steps is *in* the prefix: it is charged
        there once, and a reader shown its characters a second time would
        conclude the opposite of what happened."""
        block = view_block()
        directory = record(tmp_path, [
            ("mission", request(("system", "S" * 60), ("user", "go"),
                                ("user", block))),
            ("mission", request(("system", "S" * 60), ("user", "go"),
                                ("user", block), ("assistant", "tail"))),
        ])
        cost = cost_of_run(directory)
        assert cost.calls[0].block_chars == len(block)
        assert cost.calls[0].block_unpinned_chars == 0
        for call in cost.calls:
            self._check(call)

    def test_a_block_that_changed_is_charged_to_the_call_that_paid_for_it(
            self, tmp_path):
        block = view_block()
        directory = record(tmp_path, [
            ("mission", request(("system", "S" * 60), ("user", "go"))),
            ("mission", request(("system", "S" * 60), ("user", "go"),
                                ("user", block))),
        ])
        cost = cost_of_run(directory)
        assert cost.calls[1].block_chars == len(block)
        assert cost.calls[1].block_unpinned_chars == len(block)
        assert cost.calls[1].sections == ("facts",)
        for call in cost.calls:
            self._check(call)

    def test_the_union_is_counted_once(self):
        assert mod._merged_length([(0, 10), (4, 6)]) == 10
        assert mod._merged_length([(0, 10), (8, 14)]) == 14
        assert mod._merged_length([(0, 0), (3, 3)]) == 0


# ── the shipped fixtures, pinned ─────────────────────────────────────────────

class TestTheShippedRecordings:
    """Numbers, on recordings this repository ships and a tag can rebuild."""

    def test_the_json_protocol_run_is_two_calls_and_a_pinned_head(self):
        cost = cost_of_run(JSON_RUN)
        assert [call.call for call in cost.calls] == [1, 2]
        assert [call.chars for call in cost.calls] == [4079, 4289]
        assert cost.conversations[0].prefix_chars == 4079
        assert cost.stable is True
        assert cost.slope == pytest.approx(210.0)
        assert cost.peak_chars == 4289

    def test_it_carried_no_compiled_view_and_says_zero_not_nothing(self):
        cost = cost_of_run(JSON_RUN)
        assert cost.block_chars == 0
        assert cost.block_share == 0.0

    def test_the_swarm_run_is_two_conversations_and_reports_both(self):
        cost = cost_of_run(SWARM_RUN)
        kinds = {c.kind: c for c in cost.conversations}
        assert set(kinds) == {"plain", "mission"}
        assert len(kinds["mission"].calls) == 4
        assert kinds["mission"].stable is True
        assert kinds["mission"].prefix_chars == 4620
        # Three unrelated prompts in one run: the router, the recap and the
        # summariser. Not one head, and the report says where it moved.
        assert kinds["plain"].stable is False
        assert kinds["plain"].diverged_at == 2

    def test_no_provider_usage_means_characters_only_and_it_is_stated(self):
        found = profile(JSON_RUN)
        assert found.tokens_recorded is False
        assert found.summary.prompt_tokens is None
        assert found.summary.mean_tokens is None
        assert "**Characters only.**" in found.to_markdown()

    def test_tokens_are_the_provider_s_and_never_estimated(self, tmp_path):
        store = RunStore(tmp_path)
        run = store.create()
        path = store.directory(run.run_id) / MODEL_LOG
        lines = []
        for index in (1, 2):
            lines.append(json.dumps({
                "call": index, "at": "now", "kind": "mission",
                "request": {"messages": [{"role": "system", "content": "S"},
                                         {"role": "user", "content": "u"}]},
                "reply": {"content": "ok", "tool_calls": [],
                          "usage": {"prompt_tokens": 100 * index,
                                    "completion_tokens": 1,
                                    "total_tokens": 100 * index + 1}}}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cost = cost_of_run(store.directory(run.run_id))
        assert [call.prompt_tokens for call in cost.calls] == [100, 200]
        assert cost.prompt_tokens == 300
        assert "**Characters only.**" not in profile(
            store.directory(run.run_id)).to_markdown()

    def test_one_call_without_usage_withholds_the_whole_run_s_total(
            self, tmp_path):
        """All or nothing: a total over the calls that happened to report
        is a smaller number wearing the shape of the whole run's cost."""
        store = RunStore(tmp_path)
        run = store.create()
        path = store.directory(run.run_id) / MODEL_LOG
        first = {"call": 1, "kind": "mission",
                 "request": {"messages": [{"role": "user", "content": "a"}]},
                 "reply": {"usage": {"prompt_tokens": 10}}}
        second = {"call": 2, "kind": "mission",
                  "request": {"messages": [{"role": "user", "content": "b"}]},
                  "reply": {"usage": None}}
        path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n",
                        encoding="utf-8")
        assert cost_of_run(store.directory(run.run_id)).prompt_tokens is None


# ── what is refused ──────────────────────────────────────────────────────────

class TestNothingRecordedIsRefusedByName:
    def test_a_directory_with_no_model_log_names_what_it_wanted(self,
                                                               tmp_path):
        (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
        cost = cost_of_run(tmp_path)
        assert not cost.measured
        assert MODEL_LOG in cost.refused
        assert "recorder wrote" in cost.refused

    def test_a_model_log_with_nothing_readable_in_it_is_its_own_refusal(
            self, tmp_path):
        (tmp_path / MODEL_LOG).write_text("\n{not json\n", encoding="utf-8")
        cost = cost_of_run(tmp_path)
        assert not cost.measured
        assert "no readable call" in cost.refused

    def test_a_torn_last_line_costs_only_that_line(self, tmp_path):
        good = json.dumps({
            "call": 1, "kind": "mission",
            "request": {"messages": [{"role": "user", "content": "hello"}]},
            "reply": {"usage": None}})
        (tmp_path / MODEL_LOG).write_text(good + "\n{\"call\": 2, \"req",
                                          encoding="utf-8")
        cost = cost_of_run(tmp_path)
        assert [call.call for call in cost.calls] == [1]

    def test_the_command_line_exits_two_and_says_so(self, tmp_path, capsys):
        (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
        assert eval_main(["context", "--runs", str(tmp_path)]) == 2
        captured = capsys.readouterr()
        assert MODEL_LOG in captured.err
        assert MODEL_LOG in captured.out

    def test_a_root_with_no_run_under_it_at_all_says_that_instead(
            self, tmp_path, capsys):
        assert eval_main(["context", "--runs", str(tmp_path)]) == 2
        assert "no run directory at or under it" in capsys.readouterr().out


# ── finding the runs ─────────────────────────────────────────────────────────

class TestFindingTheRuns:
    def test_a_run_directory_is_taken_as_itself(self):
        assert run_shaped(JSON_RUN) == [JSON_RUN]

    def test_a_directory_of_runs_is_walked(self):
        found = run_shaped(FIXTURES)
        assert JSON_RUN in found and SWARM_RUN in found

    def test_the_harness_s_own_mission_directory_is_not_a_refusal(
            self, tmp_path):
        """`eval run` leaves `<key>/events.jsonl` beside `<key>/runs/<id>/`,
        and the child's recording is in the second. Reporting the first as
        "no model.jsonl" would put a false negative beside every real run.
        """
        mission = tmp_path / "rep1" / "the_mission"
        mission.mkdir(parents=True)
        (mission / "events.jsonl").write_text("", encoding="utf-8")
        inner = record(mission / "runs", [
            ("mission", request(("system", "S"), ("user", "u")))])
        assert run_shaped(tmp_path) == [inner]

    def test_a_run_shaped_directory_with_nothing_below_it_is_reported(
            self, tmp_path):
        mission = tmp_path / "rep1" / "the_mission"
        mission.mkdir(parents=True)
        (mission / "events.jsonl").write_text("", encoding="utf-8")
        assert run_shaped(tmp_path) == [mission]

    def test_a_path_that_is_not_there_contributes_nothing(self, tmp_path):
        assert run_shaped(tmp_path / "nowhere") == []
        assert summarise_runs([tmp_path / "nowhere"]) == ContextSummary()


# ── the ablation column ──────────────────────────────────────────────────────

def _report(passed) -> Report:
    """One repeat's report, straight from verdicts — `test_eval_ablation`'s
    helper, kept in this file's own terms so neither moves the other."""
    verdicts = tuple(
        Verdict(key=key, flag="synthesis", split="train", passed=value,
                kpis={"outcome": "answered", "run_id": f"run_{key}"})
        for key, value in passed.items())
    return Report(suite="toy", halves={
        "train": Half(split="train", verdicts=verdicts, overall=Totals(),
                      by_flag={})})


def _arm(tmp_path: Path, name: str, passed, *, block: bool,
         flags=("--cognition",)) -> ArmResult:
    """One arm with a real recording under it: `<rep1>/<key>/runs/<id>/`."""
    rep = tmp_path / name / "rep1"
    for key in passed:
        mission = rep / key
        mission.mkdir(parents=True)
        (mission / "events.jsonl").write_text("", encoding="utf-8")
        view = view_block()
        record(mission / "runs", [
            ("mission", request(("system", "S" * 200), ("user", "go"))),
            ("mission", request(("system", "S" * 200), ("user", "go"),
                                *(("user", view),) if block else (),
                                ("assistant", "a"))),
        ])
    arm = ARMS[0] if name == "baseline" else Arm(name=name, flags=flags,
                                                 why="the arm under test")
    return ArmResult(arm=arm, reports=(_report(passed),),
                     directories=(rep,), command=("judais",))


def _ablation(*arms) -> Ablation:
    keys = tuple(sorted({verdict.key for arm in arms
                         for report in arm.reports
                         for verdict in report.halves["train"].verdicts}))
    return Ablation(suite="toy", split="train", arms=arms,
                    keys={"train": keys},
                    flags={key: "synthesis" for key in keys})


class TestTheArmsCarryTheirPrice:
    def test_the_rate_table_gains_the_two_columns(self, tmp_path):
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=True))
        text = ablated.to_markdown()
        assert "| chars/call | view share |" in text
        assert "Δ chars/call" in text

    def test_the_figures_are_the_analyzer_s_own(self, tmp_path):
        baseline = _arm(tmp_path, "baseline", {"m1": True}, block=False)
        shadow = _arm(tmp_path, "shadow", {"m1": True}, block=True)
        ablated = _ablation(baseline, shadow)
        direct = summarise_runs([shadow.directories[0] / "m1"])
        assert ablated.context(shadow, "train") == direct
        assert direct.measured
        assert direct.block_chars == len(view_block())

    def test_the_block_costs_the_arm_what_the_view_is(self, tmp_path):
        baseline = _arm(tmp_path, "baseline", {"m1": True}, block=False)
        shadow = _arm(tmp_path, "shadow", {"m1": True}, block=True)
        ablated = _ablation(baseline, shadow)
        before = ablated.context(baseline, "train")
        after = ablated.context(shadow, "train")
        # One block, on one of two calls: the mean call grows by half of it
        # plus the separator the template puts in front of it.
        assert after.mean_chars - before.mean_chars == pytest.approx(
            (len(view_block()) + 1) / 2)

    def test_the_paired_row_carries_the_price_of_its_own_delta(self,
                                                               tmp_path):
        """The one line the owner's question is answered on: what the arm
        fixed, what it broke, and what it cost to do either."""
        baseline = _arm(tmp_path, "baseline", {"m1": True}, block=False)
        shadow = _arm(tmp_path, "shadow", {"m1": True}, block=True)
        ablated = _ablation(baseline, shadow)
        before = ablated.context(baseline, "train")
        after = ablated.context(shadow, "train")
        expected = f"{after.mean_chars - before.mean_chars:+,.0f}"
        lines = ablated.to_markdown().splitlines()
        heading = [index for index, line in enumerate(lines)
                   if line.startswith("| arm |") and "which broke" in line]
        assert len(heading) == 1
        header = lines[heading[0]]
        row = [line for line in lines[heading[0]:]
               if line.startswith("| `shadow` | `--cognition` |")]
        assert len(row) == 1
        assert f"| {expected} |" in row[0]
        # A cell dropped from the row and left in the header is a table
        # that renders, reads plausibly, and puts every number one column
        # to the left of its name.
        assert row[0].count("|") == header.count("|")

    def test_the_json_carries_the_same_figures_per_half(self, tmp_path):
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=True))
        arms = {entry["name"]: entry for entry in ablated.as_dict()["arms"]}
        assert arms["shadow"]["context"]["train"]["calls"] == 2
        assert arms["shadow"]["context"]["train"]["block_chars"] == len(
            view_block())

    def test_an_arm_with_no_recording_is_a_dash_and_not_a_zero(self,
                                                              tmp_path):
        """A run that recorded no model log did not send a zero-character
        request; it sent requests nobody wrote down."""
        rep = tmp_path / "bare" / "rep1"
        (rep / "m1").mkdir(parents=True)
        arm = ArmResult(arm=ARMS[0], reports=(_report({"m1": True}),),
                        directories=(rep,))
        ablated = _ablation(arm)
        assert not ablated.context(arm, "train").measured
        assert ablation_mod._chars(ablated.context(arm, "train")) == "—"
        assert "| — | — |" in ablated.to_markdown()


class TestTheOwnersCriterion:
    """An arm that added context and no capability is flagged by name."""

    def test_it_fires_on_context_up_and_missions_flat(self, tmp_path):
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=True))
        flagged = bloat(ablated, "train")
        assert [entry["arm"] for entry in flagged] == ["shadow"]
        assert flagged[0]["passes"] == 0
        assert flagged[0]["chars"] > 0
        text = ablated.to_markdown()
        assert "capability vs cost" in text
        assert "added context and no capability" in text
        assert "does not make the context bloated" in text

    def test_it_is_silent_when_the_arm_bought_something(self, tmp_path):
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": False}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=True))
        assert bloat(ablated, "train") == []
        assert "added context and no capability" not in ablated.to_markdown()

    def test_it_is_silent_when_the_arm_cost_nothing(self, tmp_path):
        """Flat and free is not bloat. The criterion is about what was
        *added*."""
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=False))
        assert bloat(ablated, "train") == []

    def test_it_is_silent_where_nothing_was_recorded(self, tmp_path):
        """Inventing a cost figure so a note can fire would be the report
        manufacturing its own evidence."""
        rep = tmp_path / "bare" / "rep1"
        (rep / "m1").mkdir(parents=True)
        bare = ArmResult(arm=Arm(name="shadow", flags=("--cognition",)),
                         reports=(_report({"m1": True}),), directories=(rep,))
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False), bare)
        assert bloat(ablated, "train") == []

    def test_the_json_carries_the_flag_so_a_platform_need_not_read_prose(
            self, tmp_path):
        ablated = _ablation(
            _arm(tmp_path, "baseline", {"m1": True}, block=False),
            _arm(tmp_path, "shadow", {"m1": True}, block=True))
        flagged = ablated.as_dict()["capability_vs_cost"]["train"]
        assert [entry["arm"] for entry in flagged] == ["shadow"]


# ── the command line ─────────────────────────────────────────────────────────

class TestTheCommandLine:
    def test_it_prints_the_growth_curve_and_the_prefix_finding(self, capsys):
        assert eval_main(["context", "--runs", str(JSON_RUN)]) == 0
        out = capsys.readouterr().out
        assert "byte-stable: YES" in out
        assert "growth **+210** chars/step" in out
        assert "4,079" in out

    def test_json_is_the_same_profile(self, capsys):
        assert eval_main(["context", "--runs", str(JSON_RUN), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["calls"] == 2
        assert payload["runs"][0]["stable"] is True

    def test_report_writes_the_markdown_and_the_json_beside_it(
            self, tmp_path, capsys):
        stem = tmp_path / "profile.md"
        assert eval_main(["context", "--runs", str(JSON_RUN),
                          "--report", str(stem)]) == 0
        capsys.readouterr()
        assert stem.exists()
        beside = tmp_path / "profile.json"
        assert json.loads(beside.read_text(encoding="utf-8"))["runs"]

    def test_it_needs_no_suite_and_spawns_nothing(self):
        """`context` reads recordings, so there is no suite in this
        checkout to hold one to — the run it reads may have happened on
        another machine a month ago."""
        parser = __import__("core.eval.run", fromlist=["_parser"])._parser()
        action = [entry for entry in parser._subparsers._group_actions][0]
        assert "context" in action.choices
        assert "--suite" not in action.choices["context"].format_usage()
