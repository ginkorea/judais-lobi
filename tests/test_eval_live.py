# tests/test_eval_live.py — the live matrix: `python -m core.eval measure`

"""The measurement harness, held to everything it claims, with no network.

`measure` is the subcommand that needs a model, so the interesting question
is how to test it without one. The answer is the same one
`tests/test_eval_stub_suite.py` gives: **the model is the only fake**. The
CLI is the real CLI, the tool plane is a real subprocess of the real MCP
stub, the skill manifest is a real manifest — the variant this harness
wrote — the grounding validator is real and the run store is real. What is
scripted is the replies.

That matters more here than anywhere else in the package, because what
`measure` owns is precisely the shape of a spawn: which flags reached the
child, which manifest it was handed, where its stream landed and whether
that directory can be scored again tomorrow. A fake that only replayed a
committed stream would confirm none of it.

Two things are asserted from a distance rather than driven:

* the **native** row, because a scripted backend's capabilities are a
  `MagicMock` and every attribute of one is truthy — an endpoint that says
  "no" has to be stated, not mocked into existence;
* the **per-mission timeout**, driven against a child that hangs on
  purpose, because a real mission that hangs takes ten minutes to prove it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.eval import measure as M
from core.eval.run import DEFAULT_TIMEOUT_S
from core.eval.stub_suite import SUITE
from core.runtime import contract

pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")
pytest.importorskip("mcp", reason="the MCP client is an optional extra")

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval"
STUB_SKILL = FIXTURES / "stub_skill.md"
MEASURE_SKILL = FIXTURES / "measure_skill.md"
STUB_SERVER = Path(__file__).resolve().parent / "mcp_stub_server.py"

#: The two missions the driven runs use: one from each half, so a matrix
#: produced here has both tables populated and neither is asserted from an
#: empty one.
TRAIN_KEY = "carry_the_result_forward"
TEST_KEY = "two_views_one_line"


# ── the matrix as data ───────────────────────────────────────────────────────

class TestTheMatrixIsData:
    """Every configuration is one entry, and nothing else knows its name."""

    def test_every_entry_is_named_once(self):
        names = [m.name for m in M.MEASUREMENTS]
        assert len(names) == len(set(names))

    def test_the_baseline_changes_nothing(self):
        direct = M.MEASUREMENTS[0]
        assert (direct.name, direct.flags, direct.tier) == ("direct", (), None)

    def test_the_three_questions_the_roadmap_left_open_are_all_here(self):
        """§2.5's swarm, §2.7's protocol, and 0.13.0's three tiers."""
        by_name = {m.name: m for m in M.MEASUREMENTS}
        assert by_name["swarm"].flags == ("--swarm",)
        assert by_name["native"].flags == ("--protocol", "native")
        assert {m.tier for m in M.MEASUREMENTS if m.tier} == set(M.TIER_KEYS)

    def test_every_configuration_says_why_it_is_in_the_matrix(self):
        assert all(m.why for m in M.MEASUREMENTS)

    def test_every_flag_the_matrix_spawns_with_is_published(self):
        """The rule a mission's own flags are held to, held to the matrix's."""
        M._check_flags_are_published(M.MEASUREMENTS)
        for entry in M.MEASUREMENTS:
            for token in entry.flags:
                if token.startswith("--"):
                    assert token in contract.CLI_FLAGS

    def test_an_unpublished_flag_is_refused(self):
        rogue = M.Measurement(name="rogue", flags=("--not-a-flag",))
        with pytest.raises(M.Unmeasurable) as exc:
            M._check_flags_are_published([rogue])
        assert "--not-a-flag" in str(exc.value)

    def test_every_kpi_a_column_reads_is_one_the_scorer_records(self):
        """A column asking for a KPI nobody writes prints `—` for ever.

        The names are the scorer's, spelled here; a rename on that side and
        not this one would empty a column silently, which is the failure a
        table cannot show you.
        """
        from core.eval.score import _kpis
        recorded = set(_kpis([]))
        read_directly = ("staged", "reply_rejected", "human_interventions",
                         "grounded")
        for key in (*M._MEANS, *read_directly):
            assert key in recorded, key

    def test_every_column_is_a_cell_the_row_can_answer(self):
        """And the other half: a heading with no number behind it."""
        from core.eval.score import Half, Report, Totals, Verdict
        verdict = Verdict(key="k", flag="f", split="train", passed=True,
                          kpis={key: 1 for key in M._MEANS})
        configured = M.Configured(name="c", reports=(Report(
            suite="s", halves={"train": Half(
                split="train", verdicts=(verdict,), overall=Totals(),
                by_flag={})}),))
        row = M.columns_for(configured, "train")
        for _title, key in M._COLUMNS:
            assert M._cell(row, key) != "", key
        assert M._cell(row, "passed") == "1/1"


class TestTheSpawnLineIsTheCallersPlusTheDelta:
    BASE = ["judais", "{objective}", "--mission", "--skill", "/s/SKILL.md",
            "--provider", "local"]

    def test_flags_go_on_the_end_and_nothing_is_reordered(self):
        line = M.spawn_line_for(self.BASE, M.Measurement("swarm",
                                                        flags=("--swarm",)),
                                None)
        assert line[:len(self.BASE)] == self.BASE
        assert line[len(self.BASE):] == ["--swarm"]

    def test_the_skill_is_repointed_at_the_variant(self, tmp_path):
        variant = tmp_path / "v.md"
        line = M.spawn_line_for(self.BASE, M.MEASUREMENTS[0], variant)
        assert line[line.index("--skill") + 1] == str(variant)

    def test_the_joined_spelling_is_repointed_too(self, tmp_path):
        variant = tmp_path / "v.md"
        line = M.spawn_line_for(["judais", "--skill=/s/SKILL.md"],
                                M.MEASUREMENTS[0], variant)
        assert line[1] == f"--skill={variant}"

    def test_a_line_with_no_skill_has_none_to_find(self):
        assert M._skill_path(["judais", "--mission"]) is None


# ── the manifest variants ────────────────────────────────────────────────────

def _grounding_of(path: Path) -> dict:
    import yaml
    from core.runtime.skills import SkillManifest
    front, _body = SkillManifest._split(path, path.read_text(encoding="utf-8"))
    assert yaml  # imported for the parse the splitter does
    return dict((front.get("skill") or {}).get("grounding") or {})


class TestTheManifestVariants:
    """One switch per configuration, and the baseline turns all of them off."""

    def test_the_baseline_strips_every_tier(self, tmp_path):
        variant = M.manifest_variant(MEASURE_SKILL, M.MEASUREMENTS[0],
                                     tmp_path / "direct.md")
        grounding = _grounding_of(variant)
        assert not set(grounding) & set(M.TIER_KEYS)
        # and keeps everything that is not a tier
        assert grounding["identifier_pattern"]
        assert grounding["number_pattern"]

    def test_reading_is_switched_on_with_the_table_it_needs(self, tmp_path):
        entry = next(m for m in M.MEASUREMENTS if m.tier == "reading")
        grounding = _grounding_of(M.manifest_variant(
            MEASURE_SKILL, entry, tmp_path / "reading.md"))
        assert grounding["reading"] is True
        assert grounding["claim_table"] is True
        assert "critic" not in grounding and "planes" not in grounding

    def test_critic_is_switched_on_alone(self, tmp_path):
        entry = next(m for m in M.MEASUREMENTS if m.tier == "critic")
        grounding = _grounding_of(M.manifest_variant(
            MEASURE_SKILL, entry, tmp_path / "critic.md"))
        assert grounding["critic"] is True
        assert "reading" not in grounding and "planes" not in grounding

    def test_planes_keeps_the_block_the_manifest_declared(self, tmp_path):
        entry = next(m for m in M.MEASUREMENTS if m.tier == "planes")
        grounding = _grounding_of(M.manifest_variant(
            MEASURE_SKILL, entry, tmp_path / "planes.md"))
        assert set(grounding["planes"]) == {"catalogue", "arithmetic"}
        assert grounding["planes"]["arithmetic"]["tools"] == ["mcp.add"]

    def test_a_manifest_with_no_plane_cannot_have_one_invented_for_it(
            self, tmp_path):
        """The one tier that is a table and not a switch.

        `stub_skill.md` declares no `planes:`, so the row is skipped and the
        note says why. A harness that wrote a plane here would be naming a
        deployment's tool families for it.
        """
        entry = next(m for m in M.MEASUREMENTS if m.tier == "planes")
        with pytest.raises(M.Unmeasurable) as exc:
            M.manifest_variant(STUB_SKILL, entry, tmp_path / "planes.md")
        assert "planes" in str(exc.value)

    def test_the_variant_still_loads_as_a_manifest(self, tmp_path):
        """Written through the manifest owner's own splitter, and read back
        by the loader a mission uses — a variant the CLI cannot open is a
        row that fails for the harness's reason and not the model's."""
        from core.runtime.skills import load_skill
        for entry in M.MEASUREMENTS:
            if entry.tier == "planes":
                source = MEASURE_SKILL
            else:
                source = STUB_SKILL
            variant = M.manifest_variant(source, entry,
                                         tmp_path / f"{entry.name}.md")
            loaded = load_skill(variant)
            assert loaded.name == "stub_plane"
            assert "mcp.run_shell_command" in loaded.allowed_tools

    def test_the_measure_manifest_is_the_stub_manifest_plus_planes(self):
        """The second copy cannot drift into a second declaration.

        `measure_skill.md` exists only to declare a plane; every other field
        is `stub_skill.md`'s, and a change to one that is not made to the
        other would make the matrix's baseline a different skill from the
        corpus's.
        """
        from core.runtime.skills import SkillManifest
        stub, stub_body = SkillManifest._split(
            STUB_SKILL, STUB_SKILL.read_text(encoding="utf-8"))
        both, _ = SkillManifest._split(
            MEASURE_SKILL, MEASURE_SKILL.read_text(encoding="utf-8"))
        assert stub_body                      # the bodies differ on purpose
        stub_skill = dict(stub["skill"])
        both_skill = dict(both["skill"])
        planes = dict(both_skill["grounding"]).pop("planes", None)
        assert planes, "measure_skill.md exists to declare a plane"
        both_skill["grounding"] = {
            k: v for k, v in both_skill["grounding"].items() if k != "planes"}
        assert both_skill == stub_skill
        assert {k: v for k, v in both.items() if k != "skill"} == \
               {k: v for k, v in stub.items() if k != "skill"}


# ── what an endpoint cannot speak is skipped, not guessed ────────────────────

class TestNativeIsSkippedWhenTheEndpointSaysSo:
    NATIVE = next(m for m in M.MEASUREMENTS if m.name == "native")

    def test_a_backend_without_tool_calls_skips_it_with_a_note(self):
        caps = SimpleNamespace(supports_tool_calls=False,
                               supports_tool_choice_required=False)
        note = M._cannot_speak(self.NATIVE, caps)
        assert "supports_tool_calls=False" in note
        assert "not running" in note

    def test_a_backend_that_speaks_it_is_not_skipped(self):
        caps = SimpleNamespace(supports_tool_calls=True,
                               supports_tool_choice_required=True)
        assert M._cannot_speak(self.NATIVE, caps) == ""

    def test_an_endpoint_that_cannot_be_asked_is_not_a_skip(self):
        """`None` is "nobody could say", and the CLI's own door is the
        honest place for that refusal — not a row this harness greyed out
        on a guess."""
        assert M._cannot_speak(self.NATIVE, None) == ""

    def test_the_baseline_needs_nothing_and_is_never_skipped(self):
        caps = SimpleNamespace(supports_tool_calls=False,
                               supports_tool_choice_required=False)
        assert M._cannot_speak(M.MEASUREMENTS[0], caps) == ""

    def test_the_skipped_row_carries_the_note_into_the_matrix(self, tmp_path):
        caps = SimpleNamespace(supports_tool_calls=False,
                               supports_tool_choice_required=False)
        matrix = M.measure(
            SUITE, ["judais", "{objective}"], tmp_path / "out",
            measurements=[self.NATIVE], only=[TRAIN_KEY], capabilities=caps,
            log=lambda *_: None)
        row = matrix.configured[0]
        assert not row.ran and "supports_tool_calls=False" in row.skipped
        assert "Configurations not run" in matrix.to_markdown()

    def test_a_tier_without_a_skill_is_skipped_with_its_own_note(
            self, tmp_path):
        entry = next(m for m in M.MEASUREMENTS if m.tier == "critic")
        matrix = M.measure(
            SUITE, ["judais", "{objective}"], tmp_path / "out",
            measurements=[entry], only=[TRAIN_KEY], capabilities=None,
            log=lambda *_: None)
        assert "no --skill" in matrix.configured[0].skipped


# ── the header ───────────────────────────────────────────────────────────────

class TestTheHeaderSaysWhatProducedTheNumbers:
    def test_it_carries_the_commit_the_model_and_the_date(self):
        meta = M.header(["judais", "--provider", "local", "--model", "m-1"],
                        {"LOCAL_API_BASE": "http://h:8000/v1"})
        assert meta["commit"] and meta["date"] and meta["model"] == "m-1"
        assert meta["provider"] == "local"

    def test_a_key_in_the_endpoint_is_not_written_down(self):
        assert M.scrubbed("https://tok@host/v1?key=s3cret") == \
            "https://host/v1"

    def test_a_bare_endpoint_survives_scrubbing(self):
        assert M.scrubbed("http://127.0.0.1:8000/v1") == \
            "http://127.0.0.1:8000/v1"

    def test_nothing_configured_is_reported_as_nothing(self):
        meta = M.header(["judais"], {})
        assert meta["provider"] == "" and meta["endpoint"] == ""

    def test_the_commit_degrades_to_a_word_rather_than_raising(self, tmp_path):
        assert M.commit_of(tmp_path / "not-a-repo") == "unknown"


# ── narrowing ────────────────────────────────────────────────────────────────

class TestOnly:
    def test_it_keeps_the_named_missions(self):
        narrowed = M._narrowed(SUITE, [TEST_KEY, TRAIN_KEY])
        assert set(narrowed.keys()) == {TEST_KEY, TRAIN_KEY}

    def test_a_key_the_suite_does_not_hold_is_refused(self):
        with pytest.raises(M.Unmeasurable) as exc:
            M._narrowed(SUITE, ["the_bounary_holds"])
        assert "the_bounary_holds" in str(exc.value)

    def test_nothing_named_is_the_whole_suite(self):
        assert M._narrowed(SUITE, []) is SUITE


# ── driving the real CLI with a scripted model ───────────────────────────────

#: A `judais` whose model is scripted and whose everything else is real.
#: Written out as a script because `measure` spawns a process — driving
#: `_main` in-process would test a different thing from the one that runs.
DRIVER = textwrap.dedent('''\
    import json, os, sys
    sys.path.insert(0, {repo!r})

    argv = sys.argv[1:]
    runs = os.environ.get("JUDAIS_LOBI_RUNS", "")
    skill = ""
    if "--skill" in argv:
        skill = open(argv[argv.index("--skill") + 1],
                     encoding="utf-8").read()
    if runs:
        os.makedirs(os.path.dirname(runs), exist_ok=True)
        with open(os.path.join(os.path.dirname(runs), "spawn.json"), "w") as f:
            json.dump({{"argv": sys.argv, "skill": skill}}, f)

    if "--hang" in argv:
        import time
        time.sleep(120)

    from core.eval.stub_suite import SUITE
    from tests.test_eval_stub_suite import SCRIPTS, _agent
    from core.cli import _main

    mission = next(m for m in SUITE.missions if m.prompt == sys.argv[1])
    _main(_agent(SCRIPTS[mission.key]["good"]))
    ''')


@pytest.fixture
def driver(tmp_path):
    path = tmp_path / "driver.py"
    path.write_text(DRIVER.format(repo=str(REPO)), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def template(driver, tmp_path):
    """The caller's spawn line: the real CLI, the real stub, the real skill."""
    from core.eval.run import OBJECTIVE
    return [sys.executable, str(driver), OBJECTIVE,
            "--mission",
            "--mcp-stdio", f"{sys.executable} {STUB_SERVER}",
            "--skill", str(MEASURE_SKILL),
            "--no-stream"]


@pytest.fixture
def sandboxed(tmp_path, monkeypatch):
    """A whole run's footprint under tmp, for the children too."""
    for name, value in (("JUDAIS_LOBI_AUDIT", tmp_path / "audit.jsonl"),
                        ("JUDAIS_LOBI_APPROVALS", tmp_path / "approvals")):
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    return tmp_path


@pytest.fixture
def driven(template, sandboxed, tmp_path):
    """One matrix, two configurations, two missions, really spawned."""
    entries = [m for m in M.MEASUREMENTS if m.name in ("direct", "planes")]
    return M.measure(
        SUITE, template, tmp_path / "out", measurements=entries,
        only=[TRAIN_KEY, TEST_KEY], capabilities=None, timeout_s=120,
        log=lambda *_: None)


class TestTheDrivenMatrix:
    def test_one_row_per_configuration_with_the_kpi_columns(self, driven):
        text = driven.to_markdown()
        assert [c.name for c in driven.configured] == ["direct", "planes"]
        for title, _key in M._COLUMNS:
            assert f"| {title} " in text or f" {title} |" in text
        for name in ("direct", "planes"):
            assert f"| `{name}` |" in text

    def test_both_halves_are_reported_and_never_blended(self, driven):
        text = driven.to_markdown()
        assert "## train" in text and "## test" in text
        assert "blended number" in text
        # the per-mission grid puts each mission under its own half
        assert TRAIN_KEY in text and TEST_KEY in text

    def test_the_missions_passed_against_the_scripted_agent(self, driven):
        for configuration in driven.configured:
            for report in configuration.reports:
                for half in report.halves.values():
                    for verdict in half.verdicts:
                        assert verdict.passed, (configuration.name,
                                                verdict.key, verdict.reasons)

    def test_the_child_was_handed_the_variant_and_not_the_original(
            self, driven, tmp_path):
        """The manifest the harness wrote is the one the mission ran under.

        Read out of the child's own record of what it opened, because a
        variant written to disk and not passed on is exactly the failure
        that would make every tier row a copy of the baseline.
        """
        for name, tier in (("direct", False), ("planes", True)):
            spawn = json.loads((tmp_path / "out" / name / "rep1" / TRAIN_KEY
                                / "spawn.json").read_text(encoding="utf-8"))
            # Read as a manifest, not grepped: `measure_skill.md`'s BODY
            # explains the `planes:` block in prose, and a substring test
            # would pass on the prose of the file that was not switched on.
            echoed = tmp_path / f"echoed-{name}.md"
            echoed.write_text(spawn["skill"], encoding="utf-8")
            assert ("planes" in _grounding_of(echoed)) is tier
            assert str(tmp_path / "out" / name / "skill.md") in spawn["argv"]
            assert str(MEASURE_SKILL) not in spawn["argv"]

    def test_the_matrix_records_where_every_row_can_be_scored_again(
            self, driven, tmp_path):
        for configuration in driven.configured:
            assert configuration.directories
            for directory in configuration.directories:
                assert (directory / TRAIN_KEY / "events.jsonl").exists()

    def test_score_over_the_recorded_directory_reproduces_the_verdicts(
            self, driven, tmp_path):
        """The no-GPU path, over the bytes this run left behind.

        This is ROADMAP §4's sentence as a test: the score in the table is
        reproducible from the recorded runs, by the shipped command, on a
        machine with no endpoint at all.
        """
        for configuration in driven.configured:
            directory = configuration.directories[0]
            done = subprocess.run(
                [sys.executable, "-m", "core.eval", "score", "--runs",
                 str(directory), "--json", "--allow-failures"],
                cwd=str(REPO), capture_output=True, text=True, timeout=300,
                env={**os.environ, "PYTHONPATH": str(REPO)})
            assert done.returncode == 0, done.stderr[-2000:]
            again = json.loads(done.stdout)
            live = configuration.reports[0].as_dict()
            for half in ("train", "test"):
                mine = {v["key"]: v["passed"]
                        for v in live["halves"][half]["verdicts"]}
                theirs = {v["key"]: v["passed"]
                          for v in again["halves"][half]["verdicts"]
                          if v["key"] in mine}
                assert mine == theirs, half

    def test_the_report_files_carry_the_provenance(self, driven, tmp_path):
        report = tmp_path / "report" / "measure.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(driven.to_markdown(), encoding="utf-8")
        (report.with_suffix(".json")).write_text(driven.to_json(),
                                                 encoding="utf-8")
        text = report.read_text(encoding="utf-8")
        assert driven.meta["commit"] in text
        assert driven.meta["date"] in text
        assert "**commit**" in text and "**endpoint**" in text
        assert json.loads(report.with_suffix(".json").read_text(
            encoding="utf-8"))["meta"]["commit"] == driven.meta["commit"]


class TestTheBoundOnOneMission:
    def test_a_child_that_hangs_is_killed_and_scored_as_a_failure(
            self, driver, sandboxed, tmp_path):
        """A killed mission keeps whatever stream it emitted, and the
        scorer fails it for having no `mission_finished` — which is the
        honest reading of a run that never closed."""
        template = [sys.executable, str(driver), "{objective}", "--hang",
                    "--mission"]
        matrix = M.measure(
            SUITE, template, tmp_path / "out",
            measurements=[M.MEASUREMENTS[0]], only=[TRAIN_KEY],
            capabilities=None, timeout_s=1.0, log=lambda *_: None)
        verdicts = matrix.configured[0].reports[0].halves["train"].verdicts
        assert verdicts and not verdicts[0].passed
        record = json.loads((tmp_path / "out" / "direct" / "rep1" / TRAIN_KEY
                             / "command.json").read_text(encoding="utf-8"))
        assert record["timed_out"] is True
        assert record["wall_s"] < 30

    def test_the_default_bound_is_the_one_the_run_subcommand_uses(self):
        """One owner: a second default here would be a second answer to
        'how long may one mission take'."""
        from core.eval.run import _parser
        args = _parser().parse_args(["measure", "--out", "o"])
        assert args.per_mission_seconds == DEFAULT_TIMEOUT_S


# ── the columns ──────────────────────────────────────────────────────────────

class TestTheColumns:
    def _configured(self, *repeats):
        from core.eval.score import Half, Report, Totals

        reports = []
        for verdicts in repeats:
            half = Half(split="train", verdicts=tuple(verdicts),
                        overall=Totals(), by_flag={})
            reports.append(Report(suite="s", halves={"train": half}))
        return M.Configured(name="c", reports=tuple(reports),
                            directories=tuple(Path("/x") for _ in reports))

    def _verdict(self, key="k", passed=True, **kpis):
        from core.eval.score import Verdict
        base = {"steps": 3, "model_calls": 4, "prompt_tokens": 100,
                "completion_tokens": 10, "elapsed_s": 2.0, "staged": False,
                "reply_rejected": 0, "human_interventions": 0,
                "grounded": True}
        base.update(kpis)
        return Verdict(key=key, flag="f", split="train", passed=passed,
                       kpis=base)

    def test_counts_are_summed_and_means_are_averaged(self):
        row = M.columns_for(self._configured(
            [self._verdict(steps=2), self._verdict(key="j", steps=4,
                                                   reply_rejected=1)]),
            "train")
        assert (row["missions"], row["passed"], row["rejected"]) == (2, 2, 1)
        assert row["steps"] == 3

    def test_a_spread_appears_only_with_more_than_one_repeat(self):
        one = M.columns_for(self._configured([self._verdict()]), "train")
        assert one["steps_spread"] is None
        two = M.columns_for(self._configured([self._verdict(steps=2)],
                                             [self._verdict(steps=6)]),
                            "train")
        assert (two["steps"], two["steps_spread"]) == (4, round(
            (8 ** 0.5), 3))
        assert "±" in M._cell(two, "steps")

    def test_grounded_is_a_fraction_of_what_had_a_verdict(self):
        row = M.columns_for(self._configured(
            [self._verdict(grounded=True), self._verdict(key="j",
                                                         grounded=None),
             self._verdict(key="l", grounded=False)]), "train")
        assert (row["grounded_true"], row["grounded_known"]) == (1, 2)
        assert M._cell(row, "grounded") == "1/2"

    def test_a_number_nothing_reported_is_a_dash_and_never_a_zero(self):
        row = M.columns_for(self._configured(
            [self._verdict(prompt_tokens=None)]), "train")
        assert M._cell(row, "prompt_tokens") == "—"

    def test_staged_is_counted_because_it_is_the_routing_column(self):
        row = M.columns_for(self._configured(
            [self._verdict(staged=True), self._verdict(key="j",
                                                       staged=False)]),
            "train")
        assert row["staged"] == 1


# ── the command line ─────────────────────────────────────────────────────────

def cli(*args, expect=None, cwd=REPO):
    done = subprocess.run(
        [sys.executable, "-m", "core.eval", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": str(REPO)})
    if expect is not None:
        assert done.returncode == expect, done.stderr[-2000:]
    return done


class TestTheSubcommand:
    def test_measure_with_no_spawn_line_says_so(self, tmp_path):
        done = cli("measure", "--out", str(tmp_path / "o"), expect=2)
        assert "after `--`" in done.stderr

    def test_an_unknown_configuration_names_the_ones_there_are(self,
                                                               tmp_path):
        done = cli("measure", "--out", str(tmp_path / "o"), "--config",
                   "sworm", "--", "judais", expect=2)
        assert "sworm" in done.stderr and "swarm" in done.stderr

    def test_it_is_listed_beside_run_score_and_check(self):
        assert "measure" in cli("--help").stdout

    def test_report_writes_markdown_and_the_same_matrix_as_json_beside_it(
            self, tmp_path):
        """`--report` is the release artefact ROADMAP §4 asks for.

        Driven through `from_args` over a configuration that cannot run
        here, so the artefact is asserted without spending a model on it:
        what is under test is that both files are written, that they carry
        the provenance, and that the JSON is the same matrix rather than a
        second rendering of it.
        """
        from core.eval.run import _parser
        args = _parser().parse_args([
            "measure", "--out", str(tmp_path / "out"),
            "--report", str(tmp_path / "r" / "measure.md"),
            "--config", "critic", "--only", TRAIN_KEY, "--allow-failures"])
        assert M.from_args(SUITE, args, ["judais", "{objective}"]) == 0

        markdown = (tmp_path / "r" / "measure.md").read_text(encoding="utf-8")
        beside = json.loads((tmp_path / "r" / "measure.json").read_text(
            encoding="utf-8"))
        assert beside["meta"]["commit"] in markdown
        assert beside["meta"]["date"] in markdown
        assert beside["suite"] == "stub"
        assert [c["name"] for c in beside["configurations"]] == ["critic"]
        assert beside["configurations"][0]["skipped"]
        # and the same matrix lands beside the runs, so a results directory
        # that outlives the console still says what produced it
        assert json.loads((tmp_path / "out" / "matrix.json").read_text(
            encoding="utf-8"))["meta"] == beside["meta"]
