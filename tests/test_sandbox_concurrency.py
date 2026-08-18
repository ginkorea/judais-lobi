# tests/test_sandbox_concurrency.py

"""Two dispatches at once on one bus, and both of them sandboxed.

The bus used to sandbox a tool by **assigning** the sandbox runner onto
the executor object, calling it, and putting the old value back in a
``finally``.  One dispatch at a time that reads as save-and-restore.  Two
dispatches is a race, and the losing interleaving is:

    A applies (saving the ORIGINAL) → B applies (saving A's runner)
    → A returns and restores the ORIGINAL → B spawns

B's subprocess then ran with the original, **unsandboxed** runner while
``bus.sandbox_name`` went on saying ``bwrap``.  Nothing reported it.

Two dispatches on one bus is not exotic: ``Run.child`` gathers children
that share a plane and therefore a bus, ``SwarmRunner(parallel>1)`` does
the same, and :mod:`core.tools.serve` hands every client call to
``anyio.to_thread.run_sync`` — so any two concurrent MCP clients race.

Every test below drives that exact interleaving with events rather than
sleeps, so it is a proof and not a probability.  The fix is
:func:`core.tools.executor.use_subprocess_runner`: the runner is carried
in a :class:`~contextvars.ContextVar` for the length of one call, and
nothing shared is written, so there is nothing for a second dispatch to
restore.
"""

import asyncio
import json
import threading

import anyio
import anyio.to_thread
import pytest

from core.contracts.schemas import PolicyPack
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor, SandboxProfile
from core.tools.executor import run_subprocess
from core.tools.git_tools import GitTool
from core.tools.patch_tool import PatchTool

#: Long enough that a loaded machine does not fail the test, short enough
#: that a deadlock is a failure rather than a hung suite.
GATE = 20.0

#: What the two runners say about themselves.  The whole assertion of this
#: file is which of these two words a subprocess came back with.
SANDBOXED = "SANDBOXED"
UNSANDBOXED = "UNSANDBOXED"


def unsandboxed(cmd, **_kwargs):
    """The runner a tool was constructed with — the one the old restore
    handed back to a dispatch still in flight."""
    return 0, UNSANDBOXED, ""


class RecordingSandbox:
    """A sandbox that runs nothing and remembers everything.

    ``execute`` is the whole of the :class:`~core.tools.sandbox.SandboxRunner`
    protocol the bus uses, and recording the *profile* beside the command is
    what makes the second half of the old bug visible: a dispatch whose
    runner was replaced mid-flight did not merely lose its sandbox, it could
    finish inside **another dispatch's profile**.
    """

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def execute(self, cmd, *, profile=None, timeout=None, env=None,
                shell=None, executable=None, stdin=None):
        with self._lock:
            self.calls.append((cmd, profile))
        return 0, SANDBOXED, ""


class GatedTool:
    """A tool shaped like ``git``, ``patch`` and ``install_project``.

    It reads its runner **at call time** and hands it to
    :func:`~core.tools.executor.run_subprocess`, which is what every
    subprocess tool in this package does, and it spawns more than one
    child — so a runner swapped underneath it lands *between* two of its
    own subprocesses.

    The attribute is named ``subprocess_runner`` because that is one of
    the four names the old ``_apply_subprocess_runner`` walked for; a tool
    the swap could not find was never sandboxed at all.
    """

    def __init__(self):
        self.subprocess_runner = unsandboxed
        self.a_applied = threading.Event()
        self.b_applied = threading.Event()
        self.a_returned = threading.Event()
        self.seen = {}
        self._lock = threading.Lock()

    def _spawn(self, tag):
        _rc, out, _err = run_subprocess(
            f"echo {tag}", shell=True,
            subprocess_runner=self.subprocess_runner)
        with self._lock:
            self.seen[tag] = out
        return out

    def __call__(self, who):
        if who == "A":
            first = self._spawn("A-1")
            # A is inside its dispatch, so A has applied.
            self.a_applied.set()
            assert self.b_applied.wait(GATE), "B never entered its dispatch"
            second = self._spawn("A-2")
            return 0, f"{first},{second}", ""
        # B is inside its dispatch, so B has applied — after A did.
        self.b_applied.set()
        assert self.a_returned.wait(GATE), "A never finished its dispatch"
        return 0, self._spawn("B-1"), ""


#: The two profiles the two names below are dispatched under.  Different so
#: that "which dispatch's sandbox ran this" is answerable from the record.
PROFILE_A = SandboxProfile(max_cpu_seconds=11)
PROFILE_B = SandboxProfile(max_cpu_seconds=22)


def gated_bus():
    """One bus, one executor object, two names — the shape of the race.

    Two descriptors over the **same** executor is how a single test drives
    two dispatches that share the state the old bus wrote to, and the two
    profiles make the mid-dispatch flip visible as well as the escape.
    """
    tool = GatedTool()
    sandbox = RecordingSandbox()
    bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=sandbox)
    bus.register(ToolDescriptor(tool_name="alpha", description="A's name",
                                sandbox_profile=PROFILE_A), tool)
    bus.register(ToolDescriptor(tool_name="beta", description="B's name",
                                sandbox_profile=PROFILE_B), tool)
    return bus, tool, sandbox


def assert_both_were_sandboxed(tool, sandbox):
    """Every child of both dispatches ran inside, under its own profile."""
    assert tool.seen == {"A-1": SANDBOXED, "A-2": SANDBOXED,
                         "B-1": SANDBOXED}, tool.seen
    by_command = {cmd: profile for cmd, profile in sandbox.calls}
    assert by_command["echo A-1"] is PROFILE_A
    assert by_command["echo A-2"] is PROFILE_A
    assert by_command["echo B-1"] is PROFILE_B


class TestTwoDispatchesOnOneBus:
    def test_the_second_dispatch_is_sandboxed_though_the_first_finished(self):
        """Threads, and the exact interleaving the reviewer found.

        B's subprocess happens *after* A's dispatch has returned and put
        back whatever it saved.  With the runner on the executor that was
        the original, and B escaped.
        """
        bus, tool, sandbox = gated_bus()
        results = {}

        def dispatch_a():
            results["A"] = bus.dispatch("alpha", who="A")

        def dispatch_b():
            assert tool.a_applied.wait(GATE), "A never entered its dispatch"
            results["B"] = bus.dispatch("beta", who="B")

        thread_a = threading.Thread(target=dispatch_a)
        thread_b = threading.Thread(target=dispatch_b)
        thread_a.start()
        thread_b.start()
        thread_a.join(GATE)
        assert not thread_a.is_alive()
        # Only now, with A's dispatch fully returned and its `finally`
        # long since run, is B let go.
        tool.a_returned.set()
        thread_b.join(GATE)
        assert not thread_b.is_alive()

        assert_both_were_sandboxed(tool, sandbox)
        assert results["A"].stdout == f"{SANDBOXED},{SANDBOXED}"
        assert results["B"].stdout == SANDBOXED

    def test_the_first_dispatchs_own_children_stay_in_its_own_profile(self):
        """The other half of the bug, and it is not an escape.

        ``A-2`` is spawned after B installed *its* runner.  A tool's second
        child running under another dispatch's profile is a mission
        enforcing limits nobody asked it for — and reporting the ones it
        declared.
        """
        bus, tool, sandbox = gated_bus()
        threads = [threading.Thread(target=bus.dispatch, args=("alpha",),
                                    kwargs={"who": "A"})]
        threads[0].start()
        assert tool.a_applied.wait(GATE)
        threads.append(threading.Thread(target=bus.dispatch, args=("beta",),
                                        kwargs={"who": "B"}))
        threads[1].start()
        threads[0].join(GATE)
        tool.a_returned.set()
        for thread in threads:
            thread.join(GATE)
            assert not thread.is_alive()

        profiles = {cmd: profile for cmd, profile in sandbox.calls}
        assert profiles["echo A-2"] is PROFILE_A

    def test_the_original_runner_is_never_reached(self):
        """Stated separately because it is what a sandbox IS: the runner
        the tool was constructed with must not run a command while the bus
        has declared this dispatch isolated."""
        bus, tool, sandbox = gated_bus()
        thread = threading.Thread(target=bus.dispatch, args=("alpha",),
                                  kwargs={"who": "A"})
        thread.start()
        assert tool.a_applied.wait(GATE)
        other = threading.Thread(target=bus.dispatch, args=("beta",),
                                 kwargs={"who": "B"})
        other.start()
        thread.join(GATE)
        tool.a_returned.set()
        other.join(GATE)
        assert UNSANDBOXED not in tool.seen.values()
        assert len(sandbox.calls) == 3

    def test_the_executors_own_runner_is_left_exactly_as_it_was(self):
        """Nothing shared is written any more, so there is nothing to
        restore and nothing to restore *wrongly*."""
        bus, tool, _sandbox = gated_bus()
        tool.a_applied.set()
        tool.b_applied.set()
        tool.a_returned.set()
        bus.dispatch("alpha", who="A")
        assert tool.subprocess_runner is unsandboxed


class TestTheSameRaceOffTheEventLoop:
    """A run's children and an MCP server both reach the bus from a thread
    an event loop put them on, and a ``ContextVar`` only works there if the
    context is carried across.  Both offloads copy it — that is the whole
    reason this fix is a ``ContextVar`` and not a lock."""

    def test_two_children_gathered_through_asyncio_to_thread(self):
        """``Run.child`` + ``asyncio.gather``: this is how two missions of
        one run dispatch at the same time (``core.runtime.run``)."""
        bus, tool, sandbox = gated_bus()

        async def main():
            async def child_a():
                result = await asyncio.to_thread(bus.dispatch, "alpha",
                                                 who="A")
                tool.a_returned.set()
                return result

            async def child_b():
                await asyncio.to_thread(tool.a_applied.wait, GATE)
                return await asyncio.to_thread(bus.dispatch, "beta", who="B")

            return await asyncio.gather(child_a(), child_b())

        got_a, got_b = asyncio.run(asyncio.wait_for(main(), GATE))
        assert_both_were_sandboxed(tool, sandbox)
        assert got_a.stdout == f"{SANDBOXED},{SANDBOXED}"
        assert got_b.stdout == SANDBOXED

    def test_two_calls_gathered_through_anyios_to_thread(self):
        """The served bus's own offload — ``core.tools.serve`` runs every
        client call through ``anyio.to_thread.run_sync`` so the server can
        keep answering.  Verified against anyio 4.12, which copies the
        context; a version that stopped would fail here rather than serve
        an unsandboxed call."""
        bus, tool, sandbox = gated_bus()
        results = {}

        async def call_a():
            results["A"] = await anyio.to_thread.run_sync(
                lambda: bus.dispatch("alpha", who="A"))
            tool.a_returned.set()

        async def call_b():
            await anyio.to_thread.run_sync(tool.a_applied.wait, GATE)
            results["B"] = await anyio.to_thread.run_sync(
                lambda: bus.dispatch("beta", who="B"))

        async def main():
            with anyio.fail_after(GATE):
                async with anyio.create_task_group() as group:
                    group.start_soon(call_a)
                    group.start_soon(call_b)

        anyio.run(main)
        assert_both_were_sandboxed(tool, sandbox)
        assert results["B"].stdout == SANDBOXED


class TestTheDeclaredSandboxIsStillTheReportedOne:
    """One owner: ``mission_started.sandbox`` is derived from the runner
    the bus holds, and no amount of per-call routing may move it."""

    def test_the_name_does_not_change_while_a_dispatch_is_in_flight(self):
        seen = []

        class Watching(RecordingSandbox):
            def execute(self, cmd, **kwargs):
                seen.append(bus.sandbox_name)
                return super().execute(cmd, **kwargs)

        sandbox = Watching()
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=sandbox)
        tool = GatedTool()
        tool.a_applied.set()
        tool.b_applied.set()
        tool.a_returned.set()
        bus.register(ToolDescriptor(tool_name="alpha"), tool)
        before = bus.sandbox_name
        bus.dispatch("alpha", who="A")
        assert seen == [before, before]
        assert bus.sandbox_name == before
        assert bus.sandbox is sandbox


class TestTheRealToolsThatSpawn:
    """The synthetic tool above has the shape; these are the objects.

    A tool is only sandboxed if it reaches a subprocess through
    :func:`~core.tools.executor.run_subprocess` — that is the one seam
    now, in place of four attribute names the bus used to hunt for.  These
    dispatch the real things and assert the sandbox saw the command.
    """

    def _bus(self, name, executor, **descriptor):
        sandbox = RecordingSandbox()
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=sandbox)
        bus.register(ToolDescriptor(tool_name=name, **descriptor), executor)
        return bus, sandbox

    def test_git_goes_through_the_sandbox(self):
        bus, sandbox = self._bus("git", GitTool())
        result = bus.dispatch("git", action="status")
        assert result.stdout == SANDBOXED
        assert sandbox.calls and "git status" in sandbox.calls[0][0]

    def test_two_git_dispatches_at_once_are_both_sandboxed(self):
        """One ``GitTool``, two threads.  Not gated — a single-subprocess
        tool's window is a few instructions wide and cannot be held open
        from outside — but it is the real object, and a bus that wrote to
        it would have to write twice here."""
        bus, sandbox = self._bus("git", GitTool())
        start = threading.Barrier(2, timeout=GATE)
        out = {}

        def call(who, action):
            start.wait()
            out[who] = bus.dispatch("git", action=action)

        threads = [threading.Thread(target=call, args=("A", "status")),
                   threading.Thread(target=call, args=("B", "log"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(GATE)
            assert not thread.is_alive()
        assert {r.stdout for r in out.values()} == {SANDBOXED}
        assert len(sandbox.calls) == 2

    def test_a_patch_apply_sends_every_one_of_its_children_inside(
            self, tmp_path):
        """The multi-subprocess case, and the one the old attribute walk
        had to reach by name: ``patch`` spawns through ``PatchEngine`` —
        ``git add --intent-to-add`` and then ``git diff`` — and the walk
        had to know about ``_engine`` and ``_engine._worktree`` to find
        them.  Routed per call, the seam does not have to know they
        exist."""
        bus, sandbox = self._bus("patch", PatchTool(repo_path=str(tmp_path)))
        patch_set = json.dumps({"task_id": "t1", "patches": [{
            "file_path": "made.py", "search_block": "",
            "replace_block": "planted\n", "action": "create",
        }]})
        result = bus.dispatch("patch", action="apply",
                              patch_set_json=patch_set)
        assert result.exit_code == 0, result.stderr
        assert (tmp_path / "made.py").read_text() == "planted\n"
        commands = [cmd for cmd, _profile in sandbox.calls]
        assert len(commands) == 2, commands
        assert "add --intent-to-add" in commands[0]
        assert "git diff" in commands[1]

    def test_a_patch_tools_worktree_is_reached_too(self, tmp_path):
        """``_engine._worktree`` was the fourth and last attribute the walk
        knew about.  ``use_worktree=True`` puts its ``git worktree add`` in
        the same dispatch as the engine's own two commands: three children,
        two objects, one context — and nothing went looking for either."""
        bus, sandbox = self._bus("patch", PatchTool(repo_path=str(tmp_path)))
        patch_set = json.dumps({"task_id": "t1", "patches": [{
            "file_path": "made.py", "search_block": "",
            "replace_block": "planted\n", "action": "create",
        }]})
        result = bus.dispatch("patch", action="apply", use_worktree=True,
                              patch_set_json=patch_set)
        assert result.exit_code == 0, result.stderr
        commands = [cmd for cmd, _profile in sandbox.calls]
        assert len(commands) == 3, commands
        assert "git worktree add" in commands[0]
        assert "add --intent-to-add" in commands[1]
        assert "git diff" in commands[2]


class TestAShapeThatIsNotSandboxed:
    """Written down rather than left to be discovered.

    A context variable follows :func:`asyncio.to_thread` and anyio's
    ``to_thread.run_sync`` because both copy the context.  A bare
    :class:`threading.Thread` does not, so a tool that starts one of its own
    and spawns a subprocess from it is outside the sandbox — and a future
    tool that wants to must carry the runner across itself, which
    :func:`~core.tools.executor.current_subprocess_runner` is public for.
    """

    def test_a_thread_a_tool_starts_itself_does_not_inherit_the_runner(self):
        from core.tools.executor import current_subprocess_runner

        sandbox = RecordingSandbox()
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=sandbox)
        seen = {}

        def executor():
            seen["inside"] = current_subprocess_runner()

            def worker():
                seen["thread"] = current_subprocess_runner()

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(GATE)
            return 0, "", ""

        bus.register(ToolDescriptor(tool_name="threaded"), executor)
        bus.dispatch("threaded")
        assert seen["inside"] is not None
        assert seen["thread"] is None

    def test_carrying_it_across_by_hand_works(self):
        """The documented way out, so the limit is a limit and not a
        dead end."""
        from core.tools.executor import (current_subprocess_runner,
                                         use_subprocess_runner)

        sandbox = RecordingSandbox()
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=sandbox)
        out = {}

        def executor():
            carried = current_subprocess_runner()

            def worker():
                with use_subprocess_runner(carried):
                    _rc, text, _err = run_subprocess("echo carried",
                                                     shell=True)
                    out["text"] = text

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(GATE)
            return 0, out.get("text", ""), ""

        bus.register(ToolDescriptor(tool_name="threaded"), executor)
        assert bus.dispatch("threaded").stdout == SANDBOXED


class TestNesting:
    def test_an_inner_dispatch_that_needs_no_sandbox_keeps_the_outer_one(self):
        """``use_subprocess_runner(None)`` is a no-op and not an unset: a
        tool that reaches the bus again for something ``skip_sandbox``
        must not thereby free its own subprocesses."""
        sandbox = RecordingSandbox()
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])),
            sandbox=sandbox)
        tool = GatedTool()

        def outer():
            bus.dispatch("inner")
            _rc, text, _err = run_subprocess(
                "echo after", shell=True,
                subprocess_runner=tool.subprocess_runner)
            return 0, text, ""

        bus.register(ToolDescriptor(tool_name="outer"), outer)
        bus.register(ToolDescriptor(tool_name="inner", skip_sandbox=True),
                     lambda: (0, "inner", ""))
        assert bus.dispatch("outer").stdout == SANDBOXED


@pytest.mark.parametrize("attribute", [
    "_apply_subprocess_runner", "_restore_subprocess_runner",
])
def test_the_swap_is_gone_and_not_merely_unused(attribute):
    """A save-and-restore left lying about is a save-and-restore somebody
    calls again."""
    assert not hasattr(ToolBus, attribute)
