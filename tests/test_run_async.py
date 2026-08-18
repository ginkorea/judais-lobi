# tests/test_run_async.py — the loop is a coroutine, and `run` is the wrapper

"""What became true when :meth:`~core.runtime.run.Run.arun` became the loop.

``tests/test_run_corpus.py`` is the guard that nothing *moved*: four
recorded runs and nineteen recorded streams, replayed through this code and
compared record for record, with no drift in the prompts either.  This file
is the other half — the properties that did not exist before the loop was a
coroutine and that a corpus of yesterday's runs therefore cannot state:

* the two façades are **one run**: the transcript and the stream a caller
  gets from ``run`` are the ones ``arun`` produces, because ``run`` runs
  ``arun`` and does nothing else;
* the waiting is off the loop.  A model call, a dispatch and a critic's
  opinion go to a worker thread, so a 59 tok/s endpoint no longer holds the
  loop while it writes — asserted by running something else while it does;
* the answer's fragments arrive **as it decodes**, one awaited frame at a
  time, and they are byte for byte the fragments the synchronous drain
  cuts, because both drains share one :class:`AnswerStream`;
* an operator's command lands at the same boundary in both façades;
* a cancelled task winds up the way a thrown switch does — one
  ``mission_finished``, ``reason: cancelled`` — and neither leaves a
  watcher on a stream that just stops;
* two children can be awaited at once, on one loop, under one numbering.
  That is the capability the whole lane was for; the *policy* of running
  them in parallel is the parallel-children lane's (``ROADMAP.md`` §2.6.2)
  and the swarm is still serial.

Nothing here scripts a second idea of what a run looks like: the six
objects come from :func:`tests.test_run.six`, the scripted models from
:mod:`tests.test_mission`, and the control channel is the real one over a
real pipe read by its real daemon thread.
"""

import asyncio
import json
import threading
import time

import pytest

from core.budgets import Cancellation
from core.runtime.answer_stream import adrain, drain
from core.runtime.mission import CANCELLED
from core.runtime.mission_stream import (
    ANSWER, ANSWER_DELTA, MISSION_FINISHED, STEP_STARTED,
)
from core.runtime.run import Bounds, Model, Run, ToolPlane
from core.tools.descriptors import ToolDescriptor
from tests.test_mission import (  # noqa: F401 — `steering` is a fixture
    ScriptedModel, SpeakingModel, StreamingModel, steering,
)
from tests.test_run import (  # noqa: F401 — `bus` is a fixture
    REPLIES, bus, six, tool_call, without_the_clock,
)


def objects(bus, records, **overrides):
    """The six of :func:`tests.test_run.six`, with any of them replaced.

    Through that function and not beside it: what a run is made of has one
    owner in this suite, and a second dict of six objects here would be a
    second idea of what "an ordinary run" is — which is the defect the
    whole phase is about, written into its own tests.
    """
    built = six(bus, records)
    built.update(overrides)
    return built


def answered(text="done"):
    return json.dumps({"answer": text})


def events(records, event):
    return [record for record in records if record["event"] == event]


class Slow(ScriptedModel):
    """A scripted model that takes its time, and says how many callers it
    had at once.

    The nap is what a real endpoint is: seconds inside one function call,
    with nothing for this process to do but wait.  ``most`` is the highest
    number of callers that were inside it together, which is the only
    honest way to state "these two calls overlapped" — a wall-clock
    comparison would be a stopwatch race on a shared machine.
    """

    def __init__(self, *replies, nap=0.2):
        super().__init__(*replies)
        self.nap = nap
        self.most = 0
        self._busy = 0
        self._lock = threading.Lock()

    def __call__(self, messages):
        with self._lock:
            self._busy += 1
            self.most = max(self.most, self._busy)
        time.sleep(self.nap)
        with self._lock:
            self._busy -= 1
        return super().__call__(messages)


# ── one run, two façades ────────────────────────────────────────────────────


class TestTheFacadeIsTheLoop:
    """``run`` runs ``arun`` and does nothing else, so they are one run.

    Both halves are asserted, for the reason ``tests/test_run.py`` asserts
    both halves of the adapter's equivalence: a wrapper can preserve the
    transcript a caller is handed while losing a record a watcher is shown,
    and the stream is the half a platform reads.
    """

    def facade(self, bus):
        records = []
        return Run(**six(bus, records)).run("find assets"), records

    def loop(self, bus):
        records = []
        run = Run(**six(bus, records))
        return asyncio.run(run.arun("find assets")), records

    def test_the_transcripts_are_the_same(self, bus):
        mine, _ = self.facade(bus)
        theirs, _ = self.loop(bus)
        assert (mine.answer, mine.outcome, mine.catalogue) == \
            (theirs.answer, theirs.outcome, theirs.catalogue)
        assert [(s.index, s.tool, s.arguments, s.output, s.handle)
                for s in mine.steps] == \
            [(s.index, s.tool, s.arguments, s.output, s.handle)
             for s in theirs.steps]

    def test_the_streams_are_the_same(self, bus):
        _, mine = self.facade(bus)
        _, theirs = self.loop(bus)
        assert without_the_clock(mine) == without_the_clock(theirs)

    def test_the_facade_hands_back_a_transcript_and_not_a_coroutine(
            self, bus):
        """The property every existing caller depends on, stated once: a
        method that has been synchronous since the first version of this
        harness still is."""
        transcript, _ = self.facade(bus)
        assert transcript.answer == "Two hits for assets."
        assert not asyncio.iscoroutine(transcript)


class TestTheLoopIsFreeWhileTheModelWrites:
    """The point of the exercise, and the one thing a corpus cannot show.

    A mission spends most of its wall clock inside one model call.  Under
    the synchronous loop that was the process standing still; under
    ``arun`` it is an ``await``, and this asserts it by giving the loop
    something else to do and counting how often it got to do it.
    """

    def _with_a_ticker(self, bus, model, **overrides):
        ticks = []

        async def tick():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.005)

        async def both():
            ticker = asyncio.ensure_future(tick())
            try:
                run = Run(**objects(bus, [], model=model, **overrides))
                return await run.arun("go")
            finally:
                ticker.cancel()

        return asyncio.run(both()), ticks

    def test_a_slow_model_call_does_not_stop_the_loop(self, bus):
        transcript, ticks = self._with_a_ticker(
            bus, Model(ask=Slow(answered("slow but not blocking"))))
        assert transcript.answer == "slow but not blocking"
        # 0.2 s of endpoint at one tick every 5 ms. Ten is a floor with a
        # wide margin under a loaded machine; one is what a blocked loop
        # manages, and zero is what it manages if the tick never started.
        assert len(ticks) > 10, f"the loop ticked {len(ticks)} times"

    def test_a_slow_dispatch_does_not_stop_the_loop_either(self, bus):
        """The other place a mission waits.  A tool is a subprocess or a
        server, and the loop must not be sitting inside one."""
        bus.register(ToolDescriptor(tool_name="catalog.nap",
                                    description="Sleep on it."),
                     _nap)
        model = ScriptedModel(tool_call("catalog.nap"), answered("napped"))
        transcript, ticks = self._with_a_ticker(
            bus, Model(ask=model),
            plane=ToolPlane(bus=bus, offered=["catalog.nap"]))
        assert transcript.steps[0].tool == "catalog.nap"
        assert transcript.answer == "napped"
        assert len(ticks) > 10, f"the loop ticked {len(ticks)} times"


def _nap(**arguments):
    time.sleep(0.2)
    return 0, "slept", ""


# ── the answer, one awaited frame at a time ─────────────────────────────────


class TestTheAnswerStreamsAsItDecodes:
    """``answer_delta`` under ``arun``: the same fragments, still first.

    The corpus cannot state this — none of the recorded runs streamed, so
    not one committed fixture holds an ``answer_delta`` — which is exactly
    why the fragments are asserted here: against the other façade's, over
    identical frames against the synchronous drain, and against a clock,
    because "as it decodes" is a claim about *when* and the other two
    cannot see it.
    """

    ANSWER_TEXT = "Three assets, and the newest is from August.\nSo: three."

    def fragments(self, bus, coroutine):
        records = []
        model = Model(ask=StreamingModel(
            json.dumps({"answer": self.ANSWER_TEXT})))
        run = Run(**objects(bus, records, model=model))
        if coroutine:
            asyncio.run(run.arun("what do we hold"))
        else:
            run.run("what do we hold")
        return records

    def test_both_facades_emit_the_same_fragments(self, bus):
        """The same records whichever way the run was started — and note
        what this does **not** say.  ``run`` runs ``arun``, so both sides
        of this comparison drain through
        :func:`~core.runtime.answer_stream.adrain`; a fragment cut that
        moved would move on both sides and this would stay green.  That
        claim needs the two drains put side by side over identical frames,
        which is
        :meth:`test_the_two_drains_cut_the_same_fragments` — checked by
        mutation, which is how this docstring came to be written."""
        mine = events(self.fragments(bus, True), ANSWER_DELTA)
        theirs = events(self.fragments(bus, False), ANSWER_DELTA)
        assert [(r["part"], r["text"]) for r in mine] == \
            [(r["part"], r["text"]) for r in theirs]
        assert "".join(r["text"] for r in mine) == self.ANSWER_TEXT

    def test_they_are_several_and_they_all_precede_the_answer(self, bus):
        """Provisional text before the authoritative record is the whole
        reason the event exists: several fragments, numbered from zero
        without a gap, all of them ahead of the ``answer``.

        What this cannot see is *when* they went out — a drain that held
        every fragment until the last frame and then emitted them in order
        would pass every line below.  That one is
        :meth:`test_the_watcher_sees_them_while_the_call_is_in_flight`,
        and the split between the two was found by mutating the drain into
        exactly that lump."""
        records = self.fragments(bus, True)
        deltas = events(records, ANSWER_DELTA)
        assert len(deltas) > 1, "a newline and 64 characters both flush"
        assert [r["part"] for r in deltas] == list(range(len(deltas)))
        names = [r["event"] for r in records]
        assert names.index(ANSWER) > names.index(ANSWER_DELTA)

    def test_the_watcher_sees_them_while_the_call_is_in_flight(self, bus):
        """Emitted *as* the answer decodes, and not in a lump at the end.

        The two assertions above cannot tell those apart — a drain that
        held every fragment until the last frame and then emitted them in
        order would satisfy both — and the difference is the whole feature:
        a pane showing text as it is written, or a pane showing nothing for
        eleven seconds and then everything.  So the count is sampled from a
        task running on the same loop while the call is still going, and it
        has to be seen changing.
        """
        records = []
        counts = []
        model = Model(ask=SlowStreamingModel(
            json.dumps({"answer": "x" * 300})))

        async def both():
            async def tick():
                while True:
                    counts.append(len(events(records, ANSWER_DELTA)))
                    await asyncio.sleep(0.005)

            ticker = asyncio.ensure_future(tick())
            try:
                run = Run(**objects(bus, records, model=model))
                return await run.arun("go")
            finally:
                ticker.cancel()

        asyncio.run(both())
        assert len(set(counts)) > 2, f"the count never moved: {set(counts)}"

    def test_the_two_drains_cut_the_same_fragments(self):
        """One implementation of the cut, asserted rather than asserted
        about: :func:`~core.runtime.answer_stream.adrain` and
        :func:`~core.runtime.answer_stream.drain` are handed the same
        frames and must produce the same pieces in the same order."""
        reply = json.dumps({"answer": "x" * 200 + "\ntail"})
        frames = list(StreamingModel(reply)([]))
        mine, theirs = [], []
        assert asyncio.run(adrain(iter(frames), mine.append)) == \
            drain(iter(frames), theirs.append)
        assert mine == theirs
        assert len(mine) > 1


class SlowStreamingModel(StreamingModel):
    """Frames with time between them, which is what a served endpoint is.

    :class:`~tests.test_mission.StreamingModel` yields its pieces as fast
    as they can be read, and a test written against it cannot tell a
    fragment emitted as it decoded from one emitted at the end — there is
    no "as it decoded" to speak of.  A nap between frames is the endpoint's
    59 tok/s, and it is spent on the worker thread, which is the whole
    point of the arrangement being tested.
    """

    def __init__(self, *replies, piece=20, nap=0.02):
        super().__init__(*replies, piece=piece)
        self.nap = nap

    def _frames(self, reply):
        for frame in super()._frames(reply):
            time.sleep(self.nap)
            yield frame


# ── being steered while the model is writing ────────────────────────────────


class TestAnInjectionLandsAtTheSameBoundaryInBothFacades:
    """An operator speaks while a model call is in flight.

    The command is written to a real pipe from inside the model call, so
    it arrives while the loop is *awaiting* that call — the case the
    coroutine made new, because under ``arun`` the loop is free while it
    waits and could in principle have applied it early.  It must not: the
    only safe moment is the step boundary, where the model has finished a
    turn and has not begun the next.
    """

    def steer(self, bus, steering, coroutine):
        records = []
        steer = steering()
        model = SpeakingModel(
            steer, 0, [{"control": "inject", "text": "the SECOND corpus"}],
            *REPLIES)
        run = Run(**objects(bus, records, model=Model(ask=model),
                            bounds=Bounds(control=steer.channel)))
        if coroutine:
            asyncio.run(run.arun("go"))
        else:
            run.run("go")
        return records, model

    @pytest.mark.parametrize("coroutine", [False, True])
    def test_it_rides_the_next_step_and_no_earlier_one(
            self, bus, steering, coroutine):
        records, _ = self.steer(bus, steering, coroutine)
        steps = events(records, STEP_STARTED)
        assert [step.get("injected") for step in steps] == \
            [None, ["the SECOND corpus"]]

    @pytest.mark.parametrize("coroutine", [False, True])
    def test_the_model_is_shown_it_before_the_second_call_and_not_during(
            self, bus, steering, coroutine):
        records, model = self.steer(bus, steering, coroutine)
        first, second = model.seen[0], model.seen[1]
        assert not any("SECOND corpus" in turn["content"] for turn in first)
        assert second[-1] == {"role": "user", "content": "the SECOND corpus"}


# ── being stopped ───────────────────────────────────────────────────────────


class TestBeingCancelled:
    """Two ways to stop a run, and they end it the same way.

    The switch at a drain point is what a ``SIGTERM``, a ``--control``
    ``cancel`` and a library caller have always thrown, and it is
    unchanged.  A cancelled *task* is new — it is what somebody holding
    the coroutine can now do — and the property that matters is that it
    lands in the same place: one ``mission_finished``, ``reason:
    cancelled``, and no answer.
    """

    def finished(self, records):
        return events(records, MISSION_FINISHED)

    def test_the_switch_thrown_during_a_call_stops_the_run_at_the_boundary(
            self, bus):
        """Unchanged behaviour, restated under the coroutine: the switch is
        noticed where it has always been noticed, and not the instant it is
        thrown — the model call that was in flight still finishes."""
        switch = Cancellation()

        class Throwing(ScriptedModel):
            def __call__(self, messages):
                switch.cancel("test")
                return super().__call__(messages)

        records = []
        run = Run(**objects(bus, records,
                            model=Model(ask=Throwing(*REPLIES)),
                            bounds=Bounds(cancel=switch)))
        transcript = asyncio.run(run.arun("go"))
        assert (transcript.outcome, transcript.reason) == \
            ("incomplete", CANCELLED)
        assert [r["reason"] for r in self.finished(records)] == [CANCELLED]

    def test_a_cancelled_task_ends_with_the_same_verdict(self, bus):
        """``task.cancel()`` while the model call is in flight.  The await
        raises :class:`asyncio.CancelledError`, ``arun`` catches it at the
        drain point it was standing on, and the ``finally`` writes the one
        record a watcher is owed."""
        records = []
        holder = {}

        class Cancelling(ScriptedModel):
            def __call__(self, messages):
                holder["loop"].call_soon_threadsafe(holder["task"].cancel)
                time.sleep(0.05)
                return super().__call__(messages)

        run = Run(**objects(bus, records,
                            model=Model(ask=Cancelling(*REPLIES))))

        async def main():
            holder["loop"] = asyncio.get_running_loop()
            holder["task"] = asyncio.ensure_future(run.arun("go"))
            return await holder["task"]

        transcript = asyncio.run(main())
        assert (transcript.outcome, transcript.reason) == \
            ("incomplete", CANCELLED)
        assert [r["reason"] for r in self.finished(records)] == [CANCELLED]
        assert events(records, ANSWER) == []

    def test_the_cancelled_task_still_says_the_mission_is_over_once(
            self, bus):
        """Exactly one, and it is the last record.  A stream that just
        stops is indistinguishable from an agent that is thinking, and two
        closings render as two missions."""
        records = []
        holder = {}

        class Cancelling(ScriptedModel):
            def __call__(self, messages):
                holder["loop"].call_soon_threadsafe(holder["task"].cancel)
                time.sleep(0.05)
                return super().__call__(messages)

        run = Run(**objects(bus, records,
                            model=Model(ask=Cancelling(*REPLIES))))

        async def main():
            holder["loop"] = asyncio.get_running_loop()
            holder["task"] = asyncio.ensure_future(run.arun("go"))
            return await holder["task"]

        asyncio.run(main())
        assert [r["event"] for r in records].count(MISSION_FINISHED) == 1
        assert records[-1]["event"] == MISSION_FINISHED


# ── two children at once ────────────────────────────────────────────────────


class TestTwoChildrenAwaitedTogether:
    """The capability this lane was for, and the race it leaves behind.

    The swarm is still serial and this lane did not change it: what is
    asserted here is that ``asyncio.gather`` over :meth:`Run.child` *works*
    — one loop, one numbering, one stream — so that the parallel-children
    lane has something to turn on rather than something to build.

    **The numbering is deterministic here and is not yet safe in general.**
    A branch takes its offset from the parent's counter when it is
    constructed, which is a read and a write with no lock; these children
    are constructed inside their own coroutines and the first suspension
    point of a run comes *after* its first ``step_started``, so A is
    numbered and B is built afterwards.  Two children built in the same
    breath would collide, and the lock that fixes it is the
    parallel-children lane's — ``ROADMAP.md`` §2.6.2, item 5, which is also
    where the OPTIONAL ``branch`` field belongs.
    """

    def gathered(self, bus, model, watch=None):
        records = []
        parent = Run(**objects(
            bus, records, model=model,
            # No result store, because two children on one bus collide on
            # it: `MissionResultStore.register_on` refuses a name that is
            # taken, and `ToolPlane.lease` — the per-child store, namespaced
            # — is the parallel-children lane's and still raises
            # `NotImplementedError`. The first thing that lane has to build,
            # stated here as a constraint this test had to work around
            # rather than as a sentence in a document.
            plane=ToolPlane(bus=bus, offered=["catalog.search"],
                            store_tool="")))
        if watch is not None:
            parent.observer.sinks = parent.observer.sinks + (watch,)

        async def one(name):
            return await parent.child(branch=name, stage=True).arun("go")

        async def both():
            return await asyncio.gather(one("a"), one("b"))

        return asyncio.run(both()), records

    def test_their_steps_are_numbered_in_one_sequence(self, bus):
        transcripts, records = self.gathered(bus, Model(ask=ScriptedModel()))
        assert [t.answer for t in transcripts] == ["done", "done"]
        assert [r["index"] for r in events(records, STEP_STARTED)] == [0, 1]

    def test_their_model_calls_are_in_flight_together(self, bus):
        """Two children, two endpoints answering at once.  Serial code
        cannot produce this number, whatever else it produces."""
        model = Slow(nap=0.15)
        self.gathered(bus, Model(ask=model))
        assert model.most == 2

    def test_a_child_runs_on_the_parents_loop(self, bus):
        """No child opens a loop of its own: the records of both children
        are emitted from the one loop the parent is running on.  A child
        reached through the synchronous façade from inside ``arun`` would
        be answered on a worker thread with a loop of its own, and this is
        what says so."""
        seen = []

        def watch(record):
            if record["event"] != STEP_STARTED:
                return
            try:
                seen.append(asyncio.get_running_loop())
            except RuntimeError:                # pragma: no cover - the bug
                seen.append(None)

        self.gathered(bus, Model(ask=ScriptedModel()), watch=watch)
        assert len(seen) == 2
        assert seen[0] is seen[1] is not None


# ── which loop a synchronous caller gets ────────────────────────────────────


class TestWhichLoopRunUses:
    """The rule :func:`core.runtime.run._to_completion` states, both ways.

    Not a style question: the second case is a caller inside ``async def``
    reaching for the method that has been synchronous since the first
    version of this harness, and the two wrong answers are an exception
    (``asyncio.run cannot be called from a running event loop``) and a
    hang.  It gets neither.
    """

    def test_with_no_loop_running_it_simply_runs(self, bus):
        records = []
        transcript = Run(**six(bus, records)).run("find assets")
        assert transcript.outcome == "answered"
        assert records[-1]["event"] == MISSION_FINISHED

    def test_from_inside_a_running_loop_it_does_not_deadlock(self, bus):
        """Driven from a **daemon thread** with a bounded join, because the
        failure this is written against is a hang: a test that deadlocked
        in the main thread would take the suite with it instead of
        reporting."""
        records = []
        run = Run(**six(bus, records))
        got = {}

        def inside():
            async def main():
                transcript = run.run("find assets")
                # And the loop it was called from still turns afterwards.
                await asyncio.sleep(0)
                return transcript

            got["transcript"] = asyncio.run(main())

        thread = threading.Thread(target=inside, daemon=True)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive(), "run() inside a running loop hung"
        assert got["transcript"].answer == "Two hits for assets."
        assert records[-1]["event"] == MISSION_FINISHED

    def test_both_ways_produce_the_same_stream(self, bus):
        """The wrapper is a policy about event loops and nothing else."""
        plain = []
        Run(**six(bus, plain)).run("find assets")
        nested = []
        run = Run(**six(bus, nested))

        def inside():
            async def main():
                return run.run("find assets")

            asyncio.run(main())

        thread = threading.Thread(target=inside, daemon=True)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert without_the_clock(plain) == without_the_clock(nested)
