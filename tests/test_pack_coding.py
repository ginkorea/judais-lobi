# tests/test_pack_coding.py — the coding pack, run for real against real repositories

"""The pack that makes this framework a coding agent, held to what it claims.

`core/skills/library/coding/` is Phase 15's first mission pack (ROADMAP
§2.6b): a `SKILL.md`, a task template, four fixture repositories and eight
eval missions. This module is what stops any of that from being a
description of a coding agent rather than one.

**Nothing here is stubbed on the path under test.** The bus carries the real
`PatchTool`, the real `RepoMapTool` and the real `VerifyTool`; the sandbox is
bwrap; the fixture repository is a git checkout in a temporary directory; and
`verify test` runs the repository's own pytest against the tree the patch
actually landed in. Only the model is scripted, and the scripts are content
in `tests/pack_coding_scripts.py` where they can be read beside the files
they patch.

That arrangement is deliberate and it is the lesson of
`tests/test_coding_loop_end_to_end.py`: every unit of the coding pipeline was
green while `PatchEngine.apply` was called from no role at all, because a
seam is only visible from both sides at once. The seam here is the same one
on the mission path — did a file on disk change, and did the tests run
against the changed tree — and `TestTheChangeLandsWhereTheTestsRun` asks it
directly.

Refresh the committed corpus with::

    JUDAIS_LOBI_EVAL_FIXTURES=refresh .venv/bin/python -m pytest \\
        tests/test_pack_coding.py

and read the diff, exactly as for `tests/test_eval_stub_suite.py`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")

from core.eval.score import score_run                          # noqa: E402
from core.eval.suite import (                                  # noqa: E402
    FLAGS, MIN_TEST_MISSIONS, SPLITS, TEST_SHARE, MissionMisdeclared,
    check_the_suite_is_gradeable,
)
from core.skills.library import check_pack_suite               # noqa: E402
from core.runtime import contract                              # noqa: E402
from core.tools.sandbox import BwrapSandbox                    # noqa: E402
from tests import pack_fixtures as pack                        # noqa: E402
from tests.pack_coding_scripts import REPOS, SCRIPTS           # noqa: E402

#: Where a real stream per mission is kept, on the convention EVAL.md §7
#: already set for the in-repo suite. Under `tests/` and not inside the pack
#: because `tests/` is not in the wheel: a pack ships its manifest, its
#: template, its missions and its fixture repositories, and sixteen recorded
#: transcripts are the harness's evidence about the pack rather than part of
#: it.
CORPUS = Path(__file__).resolve().parent / "fixtures" / "eval" / "coding"

#: Same switch the stub suite uses, so there is one thing to remember.
REFRESH = os.environ.get("JUDAIS_LOBI_EVAL_FIXTURES", "") == "refresh"

#: A neutral, stable place to stand a fixture repository up for a RECORDED
#: run. Absolute paths reach the stream — a patch result names the file it
#: wrote — and `tmp_path` would put this host's user name in a committed
#: fixture, which is precisely the platform particular `CLAUDE.local.md`
#: forbids. `/tmp/judais-lobi-coding-corpus/<key>/<agent>` says nothing about
#: whose machine recorded it.
CORPUS_WORKDIR = Path(tempfile.gettempdir()) / "judais-lobi-coding-corpus"

needs_git = pytest.mark.skipif(not shutil.which("git"),
                               reason="git not available")
needs_bwrap = pytest.mark.skipif(
    not BwrapSandbox.is_available(),
    reason="the coding pack declares `sandbox: bwrap` and this host has none",
)

SUITE = pack.load_missions()
MISSIONS = [pytest.param(m, id=m.key) for m in SUITE.missions]
WITH_A_BAD_AGENT = [pytest.param(m, id=m.key) for m in SUITE.missions
                    if "bad" in SCRIPTS[m.key]]


# ── the manifest ─────────────────────────────────────────────────────────────

class TestThePackLoads:
    """A `SKILL.md` is only a skill if `core.runtime.skills` says so."""

    def test_the_manifest_loads_through_the_one_loader(self):
        manifest = pack.load_pack()
        assert manifest.name == "coding"
        assert manifest.prompt.strip()
        assert manifest.output_contract.strip()

    def test_the_closed_set_is_the_five_tools_and_one_optional(self):
        manifest = pack.load_pack()
        assert manifest.allowed_tools == (
            "repo_map", "fs", "patch", "verify", "git", "run_shell_command")
        assert manifest.optional_tools == frozenset({"run_shell_command"})

    def test_it_asks_for_isolation_because_it_permits_a_shell(self):
        """The code-plane gate, on this pack, working.

        `run_shell_command` is in the closed set, so
        `SkillManifest.code_plane_entries` sees a tool that runs code the
        model composed ON THIS HOST, and the manifest is refused unless it
        declares `sandbox: bwrap`. `verify` is deliberately NOT one of
        those — see `core.runtime.skills.CODE_PLANE_SCOPES`: it also ends
        in a subprocess, but the command is the repository's and the model
        chooses only which of lint/test/typecheck/format to invoke.
        """
        manifest = pack.load_pack()
        assert manifest.sandbox == "bwrap"
        assert [entry for entry, _tool, _scopes
                in manifest.code_plane_entries()] == ["run_shell_command"]

    def test_the_optional_shell_does_not_have_to_be_on_the_bus(self, tmp_path):
        """…and the gate applies anyway.

        Whether a mission may run shell commands must not depend on what a
        bus happened to advertise this morning, so the manifest still
        demands bwrap on a plane that never registered one.
        """
        from core.runtime.skills import SkillToolsUnavailable

        manifest = pack.load_pack()
        offered = ["repo_map", "fs", "patch", "verify", "git"]
        assert manifest.resolve(offered, sandbox="bwrap") == offered
        with pytest.raises(SkillToolsUnavailable) as raised:
            manifest.resolve(offered, sandbox="none")
        assert "bwrap" in str(raised.value)

    def test_the_grounding_grammar_compiles_and_says_what_it_means(self):
        """Two patterns, and what each is for.

        A file path is the token a reader will act on and cannot check by
        reading; a test count is the one figure in a coding answer that
        came from a machine. Anything else in the prose — "the third
        file", "two of the four" — is the model's own arithmetic, and a
        check that flagged it would train whoever reads the report to
        skip it.
        """
        from core.runtime.grounding import GroundingConfig

        config = GroundingConfig.from_mapping(pack.load_pack().grounding)
        identifiers = re.compile(config.identifier_pattern)
        figures = re.compile(config.number_pattern)

        assert identifiers.findall("changed core.py and tests/test_api.py") == [
            "core.py", "tests/test_api.py"]
        # A bare function name is NOT an identifier here. Stated as a test
        # because it is a limit somebody will otherwise assume away.
        assert identifiers.findall("renamed fmt_msg to format_message") == []
        assert figures.findall("3 passed, 1 failed") == ["3", "1"]
        assert figures.findall("the 3 files I touched") == []

    def test_the_body_teaches_the_one_argument_a_model_cannot_guess(self):
        """`patch_set_json` is a JSON string inside a JSON object.

        The catalogue renders `summarize_input_schema`, which is names and
        types and no descriptions, so under the default JSON protocol the
        schema cannot teach this shape and the skill body has to.
        """
        body = pack.load_pack().prompt
        for word in ("patch_set_json", "search_block", "replace_block",
                     "file_path", "task_id"):
            assert word in body, word


# ── the fixture repositories ─────────────────────────────────────────────────

@needs_git
class TestTheFixtureRepositories:
    """Four repositories, small, deterministic, offline."""

    def test_the_pack_carries_the_four_the_missions_name(self):
        assert pack.fixture_names() == [
            "add_cli_flag", "bug_across_files", "pkg_two_modules",
            "rename_symbol"]

    def test_none_of_them_ships_a_nested_git_directory(self):
        """A repository inside a repository is not something git carries.

        So the fixtures are plain directories and `fixture_repo` does the
        `git init`. A `.git` that had slipped in would be silently dropped
        on checkout and every fixture would arrive subtly different from
        the one that was committed.
        """
        assert list(pack.FIXTURES.rglob(".git")) == []

    @pytest.mark.parametrize("name", pack.fixture_names())
    def test_a_copy_is_a_git_repository_with_one_commit(self, name, tmp_path):
        repo = pack.fixture_repo(name, tmp_path)
        log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                             capture_output=True, text=True, check=False)
        assert log.returncode == 0
        assert len(log.stdout.strip().splitlines()) == 1
        assert pack.diffstat(repo) == ""

    @pytest.mark.parametrize("name,expected_rc", [
        ("pkg_two_modules", 0),
        ("rename_symbol", 0),
        ("add_cli_flag", 0),
        # Red on a fresh clone, and that is its whole job: the fix is in
        # two files and the suite is the only thing that says so.
        ("bug_across_files", 1),
    ])
    def test_the_repository_verifies_itself(self, name, expected_rc, tmp_path,
                                            monkeypatch):
        """`verify test` runs the repository's own command, in the repository.

        Through `VerifyTool` and not through a bare `subprocess`, so what
        is under test is the discovery of the command as well as the
        running of it: three of these declare one in `.judais-lobi.yml`
        and `rename_symbol` declares nothing and gets the default, which
        `{python}` makes portable.
        """
        from core.tools.config_loader import load_project_config
        from core.tools.verify_tools import VerifyTool

        repo = pack.fixture_repo(name, tmp_path)
        monkeypatch.chdir(repo)
        rc, out, err = VerifyTool(config=load_project_config(repo))("test")
        assert rc == expected_rc, f"{out}\n{err}"

    def test_the_repository_with_no_config_still_verifies(self, tmp_path,
                                                          monkeypatch):
        """The generic default, proved by a repository that declares nothing.

        `rename_symbol` ships no `.judais-lobi.yml` on purpose. Before the
        `{python}` token the default was the bare word `pytest`, which
        depends on a venv's `bin` being on PATH — and under bwrap that is
        whatever PATH the parent had.
        """
        repo = pack.fixture_repo("rename_symbol", tmp_path)
        assert not list(repo.glob(".judais-lobi.y*ml"))
        monkeypatch.chdir(repo)

        from core.tools.config_loader import load_project_config
        from core.tools.verify_tools import VerifyTool

        rc, out, _err = VerifyTool(config=load_project_config(repo))("test")
        assert rc == 0
        assert "3 passed" in out


# ── the suite ────────────────────────────────────────────────────────────────

class TestTheSuiteIsDeclaredWell:
    """EVAL.md §1–3, asked of a pack's suite rather than the in-repo one."""

    def test_it_loads_and_holds_eight_missions(self):
        assert len(SUITE.missions) == 8
        assert len(set(SUITE.keys())) == 8

    def test_it_grades_as_a_pack_and_would_not_as_a_whole_plane(self):
        """Both halves of the rule lane O landed, over this suite.

        `check_pack_suite` is `core.eval`'s own gradeability check with
        flag coverage scoped to the flags the suite captures. Unscoped —
        `check_the_suite_is_gradeable` — it demands every entry of
        `core.eval.FLAGS`, which is right for the one suite that grades
        the harness against everything it can do and wrong for eight
        coding missions: `submission`, `protocol_shape` and
        `partial_synthesis` cannot be captured honestly by a coding
        question, and three missions invented to fill the table would be
        measuring the table.

        The second assertion is the one worth keeping when the first
        stops being interesting: it names WHY the pack needs the scoped
        check, so the day `core.eval` grows a suite-level `flags:` and
        the adapter goes away, this reads as the reason rather than as a
        test nobody can explain.
        """
        check_pack_suite(SUITE, pack.pack())          # the pack's own check

        with pytest.raises(MissionMisdeclared) as raised:
            check_the_suite_is_gradeable(SUITE)
        problems = [line.strip() for line in str(raised.value).splitlines()[1:]
                    if line.strip()]
        assert len(problems) == 1, problems
        assert "captured by no mission" in problems[0]
        assert "partial_synthesis" in problems[0]

    def test_every_tool_its_missions_name_is_in_the_closed_set(self):
        """The rule only a pack can make, and the one that would have let
        a mission expect a tool the manifest withholds — a mission that
        can never pass, and reads as an agent failure."""
        closed = set(pack.load_pack().allowed_tools)
        assert set(SUITE.tools) <= closed
        for mission in SUITE.missions:
            named = set(mission.expects_tools) | set(mission.forbids_tools)
            assert named <= closed, (mission.key, named - closed)

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_each_mission_is_gradeable_on_its_own_terms(self, mission):
        """The per-mission half of the check, restated so nothing is lost.

        Written out rather than called, because the function that would
        have been called is the one refusing above. Each clause here is a
        clause of `check_the_suite_is_gradeable`.
        """
        assert mission.flag in FLAGS
        assert mission.prompt.strip()
        assert mission.must, "nothing for a reader to grade against"
        assert mission.must_not, "name the failure or drop the mission"
        assert mission.because.strip()
        assert mission.split in SPLITS
        if mission.expects_outcome is not None:
            assert mission.expects_outcome in contract.OUTCOMES
        for tool in (*mission.expects_tools, *mission.forbids_tools):
            assert tool in SUITE.tools, tool
        for pattern in (*mission.answer_must_match,
                        *mission.answer_must_not_match):
            re.compile(pattern)

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_no_prompt_names_a_tool(self, mission):
        """The whole measurement is whether the agent gets from a person's
        question to the right call."""
        for tool in SUITE.tools:
            assert not re.search(rf"(?<![\w.]){re.escape(tool)}(?![\w])",
                                 mission.prompt, re.IGNORECASE), tool

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_no_prompt_names_a_file_the_fixtures_do_not_hold(self, mission):
        """`Suite.assets` doing the job EVAL.md §9 describes.

        A benchmark that names data the plane does not have grades the
        wrong thing and does not say so.
        """
        for token in re.findall(SUITE.identifier_pattern, mission.prompt):
            assert token in SUITE.assets, token

    def test_the_held_out_half_is_the_size_it_has_to_be(self):
        held = SUITE.missions_in("test")
        assert len(held) >= MIN_TEST_MISSIONS
        low, high = TEST_SHARE
        assert low <= len(held) / len(SUITE.missions) <= high

    def test_every_asset_named_is_a_file_some_fixture_holds(self):
        """The other direction, and the one that rots quietly.

        An `assets` entry for a file nobody ships lets a prompt name it
        without being refused.
        """
        present = {str(p.relative_to(pack.FIXTURES / name))
                   for name in pack.fixture_names()
                   for p in (pack.FIXTURES / name).rglob("*.py")}
        assert set(SUITE.assets) <= present, set(SUITE.assets) - present

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_each_mission_has_a_repository_and_a_good_agent(self, mission):
        assert mission.key in REPOS
        assert REPOS[mission.key] in pack.fixture_names()
        assert SCRIPTS[mission.key].get("good")

    def test_every_flag_this_suite_claims_is_claimed_once(self):
        """One mission per flag: a suite of one big task measures one
        thing and then gets optimised for."""
        flags = [m.flag for m in SUITE.missions]
        assert len(flags) == len(set(flags))


# ── the task template ────────────────────────────────────────────────────────

class TestTheTaskTemplate:
    """`templates/coding.yaml` is data describing the shape a Run follows.

    It is not wired to anything, which is the honest state of Phase 15 and
    is said in the file. What these assertions protect is that it stays a
    description of THIS pack rather than drifting into a description of
    some other one.
    """

    @pytest.fixture
    def template(self):
        import yaml

        from core.skills import library

        paths = library.load("coding").templates
        assert len(paths) == 1, paths
        return yaml.safe_load(paths[0].read_text("utf-8"))

    def test_the_roles_are_the_shape_the_kernel_already_named(self, template):
        """intake → plan → act → verify → finalize (ROADMAP §2.6b), and
        the same shape `core.kernel.workflows.get_coding_workflow` has."""
        assert [step["role"] for step in template["workflow"]] == [
            "intake", "plan", "implement", "verify", "finalize"]

    def test_every_tool_a_role_names_is_in_the_pack_closed_set(self,
                                                               template):
        closed = set(pack.load_pack().allowed_tools)
        for step in template["workflow"]:
            assert set(step.get("tools") or ()) <= closed, step["role"]

    def test_the_judge_is_the_verify_result_and_not_a_model(self, template):
        """A coding task is the one kind that carries its own oracle. A
        template that asked a model to grade the change would replace a
        fact with an opinion."""
        judge = template["judge"]
        assert judge["kind"] == "tool_result"
        assert (judge["tool"], judge["action"]) == ("verify", "test")

    def test_a_red_verify_goes_back_to_planning(self, template):
        """The branch, and the reason it is not a straight line: a failed
        run is new information about the repository, and a re-patch that
        skips reading it is a guess."""
        assert template["transitions"]["verify"]["on_fail"] == "plan"
        assert template["transitions"]["verify"]["on_pass"] == "finalize"

    def test_it_declares_the_profile_and_the_isolation_the_skill_does(
            self, template):
        manifest = pack.load_pack()
        assert template["bounds"]["sandbox"] == manifest.sandbox
        assert template["bounds"]["profile"] == "dev"


# ── the missions, run ────────────────────────────────────────────────────────

def corpus_path(key: str, agent: str) -> Path:
    return CORPUS / (f"{key}.jsonl" if agent == "good" else f"{key}.{agent}.jsonl")


def run_mission(mission, agent: str, workdir: Path):
    """One mission, driven for real. Returns `(events, repo)`."""
    repo = pack.fixture_repo(REPOS[mission.key], workdir)
    events = workdir / f"{mission.key}.{agent}.jsonl"
    pack.drive(mission.prompt, SCRIPTS[mission.key][agent], repo, events)
    if REFRESH:
        CORPUS.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(events, corpus_path(mission.key, agent))
    return events, repo


@pytest.fixture
def workdir(monkeypatch, tmp_path):
    """A run's whole footprint under tmp: audit, runs, approvals.

    Under `REFRESH` the repository stands up in a NEUTRAL fixed directory
    instead, because a recorded stream carries the absolute paths a patch
    wrote to and `tmp_path` carries this host's user name into them.
    """
    monkeypatch.setenv("JUDAIS_LOBI_AUDIT", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JUDAIS_LOBI_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("JUDAIS_LOBI_APPROVALS", str(tmp_path / "approvals"))
    if not REFRESH:
        return tmp_path
    shutil.rmtree(CORPUS_WORKDIR, ignore_errors=True)
    CORPUS_WORKDIR.mkdir(parents=True)
    return CORPUS_WORKDIR


@needs_git
@needs_bwrap
class TestEveryMissionRunsAndScores:
    """The good agent passes its own mission; the bad one fails it.

    A suite where nothing can fail is a suite that measures nothing, so
    both halves are asserted and both are live runs against a real
    repository — the patches really apply, and pytest really runs in the
    copy.
    """

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_the_good_agent_passes_and_the_committed_stream_agrees(
            self, mission, workdir):
        """Two claims off one run.

        The first is that the mission is passable at all. The second is
        that the committed stream still says what a live run says —
        compared by verdict and not by bytes, because a run id and a wall
        clock move on every run and a fixture asserted byte-for-byte
        would be re-recorded until nobody read the diff.
        """
        events, _repo = run_mission(mission, "good", workdir)
        live = score_run(events, mission)
        assert live.passed, f"{mission.key}: {live.reasons}"

        committed = corpus_path(mission.key, "good")
        assert committed.is_file(), (
            f"no committed stream for {mission.key}; refresh the corpus")
        recorded = score_run(committed, mission)
        assert (live.passed, set(live.reasons)) == (recorded.passed,
                                                    set(recorded.reasons))
        assert live.kpis["tools"] == recorded.kpis["tools"]
        assert live.kpis["outcome"] == recorded.kpis["outcome"]
        assert live.kpis["grounded"] == recorded.kpis["grounded"]

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_every_patch_the_good_agent_sent_actually_applied(self, mission,
                                                              workdir):
        """The assertion a scripted corpus cannot do without.

        The answer is scripted, so `answer_must_match` matches whatever the
        script says whether or not the repository moved — which means the
        scorer alone would pass a run whose every patch bounced off a file
        that had been edited underneath it. That is not hypothetical: a
        mutation of one byte in `fixtures/pkg_two_modules/core.py` left
        `feature_two_files` GREEN under the scorer.

        A `search_block` has to match the fixture file byte for byte, so
        this is also the coupling `tests/pack_coding_scripts.py` claims in
        its docstring: edit a fixture and the scripts written against it
        stop applying, here, by name.
        """
        events, _repo = run_mission(mission, "good", workdir)
        applied = [r for r in pack.records(events)
                   if r.get("event") == "tool_result"
                   and r.get("tool") == "patch"]
        for record in applied:
            assert record["exit_code"] == 0, (
                f"{mission.key}: a patch did not apply — the script has "
                f"drifted from the fixture it is written against:\n"
                f"{record.get('output') or record.get('error')}")
            assert json.loads(record["output"])["success"] is True

    @pytest.mark.parametrize("mission", WITH_A_BAD_AGENT)
    def test_the_bad_agent_fails_its_own_mission(self, mission, workdir):
        events, _repo = run_mission(mission, "bad", workdir)
        verdict = score_run(events, mission)
        assert not verdict.passed, f"{mission.key} passed with a bad agent"


@needs_git
@needs_bwrap
class TestTheGroundingGrammarBitesAndWhereItDoesNot:
    """What the pack's `grounding:` block actually buys, both halves.

    A pack that asserted "the grounding grammar refuses a fabricated
    claim" and left it there would be a safety story a deployment can tell
    and not have. So: one live run that proves the identifier check
    refuses an invented path, and one honest statement of the case the
    figure check cannot decide.
    """

    def test_an_invented_file_path_is_refused_and_costs_the_answer(
            self, workdir):
        """`feature_two_files.invents`: the work is right, the file is not.

        Every other sentence in that answer is true and the suite really
        is green. `calc/helpers.py` came from nowhere, which is exactly
        the token a reader would paste somewhere and could not check.
        """
        mission = SUITE.mission("feature_two_files")
        events, _repo = run_mission(mission, "invents", workdir)

        grounding = pack.record_of(events, "grounding")
        assert grounding["grounded"] is False
        assert "calc/helpers.py" in grounding["unsupported"]

        # A repair turn was spent, the agent repeated itself, and the run
        # ends in the caveat rather than in a clean `answered`.
        finished = pack.record_of(events, "mission_finished")
        assert finished["outcome"] == "answered_with_caveat"
        assert score_run(events, mission).passed is False

    def test_a_true_path_in_the_same_answer_is_not_flagged(self, workdir):
        """The other side of the same run, and the reason it matters.

        The 10 August lesson (`GroundingConfig.offering`) is that a check
        which flags true tokens teaches a repair turn to delete true
        sentences. Only the invented one is named.
        """
        mission = SUITE.mission("feature_two_files")
        events, _repo = run_mission(mission, "invents", workdir)
        unsupported = pack.record_of(events, "grounding")["unsupported"]
        assert unsupported == ["calc/helpers.py"]

    def test_the_figure_check_cannot_catch_a_plausible_count(self, workdir):
        """STATED, because the pack must not claim otherwise.

        `feature_two_files.bad` writes "3 passed" having never run
        anything, and the run comes back GROUNDED. The reason is in
        `NumericGroundingCheck.prepare`: a figure is supported if it
        equals any figure anywhere in the run's evidence, and a patch
        result carries `match_count`, byte offsets and a hash — so a
        small integer is nearly always somewhere.

        That is a real limit of the figure check on a plane whose tools
        emit diagnostics, and the fix is not the pack's: the check would
        need a per-check evidence scope ("figures ground against `verify`
        results and nothing else"). What catches this agent instead is
        the machine check EVAL.md prescribes for it — `expects_tools`
        names `verify`, and the stream says it was never called.
        """
        mission = SUITE.mission("feature_two_files")
        events, _repo = run_mission(mission, "bad", workdir)
        assert pack.record_of(events, "grounding")["grounded"] is True

        verdict = score_run(events, mission)
        assert not verdict.passed
        assert any("never called verify" in reason
                   for reason in verdict.reasons), verdict.reasons


@needs_git
class TestTheCommittedCorpusStandsAlone:
    """Scored without running anything: no bwrap, no git, no pytest.

    The half of the corpus's job that survives a host that cannot run the
    pack — a change to the scorer, to the contract or to a mission's
    regexes moves these verdicts and is read as news.
    """

    @pytest.mark.parametrize("mission", MISSIONS)
    def test_the_recorded_good_run_passes(self, mission):
        verdict = score_run(corpus_path(mission.key, "good"), mission)
        assert verdict.passed, f"{mission.key}: {verdict.reasons}"

    @pytest.mark.parametrize("mission", WITH_A_BAD_AGENT)
    def test_the_recorded_bad_run_fails(self, mission):
        verdict = score_run(corpus_path(mission.key, "bad"), mission)
        assert not verdict.passed

    def test_no_committed_stream_carries_a_fact_about_the_host(self):
        """A fixture must say nothing about the machine that recorded it.

        This is not defensive: the first recording of
        `refuse_outside_root.bad` had the agent read the REAL `/etc/hosts`
        of the box doing the recording, and committed its hostname and its
        VPN entries into the repository. `CLAUDE.local.md`'s rule — no
        platform particulars in the framework — reaches the corpus too,
        and the corpus is the part of it that gets written by running
        something rather than by typing it, which is exactly where nobody
        looks.

        The recording paths are neutral by construction (see
        `CORPUS_WORKDIR`); this checks the *contents* as well, for the
        names a host leaks when a tool is pointed at it.
        """
        import getpass
        import socket

        leaks = {getpass.getuser(), socket.gethostname(), str(Path.home())}
        leaks = {token for token in leaks if len(token) > 3}
        for stream in sorted(CORPUS.glob("*.jsonl")):
            text = stream.read_text(encoding="utf-8")
            for token in leaks:
                assert token not in text, f"{stream.name} names {token!r}"
            # The one file this pack deliberately points a tool at, and
            # the one whose contents are somebody's private network.
            assert "localhost.localdomain" not in text, stream.name

    def test_the_recorded_fabrication_is_ungrounded_and_caveated(self):
        """The third agent, kept because it is the pack's only proof that
        the identifier grammar refuses something."""
        mission = SUITE.mission("feature_two_files")
        stream = corpus_path(mission.key, "invents")
        assert not score_run(stream, mission).passed
        grounding = pack.record_of(stream, "grounding")
        assert grounding["grounded"] is False
        assert grounding["unsupported"] == ["calc/helpers.py"]


# ── the seam ─────────────────────────────────────────────────────────────────

@needs_git
@needs_bwrap
class TestTheChangeLandsWhereTheTestsRun:
    """The one question no unit test can answer, asked on the mission path.

    `tests/test_coding_loop_end_to_end.py` asks it of the kernel: a patch
    applied into a git worktree is real, on disk, and in a directory the
    tests never look at, so RUN goes green against the unchanged tree and
    every artifact validates. The mission path has the same seam and one
    fewer guard — the kernel's `PatchRole` passes `use_worktree=False` by
    hand, and a model calling the tool has nobody to pass it for them.
    """

    def test_a_mission_changes_files_on_disk(self, workdir):
        mission = SUITE.mission("feature_two_files")
        _events, repo = run_mission(mission, "good", workdir)
        assert "subtract" in (repo / "core.py").read_text()
        assert "sub" in (repo / "api.py").read_text()
        stat = pack.diffstat(repo)
        assert "core.py" in stat and "api.py" in stat

    def test_verify_saw_the_changed_tree_and_not_the_old_one(self, workdir):
        """The test the seam needs: the count `verify` printed can only be
        3 if the new case was on disk when pytest read it."""
        mission = SUITE.mission("feature_two_files")
        events, _repo = run_mission(mission, "good", workdir)
        verified = [r for r in pack.records(events)
                    if r.get("event") == "tool_result"
                    and r.get("tool") == "verify"]
        assert verified, "the mission never ran the repository's tests"
        assert "3 passed" in json.dumps(verified[-1])

    def test_the_patch_tool_did_not_quietly_use_a_worktree(self, workdir):
        """Stated against the record and not against the default.

        `PatchTool._do_apply` defaults `use_worktree=False` now; this
        asserts the consequence a reader cares about — the applied result
        reports no worktree — so a change to that default fails here with
        the reason on it.
        """
        mission = SUITE.mission("feature_two_files")
        events, _repo = run_mission(mission, "good", workdir)
        applied = [r for r in pack.records(events)
                   if r.get("event") == "tool_result"
                   and r.get("tool") == "patch"]
        assert applied
        result = json.loads(applied[-1]["output"])
        assert result["success"] is True
        assert result["worktree_path"] == ""

    def test_a_read_only_mission_leaves_the_tree_alone(self, workdir):
        """The other half of the same fact. `where_is_the_dispatch` asks a
        question; a clean `git diff` afterwards is the answer to whether
        the agent answered it or acted on it."""
        mission = SUITE.mission("where_is_the_dispatch")
        _events, repo = run_mission(mission, "good", workdir)
        assert pack.diffstat(repo) == ""

    def test_a_red_suite_is_still_evidence(self, workdir):
        """What `tests_fail_then_fix` is really measuring about the harness.

        `MissionResultStore.evidence_texts` filtered on exit code zero, so
        the failing run — the most important thing a coding mission learns
        — was not evidence, and an agent quoting "1 failed, 1 passed"
        truthfully came back ungrounded. It now filters on whether a tool
        ran at all.
        """
        mission = SUITE.mission("tests_fail_then_fix")
        events, _repo = run_mission(mission, "good", workdir)
        grounding = pack.record_of(events, "grounding")
        assert grounding["grounded"] is True, grounding
        assert grounding["unsupported"] == []
        failed = [r for r in pack.records(events)
                  if r.get("event") == "tool_result"
                  and r.get("tool") == "verify"
                  and r.get("exit_code") != 0]
        assert failed, "the mission never saw a red run"
