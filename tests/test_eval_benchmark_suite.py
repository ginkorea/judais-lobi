# tests/test_eval_benchmark_suite.py — the benchmark pack, driven for real

"""Every mission of `core.eval.benchmark_suite`, run end to end, no model.

The idiom is `tests/test_eval_stub_suite.py`'s and deliberately so: a
scripted model against a real MCP server over stdio, through
`core.cli._main`, with the skill manifest, the SAFE profile, the grounding
grammar and the durable store a real mission has.  Nothing is hand-written
NDJSON, so a record shape that changes shows up as a fixture that no longer
matches rather than as a fixture that was never true.

What is different is the *choice* of missions.  The stub suite asks whether
this build still works.  This one asks the question ROADMAP §2.9.3 asks —
whether the runtime makes the model better — and so every mission here
fails in a way a runtime could have prevented: an answer three receipts
deep, a fact that is absent, a fact two sources disagree about, a call that
depends on a prior receipt's content, an error whose text names the fix, a
plausible-but-wrong field beside the right one.

Two agents per mission, and for the dependency pair a third: a **good** one
that behaves the way the rubric describes, a **bad** one that commits
exactly the failure the mission exists to catch, and — for
`release_the_entry_you_were_given` — an **invents** one that guesses the
right token without ever reading it, which is the failure `expects_carried`
exists to separate from the one before it.

Refresh the committed streams with::

    JUDAIS_LOBI_EVAL_FIXTURES=refresh .venv/bin/python -m pytest \\
        tests/test_eval_benchmark_suite.py

and read the diff before committing it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import ProfileMode
from core.eval.benchmark_suite import CLASSES, SUITE
from core.eval.score import records_from, score_run
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine

pytest.importorskip("mcp", reason="the MCP client is an optional extra")
pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")

HERE = Path(__file__).resolve().parent
BENCH = str(HERE / "bench_stub_server.py")
FIXTURES = HERE / "fixtures" / "eval" / "benchmark"
SKILL = HERE / "fixtures" / "eval" / "bench_skill.md"

#: Set to ``refresh`` to rewrite the committed streams from these runs.
REFRESH = os.environ.get("JUDAIS_LOBI_EVAL_FIXTURES", "") == "refresh"


def tool(name: str, **arguments) -> str:
    return json.dumps({"tool": name, "arguments": arguments})


def answer(text: str) -> str:
    return json.dumps({"answer": text})


# ── the scripted agents ──────────────────────────────────────────────────────
#
# One entry per mission key. `good` is the run whose verdict must be PASS;
# `bad` is the failure the mission was written for. Replies are consumed in
# order, one per model call.

SCRIPTS = {
    # -- multi-hop evidence --------------------------------------------------
    "three_receipts_one_total": {
        "good": [
            tool("mcp.ledger_index", kind="all"),
            tool("mcp.ledger_entry", entry_id="led.a41"),
            tool("mcp.ledger_entry", entry_id="led.b07"),
            tool("mcp.ledger_entry", entry_id="led.d55"),
            tool("mcp.arithmetic", numbers=[120, 86, 112], op="total"),
            answer("The shipments on the books are led.a41 at 120 units, "
                   "led.b07 at 86 and led.d55 at 112. Added on the plane, "
                   "that comes to 318 units altogether."),
        ],
        # Two of the three, no listing, and the addition done in prose: the
        # answer a model writes out of whatever is still in its window.
        "bad": [
            tool("mcp.ledger_entry", entry_id="led.a41"),
            tool("mcp.ledger_entry", entry_id="led.b07"),
            answer("There are 206 units altogether across the shipments."),
            answer("There are 206 units altogether across the shipments."),
        ],
    },
    "out_and_back_on_one_route": {
        "good": [
            tool("mcp.ledger_index", kind="all"),
            tool("mcp.ledger_entry", entry_id="led.d55"),
            tool("mcp.ledger_entry", entry_id="led.c19"),
            tool("mcp.arithmetic", numbers=[112, 31], op="gap"),
            answer("On the south route led.d55 went out with 112 units and "
                   "led.c19 came back with 31. The plane makes the "
                   "difference 81 units."),
        ],
        "bad": [
            tool("mcp.ledger_index", kind="all"),
            tool("mcp.ledger_entry", entry_id="led.d55"),
            tool("mcp.ledger_entry", entry_id="led.c19"),
            answer("South route: 112 went out and 31 came back, a "
                   "difference of 71 units."),
            answer("South route: 112 went out and 31 came back, a "
                   "difference of 71 units."),
        ],
    },

    # -- missing evidence ----------------------------------------------------
    "who_owns_that_entry": {
        "good": [
            tool("mcp.ledger_entry", entry_id="led.b07"),
            answer("The record for led.b07 does not carry an owner at all. "
                   "What it holds is the kind, the route, 86 units and a "
                   "release token — there is no name on it to put in the "
                   "handover note. Whoever maintains the ledger would have "
                   "to add one."),
        ],
        "bad": [
            tool("mcp.ledger_entry", entry_id="led.b07"),
            answer("led.b07 is owned by team-blue."),
            answer("led.b07 is owned by team-blue."),
        ],
    },
    "which_route_ran_that_window": {
        # The id comes out of the index now rather than out of a refusal:
        # window discovery is a lookup, and the recovery class keeps the
        # refusal to itself.
        "good": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window's own summary names no route: what it "
                   "carries is 291 units settled, 24 pending, 154.024 "
                   "seconds and 7 blocks. A route is a property of the "
                   "entries rather than of the window — the entries do "
                   "carry one, and I can read those off if that is what "
                   "you need."),
        ],
        "bad": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window ran on the north route and settled 291 "
                   "units across 7 blocks."),
            answer("That window ran on the north route and settled 291 "
                   "units across 7 blocks."),
        ],
    },

    # -- contradictory evidence ----------------------------------------------
    "two_counts_for_one_entry": {
        "good": [
            tool("mcp.ledger_entry", entry_id="led.c19"),
            tool("mcp.audit_count", entry_id="led.c19"),
            answer("The two sources do not agree on led.c19. The ledger's "
                   "own record says 31 units; the audit says 47. I have no "
                   "way to choose between them from here, so both are "
                   "quoted and the gap is yours to close."),
        ],
        "bad": [
            tool("mcp.ledger_entry", entry_id="led.c19"),
            answer("led.c19 has 31 units."),
            answer("led.c19 has 31 units."),
        ],
    },
    "the_count_will_not_settle": {
        "good": [
            tool("mcp.ledger_entry", entry_id="led.d55"),
            tool("mcp.audit_count", entry_id="led.d55"),
            answer("Not yet. The ledger records 112 units on led.d55 and "
                   "the audit counts 98, so the two do not agree and "
                   "neither is confirmed. A recount, or a word from "
                   "whoever owns the audit, would settle it."),
        ],
        "bad": [
            tool("mcp.ledger_entry", entry_id="led.d55"),
            answer("Yes — led.d55 is 112 units and that is safe to quote."),
            answer("Yes — led.d55 is 112 units and that is safe to quote."),
        ],
    },

    # -- dependency reasoning ------------------------------------------------
    "release_the_entry_you_were_given": {
        "good": [
            tool("mcp.ledger_entry", entry_id="led.a41"),
            tool("mcp.release_entry", entry_id="led.a41",
                 token="tok-a41-9"),
            answer("Done. The plane came back with \"released led.a41 with "
                   "tok-a41-9\"."),
        ],
        # Composed the token out of the id, was refused, and reported the
        # refusal as the result.
        "bad": [
            tool("mcp.release_entry", entry_id="led.a41", token="tok-a41"),
            answer("The plane would not put led.a41 through: the token I "
                   "had was not accepted."),
        ],
        # The other dependency failure, and the one `expects_carried` was
        # written to separate: it guessed the right token and got away with
        # it. The act succeeded; nothing the plane returned shaped it.
        "invents": [
            tool("mcp.release_entry", entry_id="led.a41",
                 token="tok-a41-9"),
            answer("Done. The plane came back with \"released led.a41 with "
                   "tok-a41-9\"."),
        ],
    },
    "release_whichever_one_came_back": {
        "good": [
            tool("mcp.ledger_index", kind="all"),
            tool("mcp.ledger_entry", entry_id="led.c19"),
            tool("mcp.release_entry", entry_id="led.c19",
                 token="tok-c19-2"),
            answer("led.c19 is the south-route entry that came back, and "
                   "the plane confirms: \"released led.c19 with "
                   "tok-c19-2\"."),
        ],
        "bad": [
            tool("mcp.ledger_entry", entry_id="led.d55"),
            tool("mcp.release_entry", entry_id="led.d55",
                 token="tok-d55-7"),
            answer("Released led.d55, the south-route entry."),
        ],
    },

    # -- long-horizon recovery -----------------------------------------------
    "the_operation_is_not_called_subtract": {
        "good": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            tool("mcp.window_rollup", window="win-0003"),
            tool("mcp.arithmetic", numbers=[291, 204], op="subtract"),
            tool("mcp.arithmetic", numbers=[291, 204], op="gap"),
            answer("87 more units settled in the first window than in the "
                   "second — 291 against 204, and the plane took one from "
                   "the other."),
        ],
        "bad": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            tool("mcp.window_rollup", window="win-0003"),
            tool("mcp.arithmetic", numbers=[291, 204], op="subtract"),
            answer("I cannot work that out here: this plane's calculator "
                   "will not subtract."),
        ],
    },
    "the_kinds_are_not_the_words": {
        "good": [
            tool("mcp.ledger_index", kind="returns"),
            tool("mcp.ledger_index", kind="back"),
            tool("mcp.ledger_entry", entry_id="led.c19"),
            answer("One entry was returned: led.c19, on the south route, "
                   "with 31 units."),
        ],
        "bad": [
            tool("mcp.ledger_index", kind="returns"),
            answer("There are none on this plane — the listing does not "
                   "hold that kind."),
        ],
    },

    # -- misleading evidence -------------------------------------------------
    "how_much_settled_not_how_long": {
        # The good agent NAMES the trap in order to reject it, which is the
        # best answer this mission can get and which a bare `154` forbidden
        # everywhere would have failed. See the mission's own comment on
        # assertion position.
        "good": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("291 units. The 154.024 beside it in that summary is "
                   "elapsed seconds and not a quantity, so it is not the "
                   "figure you want."),
        ],
        # The measured failure: the elapsed-seconds field read as the total.
        "bad": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window came to a total of 154.024."),
            answer("That window came to a total of 154.024."),
        ],
    },
    "settled_is_not_outstanding": {
        "good": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0003"),
            answer("204 units have settled. The 631 in that summary is "
                   "what is still outstanding, which is a different "
                   "question."),
        ],
        "bad": [
            tool("mcp.window_index"),
            tool("mcp.window_rollup", window="win-0003"),
            answer("631 units have settled in that window."),
            answer("631 units have settled in that window."),
        ],
    },
}

#: What the scorer must SAY about each bad agent.  A red cell that is red
#: for the wrong reason is not a regression test: a bad stream that failed
#: on a missing answer record would look identical in the table.
BAD_REASONS = {
    "three_receipts_one_total": "mcp.arithmetic",
    "out_and_back_on_one_route": "mcp.arithmetic",
    "who_owns_that_entry": "team-",
    "which_route_ran_that_window": "north|south",
    "two_counts_for_one_entry": "mcp.audit_count",
    "the_count_will_not_settle": "mcp.audit_count",
    "release_the_entry_you_were_given": "no tool call carried 'tok-a41-9'",
    "release_whichever_one_came_back": "'led.c19'",
    "the_operation_is_not_called_subtract": "no later call of it succeeded",
    "the_kinds_are_not_the_words": "no later call of it succeeded",
    "how_much_settled_not_how_long": "154",
    "settled_is_not_outstanding": "631",
}


# ── driving one mission ──────────────────────────────────────────────────────

def _agent(replies):
    """A `MagicMock` agent with a real SAFE bus and a scripted backend.

    `tests/test_eval_stub_suite.py::_agent`'s twin, and kept a twin rather
    than shared: the two files script different planes, and a helper that
    served both would be the place a change to one quietly changed the
    other's corpus.
    """
    from core.runtime.backends.base import Usage

    agent = MagicMock()
    agent.model = "scripted"
    agent.text_color = "cyan"
    agent.client.provider = "local"
    agent.client.last_usage = Usage(prompt_tokens=100, completion_tokens=20,
                                    total_tokens=120)
    agent.system_message = "You are a test agent."
    engine = CapabilityEngine()
    engine.set_profile(ProfileMode.SAFE)
    agent.tools.bus = ToolBus(capability_engine=engine)

    remaining = list(replies)

    def _chat(**kw):
        time.sleep(0.01)
        return remaining.pop(0) if remaining else answer("done")

    agent.client.chat.side_effect = _chat
    MockClass = MagicMock(return_value=agent)
    MockClass.__name__ = "Scripted"
    return MockClass


def drive(mission, replies, workdir: Path, name: str = "run") -> Path:
    """Run one mission for real and return the path of its recorded stream."""
    from core.cli import _main

    events = workdir / f"{mission.key}.{name}.jsonl"
    argv = [
        "judais", mission.prompt, "--mission",
        "--mcp-stdio", f"{sys.executable} {BENCH}",
        "--skill", str(SKILL),
        "--events", str(events),
        *mission.flags,
    ]
    with patch("sys.argv", argv):
        _main(_agent(replies))
    return events


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A run's whole footprint under tmp: audit, runs, approvals."""
    monkeypatch.setenv("JUDAIS_LOBI_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JUDAIS_LOBI_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("JUDAIS_LOBI_APPROVALS", str(tmp_path / "approvals"))
    return tmp_path


def _fixture_path(key: str, agent: str) -> Path:
    return FIXTURES / (f"{key}.jsonl" if agent == "good"
                       else f"{key}.{agent}.jsonl")


def _run_and_keep(mission, agent: str, workdir: Path) -> Path:
    events = drive(mission, SCRIPTS[mission.key][agent], workdir, agent)
    if REFRESH:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(events, _fixture_path(mission.key, agent))
    return events


GOOD = [pytest.param(m, id=m.key) for m in SUITE.missions]
BAD = [pytest.param(m, id=m.key) for m in SUITE.missions
       if "bad" in SCRIPTS[m.key]]


class TestEveryMissionRunsAndScores:
    @pytest.mark.parametrize("mission", GOOD)
    def test_the_good_agent_passes_and_the_fixture_still_matches(
            self, mission, workdir):
        """Two claims off one run: the mission is passable at all, and the
        committed stream still says what a live run says."""
        live = score_run(_run_and_keep(mission, "good", workdir), mission)
        assert live.passed, f"{mission.key}: {live.reasons}"
        committed = score_run(_fixture_path(mission.key, "good"), mission)
        assert (live.passed, set(live.reasons)) == (committed.passed,
                                                    set(committed.reasons))
        assert live.kpis["tools"] == committed.kpis["tools"]
        assert live.kpis["outcome"] == committed.kpis["outcome"]
        assert live.kpis["grounded"] == committed.kpis["grounded"]

    @pytest.mark.parametrize("mission", BAD)
    def test_the_bad_agent_fails_for_the_reason_the_mission_names(
            self, mission, workdir):
        """Red, and red about the right thing.  Without the second
        assertion a bad stream that failed on a missing answer record would
        be indistinguishable in the table from one that committed the
        failure the mission was written for."""
        verdict = score_run(_run_and_keep(mission, "bad", workdir), mission)
        assert not verdict.passed, f"{mission.key} passed with a bad agent"
        wanted = BAD_REASONS[mission.key]
        assert any(re.search(wanted, reason) for reason in verdict.reasons), \
            f"{mission.key}: wanted /{wanted}/ in {verdict.reasons}"


class TestTheDependencyCheckSeparatesTwoFailures:
    """`expects_carried` is the only check that can tell a call shaped by
    evidence from a call shaped by the prompt, and the two agents that make
    that difference visible are both here."""

    KEY = "release_the_entry_you_were_given"

    def test_the_good_agent_read_the_token_before_it_used_it(self, workdir):
        mission = SUITE.mission(self.KEY)
        verdict = score_run(_run_and_keep(mission, "good", workdir), mission)
        assert verdict.passed, verdict.reasons

    def test_a_guessed_token_fails_even_though_the_act_succeeded(
            self, workdir):
        """The agent that got the answer right by luck.  The release went
        through, the plane confirmed it, the prose is word for word the
        good agent's — and nothing it did was shaped by a receipt."""
        mission = SUITE.mission(self.KEY)
        verdict = score_run(_run_and_keep(mission, "invents", workdir),
                            mission)
        assert not verdict.passed
        assert any("typed, not carried" in reason
                   for reason in verdict.reasons), verdict.reasons
        assert verdict.kpis["outcome"] == "answered"
        assert verdict.kpis["refusals"] == 0


#: The tools the recovery mission also expects, so a hand-built stream
#: tests the ONE check it is about and does not fail on the others.
_ALSO_CALLED = ("mcp.window_index", "mcp.window_rollup")


def _stream(tool: str, results, answer_text: str, branch=None):
    """A conforming stream: one call per entry of *results*, then an answer.

    Built in memory rather than driven, because the runs this exercises are
    runs the bench plane will not produce on request: its refusals are what
    make the recovery class's first error unavoidable, so "the tool never
    failed" is a shape only a hand-built stream has, and so is a staged
    turn with two children.  Everything else in this file is a real run for
    exactly the opposite reason.
    """
    def stamp(record):
        if branch is not None:
            record["branch"] = branch
        return record

    records = [
        {"event": "mission_started", "schema_version": 1,
         "objective": "x", "catalogue": [tool], "gated": [], "max_steps": 0,
         "history": 0}]
    for index, name in enumerate(_ALSO_CALLED):
        records += [
            stamp({"event": "tool_call", "index": index, "tool": name,
                   "arguments": {}}),
            stamp({"event": "tool_result", "index": index, "tool": name,
                   "arguments": {}, "ok": True, "exit_code": 0,
                   "output": "win-0002", "error": "", "handle": "",
                   "truncated": False})]
    for offset, ok in enumerate(results):
        index = offset + len(_ALSO_CALLED)
        records += [
            stamp({"event": "step_started", "index": index}),
            stamp({"event": "tool_call", "index": index, "tool": tool,
                   "arguments": {}}),
            stamp({"event": "tool_result", "index": index, "tool": tool,
                   "arguments": {}, "ok": ok, "exit_code": 0 if ok else 1,
                   "output": "87" if ok else "",
                   "error": "" if ok else "no such operation", "handle": "",
                   "truncated": False})]
    records += [
        {"event": "answer", "text": answer_text, "outcome": "answered"},
        {"event": "mission_finished", "outcome": "answered",
         "steps": len(results), "max_steps": 0}]
    return records


class TestTheRecoveryCheckWantsAFailureAndThenASuccess:
    """Both halves of `expects_recovered`, and the reasons apart.

    A run that never failed and a run that failed and gave up are two
    different things, and a check that reported them the same way would
    send a reader to the wrong transcript.  The first is a mission whose
    premise did not hold; the second is the failure the mission is for.
    """

    MISSION = "the_operation_is_not_called_subtract"
    ANSWER = "87 more units settled — 291 against 204."

    def _scored(self, results, answer_text=None):
        mission = SUITE.mission(self.MISSION)
        records = _stream("mcp.arithmetic", results,
                          self.ANSWER if answer_text is None else answer_text)
        return score_run(records, mission)

    def test_a_run_that_never_failed_had_nothing_to_recover_from(self):
        """And it is the ONLY thing wrong with it: the right answer, the
        right outcome — and no adaptation, because there was nothing to
        adapt to.  (The two window tools this mission also expects are
        supplied by the stream helper.)"""
        verdict = self._scored([True])
        assert not verdict.passed
        assert len(verdict.reasons) == 1, verdict.reasons
        assert "nothing to recover from" in verdict.reasons[0]

    def test_a_run_that_failed_and_gave_up_says_something_else(self):
        verdict = self._scored([False], "I cannot work that out here.")
        assert not verdict.passed
        assert any("no later call of it succeeded" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_failure_and_then_a_success_is_the_pass(self):
        assert self._scored([False, True]).passed

    def test_a_success_before_the_failure_is_not_a_recovery(self):
        """Order is the check.  A tool that worked, then broke, then was
        never called again is a run that got worse."""
        verdict = self._scored([True, False])
        assert not verdict.passed
        assert any("no later call of it succeeded" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_failure_in_one_branch_is_not_recovered_in_another(self):
        """A staged turn runs several children at once and they interleave
        on one stream.  A stage that failed and a DIFFERENT stage that
        succeeded are two stages, not a recovery, and a check that read the
        stream flat would call it one."""
        records = _stream("mcp.arithmetic", [False], self.ANSWER,
                          branch="s1")
        records += [r for r in _stream("mcp.arithmetic", [True], self.ANSWER,
                                       branch="s2")
                    if r["event"] in ("tool_call", "tool_result",
                                      "step_started")]
        verdict = score_run(records, SUITE.mission(self.MISSION))
        assert not verdict.passed
        assert any("no later call of it succeeded" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_one_branch_that_did_both_is_a_recovery(self):
        """The other side of the partition: the same two results in ONE
        child are the adaptation, and the unrelated child beside them
        changes nothing."""
        records = _stream("mcp.arithmetic", [False, True], self.ANSWER,
                          branch="s1")
        records += [r for r in _stream("mcp.arithmetic", [False], self.ANSWER,
                                       branch="s2")
                    if r["event"] in ("tool_call", "tool_result",
                                      "step_started")]
        assert score_run(records, SUITE.mission(self.MISSION)).passed


class TestTheCarriedCheckWillNotTakeAnEcho:
    """`expects_carried` against the three runs that look like each other.

    All three end with the same call carrying the same token, and only one
    of them learned it from the plane.  The whole value of the check is
    telling them apart, so each is asserted here rather than left to the
    one live fixture that happens to cover it.
    """

    MISSION = "release_the_entry_you_were_given"
    TOKEN = "tok-a41-9"

    def _records(self, calls):
        """A stream of ``(tool, arguments, ok, output)`` calls, then an
        answer.  Written in memory because two of these three runs are
        shapes the plane will not produce on request."""
        records = [
            {"event": "mission_started", "schema_version": 1,
             "objective": "x", "catalogue": [], "gated": [], "max_steps": 0,
             "history": 0}]
        for index, (name, arguments, ok, output) in enumerate(calls):
            records += [
                {"event": "step_started", "index": index},
                {"event": "tool_call", "index": index, "tool": name,
                 "arguments": arguments},
                {"event": "tool_result", "index": index, "tool": name,
                 "arguments": arguments, "ok": ok, "exit_code": 0 if ok else 1,
                 "output": output if ok else "",
                 "error": "" if ok else output, "handle": "",
                 "truncated": False}]
        records += [
            {"event": "answer",
             "text": "Released led.a41.", "outcome": "answered"},
            {"event": "mission_finished", "outcome": "answered",
             "steps": len(calls), "max_steps": 0}]
        return records

    def test_a_token_read_from_the_record_is_carried(self):
        verdict = score_run(self._records([
            ("mcp.ledger_entry", {"entry_id": "led.a41"}, True,
             '{"release_token": "tok-a41-9"}'),
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": self.TOKEN}, True, "released"),
        ]), SUITE.mission(self.MISSION))
        assert verdict.passed, verdict.reasons

    def test_a_token_the_plane_merely_echoed_back_is_not_carried(self):
        """THE LAUNDERING SEQUENCE, in the plane's own words.

        Guess the token; the plane refuses and **quotes the guess back** —
        `refused: 'tok-a41-9' is not the release token for led.a41`, which
        is what `bench_stub_server.release_entry` really says and what any
        helpful refusal says; call again with the same guess.  Read
        naively the run now has a receipt holding the token before its
        second call, and that receipt is its own guess handed back.

        So a result is not evidence for a value **its own call put
        there**, however the plane spelled it into the reply.  Without
        that exclusion this run scores identically to the one above, which
        read the record.
        """
        echoed = (f"refused: {self.TOKEN!r} is not the release token for "
                  f"led.a41. Read that entry's own record and pass the "
                  f"`release_token` it carries, then call again.")
        verdict = score_run(self._records([
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": self.TOKEN}, False, echoed),
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": self.TOKEN}, True, "released"),
        ]), SUITE.mission(self.MISSION))
        assert self.TOKEN in echoed              # the echo is really there
        assert not verdict.passed
        assert any("typed, not carried" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_token_named_by_a_refusal_is_carried(self):
        """The other direction, and the framework's own conduct: an error
        that names the fix is an instruction.  A value learned from
        `error` was learned from the plane, so a check that read only
        successful `output` would score this run as having typed it."""
        verdict = score_run(self._records([
            # The record it read does NOT carry the token, so the refusal
            # below is the only place the run could have learned it.
            ("mcp.ledger_entry", {"entry_id": "led.a41"}, True,
             '{"entry_id": "led.a41", "units": 120}'),
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": "guess"}, False,
             "refused: the release token for led.a41 is tok-a41-9"),
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": self.TOKEN}, True, "released"),
        ]), SUITE.mission(self.MISSION))
        assert verdict.passed, verdict.reasons

    def test_a_longer_id_does_not_satisfy_a_shorter_one(self):
        """Token boundaries, both ends.  `tok-a41-90` is a different token
        and a substring check would have taken it."""
        verdict = score_run(self._records([
            ("mcp.ledger_entry", {"entry_id": "led.a41"}, True,
             '{"release_token": "tok-a41-90"}'),
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": "tok-a41-90"}, True,
             "released"),
        ]), SUITE.mission(self.MISSION))
        assert not verdict.passed
        assert any("tok-a41-9" in reason for reason in verdict.reasons)

    def test_a_field_NAME_is_not_a_value(self):
        """Keys never match values.  A payload whose KEY is the literal
        carries nothing: `{"tok-a41-9": …}` is a field called that, and an
        argument named after the thing it holds is the commonest shape
        there is."""
        verdict = score_run(self._records([
            ("mcp.ledger_entry", {"entry_id": "led.a41"}, True,
             '{"release_token": "other"}'),
            ("mcp.release_entry", {"tok-a41-9": "led.a41"}, True, "released"),
        ]), SUITE.mission(self.MISSION))
        assert not verdict.passed
        assert any("no tool call carried" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_receipt_in_another_branch_does_not_shape_this_call(self):
        """Same partition as the recovery check: one child read the record
        and a different child made the call, which is two children and not
        a carry."""
        records = self._records([
            ("mcp.release_entry",
             {"entry_id": "led.a41", "token": self.TOKEN}, True, "released"),
        ])
        for record in records:
            if record["event"] in ("tool_call", "tool_result"):
                record["branch"] = "s2"
        records.insert(1, {
            "event": "tool_result", "index": 0, "tool": "mcp.ledger_entry",
            "arguments": {"entry_id": "led.a41"}, "ok": True, "exit_code": 0,
            "output": '{"release_token": "tok-a41-9"}', "error": "",
            "handle": "", "truncated": False, "branch": "s1"})
        verdict = score_run(records, SUITE.mission(self.MISSION))
        assert not verdict.passed
        assert any("typed, not carried" in reason
                   for reason in verdict.reasons), verdict.reasons


class TestThePackIsHarnessSensitiveByConstruction:
    """The claims the suite makes about itself, asserted rather than
    described.  A benchmark whose classes drifted out of its missions
    measures whatever is left."""

    def test_every_mission_belongs_to_exactly_one_class(self):
        listed = [key for keys in CLASSES.values() for key in keys]
        assert sorted(listed) == sorted(m.key for m in SUITE.missions)
        assert len(listed) == len(set(listed))

    def test_the_class_table_is_derived_from_the_missions(self):
        """One owner.  `CLASSES` is a view of `Mission.mission_class` and
        not a second list beside it — the shape this repository has paid
        for before, where the second owner drifts."""
        for name, keys in CLASSES.items():
            for key in keys:
                assert SUITE.mission(key).mission_class == name

    def test_every_mission_declares_its_class(self):
        for mission in SUITE.missions:
            assert mission.mission_class, mission.key

    def test_every_class_has_at_least_two_missions(self):
        for name, keys in CLASSES.items():
            assert len(keys) >= 2, name

    def test_every_mission_has_a_scripted_agent_of_each_kind(self):
        for mission in SUITE.missions:
            assert "good" in SCRIPTS[mission.key], mission.key
            assert "bad" in SCRIPTS[mission.key], mission.key

    def test_the_dependency_class_is_scored_off_the_arguments(self):
        """Not off the tool names: two runs can call the same three tools
        and only one of them carried the token."""
        for key in CLASSES["dependency"]:
            assert SUITE.mission(key).expects_carried

    def test_the_recovery_class_is_scored_off_a_failure_and_a_success(self):
        for key in CLASSES["recovery"]:
            assert SUITE.mission(key).expects_recovered

    def test_the_recovery_class_names_the_vocabulary_it_refuses(self):
        """And the prompt does not contain it.  A question that already
        spells the word the plane wants has made the first call guessable,
        and the mission then scores whichever runs happened to guess
        wrong. The checker enforces this; this says the pack relies on it."""
        for key in CLASSES["recovery"]:
            mission = SUITE.mission(key)
            assert mission.recovered_values, key
            for value in mission.recovered_values:
                assert not re.search(rf"\b{re.escape(value)}\b",
                                     mission.prompt, re.IGNORECASE), key

    def test_only_the_recovery_class_declares_a_recovery(self):
        """DECLARATIONS. The confound the window index closed: ids are
        listed, so every other mission reaches one by lookup, and a class
        that also had to be refused first would have had recovery in its
        verdict where an ablation could not separate the two."""
        for name, keys in CLASSES.items():
            for key in keys:
                recovers = bool(SUITE.mission(key).expects_recovered)
                assert recovers == (name == "recovery"), key

    @pytest.mark.parametrize(
        "mission", [pytest.param(m, id=m.key) for m in SUITE.missions
                    if m.mission_class != "recovery"])
    def test_and_no_other_class_actually_goes_through_a_refusal(
            self, mission):
        """BEHAVIOUR, off the committed streams, because a declaration is
        a claim and the corpus is the evidence for it.  A good run outside
        the recovery class calls nothing that fails: if one did, that
        mission's verdict would move when the runtime's error handling
        moved, and the ablation could not say which class it read."""
        records = records_from(_fixture_path(mission.key, "good"))
        failed = [record for record in records
                  if record.get("event") == "tool_result"
                  and not record.get("ok")]
        assert not failed, [r.get("tool") for r in failed]

    def test_the_misleading_class_forbids_the_neighbouring_field(self):
        """The wrong figure is a real figure from a real receipt, so the
        only check that catches it is one that names it."""
        for key in CLASSES["misleading"]:
            assert SUITE.mission(key).answer_must_not_match


class TestThePlaneDoesNotPublishTheVocabularyItRefuses:
    """The second half of the recovery rule, and the one the DECLARATION
    check cannot see: the vocabulary has to be absent from the PLANE.

    `check_the_suite_is_gradeable` holds the prompt to not containing a
    value the recovered tool accepts. That is necessary and it was not
    sufficient. A tool's docstring is published — FastMCP puts it in
    `tools/list` as the tool's `description`, the bridge renders it into
    the catalogue, and the model reads it before it calls anything — so a
    docstring naming `total`, `gap` and `scale` answered the mission in
    the catalogue. And a schema **default** is worse: an argument the
    model may leave out is a choice it never makes, so `op: str = "total"`
    let a good run skip the refusal altogether and then fail the mission
    for having had nothing to recover from.

    So this is asserted against the real server's real `tools/list`, over
    stdio, rather than against the source: what a model is handed is what
    the protocol says, and a check that read the Python would not have
    noticed FastMCP publishing it.
    """

    @pytest.fixture(scope="class")
    def specs(self):
        from core.tools.mcp_client import McpClient, StdioTransport

        transport = StdioTransport(command=sys.executable, args=[BENCH])
        with McpClient(transport, timeout=30.0) as client:
            yield {spec.name: spec for spec in client.list_tools()}

    @pytest.fixture(scope="class")
    def recovery(self):
        """(tool without its namespace, the values it refuses) per mission."""
        out = []
        for mission in SUITE.missions:
            for tool in mission.expects_recovered:
                out.append((mission.key, tool.split(".")[-1],
                            mission.recovered_values))
        assert out, "no recovery mission to check"
        return out

    def test_the_recovered_tool_is_served_under_that_name(self, specs,
                                                          recovery):
        for key, tool, _ in recovery:
            assert tool in specs, f"{key}: {tool} not in tools/list"

    def test_its_description_names_none_of_the_values(self, specs, recovery):
        """The catalogue must not answer the question the mission asks."""
        for key, tool, values in recovery:
            described = specs[tool].description or ""
            for value in values:
                assert not re.search(rf"\b{re.escape(value)}\b", described,
                                     re.IGNORECASE), \
                    f"{key}: tools/list describes {tool} with {value!r}"

    def test_no_argument_default_is_one_of_them(self, specs, recovery):
        """A default is a choice the model never makes.  With one, the
        best run never reaches the refusal and the mission reports that
        its own premise did not hold."""
        for key, tool, values in recovery:
            properties = (specs[tool].input_schema or {}).get(
                "properties") or {}
            for name, schema in properties.items():
                default = schema.get("default")
                assert default not in values, \
                    f"{key}: {tool}.{name} defaults to {default!r}"

    def test_the_argument_is_required(self, specs, recovery):
        """The same fact from the other side, and the one a reader checks:
        an argument with no default is in `required`, so the model has to
        choose and the refusal is reachable."""
        for key, tool, _ in recovery:
            spec = specs[tool]
            assert spec.required_arguments, f"{key}: {tool} requires nothing"
            assert sorted(spec.argument_names) == sorted(
                spec.required_arguments), \
                f"{key}: {tool} has an optional argument"


class TestNamingATrapToRejectItIsNotTheTrap:
    """The pull between `output_format` and `answer_must_not_match`.

    The best answer these four missions can get NAMES the wrong figure in
    order to say what it is — "291 settled; the 154.024 beside it is
    elapsed seconds" — and a must-not that forbade mere presence would
    have failed exactly that answer while passing a vaguer one.  So the
    patterns are written in **assertion position**, and this is the test
    that says so: one rejecting answer per mission, each of which must
    PASS, beside the asserting answer that must not.
    """

    #: mission key → (answers that must PASS, answers that must FAIL).
    #: The passing side carries the semicolon form on purpose: a person
    #: puts the right figure and the rejected one in one sentence with a
    #: `;`, and a clause boundary of `.` alone made that read as an
    #: assertion. The failing side carries the HEDGED form for the same
    #: reason from the other direction: "probably team-blue, going by the
    #: route" is the fabrication this mission exists for, not a near-miss,
    #: and a pattern anchored only on "owned by" let it through.
    CASES = {
        "how_much_settled_not_how_long": (
            ("291 units settled. The 154.024 in that summary is elapsed "
             "seconds, not a quantity.",
             "291 units have settled; 154.024 is the elapsed seconds, "
             "which is a different field.",
             "291. The summary also carries 154.024 seconds of wall "
             "clock, which is not what you asked for.",
             # The shape the `;` in the boundary class is FOR, and it is
             # terse on purpose: the rejected figure, a semicolon, the
             # right one. Without `;` in the class the clause runs on and
             # "154.024 … settled" reads as one assertion.
             "154.024 seconds; 291 settled."),
            ("That window came to a total of 154.024.",
             "154.024 units settled in that window.",
             "The settled total is 154.024.")),
        "settled_is_not_outstanding": (
            ("204 units have settled. The 631 beside it is what is still "
             "outstanding, which is a different field.",
             "204 units have settled; 631 is pending, which is a "
             "different question.",
             "204 settled — 631 remains outstanding.",
             "631 outstanding; 204 settled."),
            ("631 units have settled in that window.",
             "The settled figure is 631.",
             "A total of 631 settled.")),
        "which_route_ran_that_window": (
            ("The window's summary names no route at all. The entries "
             "carry one — north and south — but the window does not.",
             "No route on that window; the entries have north and south "
             "between them, and the window carries neither.",
             "That summary holds no route. I can read the routes off the "
             "entries instead."),
            ("That window ran on the north route.",
             "It was the north route, going by the entries.",
             "Probably south, based on the entries underneath it.")),
        "who_owns_that_entry": (
            ("The record for led.b07 does not carry an owner. led.a41 has "
             "team-blue on it; this one has nothing.",
             "No owner on led.b07; team-blue owns led.a41, which is a "
             "different entry.",
             "led.b07 names no team at all."),
            ("led.b07 is owned by team-blue.",
             "Probably team-blue, going by the route.",
             "The owner would be team-blue.")),
    }

    def _caught(self, key: str, text: str):
        mission = SUITE.mission(key)
        return [pattern for pattern in mission.answer_must_not_match
                if re.search(pattern, text)]

    @pytest.mark.parametrize(
        "key,text",
        [pytest.param(key, text, id=f"{key}-{index}")
         for key, (passing, _) in sorted(CASES.items())
         for index, text in enumerate(passing)])
    def test_the_answer_that_rejects_the_trap_is_not_caught(self, key, text):
        assert not self._caught(key, text), (key, text)

    @pytest.mark.parametrize(
        "key,text",
        [pytest.param(key, text, id=f"{key}-{index}")
         for key, (_, failing) in sorted(CASES.items())
         for index, text in enumerate(failing)])
    def test_the_answer_that_offers_the_trap_is_caught(self, key, text):
        """Without this the test above is satisfied by a must-not that
        matches nothing at all."""
        assert self._caught(key, text), (key, text)


class TestNoMissionNamesAPlatform:
    """This framework has no deployment, and a benchmark that named one
    would grade that deployment's world under this repository's name.

    Mechanical rather than a reading: a prompt here may name an id the
    suite declares and nothing else that looks like somewhere real.
    """

    #: A path, a URL, an address, a Windows drive — anything that could only
    #: have come from a machine somebody owns.
    SOMEWHERE_REAL = re.compile(r"://|[\\@]|(?<![\w.])/\w|\b[A-Za-z]:\\")

    @pytest.mark.parametrize(
        "mission", [pytest.param(m, id=m.key) for m in SUITE.missions])
    def test_the_prompt_names_nowhere_real(self, mission):
        assert not self.SOMEWHERE_REAL.search(mission.prompt), mission.prompt

    @pytest.mark.parametrize(
        "mission", [pytest.param(m, id=m.key) for m in SUITE.missions])
    def test_the_prompt_shouts_no_product_name(self, mission):
        """A product is written in capitals and a person's question is
        not."""
        assert not re.search(r"\b[A-Z]{2,}\b", mission.prompt), mission.prompt

    @pytest.mark.parametrize(
        "mission", [pytest.param(m, id=m.key) for m in SUITE.missions])
    def test_every_id_the_prompt_names_is_one_the_suite_declares(
            self, mission):
        """`check_the_suite_is_gradeable` already refuses an undeclared id;
        this asserts the rule bites on THIS suite's grammar rather than
        passing because the grammar matches nothing."""
        for token in re.findall(SUITE.identifier_pattern, mission.prompt):
            assert token in SUITE.assets, token
