# tests/test_fs_root.py — the mission root, enforced rather than asked for

"""The in-process tools are confined to the mission's working directory.

`bwrap` isolates a **subprocess**. `FsTool` is `pathlib` in this
interpreter and `PatchTool` writes through the patch engine, so a mission
under `--profile dev` could write anywhere the user can, sandbox or no
sandbox — and the coding pack's `refuse_outside_root` mission graded
whether the *agent* honoured a sentence in `SKILL.md` about it. That is a
measurement of the model. This module is the property.

The rule and its wording live in `core/tools/root.py`; four tools ask it
the same question, which is what keeps them from having four ideas about
what `..` means. Two halves are asserted here: a path outside the root is
refused **as a tool result** — exit code 1, on the stream, readable by the
model, because the scope was granted and it is the PATH that is out of
bounds — and a tool with no root behaves exactly as it did, which is what
chat is.
"""

import json
import os
from pathlib import Path

import pytest

from core.contracts.schemas import PolicyPack
from core.tools import Tools
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import FS_DESCRIPTOR
from core.tools.fs_tools import FsTool
from core.tools.git_tools import GitTool
from core.tools.patch_tool import PatchTool
from core.tools.repo_map_tool import RepoMapTool
from core.tools.root import MissionRoot, rooted
from core.tools.sandbox import NoneSandbox


@pytest.fixture
def root_dir(tmp_path, monkeypatch):
    """A mission's working directory, and the process standing in it.

    The two are one fact on the mission path — the CLI takes the root
    from the working directory — and a fixture that let them differ would
    be testing an arrangement no deployment has.
    """
    (tmp_path / "inside.txt").write_text("in\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def outside(tmp_path_factory):
    """Somewhere the mission was not pointed at."""
    other = tmp_path_factory.mktemp("elsewhere")
    (other / "secret.txt").write_text("not yours\n", encoding="utf-8")
    return other


class TestWhatInsideMeans:
    """`MissionRoot`, asked directly. Four ways out, one answer."""

    def test_the_root_itself_is_inside_it(self, root_dir):
        assert MissionRoot(root_dir).holds(root_dir)

    def test_a_path_under_it_is_inside(self, root_dir):
        assert MissionRoot(root_dir).holds(root_dir / "sub" / "new.txt")

    def test_an_absolute_path_elsewhere_is_not(self, root_dir, outside):
        assert not MissionRoot(root_dir).holds(outside / "secret.txt")

    def test_a_dot_dot_escape_is_not(self, root_dir):
        assert not MissionRoot(root_dir).holds("../../etc/hosts")

    def test_a_symlink_out_of_the_tree_is_not(self, root_dir, outside):
        link = root_dir / "way_out"
        link.symlink_to(outside)
        assert not MissionRoot(root_dir).holds(link / "secret.txt")

    def test_a_symlink_out_is_refused_even_where_nothing_exists_yet(
            self, root_dir, outside):
        """The case a `strict` resolution misses: a mission writes
        through a link into a directory it is about to create."""
        link = root_dir / "way_out"
        link.symlink_to(outside)
        assert not MissionRoot(root_dir).holds(link / "new" / "file.txt")

    def test_a_sibling_with_the_same_prefix_is_not_inside(self, tmp_path):
        """String containment is not path containment: `/tmp/x-2` is not
        under `/tmp/x`."""
        (tmp_path / "x").mkdir()
        (tmp_path / "x-2").mkdir()
        assert not MissionRoot(tmp_path / "x").holds(tmp_path / "x-2" / "f")

    def test_the_refusal_names_the_root_and_the_path(self, root_dir):
        refusal = MissionRoot(root_dir).refusal("../../etc/hosts")
        assert f"outside the mission root {root_dir}" in refusal
        assert "../../etc/hosts" in refusal
        assert "/etc/hosts" in refusal        # what it resolved to

    def test_no_root_is_no_opinion(self):
        """`rooted(None, ...)` is chat, and chat reaches what it is told
        to reach."""
        assert rooted(None, "/etc/hosts") is None


class TestTheFilesystemTool:
    def test_a_read_inside_the_root_works(self, root_dir):
        assert FsTool(root=MissionRoot(root_dir))(
            "read", "inside.txt") == (0, "in\n", "")

    def test_an_absolute_path_outside_is_refused(self, root_dir, outside):
        rc, out, err = FsTool(root=MissionRoot(root_dir))(
            "read", str(outside / "secret.txt"))
        assert rc == 1
        assert out == ""
        assert "outside the mission root" in err

    def test_a_dot_dot_escape_is_refused(self, root_dir, outside):
        rc, _out, err = FsTool(root=MissionRoot(root_dir))(
            "read", os.path.join("..", outside.name, "secret.txt"))
        assert rc == 1
        assert "outside the mission root" in err

    def test_a_write_outside_writes_nothing(self, root_dir, outside):
        target = outside / "planted.txt"
        rc, _out, err = FsTool(root=MissionRoot(root_dir))(
            "write", str(target), content="x")
        assert rc == 1
        assert "outside the mission root" in err
        assert not target.exists()

    def test_a_delete_outside_deletes_nothing(self, root_dir, outside):
        doomed = outside / "secret.txt"
        rc, _out, _err = FsTool(root=MissionRoot(root_dir))(
            "delete", str(doomed))
        assert rc == 1
        assert doomed.exists()

    @pytest.mark.parametrize("action", ["read", "write", "delete", "list",
                                        "stat"])
    def test_every_action_is_confined(self, root_dir, outside, action):
        """Not one guard per handler: every action this tool has takes a
        path as its first argument, and five guards is four places to
        forget one."""
        rc, _out, err = FsTool(root=MissionRoot(root_dir))(
            action, str(outside))
        assert rc == 1
        assert "outside the mission root" in err

    def test_chat_is_unrooted_and_unchanged(self, root_dir, outside):
        """`lobi --shell` is a person asking for a file, and the file is
        where they said it is."""
        rc, out, _err = FsTool()("read", str(outside / "secret.txt"))
        assert rc == 0
        assert out == "not yours\n"


class TestThePatchTool:
    def make_patch(self, path: str) -> str:
        return json.dumps({"task_id": "t1", "patches": [{
            "file_path": path,
            "search_block": "",
            "replace_block": "planted\n",
            "action": "create",
        }]})

    def test_a_patch_inside_the_root_applies(self, root_dir):
        tool = PatchTool(repo_path=str(root_dir),
                         root=MissionRoot(root_dir))
        rc, out, _err = tool("apply", patch_set_json=self.make_patch("new.py"))
        assert rc == 0, out
        assert (root_dir / "new.py").read_text() == "planted\n"

    def test_a_patch_outside_the_root_is_refused(self, root_dir, outside):
        target = outside / "planted.py"
        tool = PatchTool(repo_path=str(root_dir),
                         root=MissionRoot(root_dir))
        rc, _out, err = tool("apply",
                             patch_set_json=self.make_patch(str(target)))
        assert rc == 1
        assert "outside the mission root" in err
        assert not target.exists()

    def test_validate_refuses_it_too(self, root_dir, outside):
        """A dry run that reported a clean match for a file the apply
        would refuse teaches the model to try the apply."""
        tool = PatchTool(repo_path=str(root_dir),
                         root=MissionRoot(root_dir))
        rc, _out, err = tool(
            "validate",
            patch_set_json=self.make_patch(str(outside / "planted.py")))
        assert rc == 1
        assert "outside the mission root" in err

    def test_one_bad_file_refuses_the_whole_set(self, root_dir, outside):
        """A patch set is one call because a half-applied change is a
        repository nobody asked for; refusing it halfway through would be
        exactly that."""
        both = json.dumps({"task_id": "t1", "patches": [
            {"file_path": "good.py", "search_block": "",
             "replace_block": "ok\n", "action": "create"},
            {"file_path": str(outside / "bad.py"), "search_block": "",
             "replace_block": "no\n", "action": "create"},
        ]})
        tool = PatchTool(repo_path=str(root_dir),
                         root=MissionRoot(root_dir))
        rc, _out, err = tool("apply", patch_set_json=both)
        assert rc == 1
        assert "outside the mission root" in err
        assert not (root_dir / "good.py").exists()

    def test_the_engine_jails_to_the_repository_it_was_built_against(
            self, root_dir, outside):
        """Stated so the root check is not mistaken for the only guard.

        `core.patch.applicator.jail_path` already refuses an absolute
        path, a `..` component and a symlink escape — but it refuses them
        against `repo_path`, the directory this tool was *constructed*
        with, and it says so in the engine's words at the bottom of a JSON
        result. The root is the mission's own answer, checked before the
        engine is reached and refused in the mission's words.
        """
        rc, out, _err = PatchTool(repo_path=str(root_dir))(
            "apply", patch_set_json=self.make_patch(str(outside / "x.py")))
        assert rc == 1
        assert "Absolute path rejected" in out
        assert "outside the mission root" not in out

    def test_the_root_wins_where_the_repository_is_the_wrong_one(
            self, root_dir, outside):
        """The case the engine's jail cannot answer: a tool built against
        a repository that is not this mission's root. `planted.py` is
        relative and perfectly legal to the engine — it resolves inside
        the repo it was handed — and it lands outside the directory the
        mission was given."""
        target = outside / "planted.py"
        tool = PatchTool(repo_path=str(outside), root=MissionRoot(root_dir))
        rc, _out, err = tool("apply",
                             patch_set_json=self.make_patch("planted.py"))
        assert rc == 1
        assert "outside the mission root" in err
        assert not target.exists()

    def test_unrooted_that_same_call_writes(self, root_dir, outside):
        """The mutation for the test above: with no root, the engine's
        jail says yes, because to the engine that IS the repository."""
        target = outside / "planted.py"
        rc, out, _err = PatchTool(repo_path=str(outside))(
            "apply", patch_set_json=self.make_patch("planted.py"))
        assert rc == 0, out
        assert target.exists()


class TestTheGitTool:
    def runner(self):
        calls = []

        def run(cmd, *, shell=False, timeout=None, executable=None):
            calls.append(cmd)
            return 0, "", ""

        run.calls = calls
        return run

    def test_a_repository_outside_the_root_is_refused(self, root_dir,
                                                      outside):
        run = self.runner()
        rc, _out, err = GitTool(subprocess_runner=run,
                                root=MissionRoot(root_dir))(
            "status", repo_path=str(outside))
        assert rc == 1
        assert "outside the mission root" in err
        assert run.calls == [], "the refusal ran git anyway"

    def test_a_repository_inside_it_runs(self, root_dir):
        run = self.runner()
        rc, _out, _err = GitTool(subprocess_runner=run,
                                 root=MissionRoot(root_dir))(
            "status", repo_path=str(root_dir / "sub"))
        assert rc == 0
        assert run.calls

    def test_naming_no_repository_runs_where_the_process_is(self, root_dir):
        """Which, on the mission path, IS the root."""
        run = self.runner()
        rc, _out, _err = GitTool(subprocess_runner=run,
                                 root=MissionRoot(root_dir))("status")
        assert rc == 0
        assert run.calls


class TestTheRepoMapTool:
    def test_a_target_file_outside_the_root_is_refused(self, root_dir,
                                                       outside):
        """Read-only, and rooted anyway: "it only reads" is the argument
        that left `fs read` able to quote a private key into a
        transcript."""
        rc, _out, err = RepoMapTool(repo_path=str(root_dir),
                                    root=MissionRoot(root_dir))(
            "excerpt", target_files=[str(outside / "secret.txt")])
        assert rc == 1
        assert "outside the mission root" in err

    def test_a_file_hint_outside_the_root_is_refused(self, root_dir,
                                                     outside):
        rc, _out, err = RepoMapTool(repo_path=str(root_dir),
                                    root=MissionRoot(root_dir))(
            "symbol", name="thing", file_hint=str(outside / "secret.txt"))
        assert rc == 1
        assert "outside the mission root" in err


class TestWhoHandsTheRootDown:
    """`Tools(root=…)` for a mission, `Tools()` for everything else."""

    def build(self, **kw):
        return Tools(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])),
            sandbox=NoneSandbox(), audit=None, **kw)

    def test_a_rooted_bus_refuses_a_read_outside_it(self, root_dir, outside):
        bus = self.build(root=root_dir).bus
        result = bus.dispatch("fs", action="read",
                              path=str(outside / "secret.txt"))
        assert result.exit_code == 1
        assert "outside the mission root" in result.stderr

    def test_the_refusal_is_the_tools_own_and_not_a_capability_one(
            self, root_dir, outside):
        """The scope WAS granted — this profile really may read files —
        and what is out of bounds is the path. So it comes back as an
        ordinary tool result the model can read and correct, not as "you
        may not read files", which is false and teaches it to stop
        trying.

        `exit_code == -1` is the bus's own number for a call that never
        reached a tool; this one did.
        """
        bus = self.build(root=root_dir).bus
        result = bus.dispatch("fs", action="read",
                              path=str(outside / "secret.txt"))
        assert result.exit_code == 1
        assert result.exit_code != -1
        assert "capability" not in result.stderr.lower()

    def test_a_read_inside_the_root_still_works(self, root_dir):
        bus = self.build(root=root_dir).bus
        result = bus.dispatch("fs", action="read", path="inside.txt")
        assert result.exit_code == 0
        assert result.stdout == "in\n"

    def test_an_unrooted_bus_is_todays_behaviour(self, root_dir, outside):
        bus = self.build().bus
        result = bus.dispatch("fs", action="read",
                              path=str(outside / "secret.txt"))
        assert result.exit_code == 0

    def test_a_string_root_is_accepted_and_resolved(self, root_dir, outside):
        """A library caller hands a path; `Tools` makes the `MissionRoot`
        so there is one owner of what the word means."""
        bus = self.build(root=str(root_dir)).bus
        assert bus.dispatch("fs", action="stat",
                            path=str(outside)).exit_code == 1


class TestTheCliDecidesItFromTheWorkingDirectory:
    """No flag and no environment variable: the root IS the directory the
    mission was started in — the same fact `PatchTool`, `RepoMapTool` and
    `load_project_config` are already built against."""

    def build(self, **flags):
        from types import SimpleNamespace

        import core.cli as cli

        seen = {}

        class FakeAgent:
            def __init__(self, **kw):
                seen.update(kw)

        args = SimpleNamespace(model=None, provider=None, personality=None,
                               unsandboxed=False, profile=None, **flags)
        cli._build_agent(FakeAgent, args)
        return seen

    def test_a_mission_is_rooted_at_the_working_directory(self, root_dir):
        assert self.build(mission=True)["root"] == Path.cwd()

    def test_a_chat_turn_is_not_rooted(self, root_dir):
        assert self.build(mission=False)["root"] is None
