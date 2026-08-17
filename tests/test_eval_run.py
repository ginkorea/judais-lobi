# tests/test_eval_run.py — the command line: run, score, check

"""`python -m core.eval`, exercised as a person and a CI job reach it.

`score` and `check` are run as real subprocesses, because an exit code that
is only ever produced in-process is an exit code nobody has tested — a CI
job's entire reading of this harness is that number.

`run` is exercised against a **fake `judais`**: a stdlib script that replays
a committed stream onto the events descriptor it was handed. That is enough
to hold everything `run` actually owns — where the objective goes in the
argv, that the stream comes back on `fd:N` rather than through stdout, that
`JUDAIS_LOBI_RUNS` reaches the child pointed inside the mission's own
directory, that a credential in the spawn line is not written to disk, and
that a child which never finishes is killed and scored as the failure it is.
Spawning the real CLI here would need a model, which is exactly what the
no-GPU path is for.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from core.eval.run import (OBJECTIVE, WITHHELD, _argv_for, _recorded_argv,
                           main)
from core.eval.stub_suite import SUITE

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval"

#: A `judais` that needs no model: it reads the objective, finds the stream
#: somebody recorded for it, and writes that stream to the descriptor it was
#: given. Everything else on the command line is ignored, the way a real
#: consumer's extra flags are ignored by this harness.
FAKE_JUDAIS = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys, time

    args = sys.argv[1:]
    objective, rest = args[0], args[1:]
    opts, index = {}, 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--") and index + 1 < len(rest) \\
                and not rest[index + 1].startswith("--"):
            opts[token] = rest[index + 1]
            index += 2
        else:
            opts[token] = True
            index += 1

    runs = os.environ.get("JUDAIS_LOBI_RUNS", "")
    if runs:
        os.makedirs(os.path.dirname(runs), exist_ok=True)
        with open(os.path.join(os.path.dirname(runs), "spawn.json"), "w") as f:
            json.dump({"argv": sys.argv, "runs": runs,
                       "objective": objective}, f)

    if opts.get("--hang"):
        time.sleep(30)

    spec = opts["--events"]
    assert spec.startswith("fd:"), spec
    sink = os.fdopen(int(spec.split(":", 1)[1]), "w")
    streams = json.load(open(opts["--streams"]))
    path = streams.get(objective)
    if path:
        sink.write(open(path, encoding="utf-8").read())
    sink.flush()
    sink.close()
    sys.exit(0)
    ''')


@pytest.fixture
def fake_judais(tmp_path):
    path = tmp_path / "judais"
    path.write_text(FAKE_JUDAIS, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
    return path


@pytest.fixture
def streams(tmp_path):
    """objective → the committed stream the fake replays for it."""
    mapping = {m.prompt: str(FIXTURES / f"{m.key}.jsonl")
               for m in SUITE.missions}
    path = tmp_path / "streams.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


def cli(*args, expect=None):
    """`python -m core.eval …` as a subprocess, from the repository root."""
    done = subprocess.run(
        [sys.executable, "-m", "core.eval", *args], cwd=str(REPO),
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": str(REPO)})
    if expect is not None:
        assert done.returncode == expect, done.stderr[-2000:]
    return done


# ── check ────────────────────────────────────────────────────────────────────

class TestCheck:
    def test_the_in_repo_suite_is_gradeable(self):
        done = cli("check", expect=0)
        assert "gradeable" in done.stdout
        assert f"{len(SUITE.missions)} mission(s)" in done.stdout

    def test_it_says_how_much_is_held_out(self):
        assert "held out (36%)" in cli("check", expect=0).stdout

    def test_a_suite_that_cannot_be_graded_exits_one_and_says_why(
            self, tmp_path):
        raw = SUITE.to_mapping()
        raw["missions"][0]["flag"] = "hunch"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        done = cli("check", "--suite", str(path), expect=1)
        assert "hunch" in done.stderr

    def test_a_suite_file_that_is_not_there(self, tmp_path):
        done = cli("check", "--suite", str(tmp_path / "nope.json"), expect=1)
        assert "--suite" in done.stderr

    def test_scoring_refuses_an_ungradeable_suite_too(self, tmp_path,
                                                      run_dirs):
        """The check is not `check`'s. Numbers produced against a suite that
        cannot be graded cannot be compared to anything, and a `run` against
        one spends a model first."""
        raw = SUITE.to_mapping()
        raw["missions"][0]["flag"] = "hunch"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        done = cli("score", "--suite", str(path), "--runs", str(run_dirs),
                   expect=1)
        assert "hunch" in done.stderr


# ── score ────────────────────────────────────────────────────────────────────

@pytest.fixture
def run_dirs(tmp_path):
    """A directory of run directories, one per mission, from the corpus."""
    root = tmp_path / "runs"
    for mission in SUITE.missions:
        directory = root / mission.key
        directory.mkdir(parents=True)
        (directory / "events.jsonl").write_text(
            (FIXTURES / f"{mission.key}.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8")
    return root


class TestScore:
    def test_it_scores_a_directory_of_runs(self, run_dirs):
        done = cli("score", "--runs", str(run_dirs), expect=0)
        assert "## train" in done.stdout and "## test" in done.stdout
        assert "PASS" in done.stdout

    def test_json_is_json(self, run_dirs):
        blob = json.loads(cli("score", "--runs", str(run_dirs), "--json",
                              expect=0).stdout)
        assert set(blob["halves"]) == {"train", "test"}

    def test_one_half_only(self, run_dirs):
        blob = json.loads(cli("score", "--runs", str(run_dirs), "--split",
                              "test", "--json", expect=0).stdout)
        assert set(blob["halves"]) == {"test"}

    def test_a_failure_is_a_non_zero_exit(self, run_dirs):
        bad = run_dirs / "two_views_one_line" / "events.jsonl"
        bad.write_text(
            (FIXTURES / "two_views_one_line.bad.jsonl").read_text(
                encoding="utf-8"), encoding="utf-8")
        done = cli("score", "--runs", str(run_dirs), expect=1)
        assert "FAIL" in done.stdout

    def test_failures_can_be_allowed(self, run_dirs):
        (run_dirs / "two_views_one_line" / "events.jsonl").write_text(
            (FIXTURES / "two_views_one_line.bad.jsonl").read_text(
                encoding="utf-8"), encoding="utf-8")
        cli("score", "--runs", str(run_dirs), "--allow-failures", expect=0)

    def test_a_single_run_can_be_pointed_at_by_key(self, tmp_path):
        done = cli("score", "--split", "test", "--allow-failures", "--map",
                   f"two_views_one_line={FIXTURES / 'two_views_one_line.jsonl'}",
                   expect=0)
        assert "two_views_one_line" in done.stdout

    def test_a_report_can_be_written_beside_the_console(self, run_dirs,
                                                        tmp_path):
        out = tmp_path / "report"
        cli("score", "--runs", str(run_dirs), "--report", str(out), expect=0)
        assert json.loads((out / "report.json").read_text())["suite"] == "stub"
        assert "## test" in (out / "report.md").read_text()

    def test_nothing_to_score_is_a_usage_error(self):
        done = cli("score", expect=2)
        assert "--runs" in done.stderr

    def test_a_bad_map_is_a_usage_error(self):
        assert cli("score", "--map", "nonsense").returncode != 0


# ── run ──────────────────────────────────────────────────────────────────────

class TestRun:
    def _run(self, fake_judais, streams, out, *extra):
        return main(["run", "--split", "test", "--out", str(out), *extra,
                     "--", str(fake_judais), "--streams", str(streams)])

    def test_it_spawns_every_mission_and_scores_the_streams(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        code = self._run(fake_judais, streams, out)
        printed = capsys.readouterr().out
        assert code == 0, printed
        assert "## test" in printed
        for mission in SUITE.missions_in("test"):
            assert (out / mission.key / "events.jsonl").exists()
        assert json.loads((out / "report.json").read_text())["suite"] == "stub"

    def test_the_stream_arrives_on_a_descriptor_and_not_through_stdout(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        self._run(fake_judais, streams, out)
        capsys.readouterr()
        key = SUITE.missions_in("test")[0].key
        spawn = json.loads((out / key / "spawn.json").read_text())
        events = [token for token in spawn["argv"]
                  if token.startswith("fd:")]
        assert events, spawn["argv"]
        assert (out / key / "stdout.txt").read_text() == ""

    def test_the_child_records_inside_the_missions_own_directory(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        self._run(fake_judais, streams, out)
        capsys.readouterr()
        key = SUITE.missions_in("test")[0].key
        spawn = json.loads((out / key / "spawn.json").read_text())
        assert spawn["runs"] == str(out / key / "runs")

    def test_the_objective_is_the_prompt_verbatim(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        self._run(fake_judais, streams, out)
        capsys.readouterr()
        mission = SUITE.missions_in("test")[0]
        spawn = json.loads((out / mission.key / "spawn.json").read_text())
        assert spawn["objective"] == mission.prompt

    def test_a_child_that_never_finishes_is_killed_and_scored_as_failed(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        code = main(["run", "--split", "test", "--out", str(out),
                     "--timeout", "1",
                     "--", str(fake_judais), "--streams", str(streams),
                     "--hang"])
        printed = capsys.readouterr().out
        assert code == 1
        key = SUITE.missions_in("test")[0].key
        assert json.loads((out / key / "command.json").read_text())["timed_out"]
        assert "FAIL" in printed

    def test_the_spawn_line_is_recorded_without_the_credential(
            self, fake_judais, streams, tmp_path, capsys):
        out = tmp_path / "out"
        main(["run", "--split", "test", "--out", str(out), "--",
              str(fake_judais), "--streams", str(streams),
              "--mcp-url", "https://server/mcp?token=hunter2"])
        capsys.readouterr()
        key = SUITE.missions_in("test")[0].key
        recorded = (out / key / "command.json").read_text()
        assert "hunter2" not in recorded
        assert "<withheld>" in recorded
        # ... and the child still got the real one.
        spawn = json.loads((out / key / "spawn.json").read_text())
        assert "https://server/mcp?token=hunter2" in spawn["argv"]

    def test_a_run_with_no_command_line_is_a_usage_error(self, tmp_path,
                                                         capsys):
        assert main(["run", "--out", str(tmp_path)]) == 2
        assert "after `--`" in capsys.readouterr().err


class TestTheArgvItBuilds:
    """The three things the harness owns, and nothing else."""

    def test_the_objective_goes_in_at_position_one(self):
        mission = SUITE.mission("two_views_one_line")
        argv = _argv_for(mission, ["judais", "--provider", "local"], "fd:9")
        assert argv[:2] == ["judais", mission.prompt]
        assert argv[-2:] == ["--events", "fd:9"]
        assert "--mission" in argv

    def test_a_template_may_say_where_the_objective_goes(self):
        mission = SUITE.mission("two_views_one_line")
        argv = _argv_for(mission, ["python", "-m", "runner", OBJECTIVE],
                         "fd:9")
        assert argv[:3] == ["python", "-m", "runner"]
        assert argv[3] == mission.prompt

    def test_a_missions_own_flags_are_appended(self):
        routing = SUITE.mission("a_listing_is_not_a_plan")
        assert "--swarm" in _argv_for(routing, ["judais"], "fd:9")

    def test_the_mission_flag_is_not_added_twice(self):
        argv = _argv_for(SUITE.mission("two_views_one_line"),
                         ["judais", "--mission"], "fd:9")
        assert argv.count("--mission") == 1

    @pytest.mark.parametrize("flag", WITHHELD)
    def test_a_credential_bearing_flag_is_withheld_either_spelling(self, flag):
        spaced = _recorded_argv(["judais", flag, "secret", "--provider", "x"])
        assert "secret" not in spaced
        assert spaced[-2:] == ["--provider", "x"]
        joined = _recorded_argv(["judais", f"{flag}=secret"])
        assert joined == ["judais", f"{flag}=<withheld>"]

    def test_everything_else_is_recorded_as_written(self):
        line = ["judais", "--provider", "local", "--model", "gpt-oss-20b"]
        assert _recorded_argv(line) == line
