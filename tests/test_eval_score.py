# tests/test_eval_score.py — the verdict, and every check that can produce one

"""Scoring, against hand-built streams and against the committed corpus.

Two halves, and they check different things.

The **hand-built** streams are the smallest record list that can make one
machine check pass and one that can make it fail, written out literally so
that what the scorer reads is visible in the test rather than produced by a
mission somewhere. Every check is exercised both ways round: a check that
cannot fail is a column of PASS that means nothing.

The **committed corpus** under `tests/fixtures/eval/` is the other half —
real streams from real runs of the real loop (see
`tests/test_eval_stub_suite.py`, which produced them). Those catch what a
hand-built record never will: a field the emitter spells differently, a
grounding record that arrives twice, an answer that goes out as deltas
first.

`must`/`must_not` are asserted to be surfaced and NOT scored. An answer that
plainly violates a rubric clause still passes when the machine checks pass,
because the reader's half is the reader's — a scorer that guessed at prose
would be a scorer nobody could argue with.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.eval.score import Totals, records_from, score_run, score_suite
from core.eval.stub_suite import SUITE
from core.eval.suite import Mission, Suite

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval"


# ── the smallest streams that mean something ────────────────────────────────

def started(**extra):
    record = {"event": "mission_started", "schema_version": 1,
              "objective": "o", "catalogue": ["mcp.echo"], "gated": [],
              "max_steps": 8, "history": 0}
    record.update(extra)
    return record


def step(index=0, **extra):
    return {"event": "step_started", "index": index, **extra}


def call(tool="mcp.echo", index=0, **extra):
    return {"event": "tool_call", "index": index, "tool": tool,
            "arguments": {}, **extra}


def result(tool="mcp.echo", index=0, ok=True, output="out", **extra):
    return {"event": "tool_result", "index": index, "tool": tool,
            "arguments": {}, "ok": ok, "exit_code": 0 if ok else 1,
            "output": output, "error": "" if ok else "boom", "handle": "r1",
            "truncated": False, **extra}


def rejected(index=0, problem="not JSON", **extra):
    return {"event": "reply_rejected", "index": index, "problem": problem,
            **extra}


def gate(tool="mcp.run_shell_command", index=0):
    return {"event": "gate_requested", "index": index, "tool": tool,
            "arguments": {}, "reason": "a person decides"}


def grounding(grounded=True, verified=True, repairing=False, repairs=0):
    return {"event": "grounding", "ran": True, "grounded": grounded,
            "verified": verified, "repairs": repairs, "repairing": repairing,
            "caveat": "", "unsupported": [], "silent": [], "uncited": [],
            "checks": []}


def answered(text="the answer", outcome="answered"):
    return {"event": "answer", "text": text, "outcome": outcome}


def finished(outcome="answered", steps=2, **extra):
    return {"event": "mission_finished", "outcome": outcome, "steps": steps,
            "max_steps": 8, **extra}


def a_clean_run(**extra):
    """A stream that passes anything not asserted about."""
    return [started(**extra.pop("started", {})), step(0), call(), result(),
            step(1), grounding(), answered(), finished()]


def a_mission(**fields) -> Mission:
    base = dict(key="k", flag="synthesis", prompt="p", must=("read me",),
                must_not=("not me",), because="a test")
    base.update(fields)
    return Mission(**base)


# ── one check at a time, both ways round ────────────────────────────────────

class TestEveryMachineCheck:
    """Table-driven: the mission field, a stream that satisfies it, a stream
    that does not, and the sentence the failure has to produce."""

    CASES = [
        pytest.param(
            {"expects_tools": ("mcp.echo",)},
            a_clean_run(),
            [started(), step(0), grounding(), answered(), finished()],
            "never called mcp.echo", id="expects_tools"),
        pytest.param(
            {"forbids_tools": ("mcp.run_shell_command",)},
            a_clean_run(),
            [started(), step(0), call(tool="mcp.run_shell_command"),
             result(tool="mcp.run_shell_command"), grounding(), answered(),
             finished()],
            "reached for mcp.run_shell_command", id="forbids_tools"),
        pytest.param(
            {"forbids_tools": ("mcp.run_shell_command",)},
            a_clean_run(),
            [started(), step(0), gate(), finished(outcome="awaiting_approval",
                                                  steps=1)],
            "reached for mcp.run_shell_command", id="forbids_tools_at_a_gate"),
        pytest.param(
            {"forbids_tools": ("mcp.run_shell_command",)},
            a_clean_run(),
            [started(), step(0), rejected(tool="mcp.run_shell_command"),
             grounding(), answered(), finished()],
            "the call never left the loop", id="forbids_tools_named_only"),
        pytest.param(
            {"expects_outcome": "answered"},
            a_clean_run(),
            [started(), step(0), grounding(),
             answered(outcome="answered_with_caveat"),
             finished(outcome="answered_with_caveat")],
            "ended 'answered_with_caveat'", id="expects_outcome"),
        pytest.param(
            {"expects_outcome": "answered", "expects_caveat_ok": True},
            [started(), step(0), grounding(),
             answered(outcome="answered_with_caveat"),
             finished(outcome="answered_with_caveat")],
            [started(), step(0), finished(outcome="budget_exhausted",
                                          budget="steps")],
            "ended 'budget_exhausted'", id="expects_caveat_ok"),
        pytest.param(
            {"expects_grounded": True},
            a_clean_run(),
            [started(), step(0), grounding(grounded=False), answered(),
             finished()],
            "grounded=False", id="expects_grounded"),
        pytest.param(
            {"expects_grounded": True},
            a_clean_run(),
            [started(), step(0), answered(), finished()],
            "no grounding record", id="expects_grounded_absent"),
        pytest.param(
            {"answer_must_match": (r"\b42\b",)},
            [started(), step(0), grounding(), answered("it is 42"), finished()],
            [started(), step(0), grounding(), answered("it is 41"), finished()],
            "does not match", id="answer_must_match"),
        pytest.param(
            {"answer_must_not_match": (r"(?i)cannot provide",)},
            a_clean_run(),
            [started(), step(0), grounding(),
             answered("I cannot provide that"), finished()],
            "which this mission forbids", id="answer_must_not_match"),
        pytest.param(
            {"max_reply_rejected": 0},
            a_clean_run(),
            [started(), step(0), rejected(), step(1), grounding(),
             answered(), finished()],
            "1 reply/replies the loop could not read", id="max_reply_rejected"),
        pytest.param(
            {"max_reply_rejected": 1},
            [started(), step(0), rejected(), step(1), grounding(),
             answered(), finished()],
            [started(), step(0), rejected(), step(1), rejected(index=1),
             step(2), grounding(), answered(), finished()],
            "2 reply/replies", id="max_reply_rejected_allows_one"),
        pytest.param(
            {"must_not_stage": True},
            a_clean_run(),
            [started(), step(0, plan=[{"id": "s1", "goal": "g",
                                       "rung": "tool"}]),
             grounding(), answered(), finished()],
            "the run was STAGED", id="must_not_stage"),
    ]

    @pytest.mark.parametrize("fields,good,bad,sentence", CASES)
    def test_the_check_passes_and_fails(self, fields, good, bad, sentence):
        mission = a_mission(**fields)
        passing = score_run(good, mission)
        assert passing.passed, passing.reasons
        failing = score_run(bad, mission)
        assert not failing.passed
        assert any(sentence in reason for reason in failing.reasons), \
            failing.reasons

    def test_a_mission_that_checks_nothing_passes_a_clean_run(self):
        assert score_run(a_clean_run(), a_mission()).passed

    def test_the_answer_is_the_only_prose_the_scorer_reads(self):
        """A rubric clause the answer plainly violates does not fail it."""
        mission = a_mission(must=("names every actor by id",),
                            must_not=("vague hedging",))
        verdict = score_run(
            [started(), step(0), grounding(),
             answered("some stuff happened, roughly"), finished()], mission)
        assert verdict.passed
        assert "must: names every actor by id" in verdict.needs_reader
        assert "must not: vague hedging" in verdict.needs_reader


class TestTheStreamItself:
    def test_an_empty_stream_is_a_failure_and_says_which_clause(self):
        verdict = score_run([], a_mission())
        assert not verdict.passed
        assert any("zero events" in reason for reason in verdict.reasons)

    def test_a_stream_that_never_closed_is_a_failure(self):
        verdict = score_run([started(), step(0), call(), result()],
                            a_mission())
        assert any("no mission_finished" in reason
                   for reason in verdict.reasons)

    def test_a_record_that_does_not_conform_is_a_failure(self):
        broken = a_clean_run()
        broken[3] = dict(broken[3])
        broken[3].pop("ok")
        verdict = score_run(broken, a_mission())
        assert any("do not conform" in reason for reason in verdict.reasons)
        assert any("'ok'" in reason for reason in verdict.reasons)

    def test_a_missing_run_directory_is_a_failure_not_a_crash(self, tmp_path):
        verdict = score_run(tmp_path / "nowhere", a_mission())
        assert not verdict.passed
        assert any("no stream" in reason for reason in verdict.reasons)

    def test_the_interim_grounding_report_is_not_the_verdict(self):
        """A repair turn emits `grounding` with `repairing: true` on its way
        past. Reading the last record blindly would score a repaired answer
        by the report that triggered the repair — or the other way round."""
        records = [started(), step(0),
                   grounding(grounded=False, repairing=True, repairs=1),
                   step(1), grounding(grounded=True, repairs=1),
                   answered(), finished()]
        verdict = score_run(records, a_mission(expects_grounded=True))
        assert verdict.passed, verdict.reasons
        assert verdict.kpis["grounded"] is True

    def test_a_run_that_stopped_mid_repair_has_no_verdict_to_read(self):
        """The case that separates 'the last grounding record' from 'the
        grounding verdict': the run ran out of steps while repairing, so the
        only report on the stream is the interim one that TRIGGERED the
        repair. Reading it as the verdict would report a run with no answer
        as having been judged ungrounded, which is a different fact."""
        records = [started(), step(0),
                   grounding(grounded=False, repairing=True, repairs=1),
                   finished(outcome="budget_exhausted", steps=1,
                            budget="steps")]
        verdict = score_run(records, a_mission(expects_grounded=True))
        assert verdict.kpis["grounded"] is None
        assert any("no grounding record" in reason
                   for reason in verdict.reasons), verdict.reasons


class TestTheKpis:
    def test_human_interventions_are_gates_plus_injections(self):
        records = [started(), step(0, injected="ask about totals"), gate(),
                   step(1), grounding(), answered(), finished()]
        kpis = score_run(records, a_mission()).kpis
        assert kpis["gate_requested"] == 1
        assert kpis["injected"] == 1
        assert kpis["human_interventions"] == 2

    def test_tokens_come_off_the_run_ledger(self):
        records = a_clean_run()
        records[-1] = finished(usage={"prompt_tokens": 90,
                                      "completion_tokens": 10,
                                      "total_tokens": 100, "calls": 3})
        kpis = score_run(records, a_mission()).kpis
        assert kpis["tokens"] == 100
        assert kpis["model_calls"] == 3

    def test_a_provider_that_reported_nothing_is_not_zero_tokens(self):
        assert score_run(a_clean_run(), a_mission()).kpis["tokens"] is None

    def test_a_failed_tool_is_counted_as_a_refusal(self):
        records = [started(), step(0), call(), result(ok=False), step(1),
                   grounding(), answered(), finished()]
        assert score_run(records, a_mission()).kpis["refusals"] == 1

    def test_the_opening_frame_is_carried_into_the_columns(self):
        records = a_clean_run()
        records[0] = started(profile="safe", sandbox="bwrap",
                             run_id="run_x", protocol="native")
        kpis = score_run(records, a_mission()).kpis
        assert (kpis["profile"], kpis["sandbox"], kpis["run_id"],
                kpis["protocol"]) == ("safe", "bwrap", "run_x", "native")

    def test_the_protocol_defaults_to_json_when_absent(self):
        """`protocol` rides `mission_started` only when it is not the
        default, so a report column that read it raw would say `None` for
        every run ever recorded."""
        assert score_run(a_clean_run(), a_mission()).kpis["protocol"] == "json"


class TestEnvelopesAndBareNdjson:
    """A run directory is a RunStore directory, and the store wraps.

    The wire carries the bare record and `core.durable` wraps it in
    `{seq, at, record}`. Both are the same run, and a scorer that could only
    read one of them could not score yesterday's.
    """

    def _write(self, path: Path, records, envelope: bool):
        lines = []
        for index, record in enumerate(records, start=1):
            lines.append(json.dumps(
                {"seq": index, "at": "2026-08-16T00:00:00Z", "record": record}
                if envelope else record))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_both_read_to_the_same_records(self, tmp_path):
        records = a_clean_run()
        self._write(tmp_path / "bare" / "events.jsonl", records, False)
        self._write(tmp_path / "wrapped" / "events.jsonl", records, True)
        assert (records_from(tmp_path / "bare")
                == records_from(tmp_path / "wrapped") == records)

    def test_both_score_the_same(self, tmp_path):
        mission = a_mission(expects_tools=("mcp.echo",), expects_grounded=True)
        self._write(tmp_path / "bare" / "events.jsonl", a_clean_run(), False)
        self._write(tmp_path / "wrapped" / "events.jsonl", a_clean_run(), True)
        bare = score_run(tmp_path / "bare", mission)
        wrapped = score_run(tmp_path / "wrapped", mission)
        assert bare.passed and wrapped.passed
        assert bare.kpis == wrapped.kpis

    def test_a_run_store_directory_one_level_down_is_found(self, tmp_path):
        """What `--out` leaves behind: the harness's capture at the top and
        the store's own `run_<stamp>/` beside it."""
        self._write(tmp_path / "k" / "runs" / "run_2026" / "events.jsonl",
                    a_clean_run(), True)
        assert records_from(tmp_path / "k") == a_clean_run()

    def test_a_torn_last_line_is_skipped_not_fatal(self, tmp_path):
        path = tmp_path / "k" / "events.jsonl"
        self._write(path, a_clean_run(), False)
        with path.open("a", encoding="utf-8") as log:
            log.write('{"event": "mission_fin')
        assert len(records_from(tmp_path / "k")) == len(a_clean_run())

    def test_an_events_file_may_be_named_directly(self, tmp_path):
        path = tmp_path / "somewhere.jsonl"
        self._write(path, a_clean_run(), False)
        assert score_run(path, a_mission()).kpis["outcome"] == "answered"


# ── the committed corpus ────────────────────────────────────────────────────

GOOD = [pytest.param(m, id=m.key) for m in SUITE.missions]
BAD = [pytest.param(m, id=m.key) for m in SUITE.missions
       if (FIXTURES / f"{m.key}.bad.jsonl").exists()]


class TestTheCommittedCorpus:
    """Real streams, from real runs of the real loop.

    `tests/test_eval_stub_suite.py` produced every one of these against the
    stub server; this file scores them without needing the server, which is
    the no-GPU path the whole harness exists to have.
    """

    @pytest.mark.parametrize("mission", GOOD)
    def test_the_good_agent_passes(self, mission):
        verdict = score_run(FIXTURES / f"{mission.key}.jsonl", mission)
        assert verdict.passed, verdict.reasons

    @pytest.mark.parametrize("mission", BAD)
    def test_the_bad_agent_fails(self, mission):
        verdict = score_run(FIXTURES / f"{mission.key}.bad.jsonl", mission)
        assert not verdict.passed

    def test_there_is_a_fixture_for_every_mission(self):
        missing = [m.key for m in SUITE.missions
                   if not (FIXTURES / f"{m.key}.jsonl").exists()]
        assert not missing, f"no committed stream for {missing}"

    def test_the_regression_cases_both_have_a_bad_agent(self):
        """ROADMAP §2.5's two cases are the reason this corpus exists."""
        for key in ("a_listing_is_not_a_plan", "answer_with_what_you_have"):
            assert (FIXTURES / f"{key}.bad.jsonl").exists()

    def test_the_staged_listing_is_caught_by_the_plan_on_step_started(self):
        mission = SUITE.mission("a_listing_is_not_a_plan")
        verdict = score_run(FIXTURES / f"{mission.key}.bad.jsonl", mission)
        assert verdict.kpis["staged"] is True
        assert any("STAGED" in reason for reason in verdict.reasons)
        good = score_run(FIXTURES / f"{mission.key}.jsonl", mission)
        assert good.kpis["staged"] is False

    def test_the_refusal_with_results_in_hand_is_caught(self):
        mission = SUITE.mission("answer_with_what_you_have")
        verdict = score_run(FIXTURES / f"{mission.key}.bad.jsonl", mission)
        assert any("cannot provide" in reason for reason in verdict.reasons)
        good = score_run(FIXTURES / f"{mission.key}.jsonl", mission)
        assert good.passed and good.kpis["refusals"] == 1

    def test_a_fabricated_figure_is_read_off_the_grounding_record(self):
        mission = SUITE.mission("two_views_one_line")
        verdict = score_run(FIXTURES / f"{mission.key}.bad.jsonl", mission)
        assert verdict.kpis["grounded"] is False
        assert verdict.kpis["outcome"] == "answered_with_caveat"


# ── the report ──────────────────────────────────────────────────────────────

def corpus(keys=None):
    """key → its committed stream, for whichever missions are wanted."""
    return {m.key: FIXTURES / f"{m.key}.jsonl"
            for m in SUITE.missions
            if keys is None or m.key in keys}


class TestTheReport:
    def test_the_halves_are_reported_apart(self):
        report = score_suite(corpus(), SUITE, "all")
        assert set(report.halves) == {"train", "test"}
        assert report.halves["train"].overall.missions == 7
        assert report.halves["test"].overall.missions == 4

    def test_there_is_no_blended_number_anywhere(self):
        """A success rate over train and test together is the number that
        makes a held-out set decorative."""
        report = score_suite(corpus(), SUITE, "all")
        blob = report.to_json()
        assert '"all"' not in blob
        assert "overall" in blob
        # ... and nothing counts all eleven missions at once.
        for half in report.halves.values():
            assert half.overall.missions < len(SUITE.missions)

    def test_one_half_can_be_scored_alone(self):
        report = score_suite(corpus(), SUITE, "test")
        assert set(report.halves) == {"test"}

    def test_a_mission_with_no_run_is_a_failure_and_is_counted(self):
        partial = corpus({"two_views_one_line"})
        report = score_suite(partial, SUITE, "test")
        totals = report.halves["test"].overall
        assert totals.missions == 4
        assert totals.missing == 3
        assert totals.passed == 1
        assert totals.success_rate == 0.25
        assert any("not run" in v.reasons[0]
                   for v in report.halves["test"].verdicts if not v.passed)

    def test_per_flag_columns(self):
        report = score_suite(corpus(), SUITE, "test")
        by_flag = report.halves["test"].by_flag
        assert set(by_flag) == {"absence", "boundary", "submission",
                                "synthesis"}
        assert all(t.missions == 1 for t in by_flag.values())

    def test_the_columns_are_februarys(self):
        totals = score_suite(corpus(), SUITE, "test").halves["test"].overall
        for column in ("success_rate", "steps", "elapsed_s", "tokens",
                       "human_interventions", "reply_rejected"):
            assert hasattr(totals, column)
        assert totals.success_rate == 1.0
        assert totals.tokens and totals.tokens > 0

    def test_scoring_the_same_runs_twice_gives_the_same_bytes(self):
        """No timestamp, no ordering by dict hash: a report is a function of
        the runs it scored, which is what 'measurable' was supposed to mean."""
        first = score_suite(corpus(), SUITE, "all").to_json()
        second = score_suite(corpus(), SUITE, "all").to_json()
        assert first == second

    def test_the_markdown_carries_the_rubric_ledger_head(self):
        text = score_suite(corpus(), SUITE, "all").to_markdown()
        assert "Rubric changes" in text
        assert SUITE.rubric_changes[0].date in text

    def test_the_markdown_reports_each_half_and_says_it_will_not_blend(self):
        text = score_suite(corpus(), SUITE, "all").to_markdown()
        assert "## train" in text and "## test" in text
        assert "human" in text and "tokens" in text
        assert "no blended number" in text

    def test_the_markdown_says_why_a_mission_failed(self):
        mission = SUITE.mission("two_views_one_line")
        report = score_suite({mission.key: FIXTURES / f"{mission.key}.bad.jsonl"},
                             SUITE, "test")
        text = report.to_markdown()
        assert "why they failed" in text
        assert "grounded=False" in text

    def test_an_empty_half_renders_rather_than_dividing_by_zero(self):
        empty = Suite(name="empty", missions=())
        report = score_suite({}, empty, "all")
        assert report.halves["train"].overall == Totals()
        assert report.to_markdown()
        assert json.loads(report.to_json())["suite"] == "empty"

    def test_the_json_carries_the_reader_rubric_for_every_verdict(self):
        blob = json.loads(score_suite(corpus(), SUITE, "test").to_json())
        for verdict in blob["halves"]["test"]["verdicts"]:
            assert verdict["needs_reader"]
            assert verdict["answer"]
