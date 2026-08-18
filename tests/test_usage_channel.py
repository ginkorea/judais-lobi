# tests/test_usage_channel.py

"""Whose call was that? — the two side channels, under two children.

``chat`` returns a string, so what a call **cost** and what it **decided**
come back beside it: ``Backend.last_usage`` and ``Backend.last_tool_calls``,
one slot each, written when the call finishes and read by the caller when
it is next scheduled.

One mission in flight and the gap between those two moments holds nothing.
Two children of one ``Run``, gathered, hold a whole sibling call: they
share the client by identity (:meth:`~core.runtime.run.Run.child` shares
the model's ``ask`` and ``usage_fn`` and replaces only the ledger), and
each call runs on its own worker thread.  A sibling that finished inside
the gap overwrote both slots, and then one child was billed for the
other's call and — under the native protocol — quoted the other's tool
calls back to the model as its own.  Measured before the fix: a child
whose call the provider priced at 100 prompt tokens reported 1.

The fix is :func:`core.runtime.backends.base.capturing`.
:meth:`~core.runtime.run.Run._model_reply` opens a slot around the call
and its drain and hands it back **with the reply**; ``Backend``'s two
setters file the values there as well as on the object, so no backend
grew a line.  A source that is not a ``Backend`` — a replayed run, a
library caller's client, a test's function — fills nothing, and the
caller falls back to ``usage_fn``/``tool_calls_fn`` exactly as before.

The gate below is what makes the clobber a proof rather than a
probability: A writes its usage and does not return until B's call has
finished and overwritten the slot.
"""

import asyncio
import json
import threading

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.backends.base import (
    Backend, BackendCapabilities, SideChannels, Usage, capturing,
)
from core.runtime.mission import NATIVE_PROTOCOL
from core.runtime.run import (
    Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.usage import Ledger
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox

#: Long enough for a loaded machine, short enough that a deadlock fails.
GATE = 20.0

#: What each child's one call is priced at.  Wildly different so that
#: "A was billed for B's call" is unmistakable in the record and so that
#: the turn's total cannot be right by accident.
COST = {"A": 100, "B": 1}


class Gated(Backend):
    """A real ``Backend`` — which is what a deployment's client wraps —
    with one ``last_usage`` slot and one ``last_tool_calls`` slot.

    Deliberately a subclass and not a stand-in with the two attributes:
    the whole fix is that ``Backend``'s setters file the values with the
    call that produced them, and a stand-in would test the fallback.

    ``chat`` holds A inside the call until B has finished, which is the
    interleaving that used to lose: A's numbers are written, B's numbers
    replace them, and only then is A's caller allowed to read.
    """

    provider_name = "gated"

    def __init__(self, replies):
        self.replies = replies
        self.last_usage = None
        self.last_tool_calls = []
        self.a_wrote = threading.Event()
        self.b_wrote = threading.Event()
        self.asked = []

    @property
    def capabilities(self):
        return BackendCapabilities(supports_tool_calls=True)

    @staticmethod
    def whose(messages):
        text = "\n".join(str(m.get("content", "")) for m in messages)
        return "A" if "mission A" in text else "B"

    def chat(self, model, messages, stream=False, **extra):
        who = self.whose(messages)
        self.asked.append(who)
        # Cleared first, then filled — every backend in this tree.
        self.last_usage = None
        self.last_tool_calls = []
        cost = COST[who]
        self.last_usage = Usage(prompt_tokens=cost, completion_tokens=0,
                                total_tokens=cost)
        reply, calls = self.replies[who]
        self.last_tool_calls = calls
        if who == "A":
            self.a_wrote.set()
            assert self.b_wrote.wait(GATE), "B never finished its call"
        else:
            assert self.a_wrote.wait(GATE), "A never wrote its numbers"
            self.b_wrote.set()
        return reply


def answered(who):
    return json.dumps({"answer": f"{who} is done"}), []


def bus_with(*tools):
    bus = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
        sandbox=NoneSandbox())
    for name in tools:
        bus.register(
            ToolDescriptor(tool_name=name, description=f"the {name} tool"),
            lambda _name=name, **kw: (0, f"{_name} ran", ""))
    return bus


def parent_run(backend, bus, records, **model_kw):
    model = Model(ask=lambda messages, **kw: backend.chat("m", messages),
                  usage_fn=lambda: backend.last_usage,
                  tool_calls_fn=lambda: list(backend.last_tool_calls or []),
                  streaming=False, ledger=Ledger(), **model_kw)
    return Run(
        personality=Personality(system_message="You are Tai."),
        plane=ToolPlane(bus=bus, offered=list(bus.list_tools())),
        bounds=Bounds(max_steps=3),
        store=Store(),
        observer=Observer(records.append),
        model=model,
    )


def gather_two(parent):
    """The two children of one run, gathered — ``ROADMAP.md`` §2.6.2's
    shape and the one that used to lose."""
    ledgers = {"A": Ledger(), "B": Ledger()}

    async def main():
        children = {who: parent.child(branch=who.lower(), ledger=ledger)
                    for who, ledger in ledgers.items()}
        assert (children["A"].model.usage_fn
                is children["B"].model.usage_fn), "one side channel, two children"
        return await asyncio.gather(
            *(child.arun(f"mission {who}")
              for who, child in children.items()))

    transcripts = asyncio.run(asyncio.wait_for(main(), GATE))
    return ledgers, transcripts


class TestEachChildIsBilledForItsOwnCall:
    @pytest.fixture
    def gathered(self):
        backend = Gated({"A": answered("A"), "B": answered("B")})
        records = []
        ledgers, _ = gather_two(parent_run(backend, bus_with(), records))
        return backend, ledgers, records

    def test_the_expensive_call_is_billed_to_the_child_that_made_it(
            self, gathered):
        _backend, ledgers, _records = gathered
        assert ledgers["A"].as_record()["prompt_tokens"] == COST["A"]

    def test_the_cheap_call_is_not_billed_the_expensive_one_either(
            self, gathered):
        """Stated separately: a fix that simply handed both children the
        FIRST value would pass the assertion above and fail this one."""
        _backend, ledgers, _records = gathered
        assert ledgers["B"].as_record()["prompt_tokens"] == COST["B"]

    def test_the_turn_is_billed_the_sum_and_not_twice_the_cheap_one(
            self, gathered):
        """The number an operator is shown.  Before the fix both children
        read the slot B had just written, so a turn that cost 101 tokens
        was invoiced 2."""
        _backend, ledgers, _records = gathered
        total = Ledger()
        for ledger in ledgers.values():
            total.absorb(ledger)
        assert total.as_record()["total_tokens"] == sum(COST.values())
        assert total.as_record()["calls"] == 2

    def test_the_two_calls_really_did_overlap(self, gathered):
        """Otherwise the assertions above are about a serial run, which was
        never in doubt."""
        backend, _ledgers, _records = gathered
        assert backend.a_wrote.is_set() and backend.b_wrote.is_set()
        assert sorted(backend.asked) == ["A", "B"]

    def test_the_record_each_child_emitted_carries_its_own_cost(
            self, gathered):
        """The wire, not only the ledger: ``usage`` rides the record the
        step emitted, and a consumer summing that field must get the same
        number the totals do."""
        _backend, _ledgers, records = gathered
        by_branch = {r["branch"]: r for r in records
                     if r["event"] == "answer" and "usage" in r}
        assert by_branch["a"]["usage"]["prompt_tokens"] == COST["A"]
        assert by_branch["b"]["usage"]["prompt_tokens"] == COST["B"]


class TestEachChildDispatchesItsOwnDecision:
    """The other side channel, and the one where a clobber is worse than a
    wrong number: ``last_tool_calls`` is what the turn is about to RUN."""

    def _run(self):
        backend = Gated({
            "A": ("", [{"id": "a1", "name": "alpha", "arguments": {}}]),
            "B": ("", [{"id": "b1", "name": "beta", "arguments": {}}]),
        })
        # The second call each child makes answers, so the mission ends.
        chat = backend.chat

        def once_then_answer(model, messages, stream=False, **extra):
            who = Gated.whose(messages)
            if who in done:
                backend.last_usage = None
                backend.last_tool_calls = []
                return json.dumps({"answer": f"{who} is done"})
            done.add(who)
            return chat(model, messages)

        done = set()
        backend.chat = once_then_answer
        records = []
        run = parent_run(backend, bus_with("alpha", "beta"), records,
                         protocol=NATIVE_PROTOCOL)
        gather_two(run)
        return records

    def test_neither_child_ran_its_siblings_tool(self):
        records = self._run()
        dispatched = {r["branch"]: r["tool"] for r in records
                      if r["event"] == "tool_call"}
        assert dispatched == {"a": "alpha", "b": "beta"}


class TestASourceThatIsNotABackendStillWorks:
    """A replayed run, a library caller's client and every ``ask`` that is
    a plain function fill no slot.  They fall back to ``usage_fn``, which
    is what they always used, and they are serial."""

    def test_a_plain_client_with_the_attribute_is_read_as_before(self):
        class PlainClient:
            last_usage = Usage(prompt_tokens=7, completion_tokens=1,
                               total_tokens=8)

        client = PlainClient()
        records = []
        model = Model(ask=lambda messages, **kw: json.dumps({"answer": "hi"}),
                      usage_fn=lambda: client.last_usage, streaming=False,
                      ledger=Ledger())
        run = Run(
            personality=Personality(system_message="You are Tai."),
            plane=ToolPlane(bus=bus_with(), offered=[]),
            bounds=Bounds(max_steps=2), store=Store(),
            observer=Observer(records.append), model=model)
        run.run("say hello")
        assert model.ledger.as_record()["total_tokens"] == 8

    def test_an_unfilled_capture_does_not_shadow_the_callable(self):
        """The distinction the ``filled`` flag exists for: a slot nobody
        wrote to means "the answerer was not a Backend", not "the provider
        reported nothing"."""
        model = Model(ask=lambda messages: "", streaming=False,
                      usage_fn=lambda: Usage(prompt_tokens=5,
                                             completion_tokens=0,
                                             total_tokens=5))
        ledger = Ledger()
        assert model.spend(ledger, SideChannels()) == {
            "usage": {"prompt_tokens": 5, "completion_tokens": 0,
                      "total_tokens": 5}}


class TestSilenceIsStillSilence:
    def test_a_backend_that_reported_nothing_puts_no_zeros_on_the_wire(self):
        """A filled slot holding ``None`` is a provider that said nothing,
        and it must stay an ABSENT field rather than become three zeros —
        the rule ``core.runtime.usage`` is built on."""
        model = Model(ask=lambda messages: "", streaming=False,
                      usage_fn=lambda: Usage(prompt_tokens=9,
                                             completion_tokens=9,
                                             total_tokens=18))
        slot = SideChannels(usage=None, filled=True)
        ledger = Ledger()
        assert model.spend(ledger, slot) == {}
        assert ledger.calls == 0

    def test_a_source_that_throws_still_cannot_end_a_mission(self):
        def angry():
            raise RuntimeError("the client is having a day")

        model = Model(ask=lambda messages: "", usage_fn=angry,
                      streaming=False)
        assert model.spend(Ledger()) == {}


class TestTheSlotIsTheCallsAndNobodyElses:
    def test_a_backends_write_reaches_the_slot_that_is_open(self):
        class Quiet(Backend):
            provider_name = "quiet"

            @property
            def capabilities(self):
                return BackendCapabilities()

            def chat(self, model, messages, stream=False, **extra):
                return ""

        backend = Quiet()
        with capturing() as slot:
            backend.last_usage = Usage(prompt_tokens=3, completion_tokens=0,
                                       total_tokens=3)
            backend.last_tool_calls = [{"id": "x", "name": "t",
                                        "arguments": {}}]
        assert slot.filled
        assert slot.usage.prompt_tokens == 3
        assert [call["name"] for call in slot.tool_calls] == ["t"]

    def test_the_attribute_still_answers_the_library_caller(self):
        """``usage_fn`` reads ``last_usage`` and half a dozen library
        callers read it directly.  Filing a value with the call must not
        stop the object reporting it."""
        class Quiet(Backend):
            provider_name = "quiet"

            @property
            def capabilities(self):
                return BackendCapabilities()

            def chat(self, model, messages, stream=False, **extra):
                return ""

        backend = Quiet()
        with capturing():
            backend.last_usage = Usage(prompt_tokens=4, completion_tokens=0,
                                       total_tokens=4)
        assert backend.last_usage.prompt_tokens == 4
        # And outside a capture, which is every call a chat session makes.
        backend.last_usage = None
        assert backend.last_usage is None

    def test_a_write_outside_a_slot_reaches_nothing_and_raises_nothing(self):
        class Quiet(Backend):
            provider_name = "quiet"

            @property
            def capabilities(self):
                return BackendCapabilities()

            def chat(self, model, messages, stream=False, **extra):
                return ""

        with capturing() as slot:
            pass
        Quiet().last_usage = Usage(prompt_tokens=1, completion_tokens=1,
                                   total_tokens=2)
        assert not slot.filled and slot.usage is None

    def test_two_backends_do_not_share_a_tool_call_list(self):
        """The class default is one list.  It was never mutated in place
        and it still is not — the property rebinds."""
        class Quiet(Backend):
            provider_name = "quiet"

            @property
            def capabilities(self):
                return BackendCapabilities()

            def chat(self, model, messages, stream=False, **extra):
                return ""

        one, two = Quiet(), Quiet()
        one.last_tool_calls = [{"id": "1", "name": "a", "arguments": {}}]
        assert two.last_tool_calls == []
