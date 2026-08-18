# tests/test_run.py — the six objects, and the adapter that builds them

"""What each of the six owns, and that the adapter changes nothing.

``tests/test_mission.py`` is the loop's conformance suite and it stays on
:class:`~core.runtime.mission.MissionRunner` — it is the reason the adapter
exists.  ``tests/test_run_corpus.py`` is the guard that the loop's records
did not move.  This file is the third thing: the *shapes*.  Each object
built from plain values, each frozen one refusing to be edited, each of the
four behaviours that were lifted out of a method and given to an owner
(:meth:`Bounds.stop`, :meth:`Model.spend`, :meth:`Observer.emit`, the three
facts :class:`ToolPlane` reads off a bus), and the equivalence that makes
the adapter an adapter: thirty parameters and six objects produce the
same transcript and the same stream.
"""

import json
from dataclasses import FrozenInstanceError

import pytest

from core.budgets import BudgetExhausted, Cancellation, Deadline
from core.contracts.schemas import PolicyPack
from core.durable import RunStore
from core.runtime.mission import (
    ANSWER_TOOL, CANCELLED, JSON_PROTOCOL, NATIVE_PROTOCOL, MissionRunner,
)
from core.runtime.results import RESULT_TOOL, MissionResultStore
from core.runtime.backends.base import Usage
from core.runtime.run import (
    NO_SUPERVISOR, Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.supervisor import Supervisor
from core.runtime.usage import Ledger
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from core.tools.sandbox import NoneSandbox
# One owner of "a model that replays canned replies": the adapter's suite
# already has one, and the equivalence below has to script both sides of a
# comparison with the same thing or it is comparing two fakes.
from tests.test_mission import ScriptedModel


@pytest.fixture
def bus():
    b = ToolBus(
        capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    return b


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


#: One provider report, as the ledger reads it.  The real
#: :class:`~core.runtime.backends.base.Usage` and not a stand-in: the ledger
#: refuses a shape that is not a report, which is a rule worth running
#: against rather than around.
def usage():
    return Usage(prompt_tokens=11, completion_tokens=3, total_tokens=14)


#: The home directory the redactor is going to take out of a record.  Set on
#: the environment by :func:`pinned` below, exactly as
#: ``tests/test_redact.py`` does, so a developer's own ``$HOME`` is not what
#: these assertions are written against.
HOME = "/home/testuser"


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setenv("HOME", HOME)


# ── each of the six, from plain values ──────────────────────────────────────


class TestTheSixAreBuiltFromPlainValues:
    """A constructor that is data is only data if a caller can write it.

    Nothing here is a mock of anything: a personality is strings, a plane
    is a bus and a list, bounds are numbers, a store is ``None`` five
    times over, an observer is a list's ``append``, and a model is a
    function.  That is the claim ``ROADMAP.md`` §2.6.1 makes about the
    constructor, and this is it stated as six lines somebody could type.
    """

    def test_a_personality_is_a_prompt_and_what_it_is_held_to(self):
        p = Personality(system_message="You are Tai.",
                        history=[{"role": "user", "content": "hi"}])
        assert p.system_message == "You are Tai."
        assert p.history == [{"role": "user", "content": "hi"}]
        assert p.grounding is None and p.critic is None and p.sdk_import == ""

    def test_a_personality_validates_its_history_at_the_door(self):
        """The same refusal :func:`validate_history` gives the CLI, at the
        one place a history now enters the loop."""
        with pytest.raises(ValueError, match="role"):
            Personality(history=[{"role": "system", "content": "no"}])

    def test_a_tool_plane_is_a_bus_and_a_closed_set(self, bus):
        plane = ToolPlane(bus=bus, offered=["catalog.search"])
        assert plane.bus is bus
        assert plane.offered == ["catalog.search"]
        assert plane.store_tool == RESULT_TOOL
        assert plane.gated == frozenset()

    def test_a_plane_keeps_its_own_list(self, bus):
        """The membership moves under a running mission; the caller's list
        must not move with it."""
        mine = ["catalog.search"]
        plane = ToolPlane(bus=bus, offered=mine)
        plane.offered.append("late.arrival")
        assert mine == ["catalog.search"]

    def test_bounds_are_numbers_and_default_to_no_bound_at_all(self):
        b = Bounds()
        assert b.max_steps == 0
        assert b.deadline is None and b.cancel is None and b.control is None
        assert b.supervisor is None

    def test_bounds_read_a_negative_ceiling_as_no_ceiling(self):
        assert Bounds(max_steps=-3).max_steps == 0
        assert Bounds(gate_wait_s=-1.0).gate_wait_s == 0.0

    def test_a_store_is_five_nones_and_records_nothing(self):
        s = Store()
        assert (s.runs, s.run_id, s.recorder, s.approvals, s.ticket) == \
            (None, "", None, None, None)

    def test_an_observer_is_the_sinks_it_was_given(self):
        seen = []
        assert Observer(seen.append).sinks == (seen.append,)

    def test_an_observer_drops_a_sink_that_is_none(self):
        """The CLI passes ``watcher``, which is ``None`` on a run nobody is
        watching, and a run with no watcher is the common case."""
        assert Observer(None).sinks == ()

    def test_a_model_is_a_function(self):
        m = Model(ask=ScriptedModel())
        assert m.protocol == JSON_PROTOCOL and m.native is False
        assert m.ledger is None

    def test_a_model_refuses_a_protocol_nobody_speaks(self):
        with pytest.raises(ValueError, match="protocol must be one of"):
            Model(ask=ScriptedModel(), protocol="telepathy")

    def test_six_objects_are_a_run(self, bus):
        run = Run(Personality(), ToolPlane(bus=bus, offered=["catalog.search"]),
                  Bounds(), Store(), Observer(), Model(ask=ScriptedModel()))
        assert run.offered == ["catalog.search", RESULT_TOOL]
        assert isinstance(run.results, MissionResultStore)


class TestTheFourFrozenOnesRefuseToBeEdited:
    """Four of the six describe a run and do not change inside one.

    A field reassigned mid-run is the defect the whole arrangement is
    against: the plane's *membership* moves and there is a method that
    moves it, the ledger accumulates and it is not frozen, and everything
    else is settled before the first turn.
    """

    @pytest.mark.parametrize("obj,field,value", [
        (Personality(), "system_message", "new"),
        (ToolPlane(bus=object()), "store_tool", "other"),
        (Bounds(), "max_steps", 9),
        (Store(), "run_id", "run-1"),
    ])
    def test_it_cannot_be_reassigned(self, obj, field, value):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)


# ── Bounds owns the stop verdict ────────────────────────────────────────────


class TestBoundsIsTheOnlyVerdict:
    """``stop()`` is ``MissionRunner._stop``, unchanged and in one place.

    Three inputs and a precedence, and the precedence is the interesting
    one: when a clock and a person say stop at the same moment the person
    wins, because "somebody stopped this" is the truer sentence to show
    them than "it ran out of seconds".
    """

    def test_nothing_asked_it_to_stop(self):
        assert Bounds().stop() is None

    def test_a_cancellation_is_incomplete_and_says_why(self):
        cancel = Cancellation()
        cancel.cancel("operator")
        assert Bounds(cancel=cancel).stop() == ("incomplete", None, CANCELLED)

    def test_a_bare_event_works_too(self):
        """``is_set()`` is the whole of what a cancellation has to be."""
        import threading
        event = threading.Event()
        event.set()
        assert Bounds(cancel=event).stop()[0] == "incomplete"

    def test_a_spent_clock_is_budget_exhausted_and_names_the_clock(self):
        outcome, budget, reason = Bounds(
            deadline=Deadline(0.0).start()).stop()
        assert outcome == "budget_exhausted"
        assert isinstance(budget, BudgetExhausted)
        assert budget.which == "seconds"
        assert reason == ""

    def test_a_clock_that_has_not_run_out_does_not_stop_it(self):
        assert Bounds(deadline=Deadline(600.0).start()).stop() is None

    def test_the_person_outranks_the_clock(self):
        cancel = Cancellation()
        cancel.cancel("operator")
        outcome, budget, reason = Bounds(
            deadline=Deadline(0.0).start(), cancel=cancel).stop()
        assert (outcome, budget, reason) == ("incomplete", None, CANCELLED)


class TestABareBoundsIsWatched:
    """``Bounds()`` builds a supervisor, and that is the one default here
    that is not *nothing*.

    Every other field of :class:`Bounds` is a bound an operator asks for and
    the framework imposes none.  The supervisor is not one of those: it is
    what *replaced* the step budget, it is the only thing that ends an
    endless loop, and left unset it made the documented six-object example
    — ``Run(personality, plane, Bounds(), …)`` — fail open on the single
    bound 1.0 has.
    """

    def _run(self, model, bounds=None):
        return Run(Personality(system_message="You are Tai."),
                   ToolPlane(bus=object(), offered=[]),
                   Bounds() if bounds is None else bounds,
                   Store(), Observer(), model)

    def test_a_bare_bounds_gets_one(self):
        run = self._run(Model(ask=ScriptedModel()))
        assert isinstance(run.bounds.supervisor, Supervisor)

    def test_it_is_asked_through_the_plain_function_when_there_is_one(self):
        plain = ScriptedModel()
        run = self._run(Model(ask=ScriptedModel(), plain=plain))
        assert run.bounds.supervisor._chat is plain

    def test_a_json_run_with_no_plain_function_is_still_watched(self):
        """The documented example is ``Model(ask=my_chat_fn)`` and nothing
        else. Under the JSON protocol ``ask`` IS plain chat — the catalogue
        lives in the system turn and a review replaces that turn — so the
        example a platform copies gets the endless-loop catch."""
        ask = ScriptedModel()
        run = self._run(Model(ask=ask))
        assert run.bounds.supervisor._chat is ask

    def test_a_native_run_with_no_plain_function_is_not(self):
        """A review is a question, and a model with a function namespace
        declared answers a question with a tool call — the one failure
        `plain` exists to prevent. Better no watcher than a review answered
        with a call to a tool."""
        run = self._run(Model(ask=ScriptedModel(), protocol=NATIVE_PROTOCOL))
        assert run.bounds.supervisor is None

    def test_a_supervisor_that_was_handed_in_is_the_one_used(self):
        mine = object()
        run = self._run(Model(ask=ScriptedModel()),
                        bounds=Bounds(supervisor=mine))
        assert run.bounds.supervisor is mine

    def test_the_opt_out_is_a_word_and_it_means_no_watcher(self):
        """``Bounds(supervisor=NO_SUPERVISOR)`` — a run nothing can stop.
        Normalised back to ``None`` so the loop keeps ONE spelling of
        "unwatched" and no reader learns a second sentinel."""
        run = self._run(Model(ask=ScriptedModel()),
                        bounds=Bounds(supervisor=NO_SUPERVISOR))
        assert run.bounds.supervisor is None

    def test_the_callers_bounds_object_is_left_as_it_was(self):
        """Frozen and shared: a caller still holding the bounds it passed
        still holds the bounds it passed."""
        mine = Bounds()
        self._run(Model(ask=ScriptedModel()), bounds=mine)
        assert mine.supervisor is None

    def test_one_supervisor_for_a_turn_and_its_children(self):
        run = self._run(Model(ask=ScriptedModel()))
        assert run.child(branch="s1").bounds.supervisor is \
            run.bounds.supervisor

    def test_a_watched_run_that_answers_never_asks_the_watcher_anything(
            self, bus):
        """The default costs a healthy run nothing: no signal fires, so no
        review call is made and the model is asked exactly the turns the
        mission took."""
        ask = ScriptedModel('{"answer": "done"}')
        run = Run(Personality(system_message="You are Tai."),
                  ToolPlane(bus=bus, offered=["catalog.search"]),
                  Bounds(), Store(), Observer(), Model(ask=ask))
        assert run.run("q").outcome == "answered"
        assert len(ask.seen) == 1


# ── Model owns the fold ─────────────────────────────────────────────────────


class TestModelSpendsOnce:
    """``spend()`` is ``MissionRunner._spent``: fold, and render the field."""

    def test_it_folds_into_the_ledger_and_renders_the_call(self):
        ledger = Ledger()
        model = Model(ask=ScriptedModel(), usage_fn=usage)
        assert model.spend(ledger) == {
            "usage": {"prompt_tokens": 11, "completion_tokens": 3,
                      "total_tokens": 14}}
        assert ledger.as_record()["calls"] == 1

    def test_two_calls_accumulate_in_the_one_ledger(self):
        ledger = Ledger()
        model = Model(ask=ScriptedModel(), usage_fn=usage)
        model.spend(ledger)
        model.spend(ledger)
        assert ledger.as_record()["total_tokens"] == 28

    def test_nothing_reported_is_an_absent_field_and_not_a_zero(self):
        """A provider that says nothing and a call that cost nothing are
        different facts, and the wire keeps them different."""
        assert Model(ask=ScriptedModel()).spend(Ledger()) == {}
        assert Model(ask=ScriptedModel(),
                     usage_fn=lambda: None).spend(Ledger()) == {}

    def test_a_side_channel_that_throws_cannot_end_a_mission(self):
        def boom():
            raise RuntimeError("the client is gone")

        assert Model(ask=ScriptedModel(), usage_fn=boom).spend(Ledger()) == {}


# ── the Observer is the choke point ─────────────────────────────────────────


class TestTheObserverIsTheChokePoint:
    """``emit()`` is ``MissionRunner._emit``: redact, persist, then tell.

    Three claims and each is a separate failure: a record that reached a
    pane unscrubbed, a record a consumer saw that the transcript does not
    have, and a chat turn that emitted anything at all.
    """

    def test_a_record_is_scrubbed_before_anybody_sees_it(self, pinned):
        seen = []
        Observer(seen.append).emit(
            "reply_rejected", index=0,
            problem=f"{HOME}/secret/notes.txt is not JSON")
        assert seen[0]["problem"] == "<home>/secret/notes.txt is not JSON"

    def test_the_output_a_validator_reads_is_left_verbatim(self, pinned):
        """``output`` is what the grounding validator checks an answer
        against, out of the store; a rewritten stream copy would no longer
        match it."""
        seen = []
        leak = f"{HOME}/data/corpus.txt"
        Observer(seen.append).emit("tool_result", output=leak, error=leak)
        assert seen[0]["output"] == leak
        assert seen[0]["error"] == "<home>/data/corpus.txt"

    def test_the_record_is_in_the_log_before_it_is_on_the_pane(self, tmp_path):
        """The sink is a CLIENT of the durable log: a record a consumer saw
        is a record the transcript has."""
        runs = RunStore(tmp_path / "runs")
        run_id = runs.create().run_id
        depth = []
        store = Store(runs=runs, run_id=run_id)
        Observer(lambda record: depth.append(len(runs.records(run_id))),
                 store=store).emit("answer", text="done", outcome="answered")
        assert depth == [1]
        assert runs.records(run_id)[0]["event"] == "answer"

    def test_what_is_persisted_is_the_scrubbed_copy(self, tmp_path, pinned):
        """A credential that must not reach a pane must not reach a file on
        disk either."""
        runs = RunStore(tmp_path / "runs")
        run_id = runs.create().run_id
        Observer(store=Store(runs=runs, run_id=run_id)).emit(
            "answer", text=f"{HOME}/k", outcome="answered")
        assert runs.records(run_id)[0]["text"] == "<home>/k"

    def test_a_sink_that_throws_does_not_end_the_mission(self):
        def angry(record):
            raise RuntimeError("the browser closed")

        Observer(angry).emit("answer", text="done", outcome="answered")

    def test_no_sinks_and_no_log_returns_at_the_first_line(self, monkeypatch):
        """A chat turn emits exactly the nothing it emits today, and the
        redactor is not even reached — which is the line, not an outcome
        that happens to look like it."""
        def refuse(record):
            raise AssertionError("the redactor was reached")

        monkeypatch.setattr("core.runtime.run.scrub_record", refuse)
        Observer().emit("answer", text="done", outcome="answered")

    def test_a_log_with_no_sink_still_writes(self, tmp_path):
        runs = RunStore(tmp_path / "runs")
        run_id = runs.create().run_id
        Observer(store=Store(runs=runs, run_id=run_id)).emit(
            "answer", text="done", outcome="answered")
        assert len(runs.records(run_id)) == 1

    def test_every_sink_is_told(self):
        one, two = [], []
        Observer(one.append, two.append).emit("answer", text="d",
                                              outcome="answered")
        assert len(one) == len(two) == 1


class TestABranchedObserverIsTheSameStream:
    """One run, one log, one writer — whatever a child's records are called.

    The rename that ``_StageObserver`` does by hand is lane B's; what is
    here is the sharing, which is the part a child cannot be given twice.
    """

    def test_it_shares_the_sinks_and_the_store_by_identity(self, tmp_path):
        seen = []
        store = Store(runs=RunStore(tmp_path / "runs"), run_id="run-1")
        parent = Observer(seen.append, store=store)
        child = parent.branch("step-1")
        assert child.sinks == parent.sinks
        assert child.store is store
        assert child.name == "step-1"

    def test_the_branch_name_does_not_reach_the_wire(self):
        """``branch`` is an OPTIONAL field the parallel-children lane adds.
        A record carrying one now would be a contract change in the lane
        whose whole claim is that it makes none."""
        seen = []
        Observer(seen.append, branch="step-1").emit(
            "answer", text="done", outcome="answered")
        assert seen[0] == {"event": "answer", "text": "done",
                           "outcome": "answered"}


# ── the plane reads the bus, and stores nothing ─────────────────────────────


class TestThePlaneReadsTheBus:
    """``sandbox``, ``audit_ref`` and ``profile`` are properties.

    A field would be a second owner of each — a value snapshotted at
    construction and reported afterwards whatever the bus went on to say.
    The day the two disagree, the stream names a file nothing wrote to,
    which is worse than no ``audit_ref`` at all because a consumer would
    believe it.
    """

    def test_they_are_not_fields(self):
        from dataclasses import fields
        names = {f.name for f in fields(ToolPlane)}
        assert not names & {"sandbox", "audit_ref", "profile",
                            "profile_field"}

    def test_the_sandbox_is_the_word_the_installed_runner_answers_to(self):
        none = ToolBus(
            capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])),
            sandbox=NoneSandbox())
        assert ToolPlane(bus=none).sandbox == "none"

    def test_the_word_comes_off_the_bus_and_is_not_inferred(self):
        """Whatever the deployment installed says about itself — not a
        guess this module makes from the host it is running on."""
        class Bus:
            sandbox_name = "bwrap"

        assert ToolPlane(bus=Bus()).sandbox == "bwrap"

    def test_a_bus_with_no_such_word_is_reported_as_none(self):
        assert ToolPlane(bus=object()).sandbox == "none"

    def test_the_audit_ref_follows_the_bus(self):
        class Bus:
            audit_ref = None

        plane = ToolPlane(bus=Bus())
        assert plane.audit_ref is None
        Bus.audit_ref = "/tmp/audit.jsonl"
        assert plane.audit_ref == "/tmp/audit.jsonl"

    def test_the_profile_field_is_absent_when_there_is_no_profile(self, bus):
        assert ToolPlane(bus=bus).profile_field == {}
        assert ToolPlane(bus=bus).profile is None

    def test_the_profile_field_names_the_profile_when_there_is_one(self):
        from core.contracts.schemas import ProfileMode
        engine = CapabilityEngine()
        engine.set_profile(ProfileMode.SAFE)
        plane = ToolPlane(bus=ToolBus(capability_engine=engine))
        assert plane.profile_field == {"profile": "safe"}
        assert plane.profile == "safe"

    def test_a_bus_that_cannot_list_itself_is_a_plane_that_never_changes(self):
        assert ToolPlane(bus=object()).registered() is None

    def test_registered_is_what_the_bus_holds(self, bus):
        assert "catalog.search" in ToolPlane(bus=bus).registered()

    def test_the_deadline_probe_is_asked_of_the_signature(self, bus):
        assert ToolPlane(bus=bus).takes_deadline() is True
        assert ToolPlane(bus=object()).takes_deadline() is False

    def test_lease_names_the_branch_and_shares_everything_else(self, bus):
        """``lease`` is implemented now (Phase 11, lane D) and it changes
        exactly one thing.  ``narrow`` used to sit beside it here as the
        second refusal; both are behaviour, so both are asserted as such.
        What a lease is FOR — one ``mission_result`` in front of two
        children's stores — is proved in ``tests/test_run_parallel.py``."""
        plane = ToolPlane(bus=bus, offered=["catalog.search"])
        leased = plane.lease("step-1")
        assert leased is not plane
        assert leased.store_branch == "step-1"
        assert plane.store_branch == ""
        # By identity, every one of them: a lease is the same plane.
        assert leased.bus is plane.bus
        assert leased.offered is plane.offered
        assert leased.stores is plane.stores
        assert leased.store_tool == plane.store_tool

    def test_narrow_is_implemented_and_returns_a_new_plane(self, bus):
        """``set_scope_constraints`` is ``narrow`` now — governance's one
        surface. It returns a new plane and leaves the original; the denial
        semantics it applies to the bus's engine are proved in
        ``tests/test_run_roles.py``."""
        plane = ToolPlane(bus=bus)
        narrowed = plane.narrow(["read"])
        assert narrowed is not plane
        assert isinstance(narrowed, ToolPlane)


# ── a child run ─────────────────────────────────────────────────────────────


class TestAChildSharesWhatItMustShare:
    """``child()`` is what the staged path's ``_runner`` and ``_direct``
    become.  What makes it correct is identity, not equality: one log, one
    stream, one ledger, one clock, one supervisor."""

    @pytest.fixture
    def parent(self, bus):
        return Run(Personality(system_message="You are Tai."),
                   ToolPlane(bus=bus, offered=["catalog.search"]),
                   Bounds(supervisor=object()), Store(run_id="run-1"),
                   Observer(), Model(ask=ScriptedModel(), ledger=Ledger()))

    def test_the_store_the_observer_and_the_model_are_the_same_objects(
            self, parent):
        child = parent.child()
        assert child.store is parent.store
        assert child.observer is parent.observer
        assert child.model is parent.model

    def test_the_plane_and_the_bounds_come_across_too(self, parent):
        child = parent.child()
        assert child.plane is parent.plane
        assert child.bounds is parent.bounds
        assert child.bounds.supervisor is parent.bounds.supervisor

    def test_one_ledger_means_one_invoice(self, parent):
        assert parent.child().model.ledger is parent.model.ledger

    def test_a_child_takes_the_personality_it_is_given(self, parent):
        child = parent.child(personality=Personality(system_message="Step 1."))
        assert child.personality.system_message == "Step 1."
        assert parent.personality.system_message == "You are Tai."

    def test_a_child_takes_the_bounds_it_is_given(self, parent):
        tighter = Bounds(max_steps=2)
        child = parent.child(bounds=tighter)
        assert child.bounds.max_steps == 2
        assert parent.bounds.max_steps == 0

    def test_a_child_given_narrower_bounds_keeps_the_turns_supervisor(
            self, parent):
        """A narrower `Bounds` says "less clock" or "fewer steps". It never
        says "a second review budget" — and left alone it would be one,
        because `Run.__init__` builds a supervisor for bounds that have
        none, and a plan that loops across its steps is exactly the pattern
        no single sub-mission can see."""
        child = parent.child(bounds=Bounds(max_steps=2))
        assert child.bounds.supervisor is parent.bounds.supervisor

    def test_a_child_may_still_be_watched_by_something_else(self, parent):
        """Handed one, the caller's wins: this is not the parent forcing its
        watcher on a child, it is a default for the field nobody set."""
        mine = object()
        child = parent.child(bounds=Bounds(supervisor=mine))
        assert child.bounds.supervisor is mine

    def test_a_named_child_gets_its_own_observer_on_the_same_sink(self):
        seen = []
        parent = Run(Personality(), ToolPlane(bus=object()), Bounds(),
                     Store(), Observer(seen.append),
                     Model(ask=ScriptedModel()))
        child = parent.child(branch="step-1")
        assert child.observer is not parent.observer
        assert child.observer.sinks == parent.observer.sinks
        assert child.observer.store is parent.observer.store

    def test_a_child_has_its_own_result_store(self, parent):
        """Handles are a run's own: ``r1`` in a child must not address the
        parent's first result."""
        assert parent.child().results is not parent.results


# ── the adapter ─────────────────────────────────────────────────────────────


REPLIES = (tool_call("catalog.search", q="assets"),
           json.dumps({"answer": "Two hits for assets."}))


def six(bus, records, **overrides):
    """The six objects a ``MissionRunner`` with these keywords would build."""
    store = Store()
    return dict(
        personality=Personality(system_message="You are Tai."),
        plane=ToolPlane(bus=bus, offered=["catalog.search"]),
        bounds=Bounds(),
        store=store,
        observer=Observer(records.append, store=store),
        model=Model(ask=ScriptedModel(*REPLIES), usage_fn=usage),
        **overrides,
    )


def without_the_clock(records):
    return [{k: v for k, v in r.items() if k != "elapsed_s"} for r in records]


class TestTheAdapterIsTheSameRun:
    """Thirty parameters and six objects produce one run.

    This is the assertion the adapter exists to make good on, and it is
    made twice — the transcript a caller is handed, and the stream a
    watcher is shown — because a refactor can preserve either one alone.
    """

    def _both(self, bus):
        direct, adapted = [], []
        run = Run(**six(bus, direct))
        mine = run.run("find assets")
        theirs = MissionRunner(
            ScriptedModel(*REPLIES), bus, ["catalog.search"],
            system_message="You are Tai.", observer=adapted.append,
            usage_fn=usage,
        ).run("find assets")
        return (mine, direct), (theirs, adapted)

    def test_the_transcripts_are_the_same(self, bus):
        (mine, _), (theirs, _) = self._both(bus)
        assert (mine.answer, mine.outcome, mine.catalogue) == \
            (theirs.answer, theirs.outcome, theirs.catalogue)
        assert [(s.index, s.tool, s.arguments, s.output, s.handle)
                for s in mine.steps] == \
            [(s.index, s.tool, s.arguments, s.output, s.handle)
             for s in theirs.steps]

    def test_the_streams_are_the_same(self, bus):
        (_, direct), (_, adapted) = self._both(bus)
        assert without_the_clock(direct) == without_the_clock(adapted)

    def test_the_ledger_is_the_same(self, bus):
        (mine, _), (theirs, _) = self._both(bus)
        assert mine.usage.as_record() == theirs.usage.as_record()

    def test_the_adapter_carries_every_keyword_it_is_given(self, bus):
        """The mutation this class is checked with: drop one keyword on
        the way to an object and this fails.  Each of these is a keyword
        landing on a different one of the six.
        """
        runner = MissionRunner(
            ScriptedModel(), bus, ["catalog.search"],
            system_message="You are Tai.", max_steps=4,
            store_tool="results", gated=["catalog.search"],
            run_id="run-9f3c1e2a", protocol=JSON_PROTOCOL,
            max_result_bytes=500, gate_wait_s=12.0,
        )
        run = runner._run
        assert run.personality.system_message == "You are Tai."
        assert run.plane.offered == ["catalog.search"]
        assert run.plane.store_tool == "results"
        assert run.plane.gated == frozenset({"catalog.search"})
        assert run.bounds.max_steps == 4
        assert run.bounds.max_result_bytes == 500
        assert run.bounds.gate_wait_s == 12.0
        assert run.store.run_id == "run-9f3c1e2a"
        assert run.model.protocol == JSON_PROTOCOL
        assert run.observer.store is run.store

    def test_the_surface_a_caller_had_still_answers(self, bus):
        """Every name ``core/cli.py``, the swarm, the resume and this
        class's own suite reach for."""
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"],
                               run_id="run-1")
        assert runner.run_id == "run-1"
        assert runner.protocol == JSON_PROTOCOL
        assert isinstance(runner.store, MissionResultStore)
        assert runner.offered == ["catalog.search", RESULT_TOOL]
        assert runner.gated == []
        assert runner.pinned == 2
        assert "catalog.search" in runner.catalogue()
        assert runner.seed("go")[-1] == {"role": "user", "content": "go"}
        assert runner.system_turn()["role"] == "system"

    def test_the_result_store_follows_a_resumption(self, bus):
        """``store`` is a property and not a field copied at construction:
        a resumed run adopts the store the earlier stretch filled, and a
        caller reading ``runner.store`` has to get that one."""
        runner = MissionRunner(ScriptedModel(), bus, ["catalog.search"])
        adopted = MissionResultStore()
        runner._run.results = adopted
        assert runner.store is adopted

    def test_the_two_static_helpers_are_still_callable_off_the_class(self):
        decision, problem = MissionRunner._parse('{"answer": "done"}')
        assert decision == {"answer": "done"} and problem is None
        assert MissionRunner._heal_native([{"role": "user", "content": "x"}]) \
            == [{"role": "user", "content": "x"}]


class TestTheRunRefusesWhatTheRunnerRefused:
    """Construction-time refusals move with the objects that own them."""

    def test_a_native_run_may_not_offer_the_answer_function(self, bus):
        with pytest.raises(ValueError, match=ANSWER_TOOL):
            Run(Personality(),
                ToolPlane(bus=bus, offered=[ANSWER_TOOL]),
                Bounds(), Store(), Observer(),
                Model(ask=ScriptedModel(), protocol=NATIVE_PROTOCOL))

    def test_the_json_protocol_does_not_care(self, bus):
        Run(Personality(), ToolPlane(bus=bus, offered=[ANSWER_TOOL]),
            Bounds(), Store(), Observer(), Model(ask=ScriptedModel()))
