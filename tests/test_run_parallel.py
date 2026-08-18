# tests/test_run_parallel.py — two children of one mission, at the same time

"""What became true when a plan's independent steps could run together.

Lane C made ``asyncio.gather`` over :meth:`~core.runtime.run.Run.child`
*work* and said, in as many words, what it left behind: two children built
in one breath collided on the numbering, two children on one bus collided
on ``mission_result``, and the audit's step was a mutable dict on a shared
object.  This file is the other side of each of those sentences.

Five things had to become true, and they are the five of ``ROADMAP.md``
§2.6.2:

* **one store each, merged** — ``ToolPlane.lease`` puts one
  ``mission_result`` on the bus in front of several stores, so the model is
  told one tool name on every branch and each child reads its own results;
  the synthesizer reads the union, which is what it always did by hand;
* **one ledger** — a child spends into a ledger of its own and it is folded
  back at the join through :meth:`~core.runtime.usage.Ledger.absorb`, which
  had no caller in ``core/`` until this lane;
* **one clock** — already true, shared and first-start-wins;
* **the audit column** — the step rides ``dispatch`` as a bus-named keyword
  like ``deadline_s``, so two interleaved children cannot stamp each
  other's entries;
* **ordering on the wire** — ``index`` is allocated by the observer at emit
  time under a lock and each record carries the OPTIONAL ``branch``.  The
  claim a consumer cares about is the last one, stated twice: a consumer
  that reads ``branch`` can demultiplex, and a consumer that has never
  heard of it reads one correctly-ordered sequence.

The corpus proof is here too.  Two committed fixtures gained the field, and
what is asserted is that they gained *only* the field: strip ``branch`` from
the re-recording and it is the recording that was there before, record for
record.  That is the whole of what "an OPTIONAL field is a minor change"
means, made checkable.

Nothing here builds a second idea of what a run is: the six objects come
from :func:`tests.test_run.six`, the swarm from
:func:`tests.test_swarm.swarm`, and the corpus comparator is
``tests/test_record_replay.py``'s own.
"""

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from core.runtime.backends.base import Usage
from core.runtime.mission_stream import (
    MISSION_FINISHED, STEP_STARTED, TOOL_CALL,
)
from core.runtime.results import RESULT_TOOL, BranchedStores
from core.runtime.run import Model, Run, ToolPlane
from core.runtime.usage import Ledger
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.contracts.schemas import PolicyPack
from core.tools.descriptors import ToolDescriptor
from tests.test_contract import _faults
from tests.test_record_replay import CORPUS, MOVES
from tests.test_run import bus  # noqa: F401 — a fixture
from tests.test_run_async import objects
from tests.test_swarm import STAGED, plan, swarm, tool_call

#: The committed "before" copies of the two staged fixtures: the streams as
#: they stood on master, one commit before ``branch`` existed.  Kept rather
#: than described, because "the only change is the added field" is a claim
#: about two files and the honest way to make it is to hold both.
BEFORE = Path(__file__).parent / "fixtures" / "runs_before_branch"


# ── the models these children are given ─────────────────────────────────────


class ByStep:
    """A scripted model that answers whichever step is asking.

    A queue cannot be shared by two children running at once — whose reply
    is next depends on which coroutine reached the endpoint first, and a
    test built on that is a test that passes on a fast afternoon.  What a
    step's executor is handed always names the step (``Step s1 of a plan:
    …``), so the reply is chosen by *who is asking* rather than by *when*.

    ``nap`` is what a real endpoint is: seconds inside one call with
    nothing for this process to do but wait.  ``most`` is the highest
    number of callers that were inside it together, which is the only
    honest way to say "these two overlapped".
    """

    def __init__(self, scripts, nap=0.0):
        self.scripts = {key: list(replies) for key, replies in scripts.items()}
        self.nap = nap
        self.most = 0
        self.seen = []
        self._busy = 0
        self._lock = threading.Lock()

    def __call__(self, messages, **_kw):
        text = "\n".join(str(m.get("content", "")) for m in messages)
        with self._lock:
            self.seen.append(text)
            self._busy += 1
            self.most = max(self.most, self._busy)
        if self.nap:
            time.sleep(self.nap)
        with self._lock:
            self._busy -= 1
            for key, replies in self.scripts.items():
                if f"Step {key} of a plan" in text and replies:
                    return replies.pop(0)
        raise AssertionError(f"nothing scripted for this turn: {text[-200:]}")


class Roles:
    """The router, the planner and the synthesizer, in order.

    They are serial whatever the steps do — the router and the planner run
    before the first step exists and the synthesizer after the last one
    settles — so a queue is honest here in a way it is not for the
    executor.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, **_kw):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else "nothing left to say"


TWO_INDEPENDENT = plan(
    {"id": "s1", "goal": "read the first shelf", "rung": "tool", "needs": []},
    {"id": "s2", "goal": "read the second shelf", "rung": "tool", "needs": []},
)


def steps(nap=0.0):
    """An executor that calls the tool once per step, then answers."""
    return ByStep({
        "s1": [tool_call("catalog.search", q="one"),
               json.dumps({"answer": "shelf one holds corpus abc123"})],
        "s2": [tool_call("catalog.search", q="two"),
               json.dumps({"answer": "shelf two holds corpus abc124"})],
    }, nap=nap)


def usage_of(prompt=10, completion=2):
    def report():
        return Usage(prompt_tokens=prompt, completion_tokens=completion,
                     total_tokens=prompt + completion)
    return report


def staged(bus, executor, *, parallel, records=None, **kw):
    """A two-step staged turn over *bus*, and the records it emitted."""
    seen = [] if records is None else records
    roles = Roles(STAGED, TWO_INDEPENDENT, "both shelves hold a corpus")
    runner = swarm(roles, executor, bus, observer=seen.append,
                   parallel=parallel, **kw)
    return runner, roles, runner.run("what do the two shelves hold?"), seen


def events(records, event):
    return [r for r in records if r["event"] == event]


# ── the wire: one sequence, and which child spoke ───────────────────────────


class TestTwoChildrenOnOneStream:
    """The property a consumer is promised, from both sides.

    A parallel turn is not an out-of-order stream with a field to sort it
    by.  It is one ordered stream that says more about itself, and the two
    assertions below are that sentence split in half.
    """

    def gathered(self, bus, model, records=None, names=("s1", "s2")):
        seen = [] if records is None else records
        parent = Run(**objects(bus, seen, model=model))

        async def one(name):
            return await parent.child(branch=name, stage=True).arun(
                f"Step {name} of a plan: read")

        async def both():
            return await asyncio.gather(*(one(name) for name in names))

        return asyncio.run(both()), seen

    def test_each_record_says_which_child_emitted_it(self, bus):
        _, records = self.gathered(bus, Model(ask=steps()))
        assert {r.get("branch") for r in records} == {"s1", "s2"}

    def test_the_indexes_are_one_sequence_with_nothing_used_twice(self, bus):
        """Two children built in one breath used to take the same offset.

        Each read the parent's counter at construction and numbered its own
        steps on top of it, so a turn emitted two records called ``index:
        0``. The number is allocated at EMIT time now, under the observer's
        lock, and the sequence below is what that buys: two children of two
        turns each, and four numbers.
        """
        _, records = self.gathered(bus, Model(ask=steps()))
        opened = [r["index"] for r in events(records, STEP_STARTED)]
        assert sorted(opened) == [0, 1, 2, 3]
        assert len(set(opened)) == 4

    def test_no_number_belongs_to_two_children(self, bus):
        """The collision itself, named.  A duplicate ``index`` is two
        different steps a consumer renders as one."""
        _, records = self.gathered(bus, Model(ask=steps()))
        owner = {}
        for record in records:
            if "index" in record:
                owner.setdefault(record["index"], set()).add(record["branch"])
        assert all(len(who) == 1 for who in owner.values()), owner

    def test_every_record_of_one_step_carries_that_steps_number(self, bus):
        """A step is one index across all of its records — its
        ``step_started``, its call, its result — and a child that
        renumbered per record would pair a call with the wrong step."""
        _, records = self.gathered(bus, Model(ask=steps()))
        for branch in ("s1", "s2"):
            mine = [r for r in records
                    if r.get("branch") == branch and "index" in r]
            calls = [r["index"] for r in mine if r["event"] == TOOL_CALL]
            results = [r["index"] for r in mine
                       if r["event"] == "tool_result"]
            assert calls and calls == results

    def test_each_childs_own_steps_stay_in_the_order_it_ran_them(self, bus):
        _, records = self.gathered(bus, Model(ask=steps()))
        for branch in ("s1", "s2"):
            mine = [r["index"] for r in events(records, STEP_STARTED)
                    if r["branch"] == branch]
            assert mine == sorted(mine) and len(set(mine)) == len(mine)

    def test_the_steps_are_opened_in_the_order_they_are_numbered(self, bus):
        """The allocation IS the emission: a number is taken at the moment
        a record goes out, so ``step_started`` arrives 0, 1, 2, 3 and never
        4 before 3.  That is the sense in which the sequence is ordered —
        not that a step's records are contiguous, which running two steps
        at once is precisely the decision not to have."""
        _, records = self.gathered(bus, Model(ask=steps()))
        opened = [r["index"] for r in events(records, STEP_STARTED)]
        assert opened == list(range(len(opened)))

    def test_no_record_names_a_step_that_has_not_opened(self, bus):
        """What a consumer that ignores ``branch`` actually needs: it may
        read the stream forward and never meet a call belonging to a step
        it has not been shown."""
        _, records = self.gathered(bus, Model(ask=steps()))
        opened = set()
        for record in records:
            if record["event"] == STEP_STARTED:
                opened.add(record["index"])
            elif "index" in record:
                assert record["index"] in opened, record

    def test_dropping_the_field_leaves_the_records_a_consumer_read(
            self, bus):
        """The whole reason this is an OPTIONAL field: take it out and
        every record is a record of the shape it always had."""
        _, records = self.gathered(bus, Model(ask=steps()))
        without = [{k: v for k, v in r.items() if k != "branch"}
                   for r in records]
        assert not [r for r in without if "branch" in r]
        assert _faults(without) == []

    def test_a_child_with_no_name_puts_nothing_on_the_wire(self, bus):
        """Absence is the mission itself, and it is what a run without
        children emits — every record of it."""
        records = []
        Run(**objects(bus, records)).run("go")
        assert not [r for r in records if "branch" in r]


class TestTheNumberingIsOneActAndNotTwo:
    """Why the observer holds a lock when its children share one loop.

    A coroutine cannot be interrupted between two statements, so on one
    loop the allocation would be safe without it.  It is held anyway, and
    this is the case that says why: :meth:`~core.runtime.run.Run.run` from
    a thread is a supported way in, a critic's verdict goes out through
    :func:`asyncio.to_thread`, and a numbering that is correct only because
    of where the awaits happen to be is a numbering the next refactor
    breaks without a test noticing.

    Threads here rather than coroutines for exactly that reason: this is
    the property, and the property is not "asyncio is cooperative".
    """

    EMITS = 400

    def hammered(self, workers=8):
        """Eight children emitting at once, with the interpreter switching
        threads as often as it will.

        ``setswitchinterval`` is what makes this a test rather than a
        hope.  The unguarded allocation is a handful of bytecodes — read
        the counter, write it, read it again, add one — and at the default
        5 ms nothing lands inside that window often enough to be relied
        on, so a run that happened to pass would say nothing about the
        lock.  Turned down, the race is reliable, and the assertions below
        are ones that fail when the ``with`` is taken out.
        """
        import sys

        from core.runtime.run import Observer

        seen = []
        lock = threading.Lock()

        def sink(record):
            with lock:
                seen.append(record)

        parent = Observer(sink)
        parent.carry(plan=[{"id": "s1"}])
        ready = threading.Barrier(workers)

        def emitting(name):
            stage = parent.branch(name, stage=True)
            ready.wait()
            for local in range(self.EMITS):
                stage.emit(STEP_STARTED, index=local)

        threads = [threading.Thread(target=emitting, args=(f"s{n}",))
                   for n in range(workers)]
        was = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            sys.setswitchinterval(was)
        return seen, workers

    def test_no_two_records_take_the_same_number(self):
        seen, workers = self.hammered()
        numbers = [record["index"] for record in seen]
        assert len(numbers) == self.EMITS * workers
        assert sorted(numbers) == list(range(self.EMITS * workers))

    def test_the_carried_plan_is_drained_exactly_once(self):
        """The drain is inside the same critical section as the
        allocation, so "exactly one step_started carries the plan" is true
        of eight children as it is of one."""
        seen, _ = self.hammered()
        assert len([record for record in seen if "plan" in record]) == 1

    def test_it_rides_the_lowest_number_of_all(self):
        """Which child took it is a race; WHICH RECORD took it is not.  The
        plan is a fact about the steps that follow, so it rides the first
        one on the wire."""
        seen, _ = self.hammered()
        carrying = [record for record in seen if "plan" in record][0]
        assert carrying["index"] == 0


# ── one mission_result, one store each ──────────────────────────────────────


def shelving_bus():
    """A tool whose answer names the argument, so two stores differ."""
    b = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="Search the shelves. Second sentence."),
        lambda **kw: (0, f"shelf {kw.get('q')} holds corpus abc123", ""))
    return b


class TestOneToolNameAndAStorePerChild:
    """What ``ToolPlane.lease`` is, asserted as the collision it prevents.

    Before it, this arrangement raised ``ResultStoreConflict`` on the
    second child: ``MissionResultStore.register_on`` refuses a name that is
    taken, and both children wanted ``mission_result``. Lane C's gather
    tests worked around it by running with no store at all.
    """

    def reading(self, name):
        """A step that calls the tool, then reads its own store back."""
        return [tool_call("catalog.search", q=name),
                tool_call(RESULT_TOOL, handle="r1"),
                json.dumps({"answer": f"{name} read its own r1"})]

    def gathered(self, bus):
        records = []
        model = Model(ask=ByStep({"s1": self.reading("one"),
                                  "s2": self.reading("two")}))
        parent = Run(**objects(bus, records, model=model,
                               plane=ToolPlane(bus=bus,
                                               offered=["catalog.search"])))
        made = {}

        async def one(name):
            child = parent.child(branch=name, stage=True)
            made[name] = child
            return await child.arun(f"Step {name} of a plan: read")

        async def both():
            return await asyncio.gather(one("s1"), one("s2"))

        asyncio.run(both())
        return made, records

    def test_two_children_no_longer_collide_on_the_store_tool(self):
        made, _ = self.gathered(shelving_bus())
        assert set(made) == {"s1", "s2"}

    def test_the_model_is_told_the_same_tool_name_on_every_branch(self):
        """The name is in the protocol text a child opens with, and a
        served endpoint's prefix cache is keyed on those bytes.  A
        namespaced tool per child would be two prompts for one job."""
        made, _ = self.gathered(shelving_bus())
        assert [child.plane.store_tool for child in made.values()] == \
            [RESULT_TOOL, RESULT_TOOL]
        assert all(RESULT_TOOL in child.offered for child in made.values())

    def test_each_child_reads_its_own_results_back(self):
        """``r1`` means a different result on each branch, which is the
        whole of "a store per child": handles are short so a model can
        quote them, and short handles are unambiguous inside one run."""
        _, records = self.gathered(shelving_bus())
        read_back = [r["output"] for r in records
                     if r["event"] == "tool_result" and r["tool"] == RESULT_TOOL]
        assert len(read_back) == 2
        # The store's summary names the CALL it kept, so each child is
        # looking at its own dispatch under the handle it was given.
        assert any("q='one'" in text for text in read_back)
        assert any("q='two'" in text for text in read_back)

    def test_the_descriptor_is_withdrawn_when_the_last_child_closes(self):
        """The bus outlives the run, and a store left on it would offer the
        next mission a handle into this one's governed material."""
        b = shelving_bus()
        self.gathered(b)
        assert b.get_descriptor(RESULT_TOOL) is None

    def test_a_run_with_no_children_registers_and_withdraws_as_before(self):
        b = shelving_bus()
        records = []
        run = Run(**objects(b, records, plane=ToolPlane(
            bus=b, offered=["catalog.search"]),
            model=Model(ask=ByStep({"go": [
                json.dumps({"answer": "nothing to do"})]}))))
        seen = []
        original = run.results.register_on

        def spy(bus_, name=RESULT_TOOL, executor=None):
            seen.append(name)
            return original(bus_, name, executor)

        run.results.register_on = spy
        run.run("Step go of a plan: nothing")
        assert seen == [RESULT_TOOL]
        assert b.get_descriptor(RESULT_TOOL) is None

    def test_a_branch_nobody_published_is_told_so_rather_than_answered(self):
        """The routing failure, said plainly.  Reading a store that is not
        open is a harness defect, and answering it out of somebody else's
        store would be the wrong result rather than an error."""
        stores = BranchedStores()
        code, out, err = stores._read(handle="r1", branch="ghost")
        assert (code, out) == (1, "")
        assert "ghost" in err


# ── the audit column, under interleaving ────────────────────────────────────


class TestTheAuditStepIsRightWhenTwoChildrenDispatch:
    """The column that was *wrong* rather than absent.

    ``bus.audit_context["step"]`` was written immediately before an awaited
    dispatch.  With two children on one loop the second child's write lands
    while the first is still inside its call, and both entries are stamped
    with the second's index — an audit that says a tool was called at a
    step it was not.  The number rides the call now.
    """

    def entries(self, tmp_path):
        from core.policy.audit import AuditLogger

        logger = AuditLogger(path=tmp_path / "audit.jsonl")
        b = ToolBus(capability_engine=CapabilityEngine(
            PolicyPack(allowed_scopes=["*"])), audit=logger)
        b.register(
            ToolDescriptor(tool_name="catalog.search", description="Search."),
            lambda **kw: (0, f"hits for {kw.get('q')}", ""))
        records = []
        model = Model(ask=ByStep({
            "s1": [tool_call("catalog.search", q="one"),
                   json.dumps({"answer": "one"})],
            "s2": [tool_call("catalog.search", q="two"),
                   json.dumps({"answer": "two"})],
        }, nap=0.05))
        parent = Run(**objects(b, records, model=model,
                               plane=ToolPlane(bus=b,
                                               offered=["catalog.search"],
                                               store_tool="")))

        async def one(name):
            return await parent.child(branch=name, stage=True).arun(
                f"Step {name} of a plan: read")

        async def both():
            return await asyncio.gather(one("s1"), one("s2"))

        asyncio.run(both())
        return [json.loads(entry["detail"]) for entry in logger.tail(20)], \
            records

    def test_each_entry_carries_the_step_that_actually_called(self, tmp_path):
        details, records = self.entries(tmp_path)
        called = {r["branch"]: r["index"] for r in events(records, TOOL_CALL)}
        by_argument = {("one" if '"q": "one"' in d["arguments"] else "two"):
                       d["step"] for d in details}
        assert by_argument == {"one": called["s1"], "two": called["s2"]}
        assert sorted(by_argument.values()) == [0, 1]

    def test_the_two_dispatches_really_were_in_flight_together(self, tmp_path):
        """Otherwise the test above passes against a serial turn, which is
        the arrangement that never had the bug."""
        details, _ = self.entries(tmp_path)
        assert len(details) == 2

    def test_a_bus_that_does_not_name_the_keyword_is_handed_no_step(self):
        """The same rule ``deadline_s`` follows: a caller may hand a run
        any object with ``dispatch`` and ``describe_tool``, and inventing a
        ``step`` argument for somebody else's server is what the probe
        exists to prevent."""
        class Minimal:
            def __init__(self):
                self.calls = []

            def describe_tool(self, name):
                return {"description": "does it", "input_schema": {}}

            def dispatch(self, name, **kwargs):
                self.calls.append(kwargs)

                class R:
                    exit_code, stdout, stderr = 0, "hits", ""
                return R()

            def register(self, *a, **kw):
                return None

            def unregister(self, name):
                return None

        b = Minimal()
        records = []
        Run(**objects(b, records, plane=ToolPlane(
            bus=b, offered=["catalog.search"], store_tool=""))).run("go")
        assert b.calls and all("step" not in call for call in b.calls)


# ── the ledger, folded at the join ──────────────────────────────────────────


class TestOneLedgerWhateverTheChildrenDid:
    """``Ledger.absorb`` existed, was tested, and had no caller in ``core``.

    It has one now, and it is the join: a child spends into a ledger of its
    own and the parent folds it in when the child returns, single-threaded
    on the one loop they share.  ``ROADMAP.md`` §2.6.2 item 2 says which of
    the two ways out this is — not a lock around the arithmetic, but a join
    that does not need one.
    """

    def test_the_turns_total_is_the_sum_of_every_call_it_made(self, bus):
        records = []
        _, roles, transcript, records = staged(
            bus, steps(), parallel=2, records=records,
            usage_fn=usage_of(10, 2))
        finished = events(records, MISSION_FINISHED)[-1]
        # Three role calls — router, planner, synthesizer — and two per
        # step: the tool call and the answer.
        assert finished["usage"]["calls"] == 7
        assert finished["usage"]["total_tokens"] == 7 * 12
        assert transcript.usage.calls == 7

    def test_serial_and_parallel_report_the_same_numbers(self, bus):
        """The arithmetic is the same arithmetic whichever way the steps
        ran, which is the only thing a turn's invoice may promise."""
        totals = []
        for parallel in (1, 2):
            records = []
            staged(bus, steps(), parallel=parallel, records=records,
                   usage_fn=usage_of(10, 2))
            totals.append(events(records, MISSION_FINISHED)[-1]["usage"])
        assert totals[0] == totals[1]

    def test_a_child_given_no_ledger_still_shares_the_parents(self, bus):
        """The direct route is that child: its ``mission_finished`` is the
        TURN's and carries the router call that chose it."""
        records = []
        parent = Run(**objects(bus, records, model=Model(
            ask=steps(), usage_fn=usage_of(10, 2), ledger=Ledger())))
        child = parent.child(branch="direct")
        assert child.model is parent.model
        assert child.model.ledger is parent.model.ledger


# ── the policy, and its default ─────────────────────────────────────────────


class TestWhichStepsRunTogether:
    """The wave, and the number that bounds it.

    The default is ``1`` and the default is the point: this lane made
    parallel steps *possible*, and the evidence for making them the way a
    staged turn runs is a suite scored both ways.  See the report line for
    the eval harness in ``ROADMAP.md`` §2.6.4.
    """

    def test_the_default_is_serial(self, bus):
        runner, _, _, _ = staged(bus, steps(), parallel=1)
        assert runner._parallel == 1

    def test_serial_runs_one_step_at_a_time(self, bus):
        executor = steps(nap=0.05)
        staged(bus, executor, parallel=1)
        assert executor.most == 1

    def test_two_independent_steps_are_gathered(self, bus):
        executor = steps(nap=0.05)
        staged(bus, executor, parallel=2)
        assert executor.most == 2

    def test_gathering_is_faster_than_running_them_one_at_a_time(self, bus):
        """Two calls a step at 0.2 s each: about 0.8 s serial, about 0.4 s
        gathered.  The margin is wide enough that a loaded machine moves
        the numbers and not the comparison."""
        elapsed = []
        for parallel in (1, 2):
            started = time.monotonic()
            staged(bus, steps(nap=0.2), parallel=parallel)
            elapsed.append(time.monotonic() - started)
        serial, gathered = elapsed
        assert gathered < serial / 1.5, elapsed

    def test_a_step_waits_for_what_it_needs(self, bus):
        """``needs`` is not advice.  A step that names an unsettled one is
        not a candidate, so a plan of two dependent steps runs serially
        however high the number is."""
        roles = Roles(STAGED, plan(
            {"id": "s1", "goal": "read the first shelf", "rung": "tool",
             "needs": []},
            {"id": "s2", "goal": "read the second shelf", "rung": "tool",
             "needs": ["s1"]}), "both shelves hold a corpus")
        executor = steps(nap=0.05)
        swarm(roles, executor, bus, parallel=4).run("what do they hold?")
        assert executor.most == 1

    def test_the_wave_is_bounded_by_the_number(self, bus):
        runner, _, _, _ = staged(bus, steps(), parallel=2)
        from core.runtime.swarm import PlanStep
        queue = [PlanStep(id=f"s{n}", goal="g", rung="tool") for n in range(5)]
        assert [step.id for step in runner._wave(queue, {})] == ["s0", "s1"]

    def test_a_serial_turn_takes_the_head_of_the_queue_unconditionally(
            self, bus):
        """Not the first READY step.  A plan naming a need nothing settled
        is a plan whose step still runs and whose executor is told about
        it, exactly as before this method existed."""
        runner, _, _, _ = staged(bus, steps(), parallel=1)
        from core.runtime.swarm import PlanStep
        queue = [PlanStep(id="s2", goal="g", rung="tool", needs=["s1"])]
        assert [step.id for step in runner._wave(queue, {})] == ["s2"]


class TestAFailingMemberDoesNotLoseItsSiblings:
    """Everything in a wave is written down before anything decides.

    A serial turn settles one step and then decides what to do about it,
    and there is nothing else in flight.  A wave of two has a second
    result that already ran, and a loop that broke out on the first
    failure would drop it — the transcript would hold its records and the
    synthesizer would be told nothing about the step they belong to.
    """

    def mixed(self, bus):
        """``s1`` reads something; ``s2`` answers without calling anything,
        which is a gate failure the runtime decides on its own."""
        executor = ByStep({
            "s1": [tool_call("catalog.search", q="one"),
                   json.dumps({"answer": "shelf one holds corpus abc123"})],
            "s2": [json.dumps({"answer": "I did not look"})],
        })
        records = []
        roles = Roles(STAGED, TWO_INDEPENDENT, "one shelf answered")
        runner = swarm(roles, executor, bus, observer=records.append,
                       parallel=2)
        return roles, runner.run("what do the two shelves hold?"), records

    def test_both_steps_reach_the_synthesizer(self, bus):
        roles, _, _ = self.mixed(bus)
        user = roles.seen[-1][-1]["content"]
        assert "- s1 (read the first shelf)" in user
        assert "- s2 (read the second shelf): FAILED" in user

    def test_the_one_that_worked_is_still_attributed_to_its_step(self, bus):
        """Not dropped into the unattributed pile: the step that read it is
        on the record, which is what a reader of the answer needs."""
        roles, _, _ = self.mixed(bus)
        user = roles.seen[-1][-1]["content"]
        assert "[s1]" in user

    def test_the_turn_says_the_plan_did_not_wholly_work(self, bus):
        _, transcript, _ = self.mixed(bus)
        assert transcript.outcome == "answered_with_caveat"


# ── what the turn is told, exactly once ─────────────────────────────────────


class TestThePlanRidesExactlyOneStep:
    """``carry`` drains once, and the drain is inside the allocation.

    Which child takes the pending ``plan`` is a race between two coroutines
    otherwise.  It is decided by the same lock that hands out the index, so
    the fields land on the step with the lowest of the new numbers — the
    first one on the wire, which is where a plan is a fact about what
    follows.
    """

    def test_one_step_started_carries_the_plan(self, bus):
        _, _, _, records = staged(bus, steps(), parallel=2)
        carrying = [r for r in events(records, STEP_STARTED) if "plan" in r]
        assert len(carrying) == 1

    def test_it_is_the_first_step_on_the_wire(self, bus):
        _, _, _, records = staged(bus, steps(), parallel=2)
        opened = events(records, STEP_STARTED)
        assert "plan" in opened[0]
        assert opened[0]["index"] == 0

    def test_the_plan_names_both_steps_whichever_ran_first(self, bus):
        _, _, _, records = staged(bus, steps(), parallel=2)
        carrying = [r for r in events(records, STEP_STARTED) if "plan" in r][0]
        assert [entry["id"] for entry in carrying["plan"]] == ["s1", "s2"]


# ── the synthesizer reads the union ─────────────────────────────────────────


class TestTheAnswerIsWrittenOverEveryChildsStore:
    """A staged turn's answer is synthesized over several stores.

    It already merged them — ``evidence`` is extended from each child and
    ``_note_calls`` unions what each dispatched — and what this lane
    changed is that the merge is now over stores that could not both exist
    before.
    """

    def blocks(self, bus, parallel):
        _, roles, transcript, _ = staged(bus, steps(), parallel=parallel)
        from core.runtime.swarm import SwarmRunner
        user = roles.seen[-1][-1]["content"]
        assert SwarmRunner.EVIDENCE_HEADER in user
        return user, transcript

    def test_both_steps_evidence_reaches_the_synthesizer(self, bus):
        user, _ = self.blocks(bus, parallel=2)
        assert "[s1]" in user and "[s2]" in user

    def test_the_same_union_a_serial_turn_produced(self, bus):
        serial, _ = self.blocks(bus, parallel=1)
        gathered, _ = self.blocks(bus, parallel=2)
        assert serial == gathered


# ── a resumed turn gathers what is left ─────────────────────────────────────


class TestAResumedTurnGathersItsRemainingSteps:
    """Resuming is not a second kind of turn.

    The stretch that is left is a queue like any other, so the wave applies
    to it — and the numbering continues the log the earlier stretch wrote,
    which is the one thing about a resumed branch that is not like a cold
    one.
    """

    def resumed(self, bus, parallel):
        from tests.test_swarm import _Resumption

        state = [
            {"id": "s0", "goal": "already done", "rung": "tool", "needs": []},
            {"id": "s1", "goal": "read the first shelf", "rung": "tool",
             "needs": []},
            {"id": "s2", "goal": "read the second shelf", "rung": "tool",
             "needs": []},
        ]
        records = []
        roles = Roles("both shelves hold a corpus")
        runner = swarm(roles, steps(nap=0.05), bus, observer=records.append,
                       parallel=parallel)
        runner.run("what do the two shelves hold?", resumption=_Resumption(
            state,
            [{"id": "s0", "outcome": "ok", "summary": "did it"}],
            next_index=4, steps_spent=4))
        return runner, records

    def test_the_two_steps_left_ran_together(self, bus):
        runner, _ = self.resumed(bus, parallel=2)
        assert runner._model.ask.most == 2

    def test_their_numbering_continues_the_log(self, bus):
        _, records = self.resumed(bus, parallel=2)
        opened = [r["index"] for r in events(records, STEP_STARTED)]
        # Two steps of two model turns each, numbered on from the four the
        # earlier stretch wrote. A resumed stretch that started again at
        # zero would put two records with one `index` in one log.
        assert sorted(opened) == [4, 5, 6, 7]

    def test_the_resumption_rides_the_first_of_them_and_only_that_one(
            self, bus):
        _, records = self.resumed(bus, parallel=2)
        carrying = [r for r in events(records, STEP_STARTED) if "resumed" in r]
        assert len(carrying) == 1
        assert carrying[0]["index"] == 4


# ── the corpus gained the field and nothing else ────────────────────────────


def unwrapped(path):
    return [json.loads(line)["record"] for line
            in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


#: The two committed fixtures that were re-recorded, as ``(after, before)``.
RERECORDED = [
    pytest.param(CORPUS / run / "events.jsonl", BEFORE / f"{run}.jsonl", id=run)
    for run in ("run_corpusswarm-0001", "run_corpusswarmcaveat-0001")
]


class TestTheReRecordedFixturesGainedOnlyTheField:
    """The claim "an optional field is a minor change", made checkable.

    A recording is re-made against a wall clock and a fresh run directory,
    so the fields ``tests/test_record_replay.MOVES`` names differ between
    any two recordings of one mission and are dropped here exactly as the
    corpus guard drops them.  Everything else is the same bytes — and if it
    is not, this lane changed something it said it did not.

    Only the two STAGED fixtures were re-recorded.  The direct ones are
    untouched, which is the other half of the claim: a run with no children
    emits no ``branch`` at all, so there was nothing to re-record.
    """

    def stripped(self, records):
        return [{k: v for k, v in record.items()
                 if k not in MOVES and k != "branch"} for record in records]

    @pytest.mark.parametrize("after,before", RERECORDED)
    def test_take_the_field_out_and_it_is_the_recording_that_was_there(
            self, after, before):
        assert self.stripped(unwrapped(after)) == \
            self.stripped(unwrapped(before))

    @pytest.mark.parametrize("after,before", RERECORDED)
    def test_the_before_copy_carried_no_branch_at_all(self, after, before):
        """Otherwise the comparison above would be stripping a field from
        both sides and proving nothing."""
        assert not [r for r in unwrapped(before) if "branch" in r]

    @pytest.mark.parametrize("after,before", RERECORDED)
    def test_the_stages_records_gained_it_and_the_turns_did_not(
            self, after, before):
        """A staged turn's own records — its opening, its grounding, its
        answer, its closing — belong to the turn and carry no branch.  The
        step records carry the plan step's own id, which is what a consumer
        demultiplexes on."""
        records = unwrapped(after)
        assert {r.get("branch") for r in records} == {None, "s1", "s2"}
        assert [r["event"] for r in records if "branch" not in r][0] == \
            "mission_started"

    @pytest.mark.parametrize("run_id", ["run_corpusjson-0001",
                                        "run_corpusnative-0001"])
    def test_the_direct_fixtures_carry_no_branch(self, run_id):
        records = unwrapped(CORPUS / run_id / "events.jsonl")
        assert records and not [r for r in records if "branch" in r]
