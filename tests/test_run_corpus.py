# tests/test_run_corpus.py — the extraction's guard: yesterday's runs, again

"""Three recorded runs and nineteen recorded streams, replayed on the new code.

The usual rule — every new assertion must be shown to fail — is
unsatisfiable for a refactor, because a correct extraction's assertions
pass against the old code too.  **This file is the mutation check**, and it
is mutated at the *implementation*: drop a field from a record, swap two
emissions, skip the redactor, and the diff below turns red.  See
``ROADMAP.md`` §2.6.4.

Two halves, and they catch different things.

The **run corpus** (``tests/fixtures/runs/``) is three complete recordings
made against the real stub server — one under each protocol and one staged
``--swarm`` turn — replayed here through ``--replay``'s own machinery, with
the backend wired to raise if anything asks it a question.  What is asserted
is the whole stream, record for record, field for field, against the
committed ``events.jsonl`` — and **no drift**, which is the other half of
the claim: a replay reports drift when a request differs from the recorded
one, so an empty drift record says the new code asked the recording's own
questions, byte for byte, all the way through.  That is the assertion that
holds the prompt still.  A served endpoint's prefix cache is keyed on bytes,
so ``stacked``'s whitespace and ``seed``'s most-constant-first order are a
deployment's money and not a style.

The **eval corpus** (``tests/fixtures/eval/``) is nineteen streams, each
produced by a scripted agent against the same stub through the whole CLI.
They are replayed by *running them again* and scoring both, and every
column of the verdict has to agree — not the four
``tests/test_eval_stub_suite.py`` compares, but all of them bar the three
that legitimately move (see :data:`MOVING_KPIS`) and one stream that is a
recording of the pre-0.15 loop, whose diff is pinned rather than skipped
(see :data:`STALE`).

Nothing here is a second comparator.  ``comparable`` and its ``MOVES`` come
from :mod:`tests.test_record_replay`, ``drive`` and ``SCRIPTS`` from
:mod:`tests.test_eval_stub_suite`, and the corpora are the committed ones:
a guard that built its own idea of what a run looks like would be a guard
that agrees with itself.
"""

import json

import pytest

from core.eval.score import score_run
from core.eval.stub_suite import SUITE
from tests.test_eval_stub_suite import (
    FIXTURES, SCRIPTS, _fixture_path, drive, workdir,
)
from tests.test_record_replay import (
    CORPUS, CORPUS_RUNS, MOVES, REPLAY_FLAGS, comparable, corpus, records,
    replay_argv, replayed, run_cli, scripted_elf, write_skill,
)

#: The verdict columns a re-run of a committed eval stream may move, and
#: they are three rather than two.  ``elapsed_s`` is this afternoon's clock
#: and ``run_id`` is the new directory's — the same two the run corpus
#: excludes.  ``max_steps`` is the corpus being older than the harness: the
#: eval streams were recorded when the default ceiling was eight and Phase
#: 14 made it ``0``, and only ``tests/fixtures/runs/`` was re-recorded at
#: 0.15.0.  Everything else — the outcome, the tools, the grounding
#: verdict, the token count, the number of refused replies — has to be
#: what it was.
MOVING_KPIS = ("elapsed_s", "max_steps", "run_id")

#: The one committed stream that is a recording of the OLD loop, with the
#: columns it moves pinned rather than excused.
#:
#: ``a_listing_is_not_a_plan.bad`` was recorded before the step budget went:
#: the scripted agent's replies were consumed differently under a ceiling of
#: eight, and the stream holds a rejected reply and an
#: ``answered_with_caveat`` that a run of the same script does not produce
#: today.  It is stale on ``master`` too — this lane did not do it — so the
#: honest guard is not to skip the stream but to state exactly which
#: columns it may move.  A column joining this set IS this lane's problem.
STALE = {
    ("a_listing_is_not_a_plan", "bad"): {
        "model_calls", "outcome", "records", "reply_rejected", "steps",
        "tokens",
    },
}


def committed_records(run_id):
    """The recorded stream, read out of the repository itself.

    Unwrapped from the run store's envelope the way
    :meth:`core.durable.RunStore.records` unwraps it, so the two sides of
    the comparison below are the same vocabulary: the records as they were
    emitted, and not the ``seq``/``at`` a log adds around them.
    """
    path = CORPUS / run_id / "events.jsonl"
    return [json.loads(line)["record"] for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def shapes(records):
    """Each record as ``(event, its field names)``.

    ``comparable`` excuses the *values* of :data:`MOVES` — a run id, a
    clock — and it therefore cannot see a field that stopped being emitted
    at all: a dropped ``elapsed_s`` produces the same dict on both sides of
    that comparison.  Which field names a record carries is a different
    claim from what they say, and it is the one ``contract.FIELDS`` is
    about, so it is asserted separately.
    """
    return [(record["event"], sorted(record)) for record in records]


def moved_columns(live, committed):
    """Which verdict columns differ, the three that may move aside."""
    return {key for key in committed.kpis
            if key not in MOVING_KPIS
            and live.kpis.get(key) != committed.kpis.get(key)}


class TestTheGuardIsNotQuietlyWidened:
    """The exclusion list is the one thing that could make this file lie.

    A field added to ``MOVES`` is a field the corpus diff stops checking,
    and the diff is the whole of this lane's evidence.  So the list is
    pinned here as well as declared there: widening it has to be a
    deliberate edit in two files, in one commit, with a reason.
    """

    def test_the_recording_may_move_five_fields_and_no_others(self):
        assert set(MOVES) == {"run_id", "elapsed_s", "started_at", "usage",
                              "audit_ref"}


class TestTheRecordedRunsReplayUnchanged:
    """The three committed runs, record for record, against the fixture."""

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_replayed_stream_is_the_committed_stream(
            self, corpus, tmp_path, run_id):
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        fresh = replayed(corpus, run_id)
        assert comparable(records(corpus, fresh.run_id)) == \
            comparable(committed_records(run_id))

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_events_arrive_in_the_recorded_order(
            self, corpus, tmp_path, run_id):
        """The same claim as above, stated so a failure is readable.

        A record-for-record equality that fails prints two long lists; the
        sequence of event names prints the place where the loop's order
        changed, which is what a swapped ``grounding``/``answer`` looks
        like from outside.
        """
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        fresh = replayed(corpus, run_id)
        assert [r["event"] for r in records(corpus, fresh.run_id)] == \
            [r["event"] for r in committed_records(run_id)]

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_every_record_carries_the_fields_it_carried(
            self, corpus, tmp_path, run_id):
        """A field that stopped being emitted is invisible to ``comparable``.

        See :func:`shapes`.  ``elapsed_s`` is the case: it is in ``MOVES``
        because its value is this afternoon's, and a loop that stopped
        emitting it would leave the record-for-record diff clean while
        taking a required field off the wire.
        """
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        fresh = replayed(corpus, run_id)
        assert shapes(records(corpus, fresh.run_id)) == \
            shapes(committed_records(run_id))

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_the_replay_reports_no_drift(self, corpus, tmp_path, run_id):
        """Nothing moved in the PROMPT either, which the stream cannot say.

        Two runs can emit identical records off different requests — a
        reordered system turn changes what the endpoint is billed for and
        nothing a consumer sees.  ``ReplayModel`` compares each request to
        the recorded one and counts the differences; ``first: None`` is the
        positive statement that this code asked the recording's own
        questions.
        """
        MockClass, _ = scripted_elf(refuse=True)
        run_cli(MockClass, *replay_argv(run_id, write_skill(tmp_path),
                                        *REPLAY_FLAGS.get(run_id, ())))
        drift = replayed(corpus, run_id).meta["drift"]
        assert drift["first"] is None, drift
        assert drift["calls"] == 0
        # And every recorded call was served: a replay that asked fewer
        # questions than the recording holds is a loop that lost a turn,
        # and it would leave the drift count at zero while doing it.
        assert drift["served"] == drift["recorded"]


#: Every committed eval stream, as ``(mission key, scripted agent)``.  Read
#: off the scripts and the fixture directory together, so a stream added to
#: the corpus is scored here without this list being edited.
PAIRS = [(key, agent) for key in sorted(SCRIPTS)
         for agent in sorted(SCRIPTS[key])
         if _fixture_path(key, agent).exists()]

STREAMS = [pytest.param(key, agent, id=f"{key}.{agent}")
           for key, agent in PAIRS]

#: The streams whose whole verdict — the sentences, not only the pass —
#: has to come back unchanged.
FRESH = [pytest.param(key, agent, id=f"{key}.{agent}")
         for key, agent in PAIRS if (key, agent) not in STALE]


def scored(key, agent, workdir):
    """``(live verdict, committed verdict)`` for one stream."""
    mission = SUITE.mission(key)
    live = score_run(drive(mission, SCRIPTS[key][agent], workdir, agent),
                     mission)
    return live, score_run(_fixture_path(key, agent), mission)


class TestTheEvalCorpusScoresTheSame:
    """Run each committed stream again and read the same verdict.

    The eval fixtures are what the harness produced, and the scorer reads
    only the stream — so a verdict that moved is a record that moved, and a
    column that moved is a field that moved.  Both are compared, because
    ``passed`` is a coarse signal: a run that stopped citing its evidence
    and a run that answered from a different tool can both still pass their
    own mission.
    """

    @pytest.mark.parametrize("key,agent", FRESH)
    def test_the_verdict_is_the_committed_verdict(self, key, agent, workdir):
        live, committed = scored(key, agent, workdir)
        assert (live.passed, set(live.reasons)) == \
            (committed.passed, set(committed.reasons))

    @pytest.mark.parametrize("key,agent", STREAMS)
    def test_the_columns_that_moved_are_the_ones_allowed_to(
            self, key, agent, workdir):
        live, committed = scored(key, agent, workdir)
        assert moved_columns(live, committed) == STALE.get((key, agent), set())

    @pytest.mark.parametrize("key,agent", STREAMS)
    def test_a_stream_that_passed_still_passes_and_one_that_failed_fails(
            self, key, agent, workdir):
        """True of the stale stream too: what it records is a failure of
        the mission it was written for, and it is still one."""
        live, committed = scored(key, agent, workdir)
        assert live.passed == committed.passed

    def test_every_committed_stream_is_scored(self):
        """A parametrisation that collected nothing passes silently, and a
        stream added to ``tests/fixtures/eval/`` with no script behind it
        would be a fixture this guard never looks at."""
        committed = {path.name for path in FIXTURES.glob("*.jsonl")}
        scored_names = {_fixture_path(key, agent).name for key, agent in PAIRS}
        assert committed == scored_names
