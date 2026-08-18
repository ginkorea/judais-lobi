# tests/pack_fixtures.py — standing a coding pack's fixture repository up,
# and driving a mission at it

"""What it takes to run the `coding` pack against a real repository.

Not a test module: a support one, imported by `tests/test_pack_coding.py`
and by the live script the lane left behind, so that "a mission over a
fixture repository" is described once.  Three things live here.

**`fixture_repo(name, tmp)`** copies one of the pack's fixture repositories
out of `core/skills/library/coding/fixtures/` into a temporary directory
and makes it a git repository.  The fixtures are committed as plain
directories with no nested `.git` — a repository inside a repository is not
something git will carry, and a fixture that had to be un-nested on
checkout would be a fixture nobody could read.  So the `git init`, the
identity and the first commit happen here, at copy time, and every mission
gets a clean tree with one commit in it.

**`coding_bus(...)`** builds the tool plane the pack's closed set names,
aimed at that repository: the real `PatchTool`, the real `RepoMapTool`, the
real `VerifyTool` reading the repository's own `.judais-lobi.yml`.  No
doubles.  A double for `verify` would put the one thing this pack is about
— did the tests actually run, against the tree that was actually patched —
back behind a stub, which is the seam
`tests/test_coding_loop_end_to_end.py` was written to catch on the kernel
path.

**`drive(...)`** runs one mission through `MissionRunner` with a scripted
model and writes the NDJSON stream a `core.eval` scorer reads.  It is the
mission path's equivalent of what `tests/test_eval_stub_suite.py` does
through `core.cli._main`; it does not go through the CLI because
`--mission` still requires an MCP server (`_build_mcp_transport`) and this
pack's plane is entirely in-process.  When that changes, this function
becomes a call to `_main` and nothing else here moves.

Everything below assumes the process's working directory **is** the
repository.  That is not a shortcut: `PatchTool`, `RepoMapTool` and
`load_project_config` are all constructed against a path and `VerifyTool`
runs where the process is, and bwrap binds the working directory
read-write and nothing else — so "the repository the agent is working in"
has to be one fact rather than four that can disagree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.skills import library

#: This pack's name, and the only string here that is not read off the
#: loader. Everything else — where the pack is, what it ships, how its
#: fixtures reach a temporary directory — is `core.skills.library`'s
#: answer, so a test never learns a path the loader would have given it.
PACK_NAME = "coding"


def pack() -> library.Pack:
    """The pack, through its one loader."""
    return library.load(PACK_NAME)


#: The pack directory, for the two tests that ask about the files on disk
#: rather than about what a mission gets.
PACK = library.library_root() / PACK_NAME
FIXTURES = PACK / library.FIXTURES_DIR


def fixture_names() -> List[str]:
    """Every fixture repository the pack carries, sorted."""
    return sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def fixture_repo(name: str, tmp) -> Path:
    """A copy of the named fixture repository, git-initialised, under *tmp*.

    Returns the path of the copy. The original is never touched — a
    mission writes to files, and a fixture a test had modified would make
    the next test's verdict depend on the order they ran in. The copy is
    made by `Pack.stage_fixtures`, which is the loader's own answer to
    "get this pack's data somewhere writable": a sandboxed run binds its
    working directory read-WRITE, so a mission run where the fixtures LIE
    would be writing inside site-packages.
    """
    if name not in fixture_names():
        raise KeyError(f"no fixture repository {name!r}; there are "
                       f"{fixture_names()}")
    staged = pack().stage_fixtures(Path(tmp) / "fixtures")
    repo = staged / name
    # Every fixture is staged and one of them is used. Cheap, and it means
    # this helper exercises the same call a mission makes rather than a
    # narrower one that could work while `stage_fixtures` did not.
    for other in staged.iterdir():
        if other != repo:
            shutil.rmtree(other) if other.is_dir() else other.unlink()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       check=False)

    git("init", "-q")
    # An identity, because a commit without one fails on a host that has no
    # global git config — which is every container this has ever run in.
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Coding Pack Fixture")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-q", "-m", "the repository as the mission finds it")
    return repo


def diffstat(repo: Path) -> str:
    """`git diff --stat` of the working tree. What the mission left behind."""
    done = subprocess.run(["git", "diff", "--stat"], cwd=repo,
                          capture_output=True, text=True, check=False)
    return (done.stdout or "").strip()


# ── the plane ────────────────────────────────────────────────────────────────

def coding_bus(repo: Path, *, sandbox=None, audit=None,
               profile=None, shell: bool = False):
    """The pack's tool plane, aimed at *repo*. Real tools, no doubles.

    *sandbox* defaults to bwrap, because the manifest declares
    `sandbox: bwrap` and `SkillManifest.resolve` refuses a bus that is not
    running it. A caller on a host without bubblewrap gets the refusal, and
    that is the manifest working rather than the harness being awkward.

    *shell* registers `run_shell_command`. Off by default: the manifest
    marks it optional (`run_shell_command?`), so a plane without it
    resolves — and the code-plane gate still demands bwrap, because what
    the gate reads is what the manifest PERMITS and not what a bus happened
    to advertise this morning.
    """
    from core.contracts.schemas import ProfileMode
    from core.tools.bus import ToolBus
    from core.tools.capability import CapabilityEngine
    from core.tools.config_loader import load_project_config
    from core.tools.descriptors import (
        FS_DESCRIPTOR, GIT_DESCRIPTOR, PATCH_DESCRIPTOR, REPO_MAP_DESCRIPTOR,
        SHELL_DESCRIPTOR, VERIFY_DESCRIPTOR,
    )
    from core.tools.fs_tools import FsTool
    from core.tools.git_tools import GitTool
    from core.tools.patch_tool import PatchTool
    from core.tools.repo_map_tool import RepoMapTool
    from core.tools.sandbox import select_sandbox
    from core.tools.verify_tools import VerifyTool

    engine = CapabilityEngine()
    engine.set_profile(profile or ProfileMode.DEV)
    bus = ToolBus(
        capability_engine=engine,
        sandbox=sandbox if sandbox is not None else select_sandbox("bwrap")[0],
        audit=audit,
    )
    bus.register(REPO_MAP_DESCRIPTOR, RepoMapTool(repo_path=str(repo)))
    bus.register(FS_DESCRIPTOR, FsTool())
    bus.register(PATCH_DESCRIPTOR, PatchTool(repo_path=str(repo)))
    bus.register(GIT_DESCRIPTOR, GitTool())
    # The repository's own commands, read out of its own `.judais-lobi.yml`
    # — or, for a repository that ships none, the default that
    # `{python}` makes portable.
    bus.register(VERIFY_DESCRIPTOR,
                 VerifyTool(config=load_project_config(repo)))
    if shell:
        from core.tools.run_shell import RunShellTool

        bus.register(SHELL_DESCRIPTOR, RunShellTool())
    return bus


def load_pack():
    """The pack's manifest, through the pack loader's one owner of it."""
    return pack().manifest


def load_missions(check: bool = True):
    """The pack's suite, graded as a PACK's suite.

    `Pack.suite()` runs `core.skills.library.check_pack_suite`, which is
    `core.eval`'s own gradeability check with flag coverage scoped to the
    flags this suite captures, plus the rule only a pack can make: every
    tool a mission names is in the pack's closed set. The unscoped check
    demands every entry of `core.eval.FLAGS`, which is right for the one
    suite that grades the harness against everything it can do and wrong
    for eight coding missions.
    """
    return pack().suite(check=check)


# ── driving one mission ──────────────────────────────────────────────────────

def tool_call(_tool: str, **arguments) -> str:
    """One scripted reply that calls a tool, in the JSON protocol.

    The tool's name is positional and underscored because `name` is itself
    an argument of two of the tools here (`repo_map symbol`, `git branch`),
    and a keyword parameter called `name` would collide with the very calls
    this helper exists to write.
    """
    return json.dumps({"tool": _tool, "arguments": arguments})


def patch_call(task_id: str, *patches: Dict[str, Any],
               **kwargs) -> str:
    """A scripted `patch apply`, with the double encoding written once.

    `patch_set_json` is a JSON *string* inside a JSON object, and a
    scripted agent that got that nesting wrong would be testing the script
    rather than the pack.
    """
    body = json.dumps({"task_id": task_id, "patches": list(patches)})
    return tool_call("patch", action="apply", patch_set_json=body, **kwargs)


def modify(file_path: str, search: str, replace: str) -> Dict[str, Any]:
    return {"file_path": file_path, "search_block": search,
            "replace_block": replace, "action": "modify"}


def create(file_path: str, content: str) -> Dict[str, Any]:
    return {"file_path": file_path, "search_block": "",
            "replace_block": content, "action": "create"}


def answer(text: str) -> str:
    return json.dumps({"answer": text})


class ScriptedModel:
    """Replies in order, then answers `done`. Records what it was asked.

    A list and not a mapping from prompt to reply: the order a mission
    calls things in is part of what is under test, and a model that
    answered by pattern-matching the prompt would paper over a loop that
    asked in the wrong order.
    """

    def __init__(self, replies: Sequence[str]):
        self._remaining = list(replies)
        self.asked: List[Any] = []

    def __call__(self, messages):
        self.asked.append(messages)
        if self._remaining:
            return self._remaining.pop(0)
        return answer("done")


def drive(objective: str, replies: Sequence[str], repo: Path,
          events: Path, *, bus=None, max_steps: int = 12,
          monkeypatch=None) -> Path:
    """Run one mission at *repo* and write its stream to *events*.

    The loop, the closed set, the schema check, the grounding validator,
    the result store and the sandbox are all the real ones; only the model
    is scripted. Returns *events*.
    """
    from core.runtime.grounding import GroundingConfig, GroundingValidator
    from core.runtime.mission import MissionRunner
    from core.runtime.mission_stream import NdjsonSink
    from core.runtime.results import RESULT_TOOL
    from core.runtime.skills import sandbox_name

    manifest = load_pack()
    bus = bus if bus is not None else coding_bus(repo)
    offered = manifest.resolve(bus.list_tools(), sandbox=sandbox_name(bus))

    grounding = GroundingConfig.from_mapping(manifest.grounding)
    validator = GroundingValidator.from_config(
        grounding.offering([*offered, RESULT_TOOL]))

    previous = os.getcwd()
    handle = events.open("w", encoding="utf-8")
    try:
        # The repository IS the working directory. See the module docstring.
        os.chdir(repo)
        runner = MissionRunner(
            ScriptedModel(replies),
            bus,
            offered,
            system_message=manifest.prompt,
            max_steps=max_steps,
            validator=validator,
            admits=manifest.admits,
            observer=NdjsonSink(handle),
        )
        runner.run(objective)
    finally:
        os.chdir(previous)
        handle.close()
    return events


def records(events: Path) -> List[Dict[str, Any]]:
    """One stream, parsed. For a test that wants to read what happened."""
    return [json.loads(line) for line in
            events.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_of(events: Path, event: str) -> Optional[Dict[str, Any]]:
    """The last record of one kind, or `None`."""
    found = [r for r in records(events) if r.get("event") == event]
    return found[-1] if found else None
