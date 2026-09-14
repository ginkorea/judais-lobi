# tests/test_cognition_shadow.py — the shadow is a shadow, and it says so

"""``--cognition`` on, and the run is the run it was: the ablation.

``ROADMAP.md`` §2.9.4 states the floor in two sentences — *cognition off is
byte-identical* and *cognition on never blocks an answer* — and this file is
the instrument for both.  It is deliberately three kinds of test, because the
claim has three halves:

**The unit half.**  What a receipt is worth (:func:`observations_of`), what a
step is (one ``derive``), what a failure costs (nothing), what a resume does
(continues, never repeats).  These run in milliseconds and they are the ones
that go red when the mapping changes.

**The ablation half** — the one this lane owes.  Every committed run in
``tests/fixtures/runs/`` is replayed **twice**, once with the flag and once
without, in one store, and the two are compared file by file: the event
stream record for record against the committed fixture, ``model.jsonl`` and
``tools.jsonl`` line for line against each other, and the directory listing
so that ``reasoning.jsonl`` is provably the *only* new byte.  A change that
made cognition visible anywhere else on disk turns that red, and it is the
same argument ``tests/test_run_corpus.py`` makes for the ``Run`` extraction.

**The completeness half.**  A shadow that harvested nothing would pass every
zero-drift assertion in here, which is why the proposition counts are pinned
per fixture: a mapping that quietly stopped asserting is a mapping that has
stopped being measured.  Pinned as exact numbers, and they are small because
the fixtures are small — a 200-actor listing in the repository is a fixture
nobody opens.

Nothing here builds its own idea of what a run looks like: the corpus, the
replay command line, the excused fields and the scripted backend all come
from :mod:`tests.test_record_replay`, so a guard that agreed with itself
would have to be written on purpose.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition import (EVENT_SCHEMA_VERSION, KERNEL_VERSION,
                            CognitiveState, EvidenceAuthority,
                            PropositionStatus, ReplayRefused)
from core.durable import RunStore, fsync_append
from core.runtime.cognition import (KERNEL_COUNT_KEY, KERNEL_EVENTS_KEY,
                                    KERNEL_KEY,
                                    KERNEL_SCHEMA_KEY, NOTE_KEY,
                                    REASONING_LOG,
                                    REASONING_SCHEMA_VERSION, RESUMED_NOTE,
                                    SCHEMA_KEY, STOPPED_NOTE, UNWATCHED_NOTE,
                                    ShadowCognition, header_record,
                                    observations_of, open_shadow,
                                    read_reasoning, replay_reasoning)
from core.runtime import cognition as cognition_module
from core.runtime.replay import canonical
from tests.test_record_replay import (CORPUS, CORPUS_RUNS, REPLAY_FLAGS,
                                      REPLAY_SKILL, SKILL, comparable, corpus,
                                      lines, records, replay_argv, run_cli,
                                      scripted_elf, write_skill)
from tests.test_cli_mission_skill import STUB as MISSION_STUB
from tests.test_cli_mission_skill import elf
from tests.test_cli_mission_skill import run_cli as mission_run_cli
from tests.test_record_replay import ASSET
from tests.test_run_corpus import committed_records

#: What each committed fixture's receipts are worth, as
#: ``(propositions, assert_observation events, derive events)``.
#:
#: Exact, and stated per fixture rather than as "more than none", because
#: "more than none" is satisfied by a mapping that harvests one field of a
#: payload and drops the rest — which is the failure this number exists to
#: catch.  The staged fixtures hold twice the direct ones because a staged
#: turn reads the view once per stage and each stage's receipt is its own
#: entity: see :meth:`core.runtime.run.Run._receipt_seq`, which is why the
#: two are not merged into one contradicted claim.
#:
#: A number that moves here is either the mapping changing or the corpus
#: being re-recorded, and both are things a commit has to say out loud.
HARVEST = {
    "run_corpusjson-0001": (2, 2, 1),
    "run_corpusnative-0001": (2, 2, 1),
    "run_corpusswarm-0001": (4, 4, 2),
    "run_corpusswarmcaveat-0001": (4, 4, 2),
}

#: One receipt, as a governed payload the stub could have returned: two
#: single-valued figures, a key holding two different numbers, a string, and
#: a key whose value is an object.  Every branch of the v1 mapping in one
#: fixture, so a test that reads it reads the whole rule.
RECEIPT = json.dumps({
    "records": 12481,
    "total_s": 154.024,
    "label": "governed",
    "window": {"from": "2026-01-01"},
    "rows": [{"score": 3}, {"score": 4}],
})


def _skill_for(tmp_path, run_id=None):
    return write_skill(tmp_path, REPLAY_SKILL.get(run_id, SKILL))


def _replay(corpus_root, tmp_path, run_id, *extra):
    """Replay *run_id* once and return the new run's id.

    :func:`tests.test_record_replay.replayed` cannot be used: it asserts
    that a store holds exactly one replay of a recording, and the ablation
    below deliberately puts two of them side by side.  Diffing the store's
    listing is the honest way to say "the one this call made".
    """
    before = {run.run_id for run in RunStore(corpus_root).list()}
    MockClass, _ = scripted_elf(refuse=True)
    run_cli(MockClass, *replay_argv(run_id, _skill_for(tmp_path, run_id),
                                    *extra, *REPLAY_FLAGS.get(run_id, ())))
    after = {run.run_id for run in RunStore(corpus_root).list()}
    fresh = after - before
    assert len(fresh) == 1, sorted(fresh)
    return fresh.pop()


def _files(corpus_root, run_id):
    directory = RunStore(corpus_root).directory(run_id)
    return sorted(path.name for path in directory.iterdir())


def _timeless(records_):
    """Recorded lines with ``at`` taken out.

    The only field of ``model.jsonl`` and ``tools.jsonl`` that is this
    afternoon's rather than the run's — the same exclusion
    :mod:`core.runtime.replay` states for a replay generally.
    """
    return [{key: value for key, value in record.items() if key != "at"}
            for record in records_]


def _reasoning(corpus_root, run_id):
    return RunStore(corpus_root).directory(run_id) / REASONING_LOG


def _without_the_run_id(path, run_id):
    """The reasoning log's bytes with the run's own id blanked out.

    Every evidence locator opens with the id of the run that made it, so
    two replays of one recording differ in exactly that many places and
    nowhere else.  Blanking it is the same excuse ``MOVES`` makes for
    ``run_id`` on the event stream: an id is a property of the run that is
    happening now, and a determinism claim is about everything else.
    """
    return Path(path).read_text(encoding="utf-8").replace(run_id, "RUN")


# ── the flag ─────────────────────────────────────────────────────────────────


def _parsed(*argv):
    from tests.test_contract import _mission_parser

    return _mission_parser().parse_args(["go", *argv])


class TestTheFlagIsOffUntilSomebodyAsks:
    """A default nobody chose is the one thing a shadow may not have.

    The environment is read as the flag's argparse *default*, which is the
    ``--mcp-timeout`` idiom and is what makes "the flag wins" true without a
    second resolution step anywhere.
    """

    def test_the_default_is_off(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_COGNITION", raising=False)
        assert _parsed().cognition is False

    def test_the_flag_turns_it_on(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_COGNITION", raising=False)
        assert _parsed("--cognition").cognition is True

    def test_the_variable_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_COGNITION", "1")
        assert _parsed().cognition is True

    def test_a_blank_variable_is_not_a_request(self, monkeypatch):
        """Exported empty is how a shell says "unset" by accident, and a
        harness that read it as yes would turn a feature on in a deployment
        that never typed its name."""
        monkeypatch.setenv("JUDAIS_LOBI_COGNITION", "   ")
        assert _parsed().cognition is False

    def test_the_flag_wins_where_the_variable_is_silent(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_COGNITION", "")
        assert _parsed("--cognition").cognition is True


# ── what a receipt is worth ──────────────────────────────────────────────────


class TestOneReceiptBecomesPropositions:
    """The v1 mapping, stated as tests so its bounds are checkable.

    Each of the four bounds in :mod:`core.runtime.cognition`'s docstring has
    an assertion here, because a bound nobody tests is a bound the next lane
    removes by accident.
    """

    def test_a_single_valued_figure_is_a_proposition(self):
        assert ("records", 12481) in observations_of(RECEIPT)

    def test_an_integral_figure_stays_an_integer(self):
        """``8`` read back as ``8.0`` is a figure the store renders
        differently from the receipt it came from."""
        assert observations_of('{"blocks": 7}') == (("blocks", 7),)

    def test_a_fractional_figure_is_a_float(self):
        assert observations_of('{"total_s": 1.5}') == (("total_s", 1.5),)

    def test_a_key_holding_two_figures_is_not_a_fact(self):
        """``rows[*].score`` is 3 and 4 — one key, two numbers, and the v1
        store is single-valued per ``(entity, field)``.  Asserting both
        would manufacture a contradiction out of a list that contradicts
        nothing."""
        assert "score" not in dict(observations_of(RECEIPT))

    def test_a_numeric_string_is_not_a_number(self):
        """``"8"`` is not ``8`` at this door.

        The store exists to be faithful to what a tool returned, and a
        receipt that said the string said the string. It cannot be asserted
        *as* a string until the ``scalars=`` sink lands, so for now it is
        dropped rather than converted — losing a field is a gap, converting
        one is a lie.
        """
        assert observations_of('{"count": "8"}') == ()
        assert observations_of('{"count": 8, "label": "9"}') == \
            (("count", 8),)

    def test_a_string_inside_a_list_is_dropped_too(self):
        """The strip is structural, so a list of numeric strings does not
        become a list of figures on the way past."""
        assert observations_of('{"rows": ["1", "2"], "n": 5}') == (("n", 5),)

    def test_a_non_numeric_scalar_waits_for_the_sink(self):
        """The documented v1 bound: the harvester on this tree reports
        figures, so ``label: "governed"`` is on the receipt and not in the
        store until ``lane/p16-extraction``'s ``scalars=`` sink lands."""
        assert "label" not in dict(observations_of(RECEIPT))

    def test_prose_yields_nothing(self):
        assert observations_of("the view holds 12481 records") == ()

    def test_a_json_object_inside_prose_is_still_found(self):
        """``json_blocks`` is the harness's one reader of "is there JSON in
        this text", and a governed view with a preamble is the case it was
        written for."""
        assert observations_of("reading…\n{\"records\": 3}\ndone") == \
            (("records", 3),)

    def test_a_figure_that_is_not_a_number_is_dropped(self):
        """``NaN`` is spelled by Python's JSON parser and by ``Decimal``,
        it is not JSON, and a store holding one would compare unequal to
        itself."""
        assert observations_of('{"score": NaN}') == ()


# ── the attachment ───────────────────────────────────────────────────────────


@pytest.fixture
def shadow(tmp_path):
    return ShadowCognition(tmp_path / REASONING_LOG, "run-1")


class TestAReceiptIsAssertedAsItself:
    def test_the_entity_is_the_receipt(self, shadow):
        shadow.receipt("mcp.governed_view", "r3", RECEIPT)
        shadow.close_step()
        assert {prop.entity for prop in shadow.state.propositions()} == \
            {"mcp.governed_view#r3"}

    def test_the_authority_is_deterministic_and_the_status_observed(self,
                                                                    shadow):
        """The kernel's wall, from this side of it: a receipt is not a
        model's opinion, so it comes in the observation door and nothing
        this module does can make it a hypothesis."""
        shadow.receipt("mcp.governed_view", "r1", RECEIPT)
        shadow.close_step()
        for prop in shadow.state.propositions():
            assert prop.authority is EvidenceAuthority.DETERMINISTIC
            assert prop.status is PropositionStatus.OBSERVED

    def test_the_evidence_locates_the_receipt(self, shadow):
        shadow.receipt("mcp.governed_view", "r3", RECEIPT)
        shadow.close_step()
        refs = {ref.locator for prop in shadow.state.propositions()
                for ref in prop.evidence}
        kinds = {ref.kind for prop in shadow.state.propositions()
                 for ref in prop.evidence}
        assert refs == {"run-1/r3/mcp.governed_view"}
        assert kinds == {"receipt"}

    def test_the_typed_payload_wins_over_the_rendering(self, shadow):
        """``structuredContent`` is where the fields actually are; the text
        beside it is a rendering of them, and a rendering is not the
        payload."""
        shadow.receipt("mcp.governed_view", "r1",
                       "records: one hundred", '{"records": 100}')
        shadow.close_step()
        assert dict((p.field, p.value)
                    for p in shadow.state.propositions()) == {"records": 100}

    def test_a_receipt_the_kernel_will_not_take_is_counted_not_fatal(self,
                                                                     shadow):
        """``?name`` is the kernel's variable spelling and an asserted
        proposition is ground, so this value is refused at its door.  The
        receipt's other field still lands."""
        shadow.receipt("t", "r1", '{"records": 5, "who": "?name"}')
        shadow.close_step()
        assert shadow.observations == 1
        assert shadow.on is True

    def test_two_receipts_are_two_entities(self, shadow):
        shadow.receipt("t", "r1", '{"records": 1}')
        shadow.receipt("t", "r2", '{"records": 2}')
        shadow.close_step()
        assert len(shadow.state.propositions()) == 2
        assert shadow.state.contradictions() == ()


class TestNothingIsDeclaredAndThatIsWhyNothingContests:
    """``declare_field`` is never called here, and this is what that buys.

    The kernel is single-valued per ``(entity, field)`` **only where a
    cardinality was declared** — undeclared is ``many``, which is the
    reading that cannot manufacture a contradiction out of a receipt that
    legitimately holds several values for one key. Asserted against the
    real :meth:`~core.cognition.state.CognitiveState.declare_field` rather
    than stated in prose, and the ``"one"`` arm below is what makes the
    first one a claim and not a tautology: the same two writes DO contest
    when a field says they must.
    """

    def test_two_values_for_one_field_both_stand(self, shadow):
        shadow.receipt("t", "r1", '{"score": 3}')
        shadow.receipt("t", "r1", '{"score": 4}')
        shadow.close_step()
        assert [(p.field, p.value, p.status.value)
                for p in shadow.state.propositions()] == \
            [("score", 3, "observed"), ("score", 4, "observed")]
        assert shadow.state.contradictions() == ()

    def test_the_same_two_writes_contest_where_a_field_says_one(self,
                                                                shadow):
        """The control. A rule pack that wants the check declares it; this
        module does not, and the difference is visible."""
        shadow.state.declare_field("score", "one")
        shadow.receipt("t", "r1", '{"score": 3}')
        shadow.receipt("t", "r1", '{"score": 4}')
        shadow.close_step()
        assert {p.status.value for p in shadow.state.propositions()} == \
            {"contested"}
        assert len(shadow.state.contradictions()) == 1

    def test_the_shadow_declares_nothing_of_its_own(self, shadow):
        """No ``declare_field`` event reaches the log from this module."""
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        assert [e["op"] for e in shadow.state.events].count(
            "declare_field") == 0


class TestTheStepIsTheOneFlushPoint:
    """The kernel review's M2 ruling, in the harness: assertions stage, and
    a step's close is the only ``derive``.

    It matters beyond tidiness.  A ``derive`` per receipt would make a
    native turn with four parallel calls produce a different log from a
    JSON turn with four sequential ones — the same run, two shapes — and
    the log is the state of record.
    """

    def test_a_step_with_four_receipts_derives_once(self, shadow):
        for n in range(4):
            shadow.receipt("t", f"r{n}", '{"records": %d}' % n)
        shadow.close_step()
        assert [e["op"] for e in shadow.state.events].count("derive") == 1

    def test_nothing_is_written_before_the_step_closes(self, shadow):
        shadow.receipt("t", "r1", RECEIPT)
        assert lines(shadow.path) == []

    def test_closing_twice_writes_nothing_twice(self, shadow):
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        once = lines(shadow.path)
        shadow.close_step()
        assert lines(shadow.path) == once

    def test_a_step_that_harvested_nothing_writes_nothing(self, shadow):
        shadow.close_step()
        assert lines(shadow.path) == []

    def test_a_step_is_one_append_however_many_events_it_made(
            self, shadow, monkeypatch):
        """The cost, pinned as a call count rather than as a stopwatch.

        A per-event ``fsync`` is a disk sync per figure, inside the loop's
        own turn — measured at 122 ms for a twenty-field step against 6.4
        for one append. A number that moves with the machine is no good in
        a test; the number of syncs is the thing that was wrong, so that is
        what is asserted.
        """
        appends = []
        real = cognition_module.fsync_append

        def spy(path, line):
            appends.append(line)
            return real(path, line)

        monkeypatch.setattr(cognition_module, "fsync_append", spy)
        shadow.receipt("t", "r1", '{"a": 1, "b": 2, "c": 3, "d": 4}')
        shadow.receipt("t", "r2", '{"e": 5, "f": 6}')
        shadow.close_step()
        assert len(appends) == 1
        # And the format did not change for it: the same lines, in order.
        assert len(lines(shadow.path)) == len(
            [e for e in shadow.state.events])


class TestNothingInHereReachesTheMission:
    """A shadow that can fail a run is not a shadow.

    The failure is *counted*, cognition stops for the rest of the run, one
    note goes into the log, and the caller gets ``None`` back — which is
    what :meth:`core.runtime.run.Run._dispatch` and
    :meth:`~core.runtime.run.Run._loop` both rely on, since neither checks
    a return value.
    """

    def test_a_poisoned_receipt_is_counted_and_swallowed(self, shadow,
                                                         monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.observations_of",
                            _boom)
        shadow.receipt("t", "r1", RECEIPT)
        assert shadow.failures == 1
        assert shadow.on is False

    def test_it_stops_for_the_rest_of_the_run(self, shadow, monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)
        shadow.receipt("t", "r1", RECEIPT)
        monkeypatch.undo()
        shadow.receipt("t", "r2", RECEIPT)
        shadow.close_step()
        assert shadow.failures == 1
        assert shadow.state.propositions() == ()

    def test_the_log_says_so_once(self, shadow, monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)
        shadow.receipt("t", "r1", RECEIPT)
        notes = [line for line in lines(shadow.path) if NOTE_KEY in line]
        assert len(notes) == 1
        assert notes[0][NOTE_KEY] == STOPPED_NOTE
        assert "Boom" in notes[0]["error"]

    def test_a_note_is_not_an_event(self, shadow, monkeypatch):
        """A reader replaying the file must skip it: the kernel refuses a
        log holding an ``op`` it cannot reconstruct, and it would be right
        to.  The note sits BETWEEN the events here, which is where one
        really lands, and the surviving events still number 1..n — so the
        kernel's own position check passes and the skip is provably a skip
        rather than a truncation."""
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        fsync_append(shadow.path, canonical(header_record()))
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)
        shadow.receipt("t", "r2", RECEIPT)
        header, events, notes = read_reasoning(shadow.path)
        assert len(notes) == 1
        envelope = {KERNEL_SCHEMA_KEY: header[KERNEL_SCHEMA_KEY],
                    KERNEL_COUNT_KEY: len(events),
                    KERNEL_EVENTS_KEY: events}
        assert replay_reasoning(shadow.path).propositions() == \
            CognitiveState.replay(envelope).propositions()


class TestWhatTheSupervisorIsTold:
    """``progress()`` — four numbers and a line, and no more than that.

    ROADMAP §2.9.6's epistemic-progress signal reads the store through this
    one method, which decides nothing: the supervisor compares readings and
    may raise the advisory review it already raises for a repeated call.
    The reading is a *read* in the kernel's sense — it flushes, like every
    reader, and writes no event of its own.
    """

    def _goal(self, shadow):
        from core.cognition.types import RuleAuthority

        shadow.state.add_rule("owner_known", ("alice", "owner_known", True),
                              [("alice", "payment_link", "?c")],
                              authority=RuleAuthority.SKILL)
        shadow.state.add_goal(("alice", "owner_known", True))
        return shadow

    def test_a_run_with_no_goals_reads_an_empty_frontier(self, shadow):
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        reading = shadow.progress()
        assert reading.obligations == 0 and reading.owed == ""
        assert reading.propositions == len(shadow.state.propositions())

    def test_it_quotes_the_top_of_the_frontier(self, shadow):
        """The same words the compiled block shows, through the same
        function, so a review and a block cannot name one obligation two
        ways."""
        from core.cognition.compile import owed_line

        self._goal(shadow)
        assert shadow.progress().owed == \
            owed_line(shadow.state.next_obligation())

    def test_the_digest_moves_when_the_frontier_does(self, shadow):
        self._goal(shadow)
        before = shadow.progress()
        shadow.receipt("mcp.x", "r1",
                       json.dumps({"units": 12}))
        shadow.close_step()
        assert shadow.progress().frontier == before.frontier, \
            "a receipt that answers nothing moves no obligation"
        shadow.state.assert_observation(
            ("alice", "payment_link", "acct-9"),
            evidence=(shadow.state.propositions()[0].evidence[0],),
            authority=EvidenceAuthority.DETERMINISTIC)
        assert shadow.progress().frontier != before.frontier

    def test_reading_it_writes_no_event(self, shadow):
        self._goal(shadow)
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        before = len(shadow.state.events)
        shadow.progress()
        shadow.progress()
        assert len(shadow.state.events) == before

    def test_a_stopped_shadow_is_not_watched(self, shadow, monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)
        shadow.receipt("t", "r1", RECEIPT)
        assert shadow.on is False
        assert shadow.progress() is None

    def test_a_frontier_that_raises_costs_the_signal_and_nothing_else(
            self, shadow, monkeypatch):
        """Failure isolation, and it is narrow on purpose: a frontier this
        run cannot read is not a store it cannot hold. The harvest keeps
        running, the log keeps growing, and the mission is the mission it
        would have been."""
        monkeypatch.setattr(type(shadow.state), "ranked_frontier", _boom)
        assert shadow.progress() is None
        assert shadow.watch_failures == 1
        assert shadow.watching is False
        assert shadow.on is True
        monkeypatch.undo()
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        assert shadow.state.propositions()
        assert shadow.progress() is None, "it stops for the rest of the run"

    def test_the_log_says_which_half_stopped(self, shadow, monkeypatch):
        monkeypatch.setattr(type(shadow.state), "ranked_frontier", _boom)
        shadow.progress()
        notes = [line for line in lines(shadow.path) if NOTE_KEY in line]
        assert [note[NOTE_KEY] for note in notes] == [UNWATCHED_NOTE]
        assert "Boom" in notes[0]["error"]


class _Boom(Exception):
    pass


def _boom(*_args, **_kwargs):
    raise _Boom("Boom")


# ── the file, and picking it back up ─────────────────────────────────────────


class TestTheLogIsTheState:
    def test_line_one_states_all_three_versions(self, tmp_path):
        store = RunStore(tmp_path / "store")
        run = store.create()
        shadow = open_shadow(store, run.run_id)
        header = lines(shadow.path)[0]
        assert header[SCHEMA_KEY] == REASONING_SCHEMA_VERSION
        assert header[KERNEL_SCHEMA_KEY] == EVENT_SCHEMA_VERSION
        assert header[KERNEL_KEY] == KERNEL_VERSION

    def test_the_header_carries_no_clock_and_no_id(self, tmp_path):
        """Either would make a replayed run's log unable to reproduce the
        recorded one's bytes, which is the property that makes this file a
        determinism proof rather than an artefact."""
        assert set(header_record()) == {SCHEMA_KEY, KERNEL_SCHEMA_KEY,
                                        KERNEL_KEY}

    def test_replaying_the_file_rebuilds_the_state(self, shadow):
        shadow.receipt("t", "r1", RECEIPT)
        shadow.receipt("t", "r2", '{"records": 9}')
        shadow.close_step()
        # The header a real log opens with; this fixture writes events only.
        text = Path(shadow.path).read_text(encoding="utf-8")
        Path(shadow.path).write_text(
            canonical(header_record()) + "\n" + text, encoding="utf-8")
        rebuilt = replay_reasoning(shadow.path)
        assert [(p.entity, p.field, p.value) for p in rebuilt.propositions()] \
            == [(p.entity, p.field, p.value)
                for p in shadow.state.propositions()]

    def test_evidence_survives_the_flush_as_evidence(self, shadow):
        """The nested half of a record, which a shallow copy loses.

        The kernel freezes an event all the way down — tuples for
        sequences, ``MappingProxyType`` for mappings — and neither is JSON.
        Under ``canonical``'s ``default=str`` a shallow ``dict(event)``
        does not *fail*; it writes each evidence ref's repr as a JSON
        string, and the log then holds records whose evidence is prose.
        Asserted on the bytes, because that is where it shows.
        """
        shadow.receipt("t", "r1", RECEIPT)
        shadow.close_step()
        written = [line for line in lines(shadow.path) if "op" in line]
        assert written
        for event in written:
            for ref in event.get("evidence", ()):
                assert isinstance(ref, dict), ref
                assert ref["kind"] == "receipt"

    def test_a_version_one_log_replays_under_version_one_rules(self,
                                                               tmp_path):
        """Replay semantics are version-aware, and the header is what says
        which. A schema-1 log states no ``count`` — the field did not exist
        — and passing this reader's own version through instead of the
        log's would refuse a log that is perfectly good."""
        path = tmp_path / REASONING_LOG
        path.write_text(
            canonical({SCHEMA_KEY: REASONING_SCHEMA_VERSION,
                       KERNEL_SCHEMA_KEY: 1, KERNEL_KEY: 1}) + "\n"
            + canonical({"n": 1, "op": "assert_observation",
                         "triple": ["t#r1", "records", 12481],
                         "text": None, "authority": "deterministic",
                         "evidence": [{"kind": "receipt", "locator": "x",
                                       "note": ""}]}) + "\n",
            encoding="utf-8")
        state = replay_reasoning(path)
        assert [(p.entity, p.field, p.value) for p in state.propositions()] \
            == [("t#r1", "records", 12481)]

    def test_an_unversioned_log_is_refused(self, tmp_path):
        path = tmp_path / REASONING_LOG
        path.write_text('{"n": 1, "op": "derive"}\n', encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_reasoning(path)

    def test_a_newer_log_is_refused(self, tmp_path):
        path = tmp_path / REASONING_LOG
        path.write_text(json.dumps(
            {SCHEMA_KEY: REASONING_SCHEMA_VERSION + 1, "event_schema": 1}
        ) + "\n", encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_reasoning(path)

    def test_a_version_of_true_is_not_version_one(self, tmp_path):
        """``True`` is an ``int`` and ``True > 1`` is ``False``, so a header
        saying ``true`` would sail through a bare ``isinstance`` check and
        be read as version 1. The kernel guards the same thing on its own
        version; three readers, one rule."""
        path = tmp_path / REASONING_LOG
        path.write_text(json.dumps(dict(header_record(),
                                        **{SCHEMA_KEY: True})) + "\n",
                        encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_reasoning(path)

    def test_a_second_header_is_refused(self, tmp_path):
        """Position blindness is right for a NOTE — one really does land
        between two events — and wrong for the header, which is what every
        other line is read under. Two of them is two logs in one file, and
        taking the last would reinterpret every event before it."""
        path = tmp_path / REASONING_LOG
        path.write_text(canonical(header_record()) + "\n"
                        + canonical(header_record()) + "\n",
                        encoding="utf-8")
        with pytest.raises(ReplayRefused):
            read_reasoning(path)

    def test_an_absent_log_is_not_an_error(self, tmp_path):
        assert read_reasoning(tmp_path / "nothing.jsonl") == (None, [], [])


class TestResumePicksTheStoreUpWhereItStopped:
    """``--resume`` continues a run, and a shadow that started again would
    give the resumed store every observation twice.

    The handle is what makes this work: a resumed run re-records the
    recorded results into its store in the same order, so ``r3`` is the same
    receipt in the second process as in the first, and the entities line up
    without anything being written down twice.
    """

    @pytest.fixture
    def store(self, tmp_path):
        return RunStore(tmp_path / "store")

    def test_a_second_open_replays_rather_than_restarts(self, store):
        run = store.create()
        first = open_shadow(store, run.run_id)
        first.receipt("t", "r1", RECEIPT)
        first.close_step()
        again = open_shadow(store, run.run_id)
        assert [(p.entity, p.field, p.value)
                for p in again.state.propositions()] == \
            [(p.entity, p.field, p.value) for p in first.state.propositions()]

    def test_a_second_open_appends_nothing(self, store):
        run = store.create()
        first = open_shadow(store, run.run_id)
        first.receipt("t", "r1", RECEIPT)
        first.close_step()
        before = Path(first.path).read_text(encoding="utf-8")
        open_shadow(store, run.run_id).close_step()
        assert Path(first.path).read_text(encoding="utf-8") == before

    def test_a_resumed_run_writes_one_header(self, store):
        run = store.create()
        open_shadow(store, run.run_id)
        open_shadow(store, run.run_id)
        assert sum(1 for line in lines(store.directory(run.run_id)
                                       / REASONING_LOG)
                   if SCHEMA_KEY in line) == 1

    def test_the_resumed_log_is_the_log_of_one_run(self, store):
        """Killed between steps, picked back up, and the file replays to the
        store the uninterrupted run would have had — the same propositions,
        each one still tracing to its own receipt."""
        killed = store.create()
        first = open_shadow(store, killed.run_id)
        first.receipt("t", "r1", '{"records": 1}')
        first.close_step()
        resumed = open_shadow(store, killed.run_id)
        resumed.receipt("t", "r2", '{"records": 2}')
        resumed.close_step()

        whole = store.create()
        straight = open_shadow(store, whole.run_id)
        straight.receipt("t", "r1", '{"records": 1}')
        straight.close_step()
        straight.receipt("t", "r2", '{"records": 2}')
        straight.close_step()

        assert [(p.entity, p.field, p.value)
                for p in replay_reasoning(first.path).propositions()] == \
            [(p.entity, p.field, p.value)
             for p in replay_reasoning(straight.path).propositions()]

    def test_the_resumed_log_has_no_duplicate_events(self, store):
        run = store.create()
        first = open_shadow(store, run.run_id)
        first.receipt("t", "r1", '{"records": 1}')
        first.close_step()
        resumed = open_shadow(store, run.run_id)
        resumed.receipt("t", "r2", '{"records": 2}')
        resumed.close_step()
        _header, events, _notes = read_reasoning(first.path)
        assert [event["n"] for event in events] == list(
            range(1, len(events) + 1))


class TestALibraryCallerDoesNotLoseTheShadow:
    """``Run`` is the library API, and the two adapters are its other doors.

    A parameter a constructor cannot take is a feature a library caller
    silently does not get — and silently is the whole problem, because a
    caller who passes ``cognition=`` and gets no ``reasoning.jsonl`` has no
    way to tell that from a run that harvested nothing.
    """

    @pytest.mark.parametrize("dotted,cls", [
        ("core.runtime.mission", "MissionRunner"),
        ("core.runtime.swarm", "SwarmRunner"),
    ])
    def test_the_adapter_takes_cognition(self, dotted, cls):
        import importlib
        import inspect

        runner = getattr(importlib.import_module(dotted), cls)
        assert "cognition" in inspect.signature(runner.__init__).parameters

    @pytest.mark.parametrize("dotted,cls", [
        ("core.runtime.mission", "MissionRunner"),
        ("core.runtime.swarm", "SwarmRunner"),
    ])
    def test_the_adapter_puts_it_on_the_store(self, dotted, cls, tmp_path):
        """Not merely accepted — carried. A parameter that is taken and
        dropped is worse than one that is refused."""
        import importlib

        from core.tools.bus import ToolBus
        from core.tools.capability import CapabilityEngine
        from core.tools.sandbox import NoneSandbox
        from core.contracts.schemas import PolicyPack

        runner = getattr(importlib.import_module(dotted), cls)
        shadow = ShadowCognition(tmp_path / REASONING_LOG, "run-1")
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))
        bus = ToolBus(capability_engine=engine, sandbox=NoneSandbox())
        built = runner(lambda messages, **kw: "{}", bus, [],
                       cognition=shadow)
        assert built._run.store.cognition is shadow


# ── the ablation ─────────────────────────────────────────────────────────────


class TestCognitionOffChangesNothingAtAll:
    """Half (a): the committed corpus, replayed with the flag absent.

    ``tests/test_run_corpus.py`` already asserts the streams; what is added
    here is the *file system* claim, which that file has no reason to make:
    a run that did not ask for cognition leaves no reasoning log, and the
    committed fixtures hold none to begin with.
    """

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_committed_fixtures_hold_no_reasoning_log(self, run_id):
        assert not (CORPUS / run_id / REASONING_LOG).exists()

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_a_replay_without_the_flag_writes_none(self, corpus, tmp_path,
                                                   run_id):
        fresh = _replay(corpus, tmp_path, run_id)
        assert REASONING_LOG not in _files(corpus, fresh)


class TestCognitionOnAddsOneFileAndNothingElse:
    """Half (b): the same four runs, replayed twice in one store.

    Each assertion names a different surface, because "nothing changed" is
    only worth what it was checked against: the event stream is held to the
    *committed* fixture (so a drift shared by both arms cannot hide), and
    the recorder's two logs are held to the arm beside them (so a change in
    what was asked or dispatched shows up even where the stream would not).
    """

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_stream_is_still_the_committed_stream(self, corpus, tmp_path,
                                                      run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        assert comparable(records(corpus, fresh)) == \
            comparable(committed_records(run_id))

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_replay_still_reports_no_drift(self, corpus, tmp_path,
                                               run_id):
        """The prompt is the half the stream cannot speak for.  ``first:
        None`` is the positive statement that a run with cognition on asked
        the recording's own questions, byte for byte."""
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        drift = RunStore(corpus).meta(fresh).meta["drift"]
        assert drift["first"] is None, drift
        assert drift["calls"] == 0
        assert drift["served"] == drift["recorded"]

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_reasoning_is_the_only_new_file(self, corpus, tmp_path, run_id):
        off = _replay(corpus, tmp_path, run_id)
        on = _replay(corpus, tmp_path, run_id, "--cognition")
        assert set(_files(corpus, on)) - set(_files(corpus, off)) == \
            {REASONING_LOG}
        assert set(_files(corpus, off)) - set(_files(corpus, on)) == set()

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_recorded_calls_and_dispatches_are_the_same(self, corpus,
                                                            tmp_path, run_id):
        off = _replay(corpus, tmp_path, run_id)
        on = _replay(corpus, tmp_path, run_id, "--cognition")
        for name in ("model.jsonl", "tools.jsonl"):
            here = RunStore(corpus).directory(on) / name
            there = RunStore(corpus).directory(off) / name
            assert _timeless(lines(here)) == _timeless(lines(there)), name

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_two_arms_end_the_same_way(self, corpus, tmp_path, run_id):
        """Stated on its own as well as inside the record-for-record diff,
        because this is the sentence ``ROADMAP.md`` §2.9.3 actually makes:
        cognition on never blocks an answer."""
        off = _replay(corpus, tmp_path, run_id)
        on = _replay(corpus, tmp_path, run_id, "--cognition")
        finished = [[r for r in records(corpus, which)
                     if r["event"] == "mission_finished"][0]
                    for which in (off, on)]
        assert finished[0]["outcome"] == finished[1]["outcome"]


class TestTheShadowMeasuredWhatWasThere:
    """Half (c): the completeness numbers, pinned.

    Every zero-drift assertion above is satisfied by a shadow that harvests
    nothing.  These are what say it harvested, and what makes a mapping
    change visible as a number rather than as a silence.
    """

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_propositions_are_the_pinned_number(self, corpus, tmp_path,
                                                    run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        path = _reasoning(corpus, fresh)
        _header, events, notes = read_reasoning(path)
        props, observed, derives = HARVEST[run_id]
        assert notes == []
        assert len(replay_reasoning(path).propositions()) == props
        assert sum(1 for e in events
                   if e["op"] == "assert_observation") == observed
        assert sum(1 for e in events if e["op"] == "derive") == derives

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_every_proposition_traces_to_a_receipt(self, corpus, tmp_path,
                                                   run_id):
        """The kernel refuses a claim with no evidence; this says the
        evidence is a *receipt of this run* and not a shape that merely got
        past the door."""
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        state = replay_reasoning(_reasoning(corpus, fresh))
        for prop in state.propositions():
            assert prop.evidence
            for ref in prop.evidence:
                assert ref.kind == "receipt"
                assert ref.locator.startswith(f"{fresh}/")

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_two_replays_write_the_same_log(self, corpus, tmp_path, run_id):
        """The determinism proof.  A replay re-runs the loop off recorded
        receipts, so cognition re-runs off the same bytes; the two logs are
        identical but for the run id inside each evidence locator, which is
        the same exclusion a replay already states for the stream."""
        first = _replay(corpus, tmp_path, run_id, "--cognition")
        second = _replay(corpus, tmp_path, run_id, "--cognition")
        assert _without_the_run_id(_reasoning(corpus, first), first) == \
            _without_the_run_id(_reasoning(corpus, second), second)


class TestAFailingShadowDoesNotMarkTheRun:
    """The isolation claim, end to end rather than in a unit.

    A shadow that raises on the first receipt of a real mission has to leave
    a stream a consumer cannot tell from the committed one — which is the
    same comparison the corpus guard makes, run against a harness that is
    on fire.
    """

    @pytest.fixture
    def poisoned(self, monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_mission_is_untouched(self, corpus, tmp_path, poisoned,
                                      run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        assert comparable(records(corpus, fresh)) == \
            comparable(committed_records(run_id))

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_reasoning_log_says_what_happened(self, corpus, tmp_path,
                                                  poisoned, run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        _header, events, notes = read_reasoning(_reasoning(corpus, fresh))
        assert events == []
        assert [note[NOTE_KEY] for note in notes] == [STOPPED_NOTE]


class TestResumingOnTheCommandLine:
    """``--resume`` with ``--cognition``, against the real stub server.

    The unit tests above drive :func:`open_shadow` directly, which proves
    the machinery and cannot prove the wiring: whether the CLI knows it is
    resuming, and whether the loop's one attachment is reached on the
    second process at all. The run here is killed at a step boundary by a
    model that goes away — which is what a served endpoint dying looks like
    from in here — and picked back up, exactly as
    ``tests/test_cli_mission_skill.py`` does it.

    Two cases, and the second is the one the review found. A run recorded
    **with** the flag continues seamlessly, because its prior log is
    replayed. A run recorded **without** it and resumed **with** it cannot:
    :mod:`core.runtime.resume` re-records the earlier receipts into the
    result store rather than dispatching them, and that path has no
    cognition in it and should not have — harvesting there would be a
    second attachment point. So that log begins at the resume, and
    :data:`RESUMED_NOTE` is line two so a short log is never read as a
    complete one.
    """

    VIEW = json.dumps({"tool": "mcp.governed_view",
                       "arguments": {"run_id": ASSET, "section": "totals"}})
    ANSWER = json.dumps({"answer": f"The view holds 12481 records, {ASSET}."})

    def _script(self, agent, *replies, then_die=False):
        """Serve *replies* in order, then answer or die."""
        queue = list(replies)

        def _chat(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            if queue:
                return queue.pop(0)
            if then_die:
                raise RuntimeError("the model server went away")
            return self.ANSWER

        agent.client.chat.side_effect = _chat

    def _first_process(self, MockClass, agent, tmp_path, *extra):
        """One tool call, then the endpoint dies. Returns the run id."""
        self._script(agent, self.VIEW, then_die=True)
        with pytest.raises(SystemExit):
            mission_run_cli(MockClass, "--skill", _skill_for(tmp_path),
                            *extra)
        listed = RunStore(tmp_path / "runs").list()
        assert len(listed) == 1, [run.run_id for run in listed]
        return listed[0].run_id

    def _resume(self, MockClass, agent, run_id, tmp_path, *extra):
        """One more tool call, then an answer."""
        self._script(agent, self.VIEW)
        from core.cli import _main
        argv = ["test", "--mission", "--resume", run_id,
                "--mcp-stdio", f"{sys.executable} {MISSION_STUB}",
                "--skill", _skill_for(tmp_path), *extra]
        with patch("sys.argv", argv):
            _main(MockClass)

    def test_a_run_recorded_with_the_flag_continues_seamlessly(
            self, elf, tmp_path):
        MockClass, agent = elf
        run_id = self._first_process(MockClass, agent, tmp_path,
                                     "--cognition")
        path = RunStore(tmp_path / "runs").directory(run_id) / REASONING_LOG
        before = read_reasoning(path)[1]
        assert before, "the first process harvested nothing to continue from"

        self._resume(MockClass, agent, run_id, tmp_path, "--cognition")
        header, events, notes = read_reasoning(path)
        assert notes == [], "a log that was continued must not claim a gap"
        # One header, one numbering, both stretches in it.
        assert [event["n"] for event in events] == \
            list(range(1, len(events) + 1))
        assert len(events) > len(before)
        # And it still replays: the resumed stretch did not write a second
        # copy of what the first one had already written.
        assert len(replay_reasoning(path).propositions()) == \
            len({(p.entity, p.field, p.value)
                 for p in replay_reasoning(path).propositions()})

    def test_a_run_recorded_without_it_says_where_the_log_begins(
            self, elf, tmp_path):
        MockClass, agent = elf
        run_id = self._first_process(MockClass, agent, tmp_path)
        path = RunStore(tmp_path / "runs").directory(run_id) / REASONING_LOG
        assert not path.exists()

        self._resume(MockClass, agent, run_id, tmp_path, "--cognition")
        raw = lines(path)
        assert SCHEMA_KEY in raw[0]
        assert raw[1].get(NOTE_KEY) == RESUMED_NOTE, raw[1]

    def test_the_counts_cover_only_what_happened_after_the_resume(
            self, elf, tmp_path):
        """The gap is real and the note is what makes it readable: every
        proposition in this log traces to a receipt the SECOND process
        dispatched, and the first process's receipt is in neither."""
        MockClass, agent = elf
        run_id = self._first_process(MockClass, agent, tmp_path)
        self._resume(MockClass, agent, run_id, tmp_path, "--cognition")
        path = RunStore(tmp_path / "runs").directory(run_id) / REASONING_LOG
        state = replay_reasoning(path)
        assert state.propositions()
        # `r1` is the FIRST process's handle; the resumed process re-records
        # it into the store without dispatching, so it is not in here, and
        # every entity that is belongs to a call this process made.
        assert {p.entity for p in state.propositions()} == \
            {"mcp.governed_view#r2"}


class TestARefusedLogDoesNotRefuseTheMission:
    """``open_shadow`` is the one call into this feature that is not total.

    It reads a log a previous process wrote, and it refuses one it cannot
    trust — a version from the future, a file whose header never reached the
    disk.  Refusing is right; refusing the *mission* for it would be the one
    thing this module promises never to do.  So the refusal is caught where
    the object is built, said out loud, and the run goes on with no shadow
    at all rather than with half of one.
    """

    def _log(self, tmp_path, *lines):
        """A run store holding a reasoning log of exactly *lines*."""
        store = RunStore(tmp_path / "store")
        run = store.create()
        (store.directory(run.run_id) / REASONING_LOG).write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8")
        return store, run.run_id

    def test_a_headerless_log_is_refused_at_the_door(self, tmp_path):
        """The shape a process killed between creating the file and writing
        line one leaves behind — which is the case that made the branch
        below necessary rather than defensive."""
        store, run_id = self._log(tmp_path, '{"n": 1, "op": "derive"}')
        with pytest.raises(ReplayRefused):
            open_shadow(store, run_id)

    def test_a_log_whose_numbering_is_not_its_positions_is_refused(
            self, tmp_path):
        """The kernel's own check, reached through this reader.

        A torn line in the MIDDLE of a log is skipped by
        :func:`read_reasoning` — which is right for the tail of a killed
        process and cannot be right here — and what it leaves is a gap in
        ``n``. Every surviving line is well-formed on its own, so nothing
        but the numbering can see it, and the numbering does.
        """
        store, run_id = self._log(
            tmp_path, canonical(header_record()),
            canonical({"n": 1, "op": "derive", "propositions": [],
                       "rules": []}),
            canonical({"n": 3, "op": "derive", "propositions": [],
                       "rules": []}))
        with pytest.raises(ReplayRefused):
            open_shadow(store, run_id)

    def test_a_log_with_evidence_that_is_not_evidence_is_refused(self,
                                                                 tmp_path):
        """``decode_evidence``'s refusal, reached the same way.

        A string is the nasty one: it is a sequence, so a decoder that
        merely iterated would walk it character by character and build refs
        out of letters. It arrives here as the same exception every other
        unreadable log does, which is the point — one ``except`` in the
        caller covers the whole class.
        """
        store, run_id = self._log(
            tmp_path, canonical(header_record()),
            canonical({"n": 1, "op": "assert_observation",
                       "triple": ["t#r1", "records", 1], "text": None,
                       "authority": "deterministic",
                       "evidence": "notalist"}))
        with pytest.raises(ReplayRefused):
            open_shadow(store, run_id)

    def test_a_log_from_a_newer_kernel_is_refused(self, tmp_path):
        store, run_id = self._log(tmp_path, canonical(
            dict(header_record(), **{KERNEL_SCHEMA_KEY:
                                     EVENT_SCHEMA_VERSION + 1})))
        with pytest.raises(ReplayRefused):
            open_shadow(store, run_id)

    @pytest.fixture
    def refusing(self, monkeypatch):
        def _refuse(*_args, **_kwargs):
            raise ReplayRefused("this log is not one I can read")

        monkeypatch.setattr("core.runtime.cognition.open_shadow", _refuse)

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_mission_still_runs(self, corpus, tmp_path, refusing, run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        assert comparable(records(corpus, fresh)) == \
            comparable(committed_records(run_id))

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_it_runs_with_no_shadow_rather_than_half_of_one(
            self, corpus, tmp_path, refusing, run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        assert REASONING_LOG not in _files(corpus, fresh)


class TestTheAttachmentIsOnePoint:
    """One harvest per receipt, counted against the stream's own receipts.

    The defect this guards is the one the swarm's grounding record had: a
    second emitter, added in good faith beside the first, producing a
    record that is nearly right.  A shadow fed from two places would double
    every proposition and nothing else in this file would notice.
    """

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_one_harvest_for_each_tool_result(self, corpus, tmp_path,
                                              monkeypatch, run_id):
        seen = []
        real = ShadowCognition.receipt

        def spy(self, tool, seq, text="", evidence=""):
            seen.append((tool, seq))
            return real(self, tool, seq, text, evidence)

        monkeypatch.setattr(ShadowCognition, "receipt", spy)
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        results = [r for r in records(corpus, fresh)
                   if r["event"] == "tool_result"]
        assert len(seen) == len(results)
        assert len(set(seen)) == len(seen)
        assert [tool for tool, _ in seen] == [r["tool"] for r in results]
