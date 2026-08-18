# tests/test_facade.py — `from judais_lobi import Run`, and the CLI as a client

"""The library API, and the claim that the CLI is one of its callers.

Three things are checked here and they are not the same thing.

**That the façade is a re-export and not a copy.**  Every name in
``judais_lobi.__all__`` has to be the *same object* as the one its owning
module holds — ``judais_lobi.Run is core.runtime.run.Run``, and so on down
the list.  A façade that rebuilt any of them would be a second definition
of a fact this repository keeps one of, and the failure mode is quiet: the
platform's ``isinstance`` stops matching, or its default bus turns out to
be a different bus from the one the CLI runs.

**That six lines is a mission.**  A :class:`Run` built the way
``PLATFORMS.md`` and the README tell a platform to build one produces a
stream every record of which satisfies :func:`core.runtime.contract.conforms`
— the same contract the CLI speaks, because it is the same loop.

**That the CLI is a client of it.**  The strong form: the same objective,
the same bus, the same scripted model, once through ``judais --mission``
and once through the six objects by hand, and the two streams compared
record for record with ``tests/test_record_replay``'s own ``comparable``.
Not a second comparator — the run id, the clock and the token counts are
the only things allowed to move, and they are the ones that move between
any two runs of anything.

The local tool plane is here rather than in a file of its own because it
is what makes the six-line example runnable at all: a platform that has to
stand up an MCP server before ``Run`` will do anything has not been handed
a library.
"""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import core.runtime.contract as contract_module
import judais_lobi
from core.contracts.schemas import PolicyPack
from core.durable import RUNS_ENV, RunStore
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox
from tests.test_record_replay import comparable, scripted_elf


# ── the manifest the runs below share ───────────────────────────────────────
#
# No `grounding:` block, deliberately. The claim being tested is that two
# ways of building one loop emit one stream, and a grammar would add a
# `grounding` record whose verdict is a second thing that has to agree —
# interesting, and not this file's question.

SKILL = textwrap.dedent("""\
    ---
    name: local
    skill:
      skill_id: local
      when_to_use: A mission over this host's own tools.
      allowed_tools:
        - governed_view
      policy:
        - Never invent an asset id.
      output_format: One sentence.
    ---

    # Local

    Read the view, then answer from it.
    """)

#: A manifest naming a tool that can only come from a server.  The closed
#: set is the whole of the difference from :data:`SKILL`.
SKILL_NEEDING_A_SERVER = SKILL.replace("    - governed_view",
                                       "    - mcp.governed_view")

ASSET = "asset.5f21"

REPLIES = (
    json.dumps({"tool": "governed_view",
                "arguments": {"run_id": ASSET, "section": "totals"}}),
    json.dumps({"answer": f"Totals for {ASSET}: 12481 records."}),
)


def write_skill(directory, text=SKILL):
    path = Path(directory) / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def local_bus():
    """A bus with one built-in tool on it and no bridge.

    Registered here rather than borrowed from :class:`core.tools.Tools`
    because the real built-ins read this checkout's filesystem, and a test
    whose result depends on what is in the working tree is a test that
    fails on somebody else's laptop.  What matters to every assertion
    below is that the tool is on the bus *before* the mission starts and
    arrived over no transport — which is exactly what a first-party skill's
    tools are.
    """
    bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(),
    )
    bus.register(
        ToolDescriptor(tool_name="governed_view",
                       description="Read a governed view of a run."),
        lambda **kw: (0, f"totals for {kw.get('run_id')}: 12481 records", ""),
    )
    return bus


def cli_elf(replies=REPLIES):
    """``scripted_elf`` with the local plane's bus under it."""
    MockClass, agent = scripted_elf(replies)
    agent.tools.bus = local_bus()
    return MockClass, agent


def run_cli(MockClass, *argv):
    from core.cli import _main
    with patch("sys.argv", ["test", *argv]):
        _main(MockClass)


def cli_records(objective, skill_path, *extra, replies=REPLIES):
    """Drive ``judais --mission`` with NO server, and read its stream back.

    The absence of ``--mcp-stdio`` is half the assertion: before the local
    plane this command line was a refusal.
    """
    MockClass, _agent = cli_elf(replies)
    run_cli(MockClass, objective, "--mission", "--skill", skill_path, *extra)
    store = RunStore(Path(os.environ[RUNS_ENV]))
    runs = store.list()
    assert len(runs) == 1, [run.run_id for run in runs]
    return store.records(runs[0].run_id)


def facade_records(objective, bus, replies=REPLIES):
    """The same mission, built out of the six objects a platform imports.

    This function IS the README's "Library API" example with a list to
    collect the stream into.  Nothing here reaches into ``core``: every
    name comes off ``judais_lobi``, which is the point.
    """
    from judais_lobi import (
        Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
    )

    seen = []
    remaining = list(replies)

    def ask(messages, **_extra):
        return remaining.pop(0) if remaining else '{"answer": "done"}'

    run = Run(
        Personality(system_message="You are Tai.\n\nRead the view, then "
                                   "answer from it."),
        ToolPlane(bus=bus, offered=["governed_view"]),
        Bounds(), Store(), Observer(seen.append), Model(ask=ask),
    )
    run.run(objective)
    return seen


# ── the façade is a re-export ───────────────────────────────────────────────


class TestEveryPromisedNameIsItsOwners:
    """``__all__`` is a promise about identity, not merely about spelling.

    A name that resolves to a *copy* passes ``hasattr`` and fails the day
    a platform writes ``isinstance(x, judais_lobi.Personality)`` about an
    object the CLI made.
    """

    #: ``name in __all__`` → the module that owns it, as a dotted path.
    OWNERS = {
        "Run": "core.runtime.run",
        "Personality": "core.runtime.run",
        "ToolPlane": "core.runtime.run",
        "Bounds": "core.runtime.run",
        "Store": "core.runtime.run",
        "Observer": "core.runtime.run",
        "Model": "core.runtime.run",
        "Tools": "core.tools",
        "load_skill": "core.runtime.skills",
        "resolve_skill": "core.runtime.skills",
        "packs": "core.skills.library",
        "Deadline": "core.budgets",
        "Cancellation": "core.budgets",
        "Supervisor": "core.runtime.supervisor",
        "MissionWindow": "core.runtime.context_window",
        "RunStore": "core.durable",
        "SCHEMA_VERSION": "core.runtime.contract",
    }

    def test_every_name_is_the_object_its_module_holds(self):
        import importlib

        for name, dotted in self.OWNERS.items():
            owner = importlib.import_module(dotted)
            assert getattr(judais_lobi, name) is getattr(owner, name), name

    def test_skill_is_the_manifest_under_a_shorter_name(self):
        """``Skill`` is the one export that is renamed, so it is the one
        that could quietly become something else."""
        from core.runtime.skills import SkillManifest

        assert judais_lobi.Skill is SkillManifest

    def test_the_contract_is_the_module_and_not_a_copy_of_it(self):
        assert judais_lobi.contract is contract_module
        assert judais_lobi.SCHEMA_VERSION == contract_module.SCHEMA_VERSION

    def test_all_is_covered_by_this_file(self):
        """The mapping above has to keep up with ``__all__``: a name added
        to the façade and not here would be exported and unchecked."""
        named = set(self.OWNERS) | {"Skill", "contract"}
        assert named == set(judais_lobi.__all__)

    def test_nothing_is_promised_twice(self):
        assert len(judais_lobi.__all__) == len(set(judais_lobi.__all__))

    def test_star_import_gets_exactly_the_promise(self):
        namespace = {}
        exec("from judais_lobi import *", namespace)  # noqa: S102
        namespace.pop("__builtins__", None)
        assert set(namespace) == set(judais_lobi.__all__)


class TestTheDefaultBusIsTheOneTheAgentRuns:
    """``Tools()`` is the façade's answer to "where does a bus come from",
    and it has to be the SAME answer ``core.agent.Agent`` gets — safe by
    default, sandboxed by default, audited by default.  A façade that
    built its own would hand a platform a bus governed differently from
    the one every CLI run is governed by, and nothing in the stream would
    say so.
    """

    def test_it_is_the_class_the_agent_instantiates(self):
        import core.agent as agent_module
        import core.tools as tools_module

        assert judais_lobi.Tools is tools_module.Tools
        assert agent_module.Tools is judais_lobi.Tools

    def test_the_default_bus_is_safe_sandboxed_and_audited(self, tmp_path,
                                                           monkeypatch):
        """The three defaults, off one construction. ``SAFE`` is the
        profile nobody asked for, the sandbox is whatever
        ``select_sandbox`` finds rather than none-by-omission, and the
        audit logger is on.

        `venv.create` is stubbed and the working directory moved: two of
        the built-in tools make a `.elfenv` beside the caller on
        construction, and a test that built one would be a test that
        writes into the repository and takes ten seconds doing it. What is
        being asserted is the bus, and the bus does not have a venv in it.
        """
        import venv

        from core.contracts.schemas import ProfileMode
        from core.policy.audit import AUDIT_ENV
        from core.tools.sandbox import select_sandbox

        monkeypatch.setattr(venv, "create", lambda *a, **kw: None)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(AUDIT_ENV, str(tmp_path / "audit.jsonl"))
        bus = judais_lobi.Tools().bus

        assert bus.capability_engine.current_profile == ProfileMode.SAFE.value
        assert bus.sandbox_name == select_sandbox(None)[1]
        assert bus.audit_ref


# ── six lines is a mission ──────────────────────────────────────────────────


class TestSixLinesIsAMission:
    def test_the_stream_conforms_record_for_record(self):
        """Not "a stream came out" — every record of it is one the
        contract declares, with the fields it requires. That is what "the
        same contract the CLI speaks" has to mean to be worth writing
        down."""
        records = facade_records("what are the totals?", local_bus())

        assert records
        for record in records:
            # `conforms` returns the PROBLEMS, so empty is the pass —
            # a checker that returned a bool could not say what was
            # wrong, and this assertion prints the list when it fails.
            assert not judais_lobi.contract.conforms(record), record

    def test_it_opens_and_closes_and_answers(self):
        records = facade_records("what are the totals?", local_bus())
        events = [record["event"] for record in records]

        assert events[0] == "mission_started"
        assert events[-1] == "mission_finished"
        assert "tool_call" in events and "tool_result" in events
        assert records[-1]["outcome"] == "answered"

    def test_the_catalogue_is_the_plane_it_was_given_plus_its_store(self):
        records = facade_records("what are the totals?", local_bus())

        assert records[0]["catalogue"] == ["governed_view", "mission_result"]
        assert records[0]["schema_version"] == judais_lobi.SCHEMA_VERSION


# ── the CLI is a client of it ───────────────────────────────────────────────


class TestTheCLIIsAClientOfThis:
    """One loop, two callers, one stream.

    ``comparable`` is imported rather than written here for the reason
    ``tests/test_run_corpus.py`` imports it: a comparison that owned its
    own idea of which fields may move would be a comparison that agrees
    with itself.
    """

    def test_the_two_streams_are_the_same_stream(self, tmp_path):
        through_the_cli = cli_records("what are the totals?",
                                      write_skill(tmp_path))
        through_the_facade = facade_records("what are the totals?",
                                            local_bus())

        assert comparable(through_the_cli) == comparable(through_the_facade)

    def test_and_it_is_not_an_empty_comparison(self, tmp_path):
        """The guard on the assertion above. Two empty lists are equal,
        and a mission that never started would make them both empty."""
        records = cli_records("what are the totals?", write_skill(tmp_path))

        assert [record["event"] for record in records] == [
            "mission_started", "step_started", "tool_call", "tool_result",
            "step_started", "answer", "mission_finished",
        ]

    def test_the_cli_run_conforms_too(self, tmp_path):
        records = cli_records("what are the totals?", write_skill(tmp_path))

        for record in records:
            # `conforms` returns the PROBLEMS, so empty is the pass —
            # a checker that returned a bool could not say what was
            # wrong, and this assertion prints the list when it fails.
            assert not judais_lobi.contract.conforms(record), record


# ── a mission does not need a server ────────────────────────────────────────


class TestTheLocalToolPlane:
    """``--mission`` with no ``--mcp-stdio`` and no ``--mcp-url``.

    It was a blanket refusal until the first-party skills, and the refusal
    was right for as long as every tool arrived over ``tools/list``.  It
    is wrong about a skill whose closed set is this package's own tools:
    they are registered on the bus before the mission starts, governed by
    the same profile and the same sandbox, and the server was never in the
    picture.  What survives is the refusal for a closed set naming
    something this host has not got — narrowed from "you passed no flag"
    to "this tool is not here", which is the sentence an operator can act
    on.
    """

    def test_a_closed_set_of_built_ins_runs_with_no_server(self, tmp_path,
                                                           capsys):
        records = cli_records("what are the totals?", write_skill(tmp_path))
        out = capsys.readouterr().out

        assert "is on its BUILT-IN tools" in out
        assert records[0]["catalogue"] == ["governed_view", "mission_result"]
        assert records[-1]["outcome"] == "answered"

    def test_the_tool_is_really_dispatched(self, tmp_path):
        records = cli_records("what are the totals?", write_skill(tmp_path))
        results = [r for r in records if r["event"] == "tool_result"]

        assert len(results) == 1 and results[0]["ok"] is True
        assert results[0]["tool"] == "governed_view"

    def test_a_closed_set_naming_a_server_tool_is_refused_by_name(
            self, tmp_path):
        """The refusal that is left, and it says which tool. "There is
        nothing to discover otherwise" sent an operator looking for a flag
        they had not forgotten."""
        MockClass, _agent = cli_elf()
        path = write_skill(tmp_path, SKILL_NEEDING_A_SERVER)

        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, "what are the totals?", "--mission",
                    "--skill", path)

        message = str(exc.value)
        assert "--mission needs a server" in message
        assert "'mcp.governed_view'" in message
        # And it says what IS here, so the operator can see the difference
        # between a typo and a missing server.
        assert "governed_view" in message

    def test_no_skill_and_no_server_is_offered_the_whole_bus(self, tmp_path,
                                                             capsys):
        """The other half of "no server": with no closed set there is
        nothing to refuse, and the run is offered every registered tool —
        which is what ``--mission`` without ``--skill`` has always been."""
        MockClass, _agent = cli_elf()
        run_cli(MockClass, "what are the totals?", "--mission")
        out = capsys.readouterr().out

        assert "is on its BUILT-IN tools" in out
        store = RunStore(Path(os.environ[RUNS_ENV]))
        records = store.records(store.list()[0].run_id)
        assert records[0]["catalogue"] == ["governed_view", "mission_result"]

    def test_a_named_server_still_takes_the_ordinary_path(self, tmp_path,
                                                          monkeypatch):
        """The local plane is what happens when no server was NAMED, and
        not a fallback for one that could not be reached: a transport that
        fails still fails. `tests/test_cli_mission_skill.py` is the whole
        proof for the connected path; this is the one line of it that
        would be lost if the two cases were ever confused.
        """
        from types import SimpleNamespace

        from core.cli import _transports

        # The environment forms name a server too, and this asserts what a
        # command line says: a shell that happens to carry MCP_URL must not
        # decide whether the local plane is what was asked for.
        for name in ("MCP_STDIO", "MCP_URL", "MCP_TOKEN"):
            monkeypatch.delenv(name, raising=False)
        args = SimpleNamespace(mcp_stdio=None, mcp_url="https://x/mcp",
                               mcp_token=None)
        assert _transports(args)
        assert _transports(
            SimpleNamespace(mcp_stdio=None, mcp_url=None,
                            mcp_token=None)) == []
