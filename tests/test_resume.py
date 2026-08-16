# tests/test_resume.py — carrying a recorded mission on, and closing the dead ones

"""Resume, asserted against the run that never stopped.

The centrepiece is :class:`TestTheReplayIsTheRunThatNeverStopped`. A resume
is only worth having if the model on the far side of it cannot tell: the same
objective, the same catalogue, the same result handles, and — the assertion
that actually pins it — the same next prompt. So every test in that class
runs one mission twice, once straight through and once killed at a step
boundary and resumed, and compares what the model was shown.

The refusals are the other half, and the one worth reading twice is the
objective mismatch. A resume of the wrong run is the only failure this
feature can produce that nothing downstream would catch: the stream is
well-formed, the outcome is ordinary, and the answer is to a question nobody
in this process asked.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.durable import RunStore
from core.runtime.contract import conforms
from core.runtime.mission import MissionRunner
from core.runtime.resume import (
    LOST_REJECTED_REPLY,
    RESUMABLE_OUTCOMES,
    LOST_STRUCTURED,
    ORPHAN_STALE_S,
    Recorded,
    ResumeRefused,
    open_for_resume,
    rebuild,
    recorded_outcome,
    reconcile_orphans,
)
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor


class ScriptedModel:
    """Replays canned replies and records exactly what it was shown.

    ``Stop`` in the script is a model server that went away mid-mission,
    which is the only way a run comes to need resuming at all.
    """

    class Stop(RuntimeError):
        pass

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        if self.replies and self.replies[0] is Stop:
            raise ScriptedModel.Stop("the model server went away")
        return self.replies.pop(0) if self.replies else '{"answer": "done"}'


#: The sentinel a script uses to say "and here the process died".
Stop = object()


def hard_kill(store, run_id):
    """Drop the trailing ``mission_finished`` — what SIGKILL leaves behind.

    A mission killed by an *exception* still closes its own log: the record
    is emitted from a ``finally``. Only a process that never reached that
    ``finally`` leaves an unterminated log, and that is the state
    :func:`~core.runtime.resume.reconcile_orphans` exists for — so the tests
    about it have to manufacture it rather than reach for an exception.
    """
    import json as _json

    path = store.log_path(run_id)
    kept = [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and '"mission_finished"' not in line]
    path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    record = _json.loads(store.meta_path(run_id).read_text(encoding="utf-8"))
    record["last_seq"] = _json.loads(kept[-1])["seq"] if kept else 0
    store.meta_path(run_id).write_text(_json.dumps(record), encoding="utf-8")
    return run_id


def tool_call(name, **arguments):
    """A reply in exactly the spelling the loop's protocol asks for.

    Canonical on purpose: what a replay can give back is the *decision* the
    ``tool_call`` record carries, rendered the way the protocol states it,
    and a script that wrote its JSON some other way would be asserting that
    the harness reproduces a model's whitespace rather than its choice.
    """
    return json.dumps({"tool": name, "arguments": arguments},
                      ensure_ascii=False)


@pytest.fixture
def bus():
    b = ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"])))
    b.register(
        ToolDescriptor(tool_name="catalog.search",
                       description="Search the catalogue."),
        lambda **kw: (0, f"hits for {kw.get('q')}", ""),
    )
    b.register(
        ToolDescriptor(tool_name="catalog.get", description="Fetch one asset."),
        lambda **kw: (0, f"asset {kw.get('asset_id')}", ""),
    )
    b.register(
        ToolDescriptor(tool_name="catalog.wipe", description="Delete an asset."),
        lambda **kw: (0, "wiped", ""),
    )
    return b


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs")


def runner(bus, model, run_store=None, run_id="", **kw):
    kw.setdefault("store_tool", "")
    return MissionRunner(model, bus, ["catalog.search", "catalog.get",
                                      "catalog.wipe"],
                         run_store=run_store, run_id=run_id, **kw)


def resume(bus, model, store, run_id, *, objective="", **kw):
    """The whole resuming half, as the CLI does it: door, runner, replay."""
    recorded = open_for_resume(store, run_id, objective=objective)
    built = runner(bus, model, run_store=store, run_id=run_id,
                   max_steps=recorded.total_steps(kw.pop("more", None)), **kw)
    return built, built.run(recorded.objective, rebuild(built, recorded))


# ── the door ─────────────────────────────────────────────────────────────────


class TestTheDoor:
    """Every refusal is answered before a server is dialled or a model asked.

    The same rule ``--skill`` and ``--history`` are read under: a refusal
    that arrives at the end of an 11,000-second mission is a refusal that
    cost what it was meant to save.
    """

    def _killed(self, bus, store):
        run_id = store.create(meta={"objective": "find it"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, ScriptedModel(tool_call("catalog.search", q="a"), Stop),
                   run_store=store, run_id=run_id).run("find it")
        return run_id

    def test_an_unknown_id_is_refused_naming_the_root(self, store):
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, "run_20260101T000000-deadbeef")
        assert "run_20260101T000000-deadbeef" in str(exc.value)
        assert str(store.root) in str(exc.value)

    def test_an_id_the_store_never_mints_is_refused_the_same_way(self, store):
        """One answer for "not there" and "not a name this store would use":
        the second is a traversal attempt and deserves no more information."""
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, "../../etc")
        assert "../../etc" in str(exc.value)

    def test_no_store_at_all_says_so_rather_than_crashing(self):
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(None, "run_20260101T000000-deadbeef")
        assert "JUDAIS_LOBI_RUNS" in str(exc.value)

    def test_a_finished_run_is_refused_naming_the_outcome_it_ended_in(
            self, bus, store):
        run_id = store.create(meta={"objective": "go"}).run_id
        runner(bus, ScriptedModel('{"answer": "ok"}'),
               run_store=store, run_id=run_id).run("go")
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, run_id)
        assert "'answered'" in str(exc.value)
        assert "already finished" in str(exc.value)

    def test_a_run_that_ran_out_of_budget_is_finished_too(self, bus, store):
        run_id = store.create(meta={"objective": "go"}).run_id
        runner(bus, ScriptedModel(tool_call("catalog.search", q="a")),
               run_store=store, run_id=run_id, max_steps=1).run("go")
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, run_id)
        assert "'budget_exhausted'" in str(exc.value)

    def test_a_gated_run_is_admitted_because_it_waits_on_a_person(
            self, bus, store):
        """``awaiting_approval`` is the one terminal outcome that is not an
        ending: nothing failed, nothing was called, and the next move belongs
        to somebody who is not this process."""
        run_id = store.create(meta={"objective": "go"}).run_id
        runner(bus, ScriptedModel(tool_call("catalog.wipe", asset_id="a")),
               run_store=store, run_id=run_id,
               gated=["catalog.wipe"]).run("go")
        assert open_for_resume(store, run_id).outcome == "awaiting_approval"

    def test_a_crashed_run_is_admitted(self, bus, store):
        """The commonest way a mission dies, and it closes its OWN log:
        ``mission_finished`` is emitted from a ``finally``, so a crash
        records ``incomplete``. Refusing that word would mean the two
        commonest deaths were the two nothing could be resumed from."""
        assert open_for_resume(store, self._killed(bus, store)).outcome == \
            "incomplete"

    def test_a_hard_killed_run_is_admitted(self, bus, store):
        run_id = hard_kill(store, self._killed(bus, store))
        assert open_for_resume(store, run_id).outcome == ""

    def test_a_reconciled_orphan_is_still_admitted(self, bus, store):
        """Reconciliation stops a follower waiting; it does not decide that a
        mission may never be picked up. A rule that refused its word would
        take resumability away from every orphan sixty seconds after it was
        born, and by a process that had nothing to do with it."""
        run_id = hard_kill(store, self._killed(bus, store))
        _age(store, run_id, ORPHAN_STALE_S + 10)
        assert reconcile_orphans(store) == [run_id]
        assert open_for_resume(store, run_id).outcome == "incomplete"

    def test_the_resumable_words_are_a_stated_subset_of_the_outcomes(self):
        """Data, not a condition buried in the door — so a new outcome word
        has to be classified rather than defaulting to resumable."""
        from core.runtime.contract import OUTCOMES

        assert set(RESUMABLE_OUTCOMES) - {""} < set(OUTCOMES)
        assert "answered" not in RESUMABLE_OUTCOMES
        assert "budget_exhausted" not in RESUMABLE_OUTCOMES

    def test_a_matching_objective_is_admitted(self, bus, store):
        run_id = self._killed(bus, store)
        assert open_for_resume(store, run_id, objective="find it").run_id == run_id

    def test_a_mismatched_objective_is_refused_naming_both(self, bus, store):
        """The failure nothing downstream would catch. The stream would be
        well-formed, the outcome ordinary, and the answer to a question
        nobody in this process asked."""
        run_id = self._killed(bus, store)
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, run_id, objective="find something else")
        assert "'find it'" in str(exc.value)
        assert "'find something else'" in str(exc.value)

    def test_an_omitted_objective_comes_off_the_record(self, bus, store):
        assert open_for_resume(store, self._killed(bus, store)).objective == \
            "find it"

    def test_the_objective_comes_off_the_stream_and_not_the_metadata(
            self, bus, store):
        """``mission_started.objective`` is what the loop was actually seeded
        with; ``meta.json``'s copy is the CLI's index over the run. When they
        disagree the stream is the one that ran."""
        run_id = self._killed(bus, store)
        store.update_meta(run_id, objective="something somebody typed later")
        assert open_for_resume(store, run_id).objective == "find it"

    def test_a_log_that_never_opened_is_refused(self, store):
        run_id = store.create(meta={"objective": "go"}).run_id
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, run_id)
        assert "never got as far as opening" in str(exc.value)

    def test_a_staged_run_is_refused_and_the_refusal_names_its_steps(
            self, bus, store):
        run_id = self._killed(bus, store)
        store.update_meta(
            run_id,
            plan=[{"id": "s1", "goal": "look", "rung": "tool"}],
            steps_done=[{"id": "s1", "outcome": "ok", "summary": "found abc"}])
        with pytest.raises(ResumeRefused) as exc:
            open_for_resume(store, run_id)
        assert "staged resume not yet supported" in str(exc.value)
        assert "s1 ok — found abc" in str(exc.value)


# ── the step budget across a resume ──────────────────────────────────────────


class TestTheStepBudgetIsTheRunsAndNotTheProcesss:
    """A cap a resume resets is a cap anybody can widen by killing the run."""

    def _recorded(self, spent, of):
        return Recorded(run_id="run_x", objective="go", meta=None,
                        records=[{"event": "step_started", "index": i}
                                 for i in range(spent)],
                        from_seq=spent, max_steps=of, outcome="")

    def test_unstated_the_total_is_the_one_the_run_started_with(self):
        assert self._recorded(spent=5, of=8).total_steps(None) == 8

    def test_so_the_resumed_stretch_gets_what_is_left_and_not_a_fresh_eight(self):
        recorded = self._recorded(spent=5, of=8)
        assert recorded.total_steps(None) - recorded.spent_steps == 3

    def test_stated_it_is_that_many_further_steps(self):
        recorded = self._recorded(spent=5, of=8)
        assert recorded.total_steps(4) == 9
        assert recorded.total_steps(4) - recorded.spent_steps == 4

    def test_a_run_that_already_met_its_total_has_nothing_left(self):
        recorded = self._recorded(spent=8, of=8)
        assert recorded.total_steps(None) - recorded.spent_steps == 0

    def test_a_step_that_was_asked_and_never_answered_still_counts(self):
        """It cost the round trip, and reusing its index would put two
        records with the same ``index`` in one log."""
        assert self._recorded(spent=3, of=8).spent_steps == 3


# ── the replay is the run that never stopped ─────────────────────────────────


SCRIPT = (
    tool_call("catalog.search", q="corpus"),
    tool_call("catalog.get", asset_id="asset.5f21"),
    '{"answer": "asset.5f21 is in the corpus"}',
)


class TestTheReplayIsTheRunThatNeverStopped:
    """One mission, run twice: straight through, and killed then resumed.

    The comparison is **the model's next prompt**. Everything else — steps,
    handles, outcomes — is a consequence of the conversation being right, and
    a test that asserted only those would pass over a transcript in which the
    model's own previous turns had been reworded.
    """

    def straight(self, bus):
        model = ScriptedModel(*SCRIPT)
        transcript = runner(bus, model).run("find it")
        return model, transcript

    def killed_then_resumed(self, bus, store):
        run_id = store.create(meta={"objective": "find it"}).run_id
        first = ScriptedModel(SCRIPT[0], Stop)
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, first, run_store=store, run_id=run_id).run("find it")
        second = ScriptedModel(*SCRIPT[1:])
        built, transcript = resume(bus, second, store, run_id)
        return second, transcript, run_id

    def test_the_model_is_shown_the_same_prompt_it_would_have_been(
            self, bus, store):
        straight, _ = self.straight(bus)
        resumed, _, _ = self.killed_then_resumed(bus, store)
        # The straight run's SECOND ask is the resumed run's FIRST: the
        # first step is what the killed process already did.
        assert resumed.seen[0] == straight.seen[1]

    def test_and_the_one_after_that_too(self, bus, store):
        straight, _ = self.straight(bus)
        resumed, _, _ = self.killed_then_resumed(bus, store)
        assert resumed.seen[1] == straight.seen[2]

    def test_the_answer_is_the_same(self, bus, store):
        _, straight = self.straight(bus)
        _, resumed, _ = self.killed_then_resumed(bus, store)
        assert resumed.answer == straight.answer
        assert resumed.outcome == straight.outcome == "answered"

    def test_the_transcript_holds_every_step_including_the_replayed_ones(
            self, bus, store):
        _, straight = self.straight(bus)
        _, resumed, _ = self.killed_then_resumed(bus, store)
        assert [s.tool for s in resumed.steps] == \
               [s.tool for s in straight.steps]

    def test_the_indexes_continue_rather_than_starting_again(self, bus, store):
        """And the step the dead process asked and never heard back on keeps
        its number. It cost the round trip, and reusing the index would put
        two records with the same ``index`` in one log."""
        _, _, run_id = self.killed_then_resumed(bus, store)
        started = [r["index"] for r in store.records(run_id)
                   if r["event"] == "step_started"]
        assert started == [0, 1, 2, 3]
        assert started == sorted(set(started))

    def test_the_step_that_was_asked_and_never_answered_produced_nothing(
            self, bus, store):
        """Index 1 is in the log and has no outcome under it — which is the
        whole evidence that the process died there."""
        _, _, run_id = self.killed_then_resumed(bus, store)
        under_one = [r["event"] for r in store.records(run_id)
                     if r.get("index") == 1]
        assert under_one == ["step_started"]

    def test_the_records_land_in_the_same_run_directory(self, bus, store):
        _, _, run_id = self.killed_then_resumed(bus, store)
        assert len(store.list()) == 1
        assert store.list()[0].run_id == run_id

    def test_the_earlier_half_of_the_log_is_not_truncated(self, bus, store):
        """``create(run_id=…)`` would have reset ``last_seq`` and rewritten
        the metadata; the resume path reads with ``meta()`` and only
        appends, so seq 1 is still seq 1."""
        _, _, run_id = self.killed_then_resumed(bus, store)
        envelopes = store.since(run_id)
        assert [e["seq"] for e in envelopes] == \
            list(range(1, len(envelopes) + 1))
        assert envelopes[0]["record"]["event"] == "mission_started"

    def test_there_is_exactly_one_mission_started_in_the_whole_log(
            self, bus, store):
        """A resumed run is the SAME mission. Two openings would make a pane
        render two."""
        _, _, run_id = self.killed_then_resumed(bus, store)
        events = [r["event"] for r in store.records(run_id)]
        assert events.count("mission_started") == 1
        assert events[0] == "mission_started"

    def test_the_first_step_of_the_resumed_stretch_says_it_is_one(
            self, bus, store):
        _, _, run_id = self.killed_then_resumed(bus, store)
        carrying = [r for r in store.records(run_id)
                    if r["event"] == "step_started" and "resumed" in r]
        assert len(carrying) == 1
        # Index 2, not 1: the killed process spent index 1 asking. And
        # ``steps_replayed`` is 1, not 2 — one step actually produced
        # something to rebuild, which is what a consumer renumbering needs
        # and is deliberately not the same number as the index.
        assert carrying[0]["index"] == 2
        assert carrying[0]["resumed"]["steps_replayed"] == 1
        assert conforms(carrying[0]) == []

    def test_from_seq_is_where_the_earlier_half_of_the_log_ends(
            self, bus, store):
        _, _, run_id = self.killed_then_resumed(bus, store)
        records = store.since(run_id)
        resumed = next(e for e in records
                       if "resumed" in (e["record"] or {}))
        cursor = resumed["record"]["resumed"]["from_seq"]
        # Exactly the records the resumed stretch wrote, and nothing twice.
        assert [e["record"]["event"] for e in store.since(run_id, cursor)] == \
            [e["record"]["event"] for e in records if e["seq"] > cursor]
        assert cursor == resumed["seq"] - 1

    def test_the_replayed_results_keep_the_handles_the_model_was_given(
            self, bus, store):
        model = ScriptedModel(SCRIPT[0], Stop)
        run_id = store.create(meta={"objective": "find it"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, model, run_store=store, run_id=run_id,
                   store_tool="mission_result").run("find it")
        recorded = open_for_resume(store, run_id)
        built = runner(bus, ScriptedModel(), run_store=store, run_id=run_id,
                       store_tool="mission_result")
        replayed = rebuild(built, recorded)
        assert [s.handle for s in replayed.store.results] == ["r1"]
        assert replayed.store.get("r1").text == "hits for corpus"

    def test_grounding_sees_the_replayed_output(self, bus, store):
        """The whole reason the store is rebuilt rather than started empty:
        an answer citing something a *replayed* tool returned is grounded."""
        model = ScriptedModel(SCRIPT[0], Stop)
        run_id = store.create(meta={"objective": "find it"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, model, run_store=store, run_id=run_id).run("find it")
        built = runner(bus, ScriptedModel(), run_store=store, run_id=run_id)
        replayed = rebuild(built, open_for_resume(store, run_id))
        assert "hits for corpus" in replayed.store.evidence_texts()


# ── what a replay cannot give back ───────────────────────────────────────────


class TestWhatIsLostIsSaidOutLoud:
    """A reconstruction that quietly differed from the run would be worse
    than no resume at all: the model would read a transcript of its own turns
    that it did not write, and nothing would say so."""

    def _stopped_after(self, bus, store, *replies):
        run_id = store.create(meta={"objective": "go"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, ScriptedModel(*replies, Stop),
                   run_store=store, run_id=run_id).run("go")
        built = runner(bus, ScriptedModel(), run_store=store, run_id=run_id)
        return rebuild(built, open_for_resume(store, run_id))

    def test_the_typed_payload_of_a_result_is_gone(self, bus, store):
        """``structuredContent`` was never on the wire. Named rather than
        discovered later by a `mission_result(path=…)` that refuses."""
        replayed = self._stopped_after(bus, store,
                                       tool_call("catalog.search", q="a"))
        assert LOST_STRUCTURED in replayed.lost
        assert replayed.store.get("r1").structured is None

    def test_a_run_with_no_results_claims_no_such_loss(self, bus, store):
        replayed = self._stopped_after(bus, store, "not json at all")
        assert LOST_STRUCTURED not in replayed.lost

    def test_the_text_of_a_rejected_reply_is_gone_and_the_refusal_is_not(
            self, bus, store):
        replayed = self._stopped_after(bus, store, "not json at all")
        assert any(s.startswith("the text of 1 rejected model reply")
                   for s in replayed.lost)
        assert replayed.tail[0] == {"role": "assistant", "content": ""}
        assert "not valid JSON" in replayed.tail[1]["content"]

    def test_the_plural_reads_as_a_sentence(self, bus, store):
        replayed = self._stopped_after(bus, store, "nope", "nope again")
        assert LOST_REJECTED_REPLY.format(n=2, y="ies") in replayed.lost


# ── a run that stopped at a gate ─────────────────────────────────────────────


class TestAGatedRunResumes:
    """The gate is not answered here and deliberately not answerable here.

    Resuming a gated run puts the proposal back in the conversation and lets
    the gated set apply exactly as it did the first time — so a mission
    nobody has decided about proposes the call and stops again, which is the
    correct behaviour and the seam a decision record plugs into.
    """

    def _gated(self, bus, store):
        run_id = store.create(meta={"objective": "go"}).run_id
        runner(bus, ScriptedModel(tool_call("catalog.wipe", asset_id="a")),
               run_store=store, run_id=run_id,
               gated=["catalog.wipe"]).run("go")
        return run_id

    def test_the_pending_decision_is_on_the_resumption(self, bus, store):
        run_id = self._gated(bus, store)
        built = runner(bus, ScriptedModel(), run_store=store, run_id=run_id,
                       gated=["catalog.wipe"])
        replayed = rebuild(built, open_for_resume(store, run_id))
        assert replayed.gate["tool"] == "catalog.wipe"
        assert replayed.gate["arguments"] == {"asset_id": "a"}

    def test_the_conversation_does_not_end_on_the_models_own_turn(
            self, bus, store):
        """The live loop returned instead of writing a user turn. A
        conversation handed to a model ending on the model's own turn is a
        conversation with nothing to answer, so the reason goes back."""
        run_id = self._gated(bus, store)
        built = runner(bus, ScriptedModel(), run_store=store, run_id=run_id,
                       gated=["catalog.wipe"])
        replayed = rebuild(built, open_for_resume(store, run_id))
        assert replayed.tail[-1]["role"] == "user"
        assert "needs a person's approval" in replayed.tail[-1]["content"]

    def test_the_resumed_run_can_answer_around_it(self, bus, store):
        run_id = self._gated(bus, store)
        _, transcript = resume(bus, ScriptedModel('{"answer": "I cannot"}'),
                               store, run_id, gated=["catalog.wipe"])
        assert transcript.outcome == "answered"

    def test_and_proposing_it_again_stops_again(self, bus, store):
        """Nothing here decides an approval, and nothing here can be made to.
        The gated set applies on the resumed turn as it did on the first."""
        run_id = self._gated(bus, store)
        _, transcript = resume(
            bus, ScriptedModel(tool_call("catalog.wipe", asset_id="a")),
            store, run_id, gated=["catalog.wipe"])
        assert transcript.outcome == "awaiting_approval"


# ── the credential is not persisted ──────────────────────────────────────────


class TestTheCredentialIsRereadAndNotRecovered:
    """A run directory outlives the process it recorded.

    So the token is not in it, and a resume cannot get one out of it: the
    resuming process reads ``MCP_TOKEN`` from its own environment or has
    none, exactly as a fresh run does.
    """

    def test_a_resume_writes_no_token_into_the_run_directory(
            self, bus, store, monkeypatch, tmp_path):
        secret = "mcp-tok-4f19a7c2e8b6"
        monkeypatch.setenv("MCP_TOKEN", secret)
        run_id = store.create(meta={"objective": "go"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, ScriptedModel(tool_call("catalog.search", q="a"), Stop),
                   run_store=store, run_id=run_id).run("go")
        resume(bus, ScriptedModel(json.dumps(
            {"answer": f"the token is {secret}"})), store, run_id)
        written = "".join(path.read_text(encoding="utf-8", errors="replace")
                          for path in (tmp_path / "runs").rglob("*")
                          if path.is_file())
        assert written
        assert secret not in written

    def test_the_transport_a_resume_builds_carries_the_environments_token(
            self, monkeypatch):
        """Re-read, not recovered. With the variable unset the resuming
        process holds no credential — the same nothing a fresh run holds,
        and not the value the first process was handed."""
        from types import SimpleNamespace

        from core.cli import _build_mcp_transport

        args = SimpleNamespace(mcp_stdio=None, mcp_url="https://x/mcp",
                               mcp_token=None)
        assert _build_mcp_transport(args).credential() is None

    def test_nothing_in_the_recorded_metadata_names_the_transport(
            self, bus, store):
        """The flags a run records are deliberately not all of them: an
        --mcp-url can carry a token in its query string."""
        from core.cli import RUN_META_FLAGS

        assert "mcp_url" not in RUN_META_FLAGS
        assert "mcp_stdio" not in RUN_META_FLAGS
        assert "mcp_token" not in RUN_META_FLAGS


# ── orphans ──────────────────────────────────────────────────────────────────


def _age(store, run_id, seconds):
    """Backdate a run's ``updated_at`` by *seconds*, on the disk.

    Through the metadata file rather than a clock patch, because
    ``updated_at`` is what the rule actually reads and a test that patched
    ``datetime`` would pass over a rule that read something else.
    """
    import json as _json
    from datetime import datetime, timedelta, timezone

    path = store.meta_path(run_id)
    record = _json.loads(path.read_text(encoding="utf-8"))
    record["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds)
    ).isoformat(timespec="seconds")
    path.write_text(_json.dumps(record), encoding="utf-8")


class TestOrphansAreClosed:
    """A log with no ``mission_finished`` leaves a follower waiting forever.

    Which is the spinner-forever state ``EXIT_CONTRACT["finished"]`` exists
    to prevent — and the reason the record is emitted from a ``finally`` in
    the first place. A process that was killed never reached its ``finally``,
    so somebody else has to.
    """

    def _killed(self, bus, store):
        """A process that never reached its ``finally``: no terminal record."""
        run_id = store.create(meta={"objective": "go"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, ScriptedModel(tool_call("catalog.search", q="a"), Stop),
                   run_store=store, run_id=run_id).run("go")
        return hard_kill(store, run_id)

    def test_a_crashed_run_that_closed_itself_is_not_an_orphan(
            self, bus, store):
        """The `finally` already did this job. An orphan is a log with no
        ending, not a log whose ending somebody dislikes."""
        run_id = store.create(meta={"objective": "go"}).run_id
        with pytest.raises(ScriptedModel.Stop):
            runner(bus, ScriptedModel(tool_call("catalog.search", q="a"), Stop),
                   run_store=store, run_id=run_id).run("go")
        _age(store, run_id, ORPHAN_STALE_S + 10)
        before = store.meta(run_id).last_seq
        assert reconcile_orphans(store) == []
        assert store.meta(run_id).last_seq == before

    def test_a_stale_orphan_is_closed(self, bus, store):
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        assert reconcile_orphans(store) == [run_id]
        assert recorded_outcome(store.records(run_id)) == "incomplete"

    def test_the_closing_record_conforms(self, bus, store):
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        reconcile_orphans(store)
        assert conforms(store.records(run_id)[-1]) == []

    def test_it_carries_the_counts_off_the_log(self, bus, store):
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        reconcile_orphans(store)
        closing = store.records(run_id)[-1]
        assert (closing["steps"], closing["max_steps"]) == (2, 8)

    def test_a_follower_reading_from_a_cursor_is_told(self, bus, store):
        """The whole point: a reader holding a cursor has to *receive* the
        ending, not merely find it if it goes looking."""
        run_id = self._killed(bus, store)
        cursor = store.meta(run_id).last_seq
        _age(store, run_id, ORPHAN_STALE_S + 10)
        reconcile_orphans(store)
        assert [r["record"]["event"] for r in store.since(run_id, cursor)] == \
            ["mission_finished"]

    def test_a_fresh_one_is_left_alone_because_it_might_be_alive(
            self, bus, store):
        """The guard, and it is the half worth having. A mission thinking for
        forty seconds has no ``mission_finished`` either, and closing its log
        out from under it would send the answer it is about to give to
        nobody."""
        run_id = self._killed(bus, store)
        assert reconcile_orphans(store) == []
        assert recorded_outcome(store.records(run_id)) == ""

    def test_the_staleness_is_a_stated_number_and_not_a_guess(self):
        assert ORPHAN_STALE_S == 60.0

    def test_the_run_being_resumed_is_never_an_orphan(self, bus, store):
        """Excluded outright rather than left to the clock: this process is
        about to append to it, and a terminal record in the middle of a live
        stream is the mistake the guard exists to prevent."""
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        assert reconcile_orphans(store, live=run_id) == []
        assert recorded_outcome(store.records(run_id)) == ""

    def test_a_finished_run_is_not_touched(self, bus, store):
        run_id = store.create(meta={"objective": "go"}).run_id
        runner(bus, ScriptedModel('{"answer": "ok"}'),
               run_store=store, run_id=run_id).run("go")
        _age(store, run_id, ORPHAN_STALE_S + 10)
        before = store.meta(run_id).last_seq
        assert reconcile_orphans(store) == []
        assert store.meta(run_id).last_seq == before

    def test_a_log_that_never_opened_is_closed_too(self, store):
        """The run that failed to reach its server. It is the one somebody
        comes looking for, and an empty log is the least closed of all."""
        run_id = store.create(meta={"objective": "go"}).run_id
        _age(store, run_id, ORPHAN_STALE_S + 10)
        assert reconcile_orphans(store) == [run_id]
        assert store.records(run_id) == [
            {"event": "mission_finished", "outcome": "incomplete",
             "steps": 0, "max_steps": 0}]

    def test_the_reconciliation_is_a_fact_about_the_run_not_the_mission(
            self, bus, store):
        """``orphaned_at`` goes in the metadata and not on the stream: a
        consumer that had to learn a word to read this ending would be
        learning one about the reconciler rather than about the mission."""
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        reconcile_orphans(store)
        assert store.meta(run_id).meta["orphaned_at"]
        assert "orphaned" not in json.dumps(store.records(run_id))

    def test_running_it_twice_closes_nothing_twice(self, bus, store):
        run_id = self._killed(bus, store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        reconcile_orphans(store)
        _age(store, run_id, ORPHAN_STALE_S + 10)
        assert reconcile_orphans(store) == []
        assert [r["event"] for r in store.records(run_id)].count(
            "mission_finished") == 1

    def test_it_closes_every_orphan_and_returns_all_of_them(self, bus, store):
        ids = [self._killed(bus, store) for _ in range(3)]
        for run_id in ids:
            _age(store, run_id, ORPHAN_STALE_S + 10)
        assert sorted(reconcile_orphans(store)) == sorted(ids)

    def test_no_store_is_not_a_crash(self):
        assert reconcile_orphans(None) == []

    def test_an_unparseable_stamp_reads_as_too_recent_to_touch(
            self, bus, store):
        """Fail closed. Appending a terminal record to a mission that is
        still going is the mistake worth not making; a directory that stays
        open until somebody looks is the other one."""
        run_id = self._killed(bus, store)
        path = store.meta_path(run_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["updated_at"] = "not a timestamp"
        path.write_text(json.dumps(record), encoding="utf-8")
        assert reconcile_orphans(store) == []
