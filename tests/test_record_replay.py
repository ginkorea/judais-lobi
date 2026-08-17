# tests/test_record_replay.py — recording a run's model and tool I/O, and running it again

"""The recorder, the replay, and the corpus the two of them exist for.

The unit half exercises :mod:`core.runtime.replay` directly — one line
per model call, streaming and not, the side channels, the typed payload,
the ordinal, the drift, the refusals.

The other half is the corpus, and it is the point of the whole thing.
``tests/fixtures/runs/`` holds three complete recorded runs made against
the real FastMCP stub over stdio — one under each protocol and one
**staged** ``--swarm`` turn, events plus ``model.jsonl`` plus
``tools.jsonl`` — and the tests below **replay them**: no server is
spawned, the backend is wired to raise if anything asks it a question,
and the replayed stream is compared to the recorded one record for
record.

The staged run is the one that pins the ordinal.  A ``--swarm`` turn
makes its calls through *two* functions — the loop's ``chat_fn`` and the
roles' ``plain_chat_fn``, which declares no tools — and they are numbered
in one sequence because they happened in one sequence.  A replay that
served them from two queues would run the router against the executor's
second turn, and nothing about the resulting stream would look wrong.

The headline is :class:`TestTheGroundingExperiment`.  It replays the JSON
corpus run under a manifest whose *only* difference is its ``grounding:``
block, and the same recorded model output comes back with a different
verdict.  That is "score a grounding change on yesterday's runs", running
in a second on a laptop with no GPU.

The corpus was produced by :func:`record_corpus` below, which is the same
code path :class:`TestTheCorpusIsWhatThisHarnessProduces` runs to check
that the committed files are still what this harness makes.
"""

import json
import os
import shutil
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.contracts.schemas import PolicyPack
from core.durable import RUNS_ENV, RunStore
from core.runtime.replay import (
    CATALOGUE_CALL, MODEL_LOG, TOOL_LOG, TOOLS_LIVE, TOOLS_RECORDED,
    Recorder, ReplayBus, ReplayExhausted, ReplayModel, ReplayRefused,
    canonical, first_difference, open_for_replay, without_credentials,
)
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox

pytest.importorskip("mcp", reason="the MCP client is an optional extra")

STUB = str(Path(__file__).parent / "mcp_stub_server.py")

#: The committed corpus.  Two run directories, each complete.
CORPUS = Path(__file__).parent / "fixtures" / "runs"

#: The stable ids the corpus runs were renamed to when they were
#: committed.  Minted ids carry a timestamp, which would make every
#: assertion below quote the afternoon somebody generated the fixture.
JSON_RUN = "run_corpusjson-0001"
NATIVE_RUN = "run_corpusnative-0001"
SWARM_RUN = "run_corpusswarm-0001"

#: Every committed run, for the checks that are true of all of them.
CORPUS_RUNS = (JSON_RUN, NATIVE_RUN, SWARM_RUN)

#: The identifier the corpus mission cites, and the one thing the
#: grounding grammar below is looking for.
ASSET = "asset.5f21"


# ── the skill the corpus runs under, and the one thing that differs ─────────
#
# `STRICTER` is `SKILL` with a different `grounding:` block and NOTHING
# else. That is load-bearing: `grounding` is one of the manifest keys the
# loader consumes structurally (`core.runtime.skills._STRUCTURAL`), so it
# never reaches the prompt — which is why the experiment below produces a
# different verdict with ZERO drift. Change a word of the body or the
# policy and the messages change, the replay reports drift, and the
# comparison stops being clean.

_SKILL = """\
---
name: corpus
skill:
  skill_id: corpus
  when_to_use: Producing the recorded-run corpus.
  allowed_tools:
    - governed_view
  policy:
    - Never invent an asset id.
  output_format: One sentence.
  grounding:
{grounding}
---

# Corpus

Read the view, then answer in one sentence.
"""

SKILL = _SKILL.format(grounding=textwrap.indent(
    "identifier_pattern: '\\basset\\.[0-9a-z]{4,}\\b'\n", "    "))

STRICTER = _SKILL.format(grounding=textwrap.indent(
    "identifier_pattern: '\\basset\\.[0-9a-z]{4,}\\b'\n"
    "must_cite:\n"
    "  identifiers: 2\n"
    "max_repairs: 0\n", "    "))


def write_skill(directory, text=SKILL):
    path = Path(directory) / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ── an agent whose backend is a script, or a landmine ───────────────────────


def scripted_elf(replies=(), *, native=False, tool_calls=(), usage=None,
                 refuse=False, streams=False):
    """The `elf` of ``tests/test_cli_mission_skill.py``, with three knobs.

    *native* declares the two capabilities ``--protocol native`` is
    refused without; *refuse* wires the backend to raise, which is how a
    replay proves it asked nothing rather than merely proving it answered;
    *streams* declares ``supports_streaming``, which is how a replay
    proves it turned streaming off rather than inheriting an off default.
    """
    agent = MagicMock()
    agent.model = "gpt-oss-20b"
    agent.text_color = "cyan"
    agent.client.provider = "local"
    agent.client.last_usage = usage
    agent.client.last_tool_calls = []
    agent.system_message = "You are Tai."
    # Stated rather than left to the mock: an unset `supports_streaming`
    # on a MagicMock is truthy, and a corpus recorded with `stream: True`
    # in every request would be recording a capability the fixture does
    # not have.
    agent.client.capabilities.supports_streaming = bool(streams)
    agent.client.capabilities.supports_tool_calls = bool(native)
    agent.client.capabilities.supports_tool_choice_required = bool(native)
    # Stated for the same reason `supports_streaming` is. The swarm asks
    # this one of the CLIENT to decide whether its three object-returning
    # roles get `response_format`, and an unset MagicMock attribute is
    # truthy — a corpus recorded with a grammar constraint nobody chose is
    # a corpus of requests this fixture cannot explain.
    agent.client.capabilities.supports_json_mode = False
    agent.tools.bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox(),
    )
    agent.replies = list(replies)
    agent.tool_calls = [list(entry) for entry in tool_calls]
    agent.seeds = []

    def _chat(**kw):
        if refuse:
            raise AssertionError(
                "the backend was asked a question during a replay")
        agent.seeds.append([dict(m) for m in kw["messages"]])
        agent.client.last_tool_calls = (agent.tool_calls.pop(0)
                                        if agent.tool_calls else [])
        return agent.replies.pop(0) if agent.replies else '{"answer": "done"}'

    agent.client.chat.side_effect = _chat
    MockClass = MagicMock(return_value=agent)
    MockClass.__name__ = "Tai"
    return MockClass, agent


def run_cli(MockClass, *argv):
    from core.cli import _main
    with patch("sys.argv", ["test", *argv]):
        _main(MockClass)


def mission_argv(objective, skill, *extra):
    return [objective, "--mission", "--mcp-stdio", f"{sys.executable} {STUB}",
            "--skill", skill, *extra]


def only_run(root):
    """The one run in a store that holds one."""
    runs = RunStore(root).list()
    assert len(runs) == 1, [run.run_id for run in runs]
    return runs[0].run_id


def lines(path):
    """A JSONL as a list, and ``[]`` for a file nothing has written yet.

    The absent file is the interesting case rather than an error one: the
    recorder creates ``model.jsonl`` on its FIRST write, so "no line yet"
    and "no file yet" are one state and a test asserting the first must
    not fall over on the second.
    """
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def records(root, run_id):
    return RunStore(root).records(run_id)


# ── producing the corpus ────────────────────────────────────────────────────


#: The scripted JSON-protocol mission: one governed read, then an answer
#: citing what it read.  Deliberately tiny — a fixture is committed, and a
#: 200-actor listing in the repository is a fixture nobody opens.
JSON_REPLIES = (
    json.dumps({"tool": "mcp.governed_view",
                "arguments": {"run_id": ASSET, "section": "totals"}}),
    json.dumps({"answer": f"Totals for {ASSET}: 12481 records."}),
)

#: The same mission under the native protocol: the decision is in the
#: side channel and the reply's ``content`` is empty, which is exactly the
#: shape a recorder that only kept the returned string would lose.
NATIVE_CALLS = (
    [{"id": "call_a", "name": "mcp.governed_view",
      "arguments": {"run_id": ASSET, "section": "totals"}}],
    [{"id": "call_b", "name": "mission_answer",
      "arguments": {"text": f"Totals for {ASSET}: 12481 records."}}],
)


#: The scripted STAGED mission: a plan of two steps, each one governed
#: view, then a synthesis over both. Two steps because a plan of one step
#: IS the direct path and the swarm says so, and no ``done`` conditions
#: because a mechanical gate needs no model call — which keeps the
#: recording to the seven calls listed below and the fixture readable.
#:
#: The seven, in the one order they happened in:
#: ``plain`` (the router), ``plain`` (the planner), ``mission`` ×2 (step
#: one's call and its answer), ``mission`` ×2 (step two's), ``plain`` (the
#: synthesizer).
SWARM_PLAN = json.dumps({"steps": [
    {"id": "s1", "goal": "read the run's totals", "rung": "tool",
     "needs": []},
    {"id": "s2", "goal": "read the second run's totals", "rung": "tool",
     "needs": ["s1"]},
]})

SWARM_REPLIES = (
    '{"route": "staged"}',
    SWARM_PLAN,
    json.dumps({"tool": "mcp.governed_view",
                "arguments": {"run_id": ASSET, "section": "totals"}}),
    json.dumps({"answer": f"{ASSET}: 12481 records."}),
    json.dumps({"tool": "mcp.governed_view",
                "arguments": {"run_id": "asset.9c40", "section": "totals"}}),
    json.dumps({"answer": "asset.9c40: 12481 records."}),
    f"Both runs hold 12481 records: {ASSET} and asset.9c40.",
)


def record_json_run(tmp_path):
    """Record the JSON-protocol corpus run.  Returns ``(root, run_id)``."""
    MockClass, _ = scripted_elf(JSON_REPLIES)
    run_cli(MockClass, *mission_argv("what are the totals?",
                                     write_skill(tmp_path)))
    root = Path(os.environ[RUNS_ENV])
    return root, only_run(root)


def record_native_run(tmp_path):
    """Record the native-protocol corpus run.  Returns ``(root, run_id)``."""
    MockClass, _ = scripted_elf(("", ""), native=True,
                                tool_calls=NATIVE_CALLS)
    run_cli(MockClass, *mission_argv("what are the totals?",
                                     write_skill(tmp_path),
                                     "--protocol", "native"))
    root = Path(os.environ[RUNS_ENV])
    return root, only_run(root)


def record_swarm_run(tmp_path):
    """Record the staged (``--swarm``) corpus run.  ``(root, run_id)``."""
    MockClass, _ = scripted_elf(SWARM_REPLIES)
    run_cli(MockClass, *mission_argv("what do the two runs hold?",
                                     write_skill(tmp_path), "--swarm"))
    root = Path(os.environ[RUNS_ENV])
    return root, only_run(root)


def rename_run(root, run_id, wanted):
    """Move a recorded run to a stable id, id references included.

    A minted id carries the second it was minted in.  Committing one would
    put an afternoon in 2026 into every assertion that quotes the corpus,
    so the fixture is renamed on its way into the repository and the
    ``run_id`` inside ``meta.json`` and on ``mission_started`` is renamed
    with it — a directory whose metadata names a different run is a
    fixture that documents a bug.
    """
    root = Path(root)
    (root / run_id).rename(root / wanted)
    for path in (root / wanted).iterdir():
        path.write_text(
            path.read_text(encoding="utf-8").replace(run_id, wanted),
            encoding="utf-8")
    return wanted


def deidentify(directory):
    """Take the generating machine back out of a fixture's metadata.

    ``--skill`` was given as an absolute path in a pytest tmp directory
    and ``_run_meta_flags`` faithfully wrote it down.  A fixture committed
    with that in it names somebody's home directory in the repository —
    which is the leak :mod:`core.redact` exists to stop a *mission*
    making, and no better for being made by a test.  The one flag that
    carries a path becomes the name of the file, which is all a reader of
    the fixture needs; nothing else in a run directory holds one, and
    :meth:`TestTheCorpusIsComplete.test_the_corpus_names_no_machine` is
    what keeps that true.
    """
    meta_path = Path(directory) / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    flags = meta.get("meta", {}).get("flags", {})
    if "skill" in flags:
        flags["skill"] = "SKILL.md"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False),
                         encoding="utf-8")


def record_corpus(destination, tmp_path):
    """Produce both corpus runs into *destination*.  Used to commit them."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    made = []
    for record, wanted in ((record_json_run, JSON_RUN),
                           (record_native_run, NATIVE_RUN),
                           (record_swarm_run, SWARM_RUN)):
        root, run_id = record(tmp_path)
        rename_run(root, run_id, wanted)
        if (destination / wanted).exists():
            shutil.rmtree(destination / wanted)
        shutil.copytree(root / wanted, destination / wanted)
        deidentify(destination / wanted)
        shutil.rmtree(root / wanted)
        made.append(wanted)
    return made


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """The committed corpus, copied into this test's own run store.

    Copied and not read in place: a replay writes a NEW run directory into
    the store it read from, and a test that scattered run directories
    through ``tests/fixtures/`` would be a test that edits the repository.
    """
    root = Path(os.environ[RUNS_ENV])
    root.mkdir(parents=True, exist_ok=True)
    for run in CORPUS_RUNS:
        shutil.copytree(CORPUS / run, root / run)
    return root


def replayed(root, recorded_id):
    """The one run in *root* that is a replay of *recorded_id*."""
    replays = [run for run in RunStore(root).list()
               if run.meta.get("replay_of") == recorded_id]
    assert len(replays) == 1, [run.run_id for run in replays]
    return replays[0]


# ── the recorder, on its own ────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "store")


@pytest.fixture
def recorder(store):
    run = store.create()
    return Recorder(store, run.run_id,
                    side=lambda: (SimpleNamespace(as_record=lambda: {
                        "prompt_tokens": 11, "completion_tokens": 3,
                        "total_tokens": 14}),
                        [{"id": "c1", "name": "catalog.search",
                          "arguments": {"q": "x"}}]))


def frames(*texts):
    """Delta frames in the shape every backend in this tree yields."""
    return [SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=text, tool_calls=None))])
        for text in texts]


class TestTheRecorderWritesOneLinePerCall:
    def test_a_whole_reply_is_one_line(self, recorder):
        ask = recorder.wrap(lambda messages, **extra: "the reply",
                            kind="mission")
        ask([{"role": "user", "content": "go"}], stream=False)
        written = lines(recorder.model_path)
        assert len(written) == 1
        assert written[0]["call"] == 1
        assert written[0]["kind"] == "mission"
        assert written[0]["reply"]["content"] == "the reply"

    def test_the_request_is_the_messages_and_the_rest_of_it(self, recorder):
        ask = recorder.wrap(lambda messages, **extra: "ok", kind="mission")
        ask([{"role": "user", "content": "go"}],
            stream=False, tool_choice="required", tools=[{"type": "function"}])
        request = lines(recorder.model_path)[0]["request"]
        assert request["messages"] == [{"role": "user", "content": "go"}]
        assert request["extra"]["tool_choice"] == "required"
        assert request["extra"]["stream"] is False
        assert request["extra"]["tools"] == [{"type": "function"}]

    def test_the_side_channels_ride_the_reply(self, recorder):
        ask = recorder.wrap(lambda messages, **extra: "", kind="mission")
        ask([{"role": "user", "content": "go"}])
        reply = lines(recorder.model_path)[0]["reply"]
        assert reply["tool_calls"] == [
            {"id": "c1", "name": "catalog.search", "arguments": {"q": "x"}}]
        assert reply["usage"]["total_tokens"] == 14

    def test_the_calls_are_numbered_in_one_sequence_across_kinds(self, recorder):
        mission = recorder.wrap(lambda messages, **extra: "a", kind="mission")
        plain = recorder.wrap(lambda messages, **extra: "b", kind="plain")
        mission([{"role": "user", "content": "1"}])
        plain([{"role": "user", "content": "2"}])
        mission([{"role": "user", "content": "3"}])
        written = lines(recorder.model_path)
        assert [(w["call"], w["kind"]) for w in written] == [
            (1, "mission"), (2, "plain"), (3, "mission")]

    def test_a_second_recorder_on_the_same_run_continues_the_numbering(
            self, store, recorder):
        recorder.wrap(lambda messages, **extra: "a", kind="mission")([])
        again = Recorder(store, recorder.run_id)
        again.wrap(lambda messages, **extra: "b", kind="mission")([])
        assert [w["call"] for w in lines(recorder.model_path)] == [1, 2]


class TestTheRecorderAndAStreamedReply:
    def test_the_frames_pass_through_untouched(self, recorder):
        made = frames("the ", "reply")
        ask = recorder.wrap(lambda messages, **extra: iter(made),
                            kind="mission")
        assert list(ask([])) == made

    def test_nothing_is_written_until_the_iterator_is_exhausted(self, recorder):
        ask = recorder.wrap(lambda messages, **extra: iter(frames("a", "b")),
                            kind="mission")
        stream = ask([])
        next(stream)
        assert lines(recorder.model_path) == []
        list(stream)
        assert len(lines(recorder.model_path)) == 1

    def test_the_recorded_content_is_the_concatenation(self, recorder):
        ask = recorder.wrap(
            lambda messages, **extra: iter(frames('{"answer": ', '"hi"}')),
            kind="mission")
        list(ask([]))
        assert lines(recorder.model_path)[0]["reply"]["content"] == \
            '{"answer": "hi"}'

    def test_a_stream_that_dies_still_records_what_arrived(self, recorder):
        def dying(messages, **extra):
            yield from frames("half ")
            raise RuntimeError("the server went away")

        with pytest.raises(RuntimeError):
            list(recorder.wrap(dying, kind="mission")([]))
        assert lines(recorder.model_path)[0]["reply"]["content"] == "half "


class TestTheRecorderAndTheToolPlane:
    @pytest.fixture
    def bus(self):
        bus = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            sandbox=NoneSandbox())
        bus.register(
            ToolDescriptor(tool_name="catalog.get", description="Fetch one.",
                           input_schema={"type": "object", "properties": {
                               "asset_id": {"type": "string"}}}),
            lambda **kw: (0, f"asset {kw.get('asset_id')}", "",
                          json.dumps({"asset_id": kw.get("asset_id")})))
        return bus

    def test_the_catalogue_is_the_first_line(self, recorder, bus):
        recorder.catalogue(recorder.bus(bus), ["catalog.get"])
        first = lines(recorder.tools_path)[0]
        assert first["call"] == CATALOGUE_CALL
        assert [entry["name"] for entry in first["catalogue"]] == ["catalog.get"]
        assert first["catalogue"][0]["input_schema"]["type"] == "object"

    def test_a_dispatch_is_one_line_with_its_arguments(self, recorder, bus):
        recorder.bus(bus).dispatch("catalog.get", asset_id="a.1")
        written = lines(recorder.tools_path)[-1]
        assert written["call"] == 1
        assert written["tool"] == "catalog.get"
        assert written["arguments"] == {"args": [], "kwargs": {"asset_id": "a.1"}}
        assert written["result"]["stdout"] == "asset a.1"
        assert written["result"]["exit_code"] == 0

    def test_the_typed_payload_is_recorded_as_json(self, recorder, bus):
        recorder.bus(bus).dispatch("catalog.get", asset_id="a.1")
        assert lines(recorder.tools_path)[-1]["result"]["structured"] == \
            {"asset_id": "a.1"}

    def test_the_result_is_the_buss_own(self, recorder, bus):
        wrapped = recorder.bus(bus)
        assert wrapped.dispatch("catalog.get", asset_id="a.1").stdout == \
            "asset a.1"

    def test_the_deadline_stays_a_named_parameter(self, recorder, bus):
        """`MissionRunner` asks the SIGNATURE whether the bus takes a
        ceiling. A proxy that swallowed it into **kwargs would silently
        stop every --mission-seconds run from bounding its tool calls."""
        from core.runtime.mission import _takes_deadline

        assert _takes_deadline(recorder.bus(bus))

    def test_the_deadline_is_not_part_of_the_recorded_arguments(
            self, recorder, bus):
        recorder.bus(bus).dispatch("catalog.get", asset_id="a.1", deadline_s=4)
        assert lines(recorder.tools_path)[-1]["arguments"]["kwargs"] == \
            {"asset_id": "a.1"}

    def test_everything_else_reaches_the_bus(self, recorder, bus):
        wrapped = recorder.bus(bus)
        assert wrapped.list_tools() == ["catalog.get"]
        assert wrapped.sandbox_name == "none"
        assert wrapped.describe_tool("catalog.get")["description"] == "Fetch one."


class TestTheRecordingIsScrubbedOfCredentialsAndNothingElse:
    def test_a_credential_in_a_reply_does_not_reach_the_disk(
            self, recorder, monkeypatch):
        monkeypatch.setenv("MCP_TOKEN", "mcp-tok-91f2ab77c410")
        recorder.wrap(lambda messages, **extra: "the token is "
                      "mcp-tok-91f2ab77c410", kind="mission")([])
        written = recorder.model_path.read_text(encoding="utf-8")
        assert "mcp-tok-91f2ab77c410" not in written
        assert "<redacted:MCP_TOKEN>" in written

    def test_a_path_is_left_alone_because_it_is_the_models_input(
            self, recorder):
        recorder.wrap(lambda messages, **extra: "read /home/somebody/x.json",
                      kind="mission")([])
        assert "/home/somebody/x.json" in \
            recorder.model_path.read_text(encoding="utf-8")

    def test_without_credentials_walks_into_nested_values(self, monkeypatch):
        monkeypatch.setenv("MCP_TOKEN", "mcp-tok-91f2ab77c410")
        scrubbed = without_credentials(
            {"messages": [{"content": "mcp-tok-91f2ab77c410"}]})
        assert scrubbed["messages"][0]["content"] == "<redacted:MCP_TOKEN>"


# ── the replay model ────────────────────────────────────────────────────────


def recorded_call(n, messages, content, *, kind="mission", tool_calls=(),
                  usage=None):
    return {"call": n, "at": "2026-08-16T00:00:00+00:00", "kind": kind,
            "request": {"messages": list(messages), "extra": {}},
            "reply": {"content": content, "tool_calls": list(tool_calls),
                      "usage": usage}}


ONE = [{"role": "user", "content": "one"}]
TWO = [{"role": "user", "content": "one"}, {"role": "user", "content": "two"}]


class TestTheReplayModelServesInOrder:
    def test_the_replies_come_back_in_the_order_they_were_recorded(self):
        model = ReplayModel([recorded_call(1, ONE, "first"),
                             recorded_call(2, TWO, "second")])
        ask = model.serving("mission")
        assert ask(ONE) == "first"
        assert ask(TWO) == "second"

    def test_the_side_channels_come_back_too(self):
        model = ReplayModel([recorded_call(
            1, ONE, "", tool_calls=[{"id": "c", "name": "t", "arguments": {}}],
            usage={"prompt_tokens": 5, "completion_tokens": 1,
                   "total_tokens": 6})])
        model.serving("mission")(ONE)
        assert model.last_tool_calls[0]["name"] == "t"
        assert model.last_usage.total_tokens == 6

    def test_a_call_the_recording_does_not_have_is_refused_by_name(self):
        model = ReplayModel([recorded_call(1, ONE, "first")])
        model.serving("mission")(ONE)
        with pytest.raises(ReplayExhausted) as exc:
            model.serving("mission")(TWO)
        assert "1 model call" in str(exc.value)
        assert "wants call 2" in str(exc.value)

    def test_the_mission_and_the_swarms_roles_share_one_ordinal(self):
        model = ReplayModel([recorded_call(1, ONE, "router", kind="plain"),
                             recorded_call(2, TWO, "loop", kind="mission")])
        assert model.serving("plain")(ONE) == "router"
        assert model.serving("mission")(TWO) == "loop"
        assert model.drift is None


class TestDriftIsReportedAndNotRefused:
    def test_matching_messages_are_no_drift(self):
        model = ReplayModel([recorded_call(1, ONE, "first")])
        model.serving("mission")(ONE)
        assert model.drift is None
        assert model.drifted == 0

    def test_a_changed_message_is_named_by_call_and_by_index(self):
        model = ReplayModel([recorded_call(1, TWO, "first")])
        model.serving("mission")([TWO[0], {"role": "user", "content": "other"}])
        assert model.drift["call"] == 1
        assert model.drift["message"] == 1
        assert "differs at message 1" in model.drift["detail"]

    def test_the_recorded_reply_is_still_served(self):
        model = ReplayModel([recorded_call(1, ONE, "first")])
        assert model.serving("mission")(TWO) == "first"

    def test_only_the_first_divergence_is_kept_and_the_rest_are_counted(self):
        model = ReplayModel([recorded_call(1, ONE, "a"),
                             recorded_call(2, ONE, "b")])
        ask = model.serving("mission")
        ask(TWO)
        ask(TWO)
        assert model.drift["call"] == 1
        assert model.drifted == 2

    def test_a_shorter_message_list_differs_where_it_runs_out(self):
        model = ReplayModel([recorded_call(1, TWO, "a")])
        model.serving("mission")(ONE)
        assert model.drift["message"] == 1

    def test_the_kind_is_part_of_being_the_same_call(self):
        model = ReplayModel([recorded_call(1, ONE, "a", kind="plain")])
        model.serving("mission")(ONE)
        assert "recorded as a 'plain' call" in model.drift["detail"]

    def test_the_drift_record_says_how_far_it_got(self):
        model = ReplayModel([recorded_call(1, ONE, "a"),
                             recorded_call(2, ONE, "b")])
        model.serving("mission")(ONE)
        assert model.as_record() == {"first": None, "calls": 0, "served": 1,
                                     "recorded": 2}

    def test_the_notifier_is_called_once_with_the_first_divergence(self):
        seen = []
        model = ReplayModel([recorded_call(1, ONE, "a"),
                             recorded_call(2, ONE, "b")],
                            on_drift=seen.append)
        ask = model.serving("mission")
        ask(TWO)
        ask(TWO)
        assert [entry["call"] for entry in seen] == [1]


class TestCanonicalisation:
    def test_key_order_is_not_a_difference(self):
        assert canonical({"a": 1, "b": 2}) == canonical({"b": 2, "a": 1})

    def test_first_difference_finds_the_index(self):
        assert first_difference(["a", "b", "c"], ["a", "x", "c"]) == 1

    def test_identical_lists_have_none(self):
        assert first_difference(["a"], ["a"]) is None


# ── the replay bus ──────────────────────────────────────────────────────────


DISPATCHES = [
    {"call": 1, "tool": "catalog.get",
     "arguments": {"args": [], "kwargs": {"asset_id": "a.1"}},
     "result": {"exit_code": 0, "stdout": "asset a.1", "stderr": "",
                "structured": {"asset_id": "a.1"}}},
]
CATALOGUE = [{"name": "catalog.get", "description": "Fetch one.",
              "input_schema": {"type": "object", "properties": {}}}]


class TestTheReplayBus:
    @pytest.fixture
    def bus(self):
        return ReplayBus(
            ToolBus(capability_engine=CapabilityEngine(
                PolicyPack(allowed_scopes=["*"])), sandbox=NoneSandbox()),
            CATALOGUE, DISPATCHES)

    def test_a_recorded_call_gets_its_recorded_result(self, bus):
        result = bus.dispatch("catalog.get", asset_id="a.1")
        assert result.exit_code == 0
        assert result.stdout == "asset a.1"

    def test_the_typed_payload_comes_back_as_evidence(self, bus):
        assert json.loads(bus.dispatch("catalog.get", asset_id="a.1").evidence) \
            == {"asset_id": "a.1"}

    def test_a_call_the_recording_never_saw_is_refused_and_says_so(self, bus):
        result = bus.dispatch("catalog.get", asset_id="a.2")
        assert result.exit_code == -1
        assert json.loads(result.stderr)["error"] == "not_in_recording"
        assert len(bus.missing) == 1

    def test_the_same_call_twice_gets_the_recorded_answer_twice(self, bus):
        first = bus.dispatch("catalog.get", asset_id="a.1")
        assert bus.dispatch("catalog.get", asset_id="a.1").stdout == first.stdout

    def test_the_catalogue_is_the_recorded_one(self, bus):
        assert bus.describe_tool("catalog.get")["description"] == "Fetch one."

    def test_a_tool_the_recording_does_not_hold_falls_through(self, bus):
        assert "error" in bus.describe_tool("nothing.at.all")

    def test_the_deadline_stays_a_named_parameter(self, bus):
        from core.runtime.mission import _takes_deadline

        assert _takes_deadline(bus)


# ── the door ────────────────────────────────────────────────────────────────


class TestTheDoorRefusesAnUnusableRecording:
    def test_no_store_is_refused_by_name(self):
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(None, JSON_RUN)
        assert "JUDAIS_LOBI_RUNS" in str(exc.value)

    def test_an_unknown_run_is_refused(self, store):
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(store, "run_nosuch-0001")
        assert "run_nosuch-0001" in str(exc.value)

    def test_an_id_this_store_never_minted_is_refused_the_same_way(self, store):
        with pytest.raises(ReplayRefused):
            open_for_replay(store, "../../etc")

    def test_a_run_with_no_model_log_names_the_file(self, store):
        run = store.create(meta={"objective": "x"})
        store.append(run.run_id, {"event": "mission_started", "objective": "x"})
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(store, run.run_id)
        assert MODEL_LOG in str(exc.value)
        assert "--resume" in str(exc.value)

    def test_a_run_with_no_recorded_plane_names_the_way_out(self, store):
        run = store.create(meta={"objective": "x"})
        store.append(run.run_id, {"event": "mission_started", "objective": "x"})
        Recorder(store, run.run_id).model_call(
            "mission", {"messages": [], "extra": {}}, "hi")
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(store, run.run_id)
        assert TOOL_LOG in str(exc.value)
        assert f"--replay-tools {TOOLS_LIVE}" in str(exc.value)

    def test_a_run_that_never_opened_is_refused(self, store):
        run = store.create(meta={"objective": "x"})
        Recorder(store, run.run_id).model_call(
            "mission", {"messages": [], "extra": {}}, "hi")
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(store, run.run_id)
        assert "mission_started" in str(exc.value)

    def test_an_unknown_plane_is_refused_naming_both_words(self, store):
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(store, JSON_RUN, tools="whatever")
        assert TOOLS_RECORDED in str(exc.value)
        assert TOOLS_LIVE in str(exc.value)

    def test_the_wrong_objective_is_refused_naming_both(self, corpus):
        with pytest.raises(ReplayRefused) as exc:
            open_for_replay(RunStore(corpus), JSON_RUN,
                            objective="something else")
        assert "what are the totals?" in str(exc.value)
        assert "something else" in str(exc.value)

    def test_the_recorded_objective_is_accepted(self, corpus):
        recording = open_for_replay(RunStore(corpus), JSON_RUN,
                                    objective="what are the totals?")
        assert recording.objective == "what are the totals?"


# ── the corpus ──────────────────────────────────────────────────────────────


class TestTheCorpusIsComplete:
    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_every_file_a_replay_needs_is_committed(self, run_id):
        for name in ("meta.json", "events.jsonl", MODEL_LOG, TOOL_LOG):
            assert (CORPUS / run_id / name).exists(), name

    @pytest.mark.parametrize("run_id", [JSON_RUN, NATIVE_RUN])
    def test_the_recording_holds_two_model_calls(self, run_id):
        assert [line["call"] for line in lines(CORPUS / run_id / MODEL_LOG)] \
            == [1, 2]

    @pytest.mark.parametrize("run_id", [JSON_RUN, NATIVE_RUN])
    def test_the_tool_log_holds_a_catalogue_and_one_dispatch(self, run_id):
        written = lines(CORPUS / run_id / TOOL_LOG)
        assert written[0]["call"] == CATALOGUE_CALL
        assert [line["tool"] for line in written[1:]] == ["mcp.governed_view"]

    @pytest.mark.parametrize("run_id", [JSON_RUN, NATIVE_RUN])
    def test_the_typed_payload_the_event_stream_never_carried_is_there(
            self, run_id):
        structured = lines(CORPUS / run_id / TOOL_LOG)[1]["result"]["structured"]
        # FastMCP wraps a tool's typed return in `result`; what matters is
        # that the parsed object is here at all, because `tool_result` on
        # the event stream carries only the text rendering of it.
        assert structured["result"]["totals"] == {"records": 12481, "blocks": 7}

    def test_the_staged_run_numbers_both_kinds_in_one_sequence(self):
        """The one thing this fixture exists for.

        A ``--swarm`` turn asks through two functions — the loop's, with
        the tools declared, and the roles', with none — and they happened
        in one order. A recording that numbered them separately would
        replay the router against the executor's second turn, and the
        resulting stream would look perfectly ordinary.
        """
        written = lines(CORPUS / SWARM_RUN / MODEL_LOG)
        assert [line["call"] for line in written] == [1, 2, 3, 4, 5, 6, 7]
        assert [line["kind"] for line in written] == [
            "plain", "plain", "mission", "mission", "mission", "mission",
            "plain"]

    def test_the_staged_runs_roles_were_asked_without_tools(self):
        """Which is why they are a different ``kind`` at all: a harmony
        model handed a function namespace answers a yes/no question with a
        tool call."""
        written = lines(CORPUS / SWARM_RUN / MODEL_LOG)
        assert not any(line["request"]["extra"].get("tools")
                       for line in written if line["kind"] == "plain")
        assert all(line["request"]["extra"]["tools"]
                   for line in written if line["kind"] == "mission")

    def test_the_staged_run_checkpointed_its_plan_and_its_steps(self):
        """The half of a staged run that is not on the event stream, and
        the half `--resume` reads."""
        meta = json.loads(
            (CORPUS / SWARM_RUN / "meta.json").read_text(encoding="utf-8"))
        assert [step["id"] for step in meta["meta"]["plan"]] == ["s1", "s2"]
        assert [entry["outcome"] for entry
                in meta["meta"]["steps_done"]] == ["ok", "ok"]

    def test_the_staged_run_reads_as_one_mission_on_the_wire(self):
        # Through the store, because a line of `events.jsonl` is a record
        # in an envelope carrying its `seq` — and the envelope is the
        # store's to open.
        recorded = records(CORPUS, SWARM_RUN)
        events = [r["event"] for r in recorded]
        assert events.count("mission_started") == 1
        assert events.count("mission_finished") == 1
        started = [r for r in recorded if r["event"] == "step_started"]
        assert [step["id"] for step in started[0]["plan"]] == ["s1", "s2"]
        assert [r["index"] for r in started] == list(range(len(started)))
        # Four turns under one numbering: two sub-missions of two turns
        # each, renumbered into the sequence a watcher reads.
        assert len(started) == 4

    def test_the_native_run_kept_the_decision_that_was_not_in_the_string(self):
        first = lines(CORPUS / NATIVE_RUN / MODEL_LOG)[0]
        assert first["reply"]["content"] == ""
        assert first["reply"]["tool_calls"][0]["name"] == "mcp.governed_view"

    def test_the_corpus_names_no_machine(self):
        """A fixture that names somebody's home directory is a location
        leak committed to the repository, and it stays there.

        The mission path scrubs its own errors through `core.redact` for
        exactly this reason; a recording made on a laptop and checked in
        is the same hazard by another road."""
        for run_id in CORPUS_RUNS:
            for path in (CORPUS / run_id).iterdir():
                text = path.read_text(encoding="utf-8")
                assert "/home/" not in text, path
                assert "/tmp/" not in text, path

    def test_the_committed_runs_are_small(self):
        """A corpus is only grown if it stays openable."""
        for run_id in CORPUS_RUNS:
            for path in (CORPUS / run_id).iterdir():
                assert path.stat().st_size < 64_000, path


class TestTheCorpusIsWhatThisHarnessProduces:
    """The committed fixture, against a fresh recording made the same way.

    Not a golden-file diff: ``at``, the run id and the wall clock all move
    legitimately. What must not move is the request — the messages the
    model was shown — because that is the thing a replay compares against
    and a fixture whose prompt has drifted from the code is a fixture that
    reports drift on every call forever.
    """

    def test_the_json_run_records_the_same_requests(self, tmp_path):
        root, run_id = record_json_run(tmp_path)
        fresh = lines(root / run_id / MODEL_LOG)
        committed = lines(CORPUS / JSON_RUN / MODEL_LOG)
        assert [line["request"] for line in fresh] == \
            [line["request"] for line in committed]

    def test_the_json_run_records_the_same_dispatches(self, tmp_path):
        root, run_id = record_json_run(tmp_path)
        fresh = lines(root / run_id / TOOL_LOG)
        committed = lines(CORPUS / JSON_RUN / TOOL_LOG)
        assert [line.get("tool") for line in fresh] == \
            [line.get("tool") for line in committed]
        assert fresh[1]["result"] == committed[1]["result"]

    def test_the_native_run_records_the_same_requests(self, tmp_path):
        root, run_id = record_native_run(tmp_path)
        assert [line["request"] for line in lines(root / run_id / MODEL_LOG)] \
            == [line["request"] for line in lines(CORPUS / NATIVE_RUN / MODEL_LOG)]

    def test_the_staged_run_records_the_same_requests_and_kinds(self,
                                                                tmp_path):
        root, run_id = record_swarm_run(tmp_path)
        fresh = lines(root / run_id / MODEL_LOG)
        committed = lines(CORPUS / SWARM_RUN / MODEL_LOG)
        assert [line["request"] for line in fresh] == \
            [line["request"] for line in committed]
        assert [line["kind"] for line in fresh] == \
            [line["kind"] for line in committed]


# ── replaying it ────────────────────────────────────────────────────────────


#: The fields of a record that legitimately move between a run and its
#: replay, and therefore the ones a record-for-record comparison drops.
#: Everything else has to match, which is the assertion worth making.
#:
#: ``run_id`` is the new directory's; ``elapsed_s`` and ``started_at`` are
#: this afternoon's clock; ``usage`` is the recorded provider's report
#: folded into a fresh ledger and rides different records under the two
#: protocols; ``audit_ref`` names a file in this test's tmp directory.
MOVES = ("run_id", "elapsed_s", "started_at", "usage", "audit_ref")


def comparable(records):
    return [{key: value for key, value in record.items() if key not in MOVES}
            for record in records]


def replay_argv(run_id, skill, *extra):
    """A replay command line with NO server on it.

    The absence of ``--mcp-stdio`` is an assertion: ``_build_mcp_transport``
    refuses a mission that names no server, so a replay that reached it
    would fail here rather than quietly spawn one.
    """
    return ["--mission", "--replay", run_id, "--skill", skill, *extra]


#: The flags a recorded run has to be replayed under.  A replay rebuilds
#: the prompts the recorded run built, and a ``--swarm`` turn builds a
#: router's and a planner's that the ordinary loop never builds at all —
#: so the flag is part of *which run this is*, and it rides here rather
#: than being guessed at.  ``meta.json`` carries it as ``flags.swarm``.
REPLAY_FLAGS = {SWARM_RUN: ("--swarm",)}


class TestARunWithAReviewInIt:
    """A supervisor review is a plain model call, and a replay is only
    honest if it serves that call too.

    The corpus is three runs of ordinary work and none of them repeats
    itself, so this one is recorded here rather than committed: what it
    pins is the ORDINAL. The review lands between the third mission call
    and the fourth, and a replay that served the two functions from two
    queues would hand the reviewer's verdict to the loop and the loop's
    tool call to the reviewer — with nothing about the resulting stream
    looking wrong.
    """

    #: Three identical reads — which is what the watcher fires on — then
    #: the verdict, then the answer the nudge produced.
    LOOPING = (
        json.dumps({"tool": "mcp.governed_view",
                    "arguments": {"run_id": ASSET, "section": "totals"}}),
        json.dumps({"tool": "mcp.governed_view",
                    "arguments": {"run_id": ASSET, "section": "totals"}}),
        json.dumps({"tool": "mcp.governed_view",
                    "arguments": {"run_id": ASSET, "section": "totals"}}),
        json.dumps({"verdict": "nudge", "note": "you already have the "
                                                "totals; answer with them"}),
        json.dumps({"answer": f"Totals for {ASSET}: 12481 records."}),
    )

    def _recorded(self, tmp_path):
        MockClass, _ = scripted_elf(self.LOOPING)
        run_cli(MockClass, *mission_argv("what are the totals?",
                                         write_skill(tmp_path)))
        root = Path(os.environ[RUNS_ENV])
        return root, only_run(root)

    def test_the_review_is_recorded_as_a_plain_call_in_one_sequence(
            self, tmp_path):
        root, run_id = self._recorded(tmp_path)
        assert [line["kind"] for line in lines(root / run_id / MODEL_LOG)] == \
            ["mission", "mission", "mission", "plain", "mission"]

    def test_the_replayed_stream_is_the_recorded_stream(self, tmp_path):
        root, run_id = self._recorded(tmp_path)
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path)))
        fresh = replayed(root, run_id)
        assert comparable(records(root, fresh.run_id)) == \
            comparable(records(root, run_id))

    def test_the_replayed_run_carries_the_review_and_the_nudge(self,
                                                               tmp_path):
        """The point of the whole thing: the verdict comes back out of the
        recording, the note is injected again, and the step that follows
        carries both fields it carried the first time."""
        root, run_id = self._recorded(tmp_path)
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path)))
        fresh = replayed(root, run_id)
        reviewed = [r for r in records(root, fresh.run_id)
                    if r["event"] == "step_started" and "review" in r]
        assert len(reviewed) == 1
        assert reviewed[0]["review"]["verdict"] == "nudge"
        assert "answer with them" in reviewed[0]["injected"][0]


class TestReplayingTheCorpus:
    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_replayed_stream_is_the_recorded_stream(
            self, corpus, tmp_path, run_id):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        fresh = replayed(corpus, run_id)
        assert comparable(records(corpus, fresh.run_id)) == \
            comparable(records(corpus, run_id))

    def test_the_staged_replay_served_every_recorded_call_in_order(
            self, corpus, tmp_path):
        """Record for record is the headline; this is the mechanism under
        it. Seven calls of two kinds, all served, none drifted — a replay
        that had queued the roles separately would have served the router
        the executor's messages and reported drift on every one of them."""
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(SWARM_RUN, write_skill(tmp_path),
                                        "--swarm"))
        drift = replayed(corpus, SWARM_RUN).meta["drift"]
        assert drift["first"] is None
        assert drift["calls"] == 0
        assert drift["served"] == drift["recorded"] == 7

    def test_the_staged_replay_checkpoints_its_own_plan(self, corpus,
                                                        tmp_path):
        """A replayed run is an ordinary run directory: it can be scored,
        read and replayed again, and a staged one carries the checkpoint a
        staged run carries."""
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(SWARM_RUN, write_skill(tmp_path),
                                        "--swarm"))
        fresh = replayed(corpus, SWARM_RUN)
        assert [step["id"] for step in fresh.meta["plan"]] == ["s1", "s2"]
        assert [entry["outcome"] for entry
                in fresh.meta["steps_done"]] == ["ok", "ok"]

    def test_a_staged_recording_replayed_without_the_flag_says_so(
            self, corpus, tmp_path, capsys):
        """It is not refused — there is no flag that turns the comparison
        off, and none that turns it into a refusal either — but it must
        never be silent. The ordinary loop's first prompt is not the
        router's, so the run diverges at call one and the drift is on the
        console and in the replayed run's metadata."""
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(SWARM_RUN, write_skill(tmp_path)))
        out = capsys.readouterr().out
        assert "replay drift" in out
        drift = replayed(corpus, SWARM_RUN).meta["drift"]
        assert drift["first"]["call"] == 1
        assert drift["calls"] >= 1

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_nothing_is_asked_and_nothing_is_spawned(
            self, corpus, tmp_path, run_id):
        """The backend raises if it is called and no transport is named.

        Two ways of saying "offline", and both of them have to hold: a
        replay that dialled the server would need `--mcp-stdio` here, and
        one that asked the model would meet the AssertionError above.
        """
        MockClass, agent = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        assert agent.seeds == []

    def test_the_replay_is_a_new_run_that_names_the_recorded_one(
            self, corpus, tmp_path):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        fresh = replayed(corpus, JSON_RUN)
        assert fresh.run_id != JSON_RUN
        assert fresh.meta["replay_of"] == JSON_RUN
        assert fresh.meta["replay_tools"] == TOOLS_RECORDED

    def test_the_recorded_run_is_left_exactly_as_it_was(self, corpus, tmp_path):
        before = (CORPUS / JSON_RUN / "events.jsonl").read_text(encoding="utf-8")
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        assert (corpus / JSON_RUN / "events.jsonl").read_text(
            encoding="utf-8") == before

    def test_a_clean_replay_says_so_rather_than_saying_nothing(
            self, corpus, tmp_path):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        drift = replayed(corpus, JSON_RUN).meta["drift"]
        assert drift["first"] is None
        assert drift["calls"] == 0
        assert drift["served"] == drift["recorded"] == 2

    def test_the_replayed_run_is_itself_recorded(self, corpus, tmp_path):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        fresh = replayed(corpus, JSON_RUN)
        assert [line["call"] for line in
                lines(corpus / fresh.run_id / MODEL_LOG)] == [1, 2]
        assert lines(corpus / fresh.run_id / TOOL_LOG)[1]["tool"] == \
            "mcp.governed_view"

    def test_the_replay_records_itself_as_not_streaming(self, corpus, tmp_path):
        """Even where the backend declares it can.

        A recording holds the reply and not the frames it arrived in, so
        there is nothing to stream. The re-recording of a replay must not
        claim `stream: true` over frames that never existed — that is a
        record of a call nobody made, and the next replay would read it.
        """
        MockClass, _ = scripted_elf(refuse=True, streams=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        fresh = replayed(corpus, JSON_RUN)
        written = lines(corpus / fresh.run_id / MODEL_LOG)
        assert written
        assert all(line["request"]["extra"]["stream"] is False
                   for line in written)

    def test_the_console_says_which_run_is_being_replayed(
            self, corpus, tmp_path, capsys):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        assert f"replay of {JSON_RUN}" in capsys.readouterr().out


class TestDriftThroughTheCommandLine:
    def test_a_changed_prompt_is_reported_and_recorded_but_not_refused(
            self, corpus, tmp_path, capsys):
        """The skill's BODY changed, which the prompt carries.

        This is the case `--replay-loose` would exist for, and the reason
        it does not: the run still finishes, still answers, and the fact
        that it was asked a different question is on the record.
        """
        moved = write_skill(tmp_path, SKILL.replace(
            "Read the view, then answer in one sentence.",
            "Read the view. Then answer in one sentence."))
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, moved))
        drift = replayed(corpus, JSON_RUN).meta["drift"]
        assert drift["first"]["call"] == 1
        assert drift["first"]["message"] == 0
        assert drift["calls"] == 2
        assert "replay drift" in capsys.readouterr().out

    def test_the_run_still_answers_on_the_recorded_reply(
            self, corpus, tmp_path):
        moved = write_skill(tmp_path, SKILL.replace(
            "Read the view, then answer in one sentence.", "Answer."))
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, moved))
        fresh = replayed(corpus, JSON_RUN)
        answers = [r for r in records(corpus, fresh.run_id)
                   if r.get("event") == "answer"]
        assert ASSET in answers[-1]["text"]


class TestTheGroundingExperiment:
    """Change the grammar, replay yesterday's run, read the new verdict.

    The whole feature, in one class. The manifest differs from the one the
    corpus was recorded under in its `grounding:` block and in nothing
    else, so the model is asked the identical question — zero drift — and
    the only thing that can have moved is the verdict.
    """

    def _replay(self, corpus, tmp_path, skill_text):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN,
                                        write_skill(tmp_path, skill_text)))
        fresh = replayed(corpus, JSON_RUN)
        return fresh, records(corpus, fresh.run_id)

    def test_the_recorded_run_was_grounded(self, corpus):
        grounding = [r for r in records(corpus, JSON_RUN)
                     if r.get("event") == "grounding"]
        assert grounding[-1]["grounded"] is True
        assert [r for r in records(corpus, JSON_RUN)
                if r.get("event") == "mission_finished"][-1]["outcome"] == \
            "answered"

    def test_the_same_answer_under_a_stricter_grammar_is_not(
            self, corpus, tmp_path):
        _, replayed_records = self._replay(corpus, tmp_path, STRICTER)
        grounding = [r for r in replayed_records
                     if r.get("event") == "grounding"]
        assert grounding[-1]["grounded"] is False

    def test_the_outcome_moves_with_it(self, corpus, tmp_path):
        _, replayed_records = self._replay(corpus, tmp_path, STRICTER)
        finished = [r for r in replayed_records
                    if r.get("event") == "mission_finished"][-1]
        assert finished["outcome"] == "answered_with_caveat"

    def test_the_experiment_is_clean_because_the_prompt_did_not_move(
            self, corpus, tmp_path):
        """No drift. The model was asked exactly what it was asked before,
        so the different verdict is the grammar's and nothing else's."""
        fresh, _ = self._replay(corpus, tmp_path, STRICTER)
        assert fresh.meta["drift"]["first"] is None
        assert fresh.meta["drift"]["calls"] == 0

    def test_the_answer_itself_is_the_recorded_one(self, corpus, tmp_path):
        _, replayed_records = self._replay(corpus, tmp_path, STRICTER)
        answered = [r for r in replayed_records if r.get("event") == "answer"][-1]
        assert answered["text"].startswith(f"Totals for {ASSET}: 12481 records.")


#: `STRICTER` with the default repair turn left in.  Same refused
#: verdict, but the loop now buys itself a THIRD model call against a
#: recording that holds two — which is the one thing a replay cannot
#: serve, and must not pretend to.
REPAIRING = _SKILL.format(grounding=textwrap.indent(
    "identifier_pattern: '\\basset\\.[0-9a-z]{4,}\\b'\n"
    "must_cite:\n"
    "  identifiers: 2\n", "    "))


class TestARunThatOutgrowsItsRecording:
    """A change that buys a turn the recording does not have.

    There is no model here. Serving the previous reply again, or an empty
    one, would put a sentence nobody generated into a transcript somebody
    is about to score — so the run ends instead, naming the call that ran
    off the end, and everything it did before that is still on disk.
    """

    def _replay(self, tmp_path):
        MockClass, _ = scripted_elf(refuse=True)
        return run_cli(MockClass, *replay_argv(
            JSON_RUN, write_skill(tmp_path, REPAIRING)))

    def test_it_is_refused_naming_the_call_that_ran_off_the_end(
            self, corpus, tmp_path):
        with pytest.raises(SystemExit) as exc:
            self._replay(tmp_path)
        assert "2 model call" in str(exc.value)
        assert "wants call 3" in str(exc.value)

    def test_the_run_still_closes_its_own_stream(self, corpus, tmp_path):
        with pytest.raises(SystemExit):
            self._replay(tmp_path)
        finished = [r for r in records(corpus, replayed(corpus, JSON_RUN).run_id)
                    if r.get("event") == "mission_finished"]
        assert finished and finished[-1]["outcome"] == "incomplete"

    def test_how_far_it_got_is_on_the_replayed_runs_record(
            self, corpus, tmp_path):
        with pytest.raises(SystemExit):
            self._replay(tmp_path)
        drift = replayed(corpus, JSON_RUN).meta["drift"]
        assert drift["served"] == drift["recorded"] == 2


class TestReplayingWithALivePlane:
    def test_live_tools_dispatch_against_the_real_server(self, corpus, tmp_path):
        """`--replay-tools live`: the model is a recording, the plane is not.

        The stub is spawned, `mcp.governed_view` is really called, and the
        result the model is shown is the server's rather than the
        recording's — which is the experiment where the TOOLS are what
        changed.
        """
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *mission_argv(
            "what are the totals?", write_skill(tmp_path),
            "--replay", JSON_RUN, "--replay-tools", TOOLS_LIVE))
        fresh = replayed(corpus, JSON_RUN)
        assert fresh.meta["replay_tools"] == TOOLS_LIVE
        results = [r for r in records(corpus, fresh.run_id)
                   if r.get("event") == "tool_result"]
        assert results and results[0]["ok"] is True

    def test_live_tools_still_need_a_server(self, tmp_path, corpus):
        MockClass, _ = scripted_elf(refuse=True)
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, *replay_argv(
                JSON_RUN, write_skill(tmp_path),
                "--replay-tools", TOOLS_LIVE))
        assert "--mission needs a server" in str(exc.value)


class TestTheSpawningSurface:
    def test_replay_without_mission_is_refused(self, tmp_path):
        MockClass, _ = scripted_elf()
        with pytest.raises(SystemExit):
            run_cli(MockClass, "go", "--replay", JSON_RUN)

    def test_replay_and_resume_together_are_refused(self, tmp_path):
        MockClass, _ = scripted_elf()
        with pytest.raises(SystemExit):
            run_cli(MockClass, "--mission", "--replay", JSON_RUN,
                    "--resume", JSON_RUN)

    def test_the_objective_may_be_omitted_with_replay(self, corpus, tmp_path):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        assert replayed(corpus, JSON_RUN).meta["objective"] == \
            "what are the totals?"

    def test_the_environment_form_is_read(self, corpus, tmp_path, monkeypatch):
        monkeypatch.setenv("MISSION_REPLAY", JSON_RUN)
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, "--mission", "--skill", write_skill(tmp_path))
        assert replayed(corpus, JSON_RUN).meta["replay_of"] == JSON_RUN

    def test_a_run_store_turned_off_is_refused_by_name(self, tmp_path,
                                                       monkeypatch):
        monkeypatch.setenv(RUNS_ENV, "off")
        MockClass, _ = scripted_elf()
        with pytest.raises(SystemExit) as exc:
            run_cli(MockClass, *replay_argv(JSON_RUN, write_skill(tmp_path)))
        assert RUNS_ENV in str(exc.value)
