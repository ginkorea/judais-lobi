# tests/test_eval_ablation.py — the arms runner, end to end over a fake spawn

"""`python -m core.eval ablation`, driven against a program that flips.

The spawn line here is a small Python script written into the test's own
tmp directory.  It answers `--help` with a usage line, and it writes a
conforming mission stream whose ANSWER depends on exactly one thing: is
the arm's flag delta on the command line.  So the arms differ by the one
variable an ablation is supposed to isolate, and a paired delta computed
against the wrong arm — or an unavailable arm scored anyway, or repeats
counted by majority — comes out wrong in a way the assertions can see.

Nothing here needs a model, an MCP server or a GPU: the spawner is
`core.eval.run.run_suite`, which is the same one `measure` and a real
ablation use, and the only thing standing in for a deployment is the
script below.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.eval import ablation as mod
from core.eval.ablation import (ARMS, Ablation, Arm, ArmResult, Unavailable,
                                ablate, accepted_flags, availability,
                                chosen_arms, paired, probe_argv, wilson)
from core.eval.run import main as eval_main
from core.eval.score import Report, Verdict, score_suite
from core.eval.suite import Mission, Suite


# ── the program the arms run ─────────────────────────────────────────────────
#
# Three behaviours, keyed off the first word of the objective:
#   steady — passes under every arm
#   fixed  — passes only when the delta flag is on the line
#   broken — passes only when it is NOT
#   flaky  — passes the first time it is asked and never again
# so one run of two arms produces a +1, a -1 and a 0 in the same table.

FAKE = '''\
import json, os, sys

USAGE = """usage: fake [--mission] [--events EVENTS] [--cognition]

options:
  --events EVENTS   where the record stream goes
  --cognition       the arm under test; unlike --graph-context, which this
                    program does not accept, it is a real option here
"""

argv = sys.argv[1:]
if "--help" in argv:
    print(USAGE)
    raise SystemExit(0)

objective = argv[0]
sink = argv[argv.index("--events") + 1]
cognition = "--cognition" in argv

word = objective.split()[0]
if word == "steady":
    good = True
elif word == "fixed":
    good = cognition
elif word == "broken":
    good = not cognition
else:
    state = os.environ["FAKE_STATE"]
    seen = {}
    if os.path.exists(state):
        seen = json.loads(open(state).read())
    good = objective not in seen
    seen[objective] = seen.get(objective, 0) + 1
    open(state, "w").write(json.dumps(seen))

records = [
    {"event": "mission_started", "schema_version": 1, "objective": objective,
     "catalogue": ["probe"], "gated": [], "max_steps": 0, "history": 0},
    {"event": "step_started", "index": 0},
    {"event": "tool_call", "index": 0, "tool": "probe", "arguments": {}},
    {"event": "tool_result", "index": 0, "tool": "probe", "arguments": {},
     "ok": True, "exit_code": 0, "output": "42", "error": "", "handle": "r1",
     "truncated": False},
    {"event": "answer", "text": "42" if good else "no figure",
     "outcome": "answered"},
    {"event": "mission_finished", "outcome": "answered", "steps": 1,
     "max_steps": 0},
]

handle = (os.fdopen(int(sink.split(":", 1)[1]), "w") if sink.startswith("fd:")
          else open(sink, "w"))
with handle as out:
    for record in records:
        out.write(json.dumps(record) + "\\n")
'''


def _mission(key: str, word: str, split: str = "train",
             mission_class: str = "") -> Mission:
    return Mission(
        key=key, flag="synthesis", split=split, mission_class=mission_class,
        prompt=f"{word} — give me the figure this plane holds.",
        must=("the figure, from the plane",),
        must_not=("a figure from nowhere",),
        because="a toy mission, so the arms runner has something to run",
        answer_must_match=(r"\b42\b",))


#: Five train and three held out: 37.5%, inside `TEST_SHARE`, so the suite
#: passes the same `check` a real one does when it goes through the CLI.
TOY = Suite(
    name="toy",
    flags=("synthesis",),
    missions=(
        _mission("steady_a", "steady", mission_class="settled"),
        _mission("fixed_a", "fixed", mission_class="moving"),
        _mission("broken_a", "broken", mission_class="moving"),
        _mission("steady_b", "steady", mission_class="settled"),
        _mission("flaky_a", "flaky", mission_class="settled"),
        _mission("steady_c", "steady", "test", mission_class="settled"),
        _mission("fixed_c", "fixed", "test", mission_class="moving"),
        _mission("broken_c", "broken", "test", mission_class="moving"),
    ),
)

#: The same suite with the classes taken off, for the one property that can
#: only be shown by their absence: a suite that declares none gets no class
#: block at all, so every report ever written stays what it was.
TOY_UNCLASSED = Suite(
    name="toy_unclassed", flags=("synthesis",),
    missions=tuple(_mission(m.key, m.prompt.split(" ")[0], m.split)
                   for m in TOY.missions))

#: The two arms this file ablates: the caller's line, and the same line
#: plus the one flag the fake program reacts to.
TWO = (ARMS[0], Arm(name="shadow", flags=("--cognition",),
                    why="the arm the fake program flips on"))


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "fake_agent.py"
    path.write_text(FAKE, encoding="utf-8")
    monkeypatch.setenv("FAKE_STATE", str(tmp_path / "state.json"))
    return [sys.executable, str(path), "{objective}"]


@pytest.fixture
def suite_file(tmp_path):
    path = tmp_path / "toy.json"
    path.write_text(json.dumps(TOY.to_mapping()), encoding="utf-8")
    return path


def quiet(*_args, **_kwargs) -> None:
    """A log that says nothing, so a bounded test stays readable."""


# ── the probe ────────────────────────────────────────────────────────────────

class TestWhatTheSpawnLineWillAccept:
    def test_the_program_is_taken_off_the_front_of_the_line(self):
        assert probe_argv(["judais", "--provider", "local"]) == [
            "judais", "--help"]
        assert probe_argv(["python", "-m", "core.cli", "--mission"]) == [
            "python", "-m", "core.cli", "--help"]
        assert probe_argv(["python", "/tmp/a.py", "{objective}"]) == [
            "python", "/tmp/a.py", "--help"]

    def test_a_prompt_on_the_line_is_not_mistaken_for_the_program(self):
        """A sentence carries a space and a program name does not."""
        assert probe_argv(["judais", "what can you do", "--mission"]) == [
            "judais", "--help"]

    def test_the_fake_program_declares_the_flag_the_arm_wants(self, fake):
        accepted = accepted_flags(fake)
        assert accepted is not None
        assert "--cognition" in accepted
        assert "--graph-context" not in accepted

    def test_a_program_that_is_not_ours_is_unknown_and_not_empty(
            self, tmp_path):
        """The anchor: the harness appends `--events` to every mission it
        spawns, so a help text that does not name it is not the help of a
        program this harness could have driven.  Answering "accepts
        nothing" there would skip every arm for the wrong reason."""
        other = tmp_path / "other.py"
        other.write_text("print('usage: other [--colour]')\n",
                         encoding="utf-8")
        assert accepted_flags([sys.executable, str(other),
                               "{objective}"]) is None

    def test_a_program_that_will_not_run_is_unknown(self, tmp_path):
        assert accepted_flags([str(tmp_path / "nothing-here")]) is None

    def test_a_flag_named_only_in_prose_is_not_declared(self, fake):
        """The fourth fact.  The fake's help TALKS about `--graph-context`
        in the description of another option — the shape a real help text
        has when it explains that a flag is refused on some backends — and
        a scan that read whole lines would have called that an
        acceptance and run an arm the program rejects."""
        text = Path(fake[1]).read_text(encoding="utf-8")
        assert "--graph-context" in text        # it IS mentioned
        accepted = accepted_flags(fake)
        assert accepted is not None
        assert "--graph-context" not in accepted

    def test_the_scan_reads_the_usage_block_and_the_option_lines(self):
        declared = mod._declared_flags(
            "usage: p [--alpha] [--beta BETA]\n"
            "\n"
            "options:\n"
            "  --beta BETA    do not confuse this with --gamma\n"
            "  -e, --events E  where records go\n"
            "\n"
            "Pass --delta to nobody; it does not exist.\n")
        assert declared == frozenset({"--alpha", "--beta", "--events"})


class TestAnArmIsSkippedRatherThanScored:
    def test_the_baseline_never_needs_asking(self):
        assert availability(ARMS, None)["baseline"] == ""

    def test_a_flag_the_cli_does_not_accept_is_a_reason_not_a_crash(
            self, fake):
        notes = availability(ARMS, accepted_flags(fake))
        assert notes["baseline"] == ""
        assert notes["shadow"] == ""          # the fake declares --cognition
        assert "--graph-context" in notes["graph"]
        assert "--compiled-context" in notes["compiled-context"]

    def test_an_unaskable_line_skips_the_arms_it_cannot_confirm(self):
        notes = availability(ARMS, None)
        assert "could not be asked" in notes["shadow"]

    def test_a_skipped_arm_has_no_numbers_at_all(self, fake, tmp_path):
        """The mutation this guards: an arm that could not run, scored
        anyway, reads in the table as an arm that scored zero — which is a
        claim about a configuration nobody ran."""
        ablated = ablate(TOY, fake, tmp_path / "out", split="train",
                         arms=(ARMS[0], ARMS[3]), log=quiet)
        graph = [result for result in ablated.arms
                 if result.arm.name == "graph"][0]
        assert graph.skipped
        assert not graph.ran
        assert graph.reports == ()
        assert graph.runs("train") == (0, 0)
        assert graph.passed("train") == {}
        assert wilson(*graph.runs("train")) is None
        assert paired(ablated.baseline, graph, "train") == {}
        assert "SKIPPED" in ablated.to_markdown()


# ── the paired reading ───────────────────────────────────────────────────────

class TestTheArmsRunTheSameMissions:
    @pytest.fixture
    def ablated(self, fake, tmp_path):
        return ablate(TOY, fake, tmp_path / "out", split="train", arms=TWO,
                      log=quiet)

    def test_both_arms_ran_every_mission_of_the_half(self, ablated):
        for result in ablated.arms:
            assert result.ran, result.skipped
            assert set(result.passed("train")) == {
                m.key for m in TOY.missions if m.split == "train"}

    def test_the_only_difference_is_the_flag_delta(self, ablated):
        baseline, shadow = ablated.arms
        assert list(shadow.command) == list(baseline.command) + [
            "--cognition"]

    def test_the_paired_delta_names_what_moved_each_way(self, ablated):
        baseline, shadow = ablated.arms
        deltas = paired(baseline, shadow, "train")
        assert deltas["fixed_a"] == 1
        assert deltas["broken_a"] == -1
        assert deltas["steady_a"] == 0
        assert deltas["steady_b"] == 0

    def test_the_delta_is_against_the_baseline_and_not_against_itself(
            self, ablated):
        """The mutation: pairing an arm against the wrong arm produces a
        table of zeros that looks exactly like a piece that changed
        nothing."""
        baseline, shadow = ablated.arms
        assert set(paired(shadow, shadow, "train").values()) == {0}
        assert set(paired(baseline, shadow, "train").values()) != {0}

    def test_the_baseline_is_the_first_arm_that_ran_and_is_named(
            self, ablated):
        assert ablated.baseline is ablated.arms[0]
        assert f"`{ablated.baseline.arm.name}`" in ablated.to_markdown()

    def test_the_baseline_is_the_first_arm_that_RAN_not_the_first_declared(
            self, fake, tmp_path):
        """`graph` is selected first and is skipped, so the pairing is
        against `baseline` — the first arm that actually produced runs.

        A baseline that was simply `arms[0]` would here be an arm with no
        reports at all: every delta would come back empty and the table
        would say the arm changed nothing, which is the most plausible
        wrong answer an ablation can give.
        """
        ablated = ablate(TOY, fake, tmp_path / "out", split="train",
                         arms=(ARMS[3], ARMS[0], TWO[1]), only=("fixed_a",),
                         log=quiet)
        assert ablated.arms[0].arm.name == "graph"
        assert not ablated.arms[0].ran
        assert ablated.baseline is not None
        assert ablated.baseline.arm.name == "baseline"
        shadow = ablated.arms[2]
        assert paired(ablated.baseline, shadow, "train") == {"fixed_a": 1}
        assert "against **`baseline`**" in ablated.to_markdown()

    def test_a_selection_that_leaves_the_baseline_out_says_so(
            self, fake, tmp_path):
        """With `--arms shadow,graph` the pairing is against `shadow`, and
        a report that still said "baseline" would be describing a run
        nobody made."""
        ablated = ablate(TOY, fake, tmp_path / "out", split="train",
                         arms=(TWO[1], ARMS[3]), log=quiet)
        assert ablated.baseline.arm.name == "shadow"
        assert "against **`shadow`**" in ablated.to_markdown()


class TestRepeatsAreAllMustPass:
    def test_a_mission_that_passed_once_of_two_did_not_pass_the_arm(self):
        """Unit, on the rule itself: majority would call this a pass and
        the rc iteration is the reason it must not."""
        result = ArmResult(arm=ARMS[0], reports=(
            _report({"a": True, "b": True}),
            _report({"a": True, "b": False})))
        assert result.passed("train") == {"a": True, "b": False}
        assert result.runs("train") == (3, 4)

    def test_two_of_three_is_still_not_a_pass(self):
        result = ArmResult(arm=ARMS[0], reports=(
            _report({"a": True}), _report({"a": False}),
            _report({"a": True})))
        assert result.passed("train") == {"a": False}
        assert result.runs("train") == (2, 3)

    def test_the_rule_bites_on_a_real_run(self, fake, tmp_path):
        """The fake's `flaky` mission passes the first time it is asked and
        never again, so two repeats is one pass and one fail."""
        ablated = ablate(TOY, fake, tmp_path / "out", split="train",
                         arms=(ARMS[0],), only=("flaky_a",), repeats=2,
                         log=quiet)
        arm = ablated.arms[0]
        assert arm.per_repeat("train")["flaky_a"] == [True, False]
        assert arm.passed("train") == {"flaky_a": False}
        assert arm.runs("train") == (1, 2)
        assert "all-must-pass" in ablated.to_markdown()


def _report(passed) -> Report:
    """One repeat's report, straight from verdicts — no run needed."""
    from core.eval.score import Half, Totals

    verdicts = tuple(
        Verdict(key=key, flag="synthesis", split="train", passed=value,
                kpis={"outcome": "answered"})
        for key, value in passed.items())
    half = Half(split="train", verdicts=verdicts, overall=Totals(),
                by_flag={})
    return Report(suite="toy", halves={"train": half})


# ── the interval ─────────────────────────────────────────────────────────────

class TestTheInterval:
    def test_nothing_measured_has_no_interval(self):
        assert wilson(0, 0) is None

    def test_a_clean_sweep_is_not_certainty(self):
        """Where the normal approximation collapses to ±0 and reads as a
        measurement nobody made."""
        low, high = wilson(8, 8)
        assert 0.0 < low < 1.0
        assert high == 1.0

    def test_the_interval_stays_inside_the_unit_range(self):
        for passes, total in ((0, 3), (1, 3), (3, 3), (1, 40)):
            low, high = wilson(passes, total)
            assert 0.0 <= low <= high <= 1.0

    def test_more_runs_narrow_it(self):
        narrow = wilson(50, 100)
        wide = wilson(5, 10)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


# ── the report ───────────────────────────────────────────────────────────────

class TestTheReportDescribesItself:
    @pytest.fixture
    def ablated(self, fake, tmp_path):
        return ablate(TOY, fake, tmp_path / "out", split="train", arms=TWO,
                      log=quiet)

    def test_every_arm_prints_its_exact_spawn_line_delta(self, ablated):
        """The mutation this guards: a table whose arms are named and
        whose deltas are not is a comparison a reader cannot check."""
        text = ablated.to_markdown()
        assert "`--cognition`" in text
        assert "`(none)`" in text
        for result in ablated.arms:
            assert f"`{result.arm.name}`" in text

    def test_the_model_is_named_beside_the_numbers(self, ablated):
        text = ablated.to_markdown()
        assert "provider / model" in text
        assert text.count("model") >= 2
        assert "at commit" in text

    def test_the_per_mission_table_has_a_column_per_arm(self, ablated):
        text = ablated.to_markdown()
        assert "per mission × arm" in text
        for mission in TOY.missions:
            if mission.split == "train":
                assert f"`{mission.key}`" in text

    def test_the_report_is_read_by_class_as_well_as_by_rate(self, ablated):
        """The grouping §2.9.3 asks for.  A rate says how much an arm
        moved; the class table says WHAT KIND of problem it moved, and
        "synthesis 2/3" answers neither question."""
        text = ablated.to_markdown()
        assert "by class" in text
        assert "| settled |" in text
        assert "| moving |" in text
        baseline, shadow = ablated.arms
        # `fixed_a` and `broken_a` are both `moving`; the flag delta fixes
        # one and breaks the other, so the class tally does not move while
        # the missions underneath it both do. That is the finding, and it
        # is invisible in a rate.
        assert ablated.by_class(baseline, "train")["moving"] == (1, 2)
        assert ablated.by_class(shadow, "train")["moving"] == (1, 2)
        assert ablated.by_class(baseline, "train")["settled"] == (3, 3)

    def test_a_suite_with_no_classes_gets_no_class_block(
            self, fake, tmp_path):
        """Absence, not an empty table: every report written before
        classes existed stays what it was."""
        ablated = ablate(TOY_UNCLASSED, fake, tmp_path / "out",
                         split="train", arms=(ARMS[0],), only=("steady_a",),
                         log=quiet)
        assert ablated.classes == {}
        assert "by class" not in ablated.to_markdown()
        assert json.loads(ablated.to_json())["arms"][0]["by_class"] == {}

    def test_the_json_carries_the_deltas_and_the_intervals(self, ablated):
        body = json.loads(ablated.to_json())
        assert body["baseline"] == "baseline"
        shadow = [arm for arm in body["arms"] if arm["name"] == "shadow"][0]
        assert shadow["flag_delta"] == ["--cognition"]
        assert shadow["paired"]["train"]["fixed_a"] == 1
        assert shadow["paired"]["train"]["broken_a"] == -1
        assert len(shadow["interval"]["train"]) == 2

    def test_the_directories_are_printed_so_a_row_can_be_rescored(
            self, ablated, tmp_path):
        text = ablated.to_markdown()
        for result in ablated.arms:
            for directory in result.directories:
                assert str(directory) in text
                assert directory.is_dir()

    def test_a_recorded_arm_rescores_to_the_same_verdicts(self, ablated):
        """ROADMAP §4's rule, asked of an arm: the table is reproducible
        from the bytes on disk with no endpoint."""
        arm = ablated.arms[0]
        runs = {mission.key: arm.directories[0] / mission.key
                for mission in TOY.missions if mission.split == "train"}
        again = score_suite(runs, TOY, "train")
        before = {v.key: v.passed
                  for v in arm.reports[0].halves["train"].verdicts}
        after = {v.key: v.passed for v in again.halves["train"].verdicts}
        assert before == after


# ── the command line ─────────────────────────────────────────────────────────

class TestTheSubcommand:
    def test_an_arm_nobody_declared_is_refused_by_name(self):
        with pytest.raises(Unavailable) as exc:
            chosen_arms("baseline,hunch")
        assert "hunch" in str(exc.value)

    def test_the_selection_keeps_the_order_it_was_given(self):
        assert [arm.name for arm in chosen_arms("shadow,baseline")] == [
            "shadow", "baseline"]

    def test_no_selection_is_every_arm(self):
        assert chosen_arms("") == ARMS

    def test_it_runs_end_to_end_and_writes_both_reports(
            self, fake, suite_file, tmp_path, capsys):
        out = tmp_path / "runs"
        report = tmp_path / "report.md"
        code = eval_main([
            "ablation", "--suite", str(suite_file), "--split", "train",
            "--out", str(out), "--report", str(report),
            "--arms", "baseline,shadow,graph", "--allow-failures",
            "--", *fake])
        assert code == 0
        printed = capsys.readouterr().out
        assert "# ablation — suite `toy`" in printed
        assert report.exists()
        assert report.with_suffix(".json").exists()
        assert (out / "ablation.json").exists()

        body = json.loads((out / "ablation.json").read_text(encoding="utf-8"))
        assert body["suite"] == "toy"
        names = {arm["name"]: arm for arm in body["arms"]}
        assert names["graph"]["skipped"]
        assert names["graph"]["reports"] == []
        assert names["shadow"]["paired"]["train"]["fixed_a"] == 1
        assert names["shadow"]["paired"]["train"]["broken_a"] == -1

    def test_a_run_with_failures_exits_non_zero_unless_allowed(
            self, fake, suite_file, tmp_path):
        out = tmp_path / "runs"
        code = eval_main([
            "ablation", "--suite", str(suite_file), "--split", "train",
            "--out", str(out), "--arms", "baseline", "--only", "broken_a",
            "--", *fake])
        assert code == 0                      # `broken` passes the baseline
        code = eval_main([
            "ablation", "--suite", str(suite_file), "--split", "train",
            "--out", str(tmp_path / "runs2"), "--arms", "shadow", "--only",
            "broken_a", "--", *fake])
        assert code == 1                      # and fails the other arm

    def test_a_missing_spawn_line_is_a_usage_error(self, suite_file,
                                                   tmp_path):
        assert eval_main(["ablation", "--suite", str(suite_file), "--out",
                          str(tmp_path / "x")]) == 2

    def test_an_unknown_only_key_exits_two_with_the_sentence(
            self, fake, suite_file, tmp_path, capsys):
        """`--only` is narrowed by `measure`'s own owner, so its refusal
        arrives wearing `Unmeasurable`.  Caught by name, it is the
        sentence that owner wrote; uncaught, it was a traceback."""
        code = eval_main([
            "ablation", "--suite", str(suite_file), "--split", "train",
            "--out", str(tmp_path / "runs"), "--arms", "baseline",
            "--only", "steday_a", "--", *fake])
        assert code == 2
        assert "steday_a" in capsys.readouterr().err

    def test_a_json_report_path_does_not_overwrite_itself(
            self, fake, suite_file, tmp_path):
        """`--report x.json` used to name the same file twice — Markdown
        written, then JSON over the top of it — and what a reader opened
        was whichever write went last."""
        report = tmp_path / "out.json"
        code = eval_main([
            "ablation", "--suite", str(suite_file), "--split", "train",
            "--out", str(tmp_path / "runs"), "--arms", "baseline",
            "--only", "steady_a", "--report", str(report), "--", *fake])
        assert code == 0
        assert report.read_text(encoding="utf-8").startswith("# ablation")
        beside = tmp_path / "out.json.json"
        assert json.loads(beside.read_text(encoding="utf-8"))["suite"] == "toy"


class TestTheArmTable:
    def test_the_baseline_is_first_and_has_no_delta(self):
        assert ARMS[0].name == "baseline"
        assert ARMS[0].flags == ()

    def test_every_arm_says_why_it_is_there(self):
        for arm in ARMS:
            assert len(arm.why) > 40, arm.name

    def test_every_arm_name_is_unique(self):
        assert len({arm.name for arm in ARMS}) == len(ARMS)

    def test_the_declared_arms_that_do_not_exist_yet_are_flagged_not_hidden(
            self):
        """`shadow`, `compiled-context` and `graph` are ROADMAP §2.9's
        pieces and none of their flags is in this release's published
        surface.  They are declared anyway, so the column exists from the
        first run and says SKIPPED until the flag lands."""
        from core.runtime import contract

        future = [arm for arm in ARMS if arm.flags]
        assert future
        for arm in future:
            assert not set(arm.flags) & set(contract.CLI_FLAGS), arm.name

    def test_the_module_exports_what_it_documents(self):
        for name in mod.__all__:
            assert hasattr(mod, name), name
