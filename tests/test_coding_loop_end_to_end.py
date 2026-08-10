# tests/test_coding_loop_end_to_end.py — the loop against a real repository

"""The test the suite did not have, and the reason the bug survived it.

Every piece of the coding pipeline was covered and green: the patch
matcher, the applicator, ``PatchEngine.apply``, the ToolBus, each phase
role, the CompositeJudge and all three of its tiers. 1518 tests passed.
And ``PatchRole`` produced a schema-valid ``PatchSet`` that **nothing
dispatched** — ``PatchEngine.apply`` was called from no role at all — so
``RunRole`` ran the suite against an unchanged tree, ``state.artifacts
["_diff"]`` was read and never written, and ``LLMReviewTier`` returned
UNKNOWN on every live run. ``CompositeJudge`` removes an UNKNOWN tier's
weight from the denominator, which is the right thing to do for a
reviewer that is genuinely unavailable and is precisely what made this
absence unobservable: the composite came out at the same number it
would have reached if the reviewer had read the diff and approved it.

INTAKE → COMPLETED, every artifact valid, nothing connected to anything.

No unit test can see that, because there is nothing wrong with any
unit. What is wrong is a *seam*, and a seam is only visible from both
sides at once. So this module runs the real orchestrator, with the real
``PatchTool`` and the real ``VerifyTool``, against a git repository on
disk, and asks the three questions the seam answers:

1. did a file on disk actually change;
2. did the tests run against the changed tree, or against the old one;
3. did the reviewer read a real diff, or was it handed nothing and
   politely excused?

The fixture repository's check script is written so that the second
question has a different answer from the first. It reads the source
file and exits non-zero unless it holds the *new* value, and it prints
what it read. A pipeline that patched a worktree, or a scratch copy, or
nothing at all, still leaves the original file for the checker to find.
"""

import json
import shutil
import subprocess

import pytest

from core.contracts.schemas import PolicyPack
from core.judge.models import TierVerdict
from core.kernel.budgets import BudgetConfig
from core.kernel.orchestrator import Orchestrator
from core.kernel.roles import LLMRoleDispatcher
from core.kernel.state import Phase
from core.kernel.workflows import get_coding_workflow
from core.sessions.manager import SessionManager
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import (
    PATCH_DESCRIPTOR,
    REPO_MAP_DESCRIPTOR,
    VERIFY_DESCRIPTOR,
    ToolDescriptor,
)
from core.tools.patch_tool import PatchTool
from core.tools.verify_tools import VerifyTool

pytestmark = pytest.mark.skipif(
    not shutil.which("git"), reason="git not available",
)


# ---------------------------------------------------------------------------
# The fixture repository
# ---------------------------------------------------------------------------

OLD_LINE = 'GREETING = "hello"\n'
NEW_LINE = 'GREETING = "hello, world"\n'

#: Reads the file from disk and reports what is actually there. The
#: pipeline's RUN phase shells out to this, so its exit code is a fact
#: about the tree and not about anything the model said.
CHECK_SCRIPT = '''\
import sys
sys.path.insert(0, ".")
import greeting
print("GREETING IS", repr(greeting.GREETING))
sys.exit(0 if greeting.GREETING == "hello, world" else 1)
'''


@pytest.fixture
def fixture_repo(tmp_path):
    repo = tmp_path / "fixture_repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)

    git("init")
    git("config", "user.email", "fixture@example.com")
    git("config", "user.name", "Fixture")
    (repo / "greeting.py").write_text(OLD_LINE)
    (repo / "check.py").write_text(CHECK_SCRIPT)
    git("add", ".")
    git("commit", "-m", "initial")
    return repo


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

class ScriptedModel:
    """Answers each phase, and reviews the diff when asked to review.

    The review turn is not a phase — ``LLMReviewTier`` prompts through
    the role context directly — so it is recognised by its own prompt.
    Every turn is recorded, which is how a test can assert the reviewer
    was shown the diff rather than merely asked for an opinion.
    """

    REVIEW_MARKER = "You are reviewing a proposed code change"

    def __init__(self, patch_search=OLD_LINE, patch_replace=NEW_LINE,
                 patches=None):
        self._patches = patches if patches is not None else [{
            "file_path": "greeting.py",
            "search_block": patch_search,
            "replace_block": patch_replace,
            "action": "modify",
        }]
        self.turns = []
        self.reviewed = ""

    def __call__(self, messages):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        self.turns.append({"system": system, "user": user})

        if self.REVIEW_MARKER in system:
            self.reviewed = user
            return json.dumps({
                "score": 0.9, "verdict": "pass",
                "concerns": ["the greeting is not localised"],
            })
        for phase, reply in self._by_phase().items():
            if f"Phase {phase}." in system:
                return reply
        return "I have no answer for that."

    def _by_phase(self):
        return {
            "INTAKE": json.dumps({
                "task_id": "t1", "description": "extend the greeting",
                "acceptance_criteria": ["check.py exits 0"],
            }),
            "CONTRACT": json.dumps({
                "task_id": "t1", "description": "extend the greeting",
            }),
            "PLAN": json.dumps({
                "task_id": "t1",
                "steps": [{"description": "widen GREETING",
                           "target_file": "greeting.py", "action": "modify"}],
            }),
            "RETRIEVE": json.dumps({
                "task_id": "t1", "repo_map_excerpt": "greeting.py",
                "symbols": [],
            }),
            "PATCH": json.dumps({"task_id": "t1", "patches": self._patches}),
            "FIX": json.dumps({"task_id": "t1", "patches": self._patches}),
        }


# ---------------------------------------------------------------------------
# The bus: the real patch engine and the real verifier
# ---------------------------------------------------------------------------

def make_real_bus(repo):
    """Every tool the coding roles dispatch, aimed at the fixture repo.

    ``patch`` and ``verify`` are the real classes — a double for either
    would put the seam under test back behind a stub. ``repo_map`` is a
    double because the map is not what is on trial here and building a
    real one costs a tree-sitter parse per test.
    """
    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=[
            "fs.read", "fs.write", "git.read", "git.write", "verify.run",
        ])))

    bus.register(PATCH_DESCRIPTOR, PatchTool(repo_path=str(repo)))
    bus.register(VERIFY_DESCRIPTOR, VerifyTool(config={"verification": {
        # Run the checker inside the fixture repo. What it reports is
        # whatever is on disk at the moment RUN dispatches.
        "test": f"cd {repo} && python check.py",
        "lint": "true",
    }}))
    bus.register(
        ToolDescriptor(tool_name="repo_map",
                       required_scopes=REPO_MAP_DESCRIPTOR.required_scopes,
                       action_scopes=dict(REPO_MAP_DESCRIPTOR.action_scopes),
                       description="Repository map."),
        lambda action=None, **kw: (
            0, json.dumps({"excerpt": "greeting.py\ncheck.py",
                           "total_files": 2}), ""),
    )
    return bus


def run_pipeline(repo, model, budget=None):
    """Run the whole workflow and hand back the state and the session.

    A real :class:`SessionManager` because the phase artifacts are what
    the run is judged on and they are only written when one is present —
    and because it is the manager that takes the ``pre_PATCH`` checkpoint
    the patch application relies on for recovery.
    """
    workflow = get_coding_workflow()
    bus = make_real_bus(repo)
    sessions = SessionManager(base_dir=repo.parent / "sessions_root")
    orchestrator = Orchestrator(
        dispatcher=LLMRoleDispatcher(chat_fn=model, tool_bus=bus,
                                     workflow=workflow),
        workflow=workflow,
        tool_bus=bus,
        session_manager=sessions,
        budget=budget or BudgetConfig(),
    )
    return orchestrator.run("extend the greeting"), sessions


def _judge_report(sessions):
    from core.judge.models import JudgeReport

    artifact = sessions.load_latest_artifact("CRITIQUE")
    assert artifact is not None, "CRITIQUE wrote no artifact"
    return JudgeReport.model_validate(artifact)


def _tier(report, name):
    return next(t for t in report.tier_results if t.tier_name == name)


# ---------------------------------------------------------------------------
# The three questions
# ---------------------------------------------------------------------------

class TestTheLoopReachesTheRepository:
    def test_a_file_on_disk_actually_changed(self, fixture_repo):
        """The patch was applied, not merely produced.

        Before the fix this assertion failed while the run reported
        COMPLETED: `PatchSet` validated, no role dispatched it, and
        greeting.py still said "hello".
        """
        model = ScriptedModel()
        state, _sessions = run_pipeline(fixture_repo, model)

        assert (fixture_repo / "greeting.py").read_text() == NEW_LINE
        assert state.current_phase == Phase.COMPLETED

    def test_the_tests_ran_against_the_changed_tree(self, fixture_repo):
        """RUN's exit code is about this tree, and it says so out loud.

        The checker prints what it read. Asserting on that, and not only
        on the exit code, is what separates "the tests passed" from "the
        tests passed *because the change was there*" — a suite run
        against an unchanged tree, or against a worktree the patch went
        to instead, would print the old value and still be a real
        subprocess with a real exit code.
        """
        model = ScriptedModel()
        state, _sessions = run_pipeline(fixture_repo, model)

        report = state.artifacts["_run_report"]
        assert report.passed is True
        assert report.exit_code == 0
        assert "GREETING IS 'hello, world'" in report.stdout
        assert "'hello'\n" not in report.stdout

    def test_the_reviewer_read_a_real_diff(self, fixture_repo):
        """The review tier returns a verdict, not UNKNOWN.

        Two independent absences produced that UNKNOWN: nothing wrote
        `_diff`, and `CritiqueRole` built a `CompositeJudge()` whose
        `LLMReviewTier` had no way to reach a model. Either one alone is
        enough to make the tier silent, and `CompositeJudge` rescales a
        silent tier away, so neither showed up in a score.
        """
        model = ScriptedModel()
        state, sessions = run_pipeline(fixture_repo, model)

        assert "_diff" in state.artifacts
        diff = state.artifacts["_diff"]
        assert "greeting.py" in diff
        assert "+GREETING" in diff

        review = _tier(_judge_report(sessions), "llm_review")
        assert review.verdict is not TierVerdict.UNKNOWN
        assert review.verdict is TierVerdict.PASS
        assert review.score == 0.9
        assert "localised" in review.details

        # And it was shown the change, not asked to opine on nothing.
        assert "+GREETING" in model.reviewed

    def test_the_diff_is_the_change_this_run_made(self, fixture_repo):
        """Not whatever else the working tree happened to be holding.

        A bare `git diff` in a dirty repository reports somebody else's
        edits as though this run had made them, and the reviewer would
        be judging a change the pipeline never proposed.
        """
        (fixture_repo / "unrelated.py").write_text("PRE_EXISTING = 1\n")
        subprocess.run(["git", "add", "unrelated.py"], cwd=fixture_repo,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "unrelated"], cwd=fixture_repo,
                       capture_output=True)
        (fixture_repo / "unrelated.py").write_text("PRE_EXISTING = 999\n")

        state, _sessions = run_pipeline(fixture_repo, ScriptedModel())

        assert "greeting.py" in state.artifacts["_diff"]
        assert "unrelated" not in state.artifacts["_diff"]


class StagedModel(ScriptedModel):
    """Patches wrong first, then right — the FIX loop, end to end."""

    WRONG = 'GREETING = "wrong"\n'

    def __init__(self):
        super().__init__()
        self.patch_turns = 0
        self.fixes = 0

    def _by_phase(self):
        if self.patch_turns == 0:
            patches = [{"file_path": "greeting.py", "search_block": OLD_LINE,
                        "replace_block": self.WRONG, "action": "modify"}]
        else:
            patches = [{"file_path": "greeting.py", "search_block": self.WRONG,
                        "replace_block": NEW_LINE, "action": "modify"}]
        return {**super()._by_phase(),
                "PATCH": json.dumps({"task_id": "t1", "patches": patches})}

    def __call__(self, messages):
        system = messages[0]["content"]
        if "Phase PATCH." in system:
            reply = super().__call__(messages)
            self.patch_turns += 1
            return reply
        if "Phase FIX." in system:
            self.fixes += 1
            return "check.py wants 'hello, world' and greeting.py says 'wrong'."
        return super().__call__(messages)


class TestTheFixLoopSeesTheTreeChange:
    def test_a_wrong_patch_goes_red_then_a_right_one_goes_green(
        self, fixture_repo,
    ):
        """The same command, twice, with a different answer each time.

        This is the sharpest form of question two. RUN dispatches one
        fixed command; nothing about it changes between the two calls.
        The only thing that differs is what is on disk. A pipeline whose
        patches never landed could not produce a red RUN followed by a
        green one, because there would be nothing for the second patch
        to change.
        """
        model = StagedModel()
        state, _sessions = run_pipeline(
            fixture_repo, model, budget=BudgetConfig(max_total_iterations=30))

        assert state.current_phase == Phase.COMPLETED
        assert model.patch_turns == 2
        assert model.fixes == 1
        assert (fixture_repo / "greeting.py").read_text() == NEW_LINE

        # The second patch searched for text the first one wrote, so the
        # first one must really have written it.
        assert state.artifacts["_run_report"].passed is True
        assert "GREETING IS 'hello, world'" in state.artifacts["_run_report"].stdout

        # And the reviewer was shown a real diff on the way through.
        # (Not the *last* CRITIQUE: that phase runs before RUN, so on the
        # second lap it scores the first lap's failed RunReport, the test
        # tier short-circuits and the review tier is SKIPPED. See the
        # note in the audit — CRITIQUE judging the previous iteration's
        # result is its own question and not this one.)
        assert "+GREETING" in model.reviewed


class TestTheLoopRefusesWhenItCannotReachTheRepository:
    def test_a_patch_that_does_not_match_fails_the_phase(self, fixture_repo):
        """The worst case, and the one that used to succeed.

        A search block matching nothing is the ordinary way a model gets
        a patch wrong. It used to validate as a `PatchSet`, succeed, and
        carry the run to a green RUN against the untouched file.
        """
        model = ScriptedModel(patch_search='GREETING = "nonexistent"\n')
        state, _sessions = run_pipeline(
            fixture_repo, model, budget=BudgetConfig(max_phase_retries=1))

        assert state.current_phase == Phase.HALTED
        assert "PATCH" in state.halt_reason
        assert (fixture_repo / "greeting.py").read_text() == OLD_LINE

    def test_an_empty_patch_set_is_not_a_change(self, fixture_repo):
        """Zero patches validates against the schema and alters nothing."""
        state, _sessions = run_pipeline(
            fixture_repo, ScriptedModel(patches=[]),
            budget=BudgetConfig(max_phase_retries=1))

        assert state.current_phase == Phase.HALTED
        assert (fixture_repo / "greeting.py").read_text() == OLD_LINE
