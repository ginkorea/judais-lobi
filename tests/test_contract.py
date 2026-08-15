"""The seam, asserted against the code that has to honour it.

:mod:`core.runtime.contract` is the whole of what a consumer may rely on, and
a consumer is now a separate program on a separate release cycle: TAIPAN pins
a version of this repo and reads its NDJSON off an inherited descriptor.  That
only works if the contract is *checked against the emitters* rather than
written down beside them, because a docstring and an ``_emit`` call drift the
moment nobody is reading both — which is how ``repairing`` came to be a field
TAIPAN indexes and this repo never mentioned, and how the swarm's ``grounding``
record came to carry six of the ten fields the direct path's does.

So every test here is the same test in a different place: *what the contract
says is what actually happens.*  The events a real loop emits pass
:func:`~core.runtime.contract.conforms`; the flags it publishes are flags the
parser takes; the environment it publishes is environment something reads; and
``CONTRACT.md``, which is the version a person reads, says the same words as
the module a program imports.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import signal
from pathlib import Path

import pytest

from core.runtime import contract as c
from core.runtime import mission_stream as ms
from core.runtime.mission import AWAITING_APPROVAL, MissionRunner

REPO = Path(__file__).resolve().parent.parent
CONTRACT_MD = REPO / "CONTRACT.md"


class _Result:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code
        self.evidence = stdout


class _Bus:
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def describe_tool(self, name):
        return {"description": f"does {name}", "input_schema": {
            "type": "object", "properties": {"q": {"type": "string"}}}}

    def dispatch(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self.answers.get(name, _Result(stdout=f"{name} said so"))

    def register_tool(self, name, tool):
        return name

    def unregister(self, name):
        return None


def _replies(*texts):
    queue = list(texts)

    def chat(messages):
        return queue.pop(0) if queue else json.dumps({"answer": "done"})
    return chat


def _run(replies, *, gated=(), tools=("catalog_search_assets",), max_steps=4,
         validator=None):
    seen = []
    runner = MissionRunner(
        _replies(*replies), _Bus(), list(tools), max_steps=max_steps,
        gated=gated, validator=validator, observer=seen.append, store_tool="",
    )
    return runner.run("what do we hold"), seen


def _faults(records):
    """Every problem across a whole stream, said with the record that had it.

    Two checks, and the second is deliberately stricter than the first.
    :func:`~core.runtime.contract.conforms` is what a *consumer* runs, and
    it tolerates a key it has never heard of on purpose: an added optional
    field is a minor change by the rule at the top of that module, and a
    checker that failed on one would make every additive release breaking.

    This repo's own emitters are held tighter than its consumers, in both
    directions.  ``FIELDS`` is the floor — ``conforms`` covers that half —
    and ``FIELDS | OPTIONAL`` is the ceiling, which is the half nothing
    checked.  A field an event does not declare is a field a consumer will
    meet and have no sentence for, and it is also what a *removal* from
    ``FIELDS`` looks like from here: drop ``reason`` from
    ``GATE_REQUESTED`` and the record that still carries it fails on this
    line, rather than only where ``CONTRACT.md`` is compared with the
    module.
    """
    problems = []
    for record in records:
        event = record.get("event")
        problems += [f"{event}: {problem}" for problem in c.conforms(record)]
        if event not in c.FIELDS:
            continue
        declared = set(c.FIELDS[event]) | set(c.OPTIONAL.get(event, ()))
        for name in sorted(set(record) - {"event"} - declared):
            problems.append(f"{event}: undeclared field {name!r}")
    return problems


def _staged(validator=None):
    """A two-step staged mission over a real bus, and what it emitted.

    Factored out because the staged path is a second emitter and drifted
    once already, so it is exercised twice from here: once as it runs for
    a caller with no grounding grammar, and once with one — the branch
    that emits a ``grounding`` record at all, and therefore the only
    branch in which its shape is a fact rather than a hope.
    """
    from core.contracts.schemas import PolicyPack
    from core.runtime.swarm import SwarmRunner
    from core.tools.bus import ToolBus
    from core.tools.capability import CapabilityEngine
    from core.tools.descriptors import ToolDescriptor

    bus = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    bus.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="search tool. Second sentence."),
        lambda **kw: (0, "corpus abc123", ""))

    seen = []
    plain = _replies(
        json.dumps({"route": "staged"}),
        json.dumps({"steps": [
            {"id": "s1", "goal": "search", "rung": "tool"},
            {"id": "s2", "goal": "search again", "rung": "tool",
             "needs": ["s1"]}]}),
        "the synthesized answer, which names abc123")
    executor = _replies(
        json.dumps({"tool": "catalog.search", "arguments": {"q": "x"}}),
        json.dumps({"answer": "abc123"}),
        json.dumps({"tool": "catalog.search", "arguments": {"q": "y"}}),
        json.dumps({"answer": "abc123 again"}))
    SwarmRunner(executor, bus, ["catalog.search"],
                system_message="You are Tai.", plain_chat_fn=plain,
                validator=validator, observer=seen.append).run("search twice")
    return seen


# ── the events a real loop emits are the events the contract declares ────────


class TestAMissionConformsToItsOwnContract:
    def test_an_ordinary_mission_end_to_end(self):
        """Tool call, result, answer, finish — the shape a consumer sees on
        nearly every turn, checked field by field rather than by name."""
        _, seen = _run([
            json.dumps({"tool": "catalog_search_assets", "arguments": {"q": "x"}}),
            json.dumps({"answer": "three assets"}),
        ])
        assert seen
        assert _faults(seen) == []

    def test_a_mission_that_was_rejected_reprompted_and_gated(self):
        """The awkward paths, because they are the ones a pane renders least
        often and therefore the ones that rot."""
        _, seen = _run(
            ["not json at all",
             json.dumps({"tool": "catalog_delete_everything", "arguments": {}}),
             json.dumps({"tool": "compute_cancel_job",
                         "arguments": {"job_id": "job_7f3"}})],
            gated=("compute_cancel_job",),
            tools=("catalog_search_assets", "compute_cancel_job"))
        assert _faults(seen) == []
        assert ms.GATE_REQUESTED in [r["event"] for r in seen]

    def test_a_mission_that_ran_out_of_steps(self):
        transcript, seen = _run(
            [json.dumps({"tool": "catalog_search_assets", "arguments": {}})] * 3,
            max_steps=2)
        assert transcript.outcome == "budget_exhausted"
        assert _faults(seen) == []

    def test_a_mission_that_repaired_and_then_caveated(self):
        """Both grounding records — the interim one carrying ``repairing`` and
        the verdict that follows it — are full records, not the subset the
        repair path happened to need."""
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        validator = GroundingValidator.from_config(GroundingConfig.from_mapping(
            {"number_pattern": r"\d+\.\d{2,}", "max_repairs": 1}))
        transcript, seen = _run(
            [json.dumps({"answer": "the score is 80.847"}),
             json.dumps({"answer": "the score is 80.848"})],
            validator=validator)
        assert transcript.outcome == "answered_with_caveat"
        grounding = [r for r in seen if r["event"] == ms.GROUNDING]
        assert [r["repairing"] for r in grounding] == [True, False]
        assert _faults(seen) == []

    def test_a_mission_that_crashed_still_ends_conformantly(self):
        """``mission_finished`` comes out of a ``finally``. A record emitted on
        the way out of an exception is still a record somebody has to parse."""
        seen = []

        def explode(messages):
            raise RuntimeError("the model server went away")

        runner = MissionRunner(explode, _Bus(), ["catalog_search_assets"],
                               observer=seen.append, store_tool="")
        with pytest.raises(RuntimeError):
            runner.run("go")
        assert _faults(seen) == []
        assert seen[-1]["outcome"] == "incomplete"

    def test_a_staged_swarm_speaks_the_same_vocabulary(self):
        """The staged path is a second emitter and drifted once already. Same
        contract or it is not one contract."""
        seen = _staged()
        assert [r["event"] for r in seen][0] == ms.MISSION_STARTED
        assert _faults(seen) == []

    def test_a_staged_swarms_grounding_record_is_the_whole_record(self):
        """The drift itself, pinned where it happened.

        A staged mission emits ``grounding`` only when a validator was
        configured, so until one was configured here the shape of that
        record was never exercised on this path — which is exactly how it
        came to carry six of the ten fields the direct path's does, hand
        listed at the emit. Ten fields through the same renderer, checked
        as a key SET rather than by picking out the ones somebody
        remembered: a consumer switching on ``event`` gets one shape per
        event, or it does not have a vocabulary.
        """
        from core.runtime.grounding import GroundingConfig, GroundingValidator

        seen = _staged(GroundingValidator.from_config(
            GroundingConfig.from_mapping(
                {"identifier_pattern": r"\babc[0-9a-z]{3,}\b"})))
        assert _faults(seen) == []
        grounding = [r for r in seen if r["event"] == ms.GROUNDING]
        assert len(grounding) == 1, "a validator ran and said nothing"
        assert set(grounding[0]) - {"event"} == (
            set(c.FIELDS[ms.GROUNDING])
            | set(c.OPTIONAL.get(ms.GROUNDING, ())))


class TestTheTwoAdditiveFields:
    def test_the_first_record_carries_the_schema_version(self):
        """On the FIRST record, so a consumer that is going to refuse the
        stream refuses it before it has rendered anything from it."""
        _, seen = _run([json.dumps({"answer": "done"})])
        assert seen[0]["event"] == ms.MISSION_STARTED
        assert seen[0]["schema_version"] == c.SCHEMA_VERSION

    def test_the_last_record_carries_the_budget_beside_the_spend(self):
        """Six steps of a stated twenty-four is not an agent that ran out of
        room, and a consumer holding only the six cannot say so."""
        _, seen = _run([json.dumps({"answer": "done"})], max_steps=24)
        finished = seen[-1]
        assert finished["event"] == ms.MISSION_FINISHED
        assert (finished["steps"], finished["max_steps"]) == (1, 24)


# ── the contract is internally whole ─────────────────────────────────────────


class TestTheContractIsWhole:
    def test_every_event_declares_its_fields(self):
        assert set(c.FIELDS) == set(c.EVENTS)

    def test_the_stream_module_re_exports_rather_than_redeclares(self):
        """One owner. A second copy of a vocabulary is its own defect, and an
        importer that has always said ``mission_stream.EVENTS`` keeps working."""
        assert ms.EVENTS is c.EVENTS
        for name in c.EVENTS:
            assert getattr(ms, name.upper()) == name

    def test_no_field_is_both_required_and_optional(self):
        for event, optional in c.OPTIONAL.items():
            assert not set(optional) & set(c.FIELDS[event]), event

    def test_optional_fields_are_declared_for_real_events(self):
        assert set(c.OPTIONAL) <= set(c.EVENTS)

    def test_the_outcome_words_are_the_ones_the_code_can_say(self):
        """Read off the source rather than off memory: an outcome assigned in
        the loop and missing here is a word a consumer will meet and have no
        sentence for."""
        source = (REPO / "core" / "runtime" / "mission.py").read_text()
        source += (REPO / "core" / "runtime" / "swarm.py").read_text()
        assigned = set(re.findall(r'\.outcome = "([a-z_]+)"', source))
        assigned |= set(re.findall(r'outcome: str = "([a-z_]+)"', source))
        assigned.add(AWAITING_APPROVAL)
        assert assigned <= set(c.OUTCOMES), assigned - set(c.OUTCOMES)

    def test_the_exit_contract_names_the_clauses_a_consumer_builds_on(self):
        assert set(c.EXIT_CONTRACT) == {
            "stdout", "events", "silence", "finished", "sigterm", "diagnostic"}
        with pytest.raises(TypeError):
            c.EXIT_CONTRACT["stdout"] = "something else"


# ── what `conforms` is for: naming what is wrong ─────────────────────────────


class TestConformsNamesTheProblem:
    def _record(self):
        return {"event": ms.MISSION_FINISHED, "outcome": "answered",
                "steps": 3, "max_steps": 24}

    def test_a_good_record_has_nothing_to_say_about_it(self):
        assert c.conforms(self._record()) == []

    @pytest.mark.parametrize("field", ("outcome", "steps", "max_steps"))
    def test_a_missing_required_field_is_named(self, field):
        """The mutation check. A checker that passes a broken record is worse
        than no checker, because somebody stops looking."""
        record = self._record()
        del record[field]
        problems = c.conforms(record)
        assert problems, f"{field} was removed and nothing complained"
        assert any(repr(field) in problem for problem in problems)

    def test_an_unknown_event_is_named_and_its_fields_are_not_guessed_at(self):
        problems = c.conforms({"event": "mission_paused"})
        assert problems == ["unknown event 'mission_paused'"]

    def test_a_record_with_no_event_at_all(self):
        assert c.conforms({"steps": 1}) == ["no 'event' field"]

    def test_a_stream_from_a_future_version_says_so(self):
        problems = c.conforms({"event": ms.MISSION_STARTED,
                               "schema_version": c.SCHEMA_VERSION + 1,
                               "objective": "x", "catalogue": [], "gated": [],
                               "max_steps": 4, "history": 0})
        assert any("schema_version" in problem for problem in problems)

    def test_an_extra_field_is_not_a_problem(self):
        """Adding an optional field is a minor change by the rule at the top of
        the module. A checker that failed on one would make every additive
        release a breaking one."""
        record = self._record()
        record["something_new"] = "later"
        assert c.conforms(record) == []

    def test_something_that_is_not_a_record_at_all(self):
        assert c.conforms(["mission_finished"]) == ["not a record: list"]


# ── the surface a consumer spawns us by ──────────────────────────────────────


def _mission_parser() -> argparse.ArgumentParser:
    """The parser ``core.cli._main`` actually builds, caught on its way to use.

    Intercepted rather than rebuilt: a copy of the flag declarations in a test
    would pass forever after somebody renamed one.
    """
    from core import cli

    class _Caught(Exception):
        pass

    caught = {}
    real = argparse.ArgumentParser.parse_args

    def _capture(self, *args, **kwargs):
        caught["parser"] = self
        raise _Caught

    argparse.ArgumentParser.parse_args = _capture
    try:
        stub = type("Tai", (), {})
        with pytest.raises(_Caught):
            cli._main(stub)
    finally:
        argparse.ArgumentParser.parse_args = real
    return caught["parser"]


#: One usable value per flag that takes one, so the flag is *parsed* rather
#: than merely spelled the same as something in the source.
_FLAG_VALUES = {
    "--mcp-url": "http://127.0.0.1:8000/mcp",
    "--mission-steps": "6",
    "--model": "gpt-oss-20b",
    "--skill": "skill.yaml",
    "--events": "-",
    "--history": "thread.json",
    "--gate-tool": "compute_cancel_job",
    "--temperature": "0.2",
    "--top-p": "0.9",
    "--seed": "7",
}


class TestTheSpawningSurface:
    def test_every_published_flag_is_one_the_parser_takes(self):
        from core.cli import PROVIDERS

        parser = _mission_parser()
        values = dict(_FLAG_VALUES, **{"--provider": list(PROVIDERS)[0]})
        for flag in c.CLI_FLAGS:
            argv = ["go", flag]
            if flag in values:
                argv.append(values[flag])
            args = parser.parse_args(argv)
            assert getattr(args, flag.lstrip("-").replace("-", "_")) is not None

    def test_every_published_env_var_is_one_something_reads(self):
        """Not a substring grep. That version passed on a name that appeared
        only in a comment, or only in the tuple two screens up that publishes
        it — a claim satisfying itself.

        So: the name has to be a string literal *whose whole value is the
        name*, parsed out of the syntax tree, in a module that reads the
        environment at all. A comment never becomes a node; a docstring or
        a ``help=`` sentence that mentions the name becomes one node
        holding the whole sentence, not the name. And ``contract.py``
        itself is excluded by construction — it publishes the list and
        imports nothing outside the standard library, so it can no longer
        satisfy its own claim.

        It deliberately does not insist on ``os.getenv("NAME")``
        adjacency. This repo reads an env var through ``_env_path(name)``
        and through ``os.environ.get(CLIENT_NAME_ENV)`` as often as
        directly, and a rule that recognised only one spelling would push
        the next author towards the spelling the test likes rather than
        the one the code wants.
        """
        readers = {}
        for path in sorted((REPO / "core").rglob("*.py")):
            source = path.read_text()
            if "os.getenv" not in source and "os.environ" not in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    readers.setdefault(node.value, set()).add(path.name)

        for name in c.ENV_VARS:
            assert name in readers, (
                f"{name} is published and nothing under core/ reads it")


# ── the human rendering says the same thing as the machine one ───────────────


def _md_section(heading: str) -> str:
    """The body under one ``##`` heading, up to the next one."""
    text = CONTRACT_MD.read_text()
    body = text.split(f"\n## {heading}\n", 1)
    assert len(body) == 2, f"CONTRACT.md has no '## {heading}' section"
    return body[1].split("\n## ", 1)[0]


def _md_names(heading: str) -> set:
    """The first backticked token of every table row or bullet in a section."""
    return set(re.findall(r"^(?:\| |- )`([^`]+)`",
                          _md_section(heading), re.MULTILINE))


class TestTheDocumentAndTheModuleAgree:
    """``CONTRACT.md`` is written by hand, which is the only reason it reads
    well and the whole reason it drifts.  Equality both ways: a name the module
    grew and the document did not is as much a defect as the reverse.
    """

    def test_the_events(self):
        assert _md_names("Events") == set(c.EVENTS)

    def test_the_outcomes(self):
        assert _md_names("Outcomes") == set(c.OUTCOMES)

    def test_the_flags(self):
        assert _md_names("Command line") == set(c.CLI_FLAGS)

    def test_the_environment(self):
        assert _md_names("Environment") == set(c.ENV_VARS)

    def test_the_required_fields_of_every_event(self):
        """The table's second column, against ``FIELDS``. The fields are the
        half of the contract somebody actually indexes."""
        rows = re.findall(r"^\| `([^`]+)` \| ([^|]*)\|",
                          _md_section("Events"), re.MULTILINE)
        assert rows
        for event, cell in rows:
            assert set(re.findall(r"`([^`]+)`", cell)) == set(c.FIELDS[event]), \
                event

    def test_the_stated_version(self):
        assert f"SCHEMA_VERSION == {c.SCHEMA_VERSION}" in CONTRACT_MD.read_text()


# ── being asked to stop is not the same as stopping ──────────────────────────


class _SpySink:
    def __init__(self):
        self.flushed = self.closed = 0

    def flush(self):
        self.flushed += 1

    def close(self):
        self.closed += 1


@pytest.fixture
def sigterm_restored():
    previous = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, previous)


class TestSigtermClosesTheStream:
    def test_no_sink_installs_nothing(self, sigterm_restored):
        before = signal.getsignal(signal.SIGTERM)
        ms.close_on_sigterm(None)
        assert signal.getsignal(signal.SIGTERM) is before

    def test_the_sink_is_flushed_and_closed_and_the_signal_re_raised(
            self, monkeypatch, sigterm_restored):
        """TAIPAN sends SIGTERM rather than SIGKILL *so that* the harness gets
        to close its stream. Nothing made that true until there was a handler,
        and swallowing the signal afterwards would report a killed turn as a
        clean exit."""
        import os

        sink = _SpySink()
        ms.close_on_sigterm(sink)
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)

        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        handler(signal.SIGTERM, None)

        assert (sink.flushed, sink.closed) == (1, 1)
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        assert killed == [(os.getpid(), signal.SIGTERM)]

    def test_a_flush_on_a_dead_stream_does_not_raise(self):
        """The handler runs while something is already going wrong. It is the
        last thing that should add a traceback to it."""
        import io

        stream = io.StringIO()
        stream.close()
        ms.NdjsonSink(stream).flush()
