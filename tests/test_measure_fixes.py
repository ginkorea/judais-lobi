# tests/test_measure_fixes.py — the three defects the first live
# measurement found, and the generic repairs for them

"""What ``EVAL.md`` §12 measured, and what it cost.

Three failures, none of them the model's, all three found only by pointing
the harness at a real endpoint:

1. **The native round trip dropped what it did not understand.**  Every
   mission of the ``native`` row ended ``incomplete`` on the turn after
   the first tool call, with a 400 saying a field was missing from the
   ``functionCall`` it had sent back.  The provider had put an opaque
   field on the call and required it echoed; the loop rebuilt the
   assistant turn out of the name and the arguments.
2. **The catalogue was a cache with a race in it.**  ``the_plane_grew``
   passed in three configurations and failed in two — a tool registered
   during a step reached the next ``step_started`` only if the bridge's
   own thread got there first.
3. **A personality's model name was sent to a local endpoint.**
   ``--provider local`` with no ``--model`` sent ``codestral-latest`` and
   got a 404 naming it.

Each of the three is fixed generically — no provider named, no transport
named, no personality named — and each is tested here at the level the
rule lives at, with an end-to-end case beside the unit one where the bug
was only visible end to end.
"""

import json
from types import SimpleNamespace

import pytest

from core.contracts.schemas import PersonalityConfig, PolicyPack
from core.runtime.backends.anthropic_backend import (
    from_anthropic_messages,
    to_anthropic_messages,
    tool_calls_from_blocks,
)
from core.runtime.backends.base import ToolCallAccumulator, tool_calls_from
from core.runtime.backends.local_backend import LocalBackend
from core.runtime.backends.mistral_backend import MistralBackend
from core.runtime.backends.openai_backend import OpenAIBackend
from core.runtime.messages import assistant_turn
from core.runtime.mission import NATIVE_PROTOCOL, MissionRunner
from core.runtime.provider_config import DEFAULT_MODELS, resolve_model
from core.durable import RunStore
from core.runtime.replay import Recorder, ReplayModel
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.conftest import FakeUnifiedClient

#: The shape the measurement actually hit: a key this repo has never heard
#: of, on the tool call, required back verbatim.  Named after nothing —
#: what matters is that the normaliser cannot know what it means.
SIGNATURE = "thought_signature"
OPAQUE = "Ct8BAdHtim9mZmZmZg=="


@pytest.fixture
def bus():
    b = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    return b


# ══════════════════════════════════════════════════════════════════════
# 1. the native round trip keeps what the provider put on a call
# ══════════════════════════════════════════════════════════════════════


class TestTheNormaliserKeepsWhatItCannotName:
    """One rule, applied by every backend's normaliser."""

    def test_an_unknown_key_on_the_call_survives_normalisation(self):
        calls = tool_calls_from([
            {"id": "c1", "type": "function", SIGNATURE: OPAQUE,
             "function": {"name": "t", "arguments": "{}"}},
        ])
        assert calls[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_an_unknown_key_on_the_function_survives_in_its_own_position(self):
        calls = tool_calls_from([
            {"id": "c1", "function": {"name": "t", "arguments": "{}",
                                      "extra_content": {"g": 1}}},
        ])
        assert calls[0]["extra"] == {"function": {"extra_content": {"g": 1}}}

    def test_nothing_extra_means_no_extra_key_at_all(self):
        """Absent stays absent. The corpus fixtures were recorded before
        any of this existed and must not move because of it."""
        calls = tool_calls_from([
            {"id": "c1", "function": {"name": "t", "arguments": "{}"}}])
        assert "extra" not in calls[0]

    def test_a_none_valued_field_is_not_echoed_back_as_a_null(self):
        """An SDK dumps its unset optionals as `None`; a wall of nulls sent
        back at a server is not fidelity."""
        calls = tool_calls_from([
            {"id": "c1", "nothing": None,
             "function": {"name": "t", "arguments": "{}"}}])
        assert "extra" not in calls[0]

    def test_an_sdk_model_is_read_the_same_way_as_a_dict(self):
        """The OpenAI backend hands over pydantic models, not dicts."""
        model = SimpleNamespace(
            model_dump=lambda: {"id": "c1", "type": "function",
                                SIGNATURE: OPAQUE,
                                "function": {"name": "t",
                                             "arguments": "{}"}},
            id="c1",
            function=SimpleNamespace(name="t", arguments="{}"),
        )
        assert tool_calls_from([model])[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_the_assistant_turn_gives_it_back_verbatim(self):
        call = tool_calls_from([
            {"id": "c1", SIGNATURE: OPAQUE,
             "function": {"name": "t", "arguments": '{"q": "x"}'}}])[0]
        turn = assistant_turn("", [call])
        assert turn["tool_calls"] == [
            {"id": "c1", "type": "function",
             "function": {"name": "t", "arguments": '{"q": "x"}'},
             SIGNATURE: OPAQUE},
        ]

    def test_a_function_level_field_goes_back_on_the_function(self):
        call = tool_calls_from([
            {"id": "c1", "function": {"name": "t", "arguments": "{}",
                                      "extra_content": {"g": 1}}}])[0]
        turn = assistant_turn("", [call])
        assert turn["tool_calls"][0]["function"] == {
            "name": "t", "arguments": "{}", "extra_content": {"g": 1}}
        assert "extra_content" not in turn["tool_calls"][0]

    def test_a_turn_with_nothing_extra_is_the_bytes_it_always_was(self):
        turn = assistant_turn("said", [
            {"id": "c1", "name": "t", "arguments": {"q": "x"}}])
        assert json.dumps(turn) == json.dumps({
            "role": "assistant", "content": "said",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "t",
                                         "arguments": '{"q": "x"}'}}]})

    def test_no_calls_means_no_tool_calls_key(self):
        assert assistant_turn("just text") == {
            "role": "assistant", "content": "just text"}

    def test_the_extra_is_never_looked_inside(self):
        """Whatever it is, it round trips: a list, a nested object, a
        number. The normaliser has no opinion about any of them."""
        weird = {"a": [1, {"b": None}], "c": 0.5, "d": "x"}
        call = tool_calls_from([
            {"id": "c1", "vendor": weird,
             "function": {"name": "t", "arguments": "{}"}}])[0]
        assert assistant_turn("", [call])["tool_calls"][0]["vendor"] == weird


class TestEveryBackendsNormaliserKeepsIt:
    """The rule has one owner; each backend applies it."""

    def _openai(self, tool_calls):
        message = SimpleNamespace(content="", tool_calls=tool_calls)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                choices=[SimpleNamespace(message=message)], usage=None))))
        backend = OpenAIBackend(openai_client=client)
        backend.chat("m", [{"role": "user", "content": "hi"}])
        return backend.last_tool_calls

    def test_openai(self):
        calls = self._openai([
            {"id": "c1", SIGNATURE: OPAQUE,
             "function": {"name": "t", "arguments": "{}"}}])
        assert calls[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_local(self, monkeypatch):
        backend = LocalBackend(endpoint="http://x/v1")
        payload = {"choices": [{"message": {
            "content": "",
            "tool_calls": [{"id": "c1", SIGNATURE: OPAQUE,
                            "function": {"name": "t",
                                         "arguments": "{}"}}]}}]}
        monkeypatch.setattr(
            backend, "_post",
            lambda body, stream=False: SimpleNamespace(
                status_code=200, json=lambda: payload, text=""))
        monkeypatch.setattr(backend, "_raise_for_status",
                            lambda res, body: None)
        backend._complete({"messages": []})
        assert backend.last_tool_calls[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_mistral(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        backend = MistralBackend()
        payload = {"choices": [{"message": {
            "content": "",
            "tool_calls": [{"id": "c1", SIGNATURE: OPAQUE,
                            "function": {"name": "t",
                                         "arguments": "{}"}}]}}]}
        monkeypatch.setattr(
            backend, "_post",
            lambda body: SimpleNamespace(
                status_code=200, json=lambda: payload, text=""))
        monkeypatch.setattr(backend, "_raise_for_status", lambda res: None)
        backend._complete({"messages": []})
        assert backend.last_tool_calls[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_anthropic_blocks(self):
        """A different wire shape, the same rule: Anthropic puts the name
        and the input on the block, so a block's unknown keys are the
        call's."""
        calls = tool_calls_from_blocks([
            {"type": "tool_use", "id": "c1", "name": "t", "input": {},
             "vendor_note": "keep me"}])
        assert calls[0]["extra"] == {"vendor_note": "keep me"}

    def test_anthropic_puts_it_back_on_the_block(self):
        _system, out = to_anthropic_messages([
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "vendor_note": "keep me",
                             "function": {"name": "t",
                                          "arguments": "{}"}}]}])
        assert out[0]["content"][0]["vendor_note"] == "keep me"

    def test_the_anthropic_round_trip_keeps_it(self):
        blocks = [{"type": "tool_use", "id": "c1", "name": "t", "input": {},
                   "vendor_note": "keep me"}]
        back = from_anthropic_messages(
            [{"role": "assistant", "content": blocks}])
        assert back[0]["tool_calls"][0]["vendor_note"] == "keep me"

    def test_a_streamed_call_folds_it_in_from_whichever_frame_carried_it(self):
        """The opaque field may ride the frame that opens the call or the
        one that closes it; the reassembled call has both."""
        acc = ToolCallAccumulator()
        acc.add([{"index": 0, "id": "c1",
                  "function": {"name": "t", "arguments": '{"q":'}}])
        acc.add([{"index": 0, SIGNATURE: OPAQUE,
                  "function": {"arguments": ' "x"}'}}])
        call = acc.result()[0]
        assert call["arguments"] == {"q": "x"}
        assert call["extra"] == {SIGNATURE: OPAQUE}

    def test_a_streamed_call_with_nothing_extra_has_no_extra(self):
        acc = ToolCallAccumulator()
        acc.add([{"index": 0, "id": "c1",
                  "function": {"name": "t", "arguments": "{}"}}])
        assert "extra" not in acc.result()[0]

    def test_index_is_not_mistaken_for_a_providers_own_field(self):
        """`index` is how a fragment says where it goes. Echoing it back on
        the assembled call would be this repo inventing a field."""
        acc = ToolCallAccumulator()
        acc.add([{"index": 3, "id": "c1",
                  "function": {"name": "t", "arguments": "{}"}}])
        assert "extra" not in acc.result()[0]


class NativeModel:
    """A constrained decoder: the reply IS the call. See test_mission.py."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []
        self.last_tool_calls = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        self.last_tool_calls = list(
            self.turns.pop(0) if self.turns else
            [{"id": "c_end", "name": "mission_answer",
              "arguments": {"text": "done"}}])
        return ""

    def tool_calls(self):
        return list(self.last_tool_calls)


class TestTheLoopSendsItBack:
    """End to end, which is the only level the 400 was visible at."""

    def _run(self, bus, *turns):
        model = NativeModel(*turns)
        runner = MissionRunner(model, bus, ["catalog.search"],
                               protocol=NATIVE_PROTOCOL, store_tool="",
                               tool_calls_fn=model.tool_calls)
        runner.run("find things")
        return model

    def test_the_next_request_quotes_the_opaque_field(self):
        model = self._run(
            self.bus_with_search(),
            [{"id": "c1", "name": "catalog.search",
              "arguments": {"q": "x"}, "extra": {SIGNATURE: OPAQUE}}])
        turn = next(m for m in model.seen[1] if m["role"] == "assistant")
        assert turn["tool_calls"][0][SIGNATURE] == OPAQUE

    def test_without_one_the_turn_is_unchanged(self):
        model = self._run(
            self.bus_with_search(),
            [{"id": "c1", "name": "catalog.search", "arguments": {"q": "x"}}])
        turn = next(m for m in model.seen[1] if m["role"] == "assistant")
        assert turn["tool_calls"] == [
            {"id": "c1", "type": "function",
             "function": {"name": "catalog.search",
                          "arguments": '{"q": "x"}'}}]

    @staticmethod
    def bus_with_search():
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(
            ToolDescriptor(tool_name="catalog.search",
                           description="Search the catalogue."),
            lambda **kw: (0, "hits", ""),
        )
        return b


class TestAReplayCarriesItThrough:
    """The reverse direction: a call read back off a recording.

    A `Resumption` cannot — a `tool_call_id` and anything beside it are the
    provider's and never travelled on the event stream, which
    `LOST_NATIVE_IDS` says out loud. A **replay** reads the model log
    itself, so what the provider sent is still there and has to survive the
    round trip through it.
    """

    def test_the_model_log_keeps_it_and_the_replay_gives_it_back(self, tmp_path):
        store = RunStore(tmp_path / "store")
        run = store.create()
        recorder = Recorder(store, run.run_id, side=lambda: (None, [
            {"id": "c1", "name": "t", "arguments": {},
             "extra": {SIGNATURE: OPAQUE}}]))
        messages = [{"role": "user", "content": "go"}]
        record = recorder.model_call(
            "mission", {"messages": messages, "extra": {}}, "")
        assert record["reply"]["tool_calls"][0]["extra"] == {SIGNATURE: OPAQUE}

        model = ReplayModel([record])
        model.serving("mission")(messages)
        assert model.last_tool_calls[0]["extra"] == {SIGNATURE: OPAQUE}

    def test_and_a_turn_rebuilt_from_it_still_carries_it(self, tmp_path):
        """The whole point of keeping it on the record: the replayed loop
        rebuilds the same assistant turn the live one sent."""
        call = {"id": "c1", "name": "t", "arguments": {},
                "extra": {SIGNATURE: OPAQUE}}
        assert assistant_turn("", [call])["tool_calls"][0][SIGNATURE] == OPAQUE


# ══════════════════════════════════════════════════════════════════════
# 2. the catalogue the model reads is the plane at that boundary
# ══════════════════════════════════════════════════════════════════════


class TestTheBusCanBePulled:
    """`follow`/`resync`: the bus learns that some entries have an
    upstream, and nothing more than that."""

    def test_a_bus_with_no_source_says_nothing_changed(self, bus):
        assert bus.resync() is False

    def test_a_source_that_registers_something_is_a_change(self, bus):
        bus.follow(lambda: bus.register(
            ToolDescriptor(tool_name="late", description="x"),
            lambda **kw: (0, "", "")))
        assert bus.resync() is True
        assert "late" in bus.list_tools()

    def test_a_source_that_changes_nothing_is_not_a_change(self, bus):
        bus.follow(lambda: None)
        assert bus.resync() is False

    def test_a_source_that_raises_leaves_the_registry_standing(self, bus):
        def boom():
            raise RuntimeError("server went away")

        bus.follow(boom)
        assert bus.resync() is False
        assert "catalog.search" in bus.list_tools()


class TestTheStepBoundaryPullsTheCatalogue:
    """The race, closed.

    A bridge re-lists on its own thread, so a tool registered during step
    N reaches the bus at a time nobody controls. Here the growth lands
    ONLY when somebody pulls — which is the failing half of the measured
    run, made deterministic — and the next `step_started` has to carry it
    every single time.
    """

    LATE = "catalog.late"

    def growing_bus(self):
        """A bus whose server grows a tool that only a pull will find.

        `catalog.grow` tells the "server" to register; the registry learns
        about it at the next `resync` and not before, which is exactly what
        a notification that has not been processed yet looks like.
        """
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        pending = []

        def grow_it(**kw):
            pending.append(self.LATE)
            return 0, "the server registered one more tool", ""

        b.register(
            ToolDescriptor(tool_name="catalog.grow",
                           description="Ask the server to register a tool."),
            grow_it,
        )

        def pull():
            while pending:
                b.register(
                    ToolDescriptor(tool_name=pending.pop(),
                                   description="Registered after the run "
                                               "began."),
                    lambda **kw: (0, "arrived late", ""),
                )

        b.follow(pull)
        return b

    def _run(self, *replies):
        events = []
        model = _Scripted(*replies)
        runner = MissionRunner(model, self.growing_bus(), ["catalog.grow"],
                               observer=events.append)
        transcript = runner.run("grow the plane")
        return runner, model, transcript, events

    @pytest.mark.parametrize("attempt", range(20))
    def test_the_next_step_started_carries_it_every_time(self, attempt):
        """Twenty times, because the thing being fixed is a race and one
        green run of a race proves nothing."""
        _r, _m, _t, events = self._run(
            _call("catalog.grow"), '{"answer": "noted"}')
        steps = [r for r in events if r["event"] == "step_started"]
        assert "catalogue" not in steps[0]
        assert self.LATE in steps[1]["catalogue"]

    def test_the_system_turn_the_model_reads_carries_it(self):
        """The failure was not that the model could not call the tool — it
        was that the model read a catalogue without it and correctly said
        so."""
        _r, model, _t, _e = self._run(
            _call("catalog.grow"), '{"answer": "noted"}')
        assert self.LATE not in model.seen[0][0]["content"]
        assert self.LATE in model.seen[1][0]["content"]

    def test_and_it_can_then_be_called(self):
        _r, _m, transcript, _e = self._run(
            _call("catalog.grow"), _call(self.LATE), '{"answer": "used it"}')
        assert [step.tool for step in transcript.steps] == [
            "catalog.grow", self.LATE, None]
        assert transcript.steps[1].output == "arrived late"

    def test_a_bus_that_cannot_be_pulled_still_runs(self):
        """Every bus that has no server behind it, which is most of them."""
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])))
        b.register(ToolDescriptor(tool_name="t", description="x"),
                   lambda **kw: (0, "ok", ""))
        model = _Scripted(_call("t"), '{"answer": "fine"}')
        transcript = MissionRunner(model, b, ["t"]).run("go")
        assert transcript.outcome == "answered"


class TestTheBridgeIsWhatGetsPulled:
    """The MCP end of the same seam, without a server."""

    class FakeClient:
        transport = SimpleNamespace(uses_network=False, name="stub")

        def __init__(self, *lists):
            self.lists = list(lists)
            self.refreshed = []
            self._on_tools_changed = None

        def list_tools(self, refresh=False, timeout=None):
            self.refreshed.append((refresh, timeout))
            if refresh and len(self.lists) > 1:
                self.lists.pop(0)
            return list(self.lists[0])

    def _spec(self, name):
        from core.tools.mcp_client import McpToolSpec
        return McpToolSpec(name=name, description="", input_schema={})

    def test_following_registers_a_pull_on_the_bus(self, bus):
        from core.tools.mcp_client import McpToolBridge
        client = self.FakeClient([self._spec("one")],
                                 [self._spec("one"), self._spec("two")])
        bridge = McpToolBridge(client, bus)
        bridge.sync()
        bridge.follow_changes()
        assert "mcp.two" not in bus.list_tools()
        assert bus.resync() is True
        assert "mcp.two" in bus.list_tools()

    def test_the_pull_is_a_refresh_and_carries_a_bound(self, bus, monkeypatch):
        from core.tools import mcp_client
        monkeypatch.setenv(mcp_client.RELIST_TIMEOUT_ENV, "0.25")
        client = self.FakeClient([self._spec("one")])
        bridge = mcp_client.McpToolBridge(client, bus)
        bridge.follow_changes()
        bus.resync()
        assert client.refreshed[-1] == (True, 0.25)

    def test_a_bridge_that_cannot_answer_in_time_keeps_the_last_set(self, bus):
        from core.tools.mcp_client import McpToolBridge

        class Slow(self.FakeClient):
            def list_tools(self, refresh=False, timeout=None):
                if refresh:
                    raise TimeoutError("the server did not answer")
                return list(self.lists[0])

        bridge = McpToolBridge(Slow([self._spec("one")]), bus)
        bridge.sync()
        assert bridge.sync(refresh=True) == ["mcp.one"]
        assert "mcp.one" in bus.list_tools()

    def test_a_bus_that_cannot_be_followed_keeps_the_push(self):
        from core.tools.mcp_client import McpToolBridge
        plain = SimpleNamespace(register=lambda *a: None,
                                unregister=lambda *a: True)
        client = self.FakeClient([self._spec("one")])
        McpToolBridge(client, plain).follow_changes()
        assert client._on_tools_changed is not None

    def test_the_default_bound_is_used_when_nothing_says_otherwise(
            self, monkeypatch):
        from core.tools import mcp_client
        monkeypatch.delenv(mcp_client.RELIST_TIMEOUT_ENV, raising=False)
        assert mcp_client.relist_timeout() == mcp_client.DEFAULT_RELIST_TIMEOUT

    @pytest.mark.parametrize("value", ["0", "-1", "nonsense", ""])
    def test_an_unusable_bound_is_the_default_and_never_no_wait(
            self, monkeypatch, value):
        """A zero here would turn the guarantee off silently."""
        from core.tools import mcp_client
        monkeypatch.setenv(mcp_client.RELIST_TIMEOUT_ENV, value)
        assert mcp_client.relist_timeout() == mcp_client.DEFAULT_RELIST_TIMEOUT


# ══════════════════════════════════════════════════════════════════════
# 3. --provider local asks the endpoint, never the personality
# ══════════════════════════════════════════════════════════════════════


class TestTheModelNameBelongsToWhoeverServesIt:
    """A model name is a name in ONE provider's catalogue."""

    def test_an_explicit_model_always_wins(self):
        assert resolve_model("local", "named-it", "a-default", "mistral",
                             served=lambda: "served") == "named-it"

    def test_a_default_chosen_for_another_provider_is_not_sent(self):
        """The measured defect: `--provider local` on a persona whose
        provider is a hosted one sent that provider's model name."""
        assert resolve_model("local", None, "a-hosted-model", "mistral",
                             served=lambda: "served-here") == "served-here"

    def test_and_then_the_endpoint_is_asked(self):
        assert resolve_model("local", None, "a-hosted-model", "mistral",
                             served=lambda: "served-here") == "served-here"

    def test_a_default_chosen_for_this_provider_is_honoured(self):
        """A persona that says `default_provider = local` and names the
        model its endpoint serves has named it — see PLATFORMS.md."""
        assert resolve_model("local", None, "what-we-serve", "local",
                             served=lambda: "probed") == "what-we-serve"

    def test_a_personality_that_named_no_provider_is_still_heard(self):
        assert resolve_model("local", None, "whatever-you-are", None,
                             served=lambda: "probed") == "whatever-you-are"

    def test_with_nothing_to_ask_the_last_resort_is_the_declared_default(self):
        assert resolve_model("local", None, "a-hosted-model", "mistral",
                             served=lambda: "") == DEFAULT_MODELS["local"]

    def test_an_endpoint_that_is_down_does_not_stop_the_run(self):
        def boom():
            raise OSError("connection refused")

        assert resolve_model("local", None, "a-hosted-model", "mistral",
                             served=boom) == DEFAULT_MODELS["local"]

    def test_a_hosted_provider_takes_its_own_personalitys_default(self):
        assert resolve_model("mistral", None, "codestral-latest",
                             "mistral") == "codestral-latest"

    def test_a_hosted_provider_does_not_take_another_ones(self):
        """The same defect in the other direction, and the same answer: a
        model name is not portable between providers."""
        assert resolve_model("anthropic", None, "codestral-latest",
                             "mistral") == DEFAULT_MODELS["anthropic"]

    def test_and_falls_back_to_the_declared_one(self):
        assert resolve_model("openai", None, None) == DEFAULT_MODELS["openai"]


class TestTheAgentAsksInThatOrder:
    """Through `Agent`, which is where the wrong name was being chosen."""

    CONFIG = PersonalityConfig(
        name="stub", system_message="s", examples=[],
        default_model="codestral-latest", default_provider="mistral",
        env_path="/nonexistent",
    )

    def _agent(self, memory, fake_tools, model=None, provider="local",
               served="probed-model"):
        from core.agent import Agent
        client = FakeUnifiedClient()
        client.default_model = served
        return Agent(self.CONFIG, model=model, provider=provider,
                     debug=False, client=client, memory=memory,
                     tools=fake_tools)

    def test_with_nothing_set_the_endpoint_decides(self, memory, fake_tools):
        assert self._agent(memory, fake_tools).model == "probed-model"

    def test_the_personalitys_default_is_never_sent(self, memory, fake_tools):
        """It was chosen for another provider; the endpoint answered."""
        agent = self._agent(memory, fake_tools)
        assert agent.model != self.CONFIG.default_model

    def test_an_explicit_model_wins(self, memory, fake_tools):
        agent = self._agent(memory, fake_tools, model="asked-for-this")
        assert agent.model == "asked-for-this"

    def test_a_client_that_cannot_be_asked_falls_to_the_last_resort(
            self, memory, fake_tools):
        agent = self._agent(memory, fake_tools, served="")
        assert agent.model == DEFAULT_MODELS["local"]

    def test_a_hosted_provider_is_untouched(self, memory, fake_tools):
        agent = self._agent(memory, fake_tools, provider="mistral")
        assert agent.model == "codestral-latest"

    def test_a_personality_written_for_the_endpoint_keeps_its_model(
            self, memory, fake_tools):
        """The other half of the rule, and the documented way a deployment
        names its model: `PLATFORMS.md`'s persona table."""
        from core.agent import Agent
        config = PersonalityConfig(
            name="stub", system_message="s", examples=[],
            default_model="what-we-serve", default_provider="local",
            env_path="/nonexistent",
        )
        client = FakeUnifiedClient()
        client.default_model = "probed-model"
        agent = Agent(config, provider="local", debug=False, client=client,
                      memory=memory, tools=fake_tools)
        assert agent.model == "what-we-serve"


class TestTheLocalBackendOwnsTheMiddleOfTheOrder:
    """`LOCAL_MODEL`, then `GET /models` — asked of the backend, because a
    second reader of `LOCAL_MODEL` is a second owner of the order."""

    def test_local_model_wins_over_the_probe(self, monkeypatch):
        monkeypatch.setenv("LOCAL_MODEL", "from-the-environment")
        backend = LocalBackend(endpoint="http://x/v1")
        assert backend.model == "from-the-environment"

    def test_otherwise_the_listing_decides(self, monkeypatch):
        monkeypatch.delenv("LOCAL_MODEL", raising=False)
        session = SimpleNamespace(get=lambda url, headers=None, timeout=None:
                                  SimpleNamespace(
                                      raise_for_status=lambda: None,
                                      json=lambda: {"data": [
                                          {"id": "what-is-served"}]}))
        backend = LocalBackend(endpoint="http://x/v1", session=session)
        assert backend.model == "what-is-served"

    def test_the_client_reports_it_as_the_default(self, monkeypatch):
        monkeypatch.setenv("LOCAL_MODEL", "from-the-environment")
        from core.unified_client import UnifiedClient
        client = UnifiedClient(provider_override="local")
        assert client.default_model == "from-the-environment"

    def test_a_backend_with_no_opinion_reports_nothing(self):
        from core.unified_client import UnifiedClient
        client = UnifiedClient(backend=SimpleNamespace())
        assert client.default_model == ""


# ── small helpers, kept at the bottom ───────────────────────────────────


class _Scripted:
    """Replays canned JSON-protocol replies and records what it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


def _call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})
