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
from core.eval.score import score_run
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
            tool("mcp.arithmetic", numbers=[120, 86, 112], op="sum"),
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
            tool("mcp.arithmetic", numbers=[112, 31], op="difference"),
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
        "good": [
            tool("mcp.window_rollup", window="2"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window's own summary names no route: what it "
                   "carries is 318 units settled, 24 pending, 154.024 "
                   "seconds and 7 blocks. A route is a property of the "
                   "entries rather than of the window, so I can read them "
                   "off the entries if that is what you need."),
        ],
        "bad": [
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window ran on the north route and settled 318 "
                   "units across 7 blocks."),
            answer("That window ran on the north route and settled 318 "
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
    "the_window_is_not_called_two": {
        "good": [
            tool("mcp.window_rollup", window="2"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window took 154.024 seconds and ran in 7 blocks."),
        ],
        "bad": [
            tool("mcp.window_rollup", window="2"),
            answer("I cannot get that: this plane holds no window 2, so "
                   "the timing is not available."),
        ],
    },
    "the_kinds_are_not_the_words": {
        "good": [
            tool("mcp.ledger_index", kind="returns"),
            tool("mcp.ledger_index", kind="back"),
            tool("mcp.ledger_entry", entry_id="led.c19"),
            answer("One entry came back: led.c19, on the south route, with "
                   "31 units."),
        ],
        "bad": [
            tool("mcp.ledger_index", kind="returns"),
            answer("There are no returns on this plane — the listing does "
                   "not hold that kind."),
        ],
    },

    # -- misleading evidence -------------------------------------------------
    "how_much_settled_not_how_long": {
        "good": [
            tool("mcp.window_rollup", window="2"),
            tool("mcp.window_rollup", window="win-0002"),
            answer("318 units settled — that is the settled figure from "
                   "the window's own summary."),
        ],
        # The measured failure: the elapsed-seconds field read as the total.
        "bad": [
            tool("mcp.window_rollup", window="win-0002"),
            answer("That window came to a total of 154.024."),
            answer("That window came to a total of 154.024."),
        ],
    },
    "settled_is_not_outstanding": {
        "good": [
            tool("mcp.window_rollup", window="3"),
            tool("mcp.window_rollup", window="win-0003"),
            answer("204 units have settled. The larger figure in that "
                   "summary is what is still outstanding, which is a "
                   "different question."),
        ],
        "bad": [
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
    "the_window_is_not_called_two": "no later call of it succeeded",
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


def _stream(tool: str, results, answer_text: str):
    """A conforming stream: one call per entry of *results*, then an answer.

    Built in memory rather than driven, because the two runs this class
    needs are runs the bench plane cannot produce: its refusals are what
    make the recovery class's first error unavoidable, so "the tool never
    failed" is a shape only a hand-built stream has.  Everything else in
    this file is a real run for exactly the opposite reason.
    """
    records = [
        {"event": "mission_started", "schema_version": 1,
         "objective": "x", "catalogue": [tool], "gated": [], "max_steps": 0,
         "history": 0}]
    for index, ok in enumerate(results):
        records += [
            {"event": "step_started", "index": index},
            {"event": "tool_call", "index": index, "tool": tool,
             "arguments": {}},
            {"event": "tool_result", "index": index, "tool": tool,
             "arguments": {}, "ok": ok, "exit_code": 0 if ok else 1,
             "output": "154.024 seconds, 7 blocks" if ok else "",
             "error": "" if ok else "no such window", "handle": "",
             "truncated": False}]
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

    MISSION = "the_window_is_not_called_two"
    ANSWER = "That window took 154.024 seconds and ran in 7 blocks."

    def test_a_run_that_never_failed_had_nothing_to_recover_from(self):
        """And it is the ONLY thing wrong with it: the right answer, the
        right tool, the right outcome — and no adaptation, because there
        was nothing to adapt to."""
        mission = SUITE.mission(self.MISSION)
        verdict = score_run(
            _stream("mcp.window_rollup", [True], self.ANSWER), mission)
        assert not verdict.passed
        assert len(verdict.reasons) == 1, verdict.reasons
        assert "nothing to recover from" in verdict.reasons[0]

    def test_a_run_that_failed_and_gave_up_says_something_else(self):
        mission = SUITE.mission(self.MISSION)
        verdict = score_run(
            _stream("mcp.window_rollup", [False], "I cannot get that."),
            mission)
        assert not verdict.passed
        assert any("no later call of it succeeded" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_failure_and_then_a_success_is_the_pass(self):
        mission = SUITE.mission(self.MISSION)
        verdict = score_run(
            _stream("mcp.window_rollup", [False, True], self.ANSWER),
            mission)
        assert verdict.passed, verdict.reasons

    def test_a_success_before_the_failure_is_not_a_recovery(self):
        """Order is the check.  A tool that worked, then broke, then was
        never called again is a run that got worse."""
        mission = SUITE.mission(self.MISSION)
        verdict = score_run(
            _stream("mcp.window_rollup", [True, False], self.ANSWER),
            mission)
        assert not verdict.passed
        assert any("no later call of it succeeded" in reason
                   for reason in verdict.reasons), verdict.reasons


class TestThePackIsHarnessSensitiveByConstruction:
    """The claims the suite makes about itself, asserted rather than
    described.  A benchmark whose classes drifted out of its missions
    measures whatever is left."""

    def test_every_mission_belongs_to_exactly_one_class(self):
        listed = [key for keys in CLASSES.values() for key in keys]
        assert sorted(listed) == sorted(m.key for m in SUITE.missions)
        assert len(listed) == len(set(listed))

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

    def test_the_misleading_class_forbids_the_neighbouring_field(self):
        """The wrong figure is a real figure from a real receipt, so the
        only check that catches it is one that names it."""
        for key in CLASSES["misleading"]:
            assert SUITE.mission(key).answer_must_not_match


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
