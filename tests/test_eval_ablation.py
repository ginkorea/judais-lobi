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
                                ablate, accepted_flags, availability, band,
                                chosen_arms, paired, probe_argv)
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
        assert band(graph, "train") == ()
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


def _report(passed, infra=()) -> Report:
    """One repeat's report, straight from verdicts — no run needed.

    *infra* names the keys whose run never reached a model, as
    `core.eval.score.infra_reason` would have marked them.
    """
    from core.eval.score import Half, Totals

    verdicts = tuple(
        Verdict(key=key, flag="synthesis", split="train", passed=value,
                infra=("the stream is empty" if key in infra else ""),
                kpis={"outcome": "answered", "run_id": f"run_{key}"})
        for key, value in passed.items())
    half = Half(split="train", verdicts=verdicts, overall=Totals(),
                by_flag={})
    return Report(suite="toy", halves={"train": half})


class TestAnArmIsNotBlamedForTheEndpoint:
    """A repeat the endpoint ate is not evidence about a flag delta.

    Counting it as a failure credits the network's bad afternoon to the arm;
    counting it as a pass is worse. So it is out of `per_repeat` — and
    therefore out of `passed`, `runs` and the interval — and reported on its
    own, which is the same rule `paired` already states for a mission one arm
    did not run: an absence is not a tie.
    """

    def _arm(self, *repeats) -> ArmResult:
        return ArmResult(arm=ARMS[0],
                         reports=tuple(_report(p, i) for p, i in repeats))

    def test_a_dead_repeat_is_out_of_the_run_level_rate(self):
        arm = self._arm(({"a": True, "b": False}, ("b",)))
        assert arm.runs("train") == (1, 1)
        assert arm.passed("train") == {"a": True}

    def test_a_mission_whose_every_repeat_died_is_absent_and_not_a_tie(self):
        arm = self._arm(({"a": True, "b": False}, ("b",)))
        assert "b" not in arm.per_repeat("train")
        assert paired(arm, arm, "train") == {"a": 0}

    def test_it_is_reported_with_its_run_id_and_its_reason(self):
        arm = self._arm(({"a": True, "b": False}, ("b",)))
        assert arm.environment("train") == [
            ("b", "run_b", "the stream is empty")]

    def test_the_table_carries_the_column_and_the_listing(self):
        ablated = Ablation(suite="toy", split="train",
                           arms=(self._arm(({"a": True, "b": False}, ("b",))),),
                           keys={"train": ("a", "b")},
                           flags={"a": "synthesis", "b": "synthesis"})
        text = ablated.to_markdown()
        assert "95% Wilson | infra |" in text
        assert "measured the environment (1)" in text
        assert "run_b" in text
        assert "run the endpoint ate" in text

    def test_the_json_lists_them_rather_than_dropping_them(self):
        ablated = Ablation(suite="toy", split="train",
                           arms=(self._arm(({"a": True, "b": False}, ("b",)),),),
                           keys={"train": ("a", "b")})
        arm = ablated.as_dict()["arms"][0]
        assert arm["infra"]["train"] == [
            {"mission": "b", "run_id": "run_b", "why": "the stream is empty"}]
        assert arm["missions"]["train"] == {"a": True}

    def test_an_arm_with_no_dead_repeat_reads_as_it_always_did(self):
        arm = self._arm(({"a": True, "b": False}, ()))
        assert arm.runs("train") == (1, 2)
        assert arm.environment("train") == []


# ── the interval ─────────────────────────────────────────────────────────────

class TestTheInterval:
    """The arithmetic is `core.eval.extraction.wilson`'s and is tested there.

    What is tested here is what this module actually owns: that an arm with
    no runs is reported with NO interval, and that the numbers reaching the
    table are the one owner's.
    """

    def _arm(self, passes: int, total: int) -> ArmResult:
        """An arm whose `runs(half)` is exactly (passes, total)."""
        assert passes <= total
        seen = {f"m{i}": i < passes for i in range(total)}
        return ArmResult(arm=ARMS[0], reports=(_report(seen),))

    def test_nothing_measured_has_no_interval(self):
        """`wilson(0, 0)` is `(0.0, 0.0)` — the honest interval of nothing —
        and printing it would claim an arm scored 0% with no spread. So the
        reporting rule turns it into an absence, here, once."""
        assert mod.band(self._arm(0, 0), "train") == ()
        assert mod._interval(self._arm(0, 0), "train") == "—"

    def test_a_clean_sweep_is_not_certainty(self):
        """Where the normal approximation collapses to ±0 and reads as a
        measurement nobody made."""
        low, high = mod.band(self._arm(8, 8), "train")
        assert 0.0 < low < 1.0
        assert high == 1.0

    def test_the_interval_stays_inside_the_unit_range(self):
        for passes, total in ((0, 3), (1, 3), (3, 3), (1, 40)):
            low, high = mod.band(self._arm(passes, total), "train")
            assert 0.0 <= low <= high <= 1.0

    def test_more_runs_narrow_it(self):
        narrow = mod.band(self._arm(50, 100), "train")
        wide = mod.band(self._arm(5, 10), "train")
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


class TestThereIsOneWilson:
    """The twin is gone.

    This module carried its own Wilson — same statistic, its own `Z95`, its
    own rounding — grown on a branch parallel to `extraction`'s. Two owners
    of one fact is the six-of-ten-fields bug waiting for a second place to
    happen, and the facade already named extraction's as the owner.
    """

    def test_the_module_does_not_define_wilson_itself(self):
        """AST and not `hasattr`: the name still RESOLVES here, because the
        module imports it, and a check that only asked whether the attribute
        existed would pass with the twin restored."""
        import ast

        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert "wilson" not in defined, "the twin is back"
        assigned = {target.id for node in ast.walk(tree)
                    if isinstance(node, ast.Assign)
                    for target in node.targets
                    if isinstance(target, ast.Name)}
        assert "Z95" not in assigned, "the twin's z is back"

    def test_the_one_it_uses_is_extractions(self):
        from core.eval import extraction

        assert mod.wilson is extraction.wilson

    @pytest.mark.parametrize("passes,total,shown", [
        (8, 8, "68%–100%"),
        (3, 4, "30%–95%"),
        (2, 2, "34%–100%"),
        # The three below MOVED when the twin was unified away — see the
        # docstring. `14/20` is the tier's own landing zone.
        (1, 2, "9%–91%"),        # was 10%–90%
        (11, 12, "65%–99%"),     # was 65%–98%
        (14, 20, "48%–85%"),     # was 48%–86%
    ])
    def test_the_rendered_interval_is_pinned(self, passes, total, shown):
        """Known values, written out, so the day somebody changes the owner's
        rounding this table says which cells moved.

        **The unification moved published intervals, and silence about that
        would be the defect.** The twin rounded to three decimals and the
        owner rounds to four, so a cell whose third decimal sat on a half
        rounds the other way at `.0%`: measured over every `k/n`, **9 of the
        230 cells with n ≤ 20 change their printed percent**, and 73 of 860
        with n ≤ 40. The new value is the more correct one — the twin was
        double-rounding — but a rate a report printed last month may differ
        from the same rate printed today in its last figure, and the three
        cells above are here so that is a pinned fact rather than a surprise.

        The one that matters to read: a 20-mission tier landing 14 printed
        `48%–86%` and now prints `48%–85%`.
        """
        arm = ArmResult(arm=ARMS[0], reports=(_report(
            {f"m{i}": i < passes for i in range(total)}),))
        assert mod._interval(arm, "train") == shown


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

    def test_arms_graduate_by_landing_in_the_contract_not_by_edits_here(
            self):
        """`shadow`, `compiled-context` and `graph` are ROADMAP §2.9's
        pieces, declared before their flags existed so the column said
        SKIPPED from the first run.  `--cognition` LANDED with the shadow
        lane, `--compiled-context` with Phase 18 and `--graph-context`
        with Phase 20a, which is the graduation this table was designed
        around: the arm becomes runnable with no edit to this module's
        machinery.

        The pin is two-sided again, because the table holds a
        declared-before-landing arm again: `extraction` is the design's
        A4 and its `--extract` door is held for the owner (W5's rule: the
        arm is DECLARED and mechanically skipped, never absent).  So
        every LANDED arm's flag must stay published surface — it fails
        the day a flag leaves the contract, because that column would
        silently go back to SKIPPED — and every waiting arm must be
        exactly the declared set, and must come back SKIPPED with the
        reason, never run.  The day `--extract` lands, the second half
        fails here and the graduation is retold, which is the ritual the
        module docstring records for the three arms before it."""
        from core.runtime import contract

        published = frozenset(
            flag for flag in contract.CLI_FLAGS if flag.startswith("--"))
        for arm in ARMS[1:]:
            assert arm.flags, arm.name
        landed = {arm.name for arm in ARMS[1:]
                  if set(arm.flags) <= published}
        waiting = {arm.name for arm in ARMS[1:]} - landed
        assert {"shadow", "compiled-context", "graph",
                "swarm-steering"} <= landed, (
            "a graduated arm's flag left the contract; its column would "
            "silently go back to SKIPPED")
        assert waiting == {"extraction"}, (
            f"the waiting set moved ({sorted(waiting)}): either a flag "
            f"landed — retell the graduation here — or an arm was added "
            f"without its declared-not-landed pin")
        notes = availability(ARMS, published)
        assert "does not accept" in notes["extraction"], notes["extraction"]
        assert "will run the day the flag lands" in notes["extraction"]

    def test_this_checkout_s_own_help_makes_the_arm_runnable(self):
        """The graduation, end to end, through the probe that decides it.

        The two tests above read the *contract*; this one asks the program
        the way an ablation does — the spawn line's own `--help`, scanned
        for what it DECLARES — because that is the only thing availability
        actually consults. A flag published in `CLI_FLAGS` and missing from
        the help would leave the column SKIPPED with the table insisting
        the arm had landed.

        Bounded by `accepted_flags`' own timeout, and it spawns one help
        page: no model, no server, no mission.
        """
        repo = Path(__file__).resolve().parent.parent
        declared = accepted_flags(
            [sys.executable, str(repo / "main.py"), "judais", "{objective}"],
            timeout_s=120.0)
        assert declared is not None, "this checkout's own help was unaskable"
        notes = availability(ARMS, declared)
        assert notes["compiled-context"] == "", notes["compiled-context"]
        assert notes["shadow"] == "", notes["shadow"]
        assert notes["graph"] == "", notes["graph"]

    def test_the_module_exports_what_it_documents(self):
        for name in mod.__all__:
            assert hasattr(mod, name), name


# ── the design arms, and what the runs spent (EVAL.md §20) ──────────────────

class TestTheSpineTally:
    """`spine` reads the arm's OWN reasoning logs, through the one reader.

    Which design arm a `compiled-context` column IS (A2 or A3) is a fact
    about the plane, and the report reads it off the links the runs
    recorded rather than off anybody's claim about the plane — so the
    tally has to come from a real log written by the real writer, count a
    log that will not replay rather than skip it, and answer `None` (not
    zero) for an arm that left no log at all.
    """

    def _run_dir(self, tmp_path, name="run_x"):
        run = tmp_path / "rep1" / "m1" / "runs" / name
        run.mkdir(parents=True)
        (run / "meta.json").write_text("{}", encoding="utf-8")
        return run

    def _log_with_one_link(self, run):
        from core.durable import fsync_append
        from core.runtime.cognition import (REASONING_LOG, ShadowCognition,
                                            header_record)
        from core.runtime.replay import canonical

        path = run / REASONING_LOG
        fsync_append(path, canonical(header_record()))
        shadow = ShadowCognition(path, run_id=run.name)

        class Plane:
            def identifiers_for(self, tool):
                return {"data.job_id": "job"}

            def for_tool(self, tool):
                return None

        shadow.declarations = Plane()
        shadow.receipt("mcp.job_status", 1, json.dumps(
            {"data": {"job_id": "jl-1", "records": 2}}))
        shadow.close_step()
        return path

    def test_links_are_counted_off_a_real_log(self, tmp_path):
        self._log_with_one_link(self._run_dir(tmp_path))
        result = ArmResult(arm=ARMS[1], reports=(_report({"m1": True}),),
                           directories=(tmp_path,))
        assert mod.spine(result) == {"links": 1, "logs": 1, "unreadable": 0}

    def test_an_arm_with_no_reasoning_log_is_none_not_zero(self, tmp_path):
        """Every arm without `--cognition`: an absent log and a log with
        zero links are different facts, exactly as an unmeasured cost
        differs from a cheap one."""
        self._run_dir(tmp_path)
        result = ArmResult(arm=ARMS[0], reports=(_report({"m1": True}),),
                           directories=(tmp_path,))
        assert mod.spine(result) is None
        assert mod.spine(ArmResult(arm=ARMS[0], skipped="no")) is None

    def test_a_log_that_will_not_replay_is_counted_not_skipped(
            self, tmp_path):
        from core.runtime.cognition import REASONING_LOG

        run = self._run_dir(tmp_path)
        (run / REASONING_LOG).write_text("not a log\n", encoding="utf-8")
        result = ArmResult(arm=ARMS[1], reports=(_report({"m1": True}),),
                           directories=(tmp_path,))
        assert mod.spine(result) == {"links": 0, "logs": 0, "unreadable": 1}

    def test_the_report_prints_the_tally_and_the_attribution_rules(
            self, tmp_path):
        """The reading rules ride IN the report — A2−A0 the view, A3−A2
        the spine, A4−A3 extraction, never A4−A0 — because a table
        outlives the person who knew how to read it."""
        self._log_with_one_link(self._run_dir(tmp_path))
        with_log = ArmResult(arm=ARMS[2], reports=(_report({"m1": True}),),
                             directories=(tmp_path,))
        text = Ablation(suite="toy", split="train",
                        arms=(with_log,)).to_markdown()
        assert "The design arms" in text
        assert "1 subject link(s) across 1 reasoning log(s)" in text
        assert "NEVER A4−A0" in text
        payload = Ablation(suite="toy", split="train",
                           arms=(with_log,)).as_dict()
        assert payload["arms"][0]["spine"] == {"links": 1, "logs": 1,
                                               "unreadable": 0}

    def test_a_table_with_no_cognition_arm_says_nothing_about_spines(self):
        text = Ablation(suite="toy", split="train", arms=(
            ArmResult(arm=ARMS[0], reports=(_report({"m1": True}),)),
        )).to_markdown()
        assert "The design arms" not in text


class TestTheSpinePairJoiner:
    """`spine_pair`: EVAL.md §20's A3−A2, joined mechanically.

    The pair is the SAME suite run twice — once against a declaring
    plane, once with the declarations withheld — so the joiner's whole
    job is two things a hand-read gets wrong: proving which table was
    which off the spine tallies the tables themselves carry, and refusing
    any two tables that were not the two halves of one experiment.
    """

    def _table(self, links, missions, *, commit="c1", suite="benchmark",
               repeats=3, model="m", logs=36, spine="default",
               skipped=""):
        tally = ({"links": links, "logs": logs, "unreadable": 0}
                 if spine == "default" else spine)
        return {
            "suite": suite, "repeats": repeats,
            "keys": {"train": sorted(missions)},
            "flags": {key: "chaining" for key in missions},
            "meta": {"provider": "local", "model": model, "commit": commit},
            "arms": [
                {"name": "baseline", "skipped": "", "spine": None},
                {"name": "compiled-context", "skipped": skipped,
                 "spine": tally,
                 "missions": {"train": dict(missions)},
                 "runs": {"train": [sum(map(bool, missions.values())) * 3,
                                    len(missions) * 3]}},
            ]}

    DECLARING = {"a": True, "b": True, "c": False}
    WITHHELD = {"a": True, "b": False, "c": True}

    def _pair(self, **withheld_changes):
        return (self._table(41, self.DECLARING),
                self._table(0, self.WITHHELD, commit="c2",
                            **withheld_changes))

    def test_the_reading_is_paired_and_labelled(self):
        text = mod.spine_pair(*self._pair())
        assert "41 subject link(s) across 36 reasoning log(s)" in text
        assert "**A3**" in text and "**A2**" in text
        assert "`c1`" in text and "`c2`" in text
        assert "| `b` | chaining | FAIL | PASS | FIXED |" in text
        assert "| `c` | chaining | PASS | FAIL | BROKE |" in text
        assert "**+1 fixed, -1 broke, 1 unchanged**" in text
        assert "A2 6/9, A3 6/9" in text
        assert "never a reading of two arms within one table" in text

    def test_a_mission_one_side_did_not_run_is_left_out(self):
        """An absence is not a tie — `paired`'s rule, kept here too."""
        declaring = self._table(41, self.DECLARING)
        withheld = self._table(0, {"a": True, "b": False}, commit="c2")
        withheld["keys"] = declaring["keys"]  # same experiment, one lost run
        text = mod.spine_pair(declaring, withheld)
        assert "| `c` |" not in text
        assert "**+1 fixed, -0 broke, 1 unchanged**" in text

    def test_swapped_files_are_refused_by_name(self):
        declaring, withheld = self._pair()
        with pytest.raises(Unavailable, match="SWAPPED"):
            mod.spine_pair(withheld, declaring)

    def test_two_bare_tables_are_refused_as_both_a2(self):
        with pytest.raises(Unavailable, match="NEITHER"):
            mod.spine_pair(self._table(0, self.DECLARING),
                           self._table(0, self.WITHHELD))

    def test_two_declaring_tables_are_refused_as_both_a3(self):
        with pytest.raises(Unavailable, match="BOTH"):
            mod.spine_pair(self._table(41, self.DECLARING),
                           self._table(7, self.WITHHELD))

    def test_a_table_with_no_reasoning_log_cannot_prove_itself(self):
        """`spine: null` (the arm never wrote a log) and zero logs are the
        same refusal: which design arm the column is cannot be proven, and
        pairing on trust is the mistake the joiner exists to remove."""
        declaring, _ = self._pair()
        for tally in (None, {"links": 0, "logs": 0, "unreadable": 3}):
            broken = self._table(0, self.WITHHELD, spine=tally)
            with pytest.raises(Unavailable, match="no readable reasoning"):
                mod.spine_pair(declaring, broken)

    @pytest.mark.parametrize("changes", [
        {"suite": "other"},
        {"repeats": 1},
        {"model": "m2"},
    ])
    def test_two_different_experiments_are_refused(self, changes):
        declaring, withheld = self._pair(**changes)
        with pytest.raises(Unavailable, match="not the same experiment"):
            mod.spine_pair(declaring, withheld)

    def test_different_mission_keys_are_two_experiments_as_well(self):
        declaring, withheld = self._pair()
        withheld["keys"] = {"train": ["a", "b", "d"]}
        with pytest.raises(Unavailable, match="not the same experiment"):
            mod.spine_pair(declaring, withheld)

    def test_a_missing_or_skipped_arm_is_refused_with_its_reason(self):
        declaring, withheld = self._pair()
        with pytest.raises(Unavailable, match="no `graph` arm"):
            mod.spine_pair(declaring, withheld, arm="graph")
        withheld["arms"][1]["skipped"] = "the flag is not accepted"
        with pytest.raises(Unavailable, match="SKIPPED"):
            mod.spine_pair(declaring, withheld)

    def test_a_file_that_is_not_an_ablation_is_refused(self):
        with pytest.raises(Unavailable, match="not an ablation JSON"):
            mod.spine_pair({"anything": 1}, self._table(0, self.WITHHELD))

    def test_the_subcommand_joins_two_files(self, tmp_path, capsys):
        declaring, withheld = self._pair()
        left = tmp_path / "declaring.json"
        right = tmp_path / "withheld.json"
        left.write_text(json.dumps(declaring), encoding="utf-8")
        right.write_text(json.dumps(withheld), encoding="utf-8")
        code = eval_main(["spine-pair", "--declaring", str(left),
                          "--withheld", str(right)])
        assert code == 0
        out = capsys.readouterr().out
        assert "A3−A2" in out and "FIXED" in out

    def test_the_subcommand_refuses_with_the_reason_on_stderr(
            self, tmp_path, capsys):
        declaring, withheld = self._pair()
        left = tmp_path / "declaring.json"
        right = tmp_path / "withheld.json"
        left.write_text(json.dumps(declaring), encoding="utf-8")
        right.write_text(json.dumps(withheld), encoding="utf-8")
        assert eval_main(["spine-pair", "--declaring", str(right),
                          "--withheld", str(left)]) == 2
        assert "SWAPPED" in capsys.readouterr().err
        assert eval_main(["spine-pair", "--declaring", str(left),
                          "--withheld", str(tmp_path / "absent.json")]) == 2
        assert "absent.json" in capsys.readouterr().err


class TestWhatTheRunsSpent:
    """`spend`: the W5 columns as one row per arm, means per graded run."""

    def _result(self, kpis_by_key, infra=()):
        from core.eval.score import Half, Totals

        verdicts = tuple(
            Verdict(key=key, flag="synthesis", split="train", passed=True,
                    infra=("the stream is empty" if key in infra else ""),
                    kpis=kpis)
            for key, kpis in kpis_by_key.items())
        half = Half(split="train", verdicts=verdicts, overall=Totals(),
                    by_flag={})
        return ArmResult(arm=ARMS[0], reports=(
            Report(suite="toy", halves={"train": half}),))

    def test_means_skip_what_nobody_reported(self):
        """`None` KPIs are out of numerator AND denominator — the `usage`
        rule — so one silent provider does not halve a cost."""
        result = self._result({
            "a": {"model_calls": 4, "tokens": 100, "dead_end_calls": 2,
                  "calls_to_chain": 3, "premature": False},
            "b": {"model_calls": None, "tokens": 300, "dead_end_calls": 0,
                  "calls_to_chain": None, "premature": True},
        })
        from core.eval.context import ContextSummary
        row = mod.spend(result, "train", ContextSummary())
        assert row["model_calls"] == 4.0
        assert row["tokens"] == 200.0
        assert row["dead_end_calls"] == 1.0
        assert row["calls_to_chain"] == 3.0
        assert row["premature"] == [1, 2]
        assert row["extraction_calls"] is None

    def test_a_verdict_is_not_averaged_as_a_number(self):
        """`premature` is a bool and bools are ints in Python: a mean that
        swallowed it would print a rate wearing a cost's name."""
        assert mod._mean_of([True, 2]) == 2.0
        assert mod._mean_of([None, True, False]) is None
        result = self._result({"a": {"premature": True}})
        row = mod.spend(result, "train", __import__(
            "core.eval.context", fromlist=["ContextSummary"]
        ).ContextSummary())
        assert row["premature"] == [1, 1]
        assert row["model_calls"] is None

    def test_an_infra_run_is_out_of_the_spend_as_well(self):
        result = self._result(
            {"a": {"model_calls": 4}, "b": {"model_calls": 400}},
            infra=("b",))
        from core.eval.context import ContextSummary
        assert mod.spend(result, "train",
                         ContextSummary())["model_calls"] == 4.0

    def test_the_extraction_breakout_rides_the_recorded_kind(self):
        from core.eval.context import ContextSummary
        row = mod.spend(self._result({"a": {"model_calls": 2}}), "train",
                        ContextSummary(runs=1, calls=5, extraction_calls=2,
                                       chars=10))
        assert row["extraction_calls"] == 2

    def test_the_markdown_carries_the_spend_table(self):
        result = self._result({
            "a": {"model_calls": 3, "tokens": 120, "elapsed_s": 2.5,
                  "unsupported": 1, "dead_end_calls": 2,
                  "calls_to_chain": 3, "premature": True}})
        text = Ablation(suite="toy", split="train", arms=(result,),
                        keys={"train": ("a",)}).to_markdown()
        assert "what the runs spent" in text
        assert "dead ends/run" in text
        assert "calls→chain" in text
        assert "1/1" in text
        assert "reads 0 until `--extract` exists" in text
