# tests/test_memory_bank.py — the three tiers, and what each one refuses

"""The bank on its own: the cap, the provenance, the ranking, the budget.

``tests/test_memory_tools.py`` is the governance half (scopes, the bus) and
``tests/test_run_memory.py`` is where the tiers meet a run.  This file is
the bank as a data structure with opinions, and most of those opinions are
refusals: a write over the cap, a write with no reason, a hint for a bank
where nothing scores.

**The ranking is asserted one factor at a time, and both ways round.**  A
test that only says "the note I expected came first" passes against a
ranking that ignores two of its three terms; each of ``relevance``,
``recency`` and ``importance`` below is shown to reverse the order on its
own, with the other two held equal by construction.
"""

import json
import time

import pytest

from core.durable import RunStore
from core.memory.bank import (
    CORE_MEMORY_TOKENS, MEMORY_ENV, MEMORY_POLICY, PRINCIPAL_ENV, Block,
    MemoryBank, bank_root, open_bank,
)
from core.memory.__main__ import main

#: A day, in seconds.  The recency term's unit.
DAY = 86_400


@pytest.fixture
def bank(tmp_path):
    return MemoryBank(tmp_path / "bank", principal="alice")


def pinned(bank, label="style", **over):
    """One valid ``add``, so a test that is about something else is short."""
    fields = {"kind": "preference", "body": "Answers are short.",
              "reason": "the operator asked twice", "source": "r3"}
    fields.update(over)
    return bank.write("add", label=label, **fields)


# ── tier 1: the cap is the whole discipline ─────────────────────────────────


class TestCoreMemoryIsCapped:
    """A block is pinned into EVERY future system turn, so the cap is the
    only thing that keeps the tier honest.  It refuses rather than evicts:
    everything in there was pinned on purpose."""

    def test_a_write_under_the_cap_is_taken(self, bank):
        code, out, err = pinned(bank)
        assert code == 0 and not err
        assert "style" in out
        assert "- [preference] style: Answers are short." in bank.core()

    def test_an_over_cap_write_is_refused_naming_the_cap(self, tmp_path):
        small = MemoryBank(tmp_path / "b", principal="alice", core_tokens=120)
        code, out, err = small.write(
            "add", label="essay", kind="fact", body="x " * 400,
            reason="because", source="operator")
        assert code == 1 and not out
        assert "120" in err, err
        assert "capped" in err

    def test_the_refused_write_left_nothing_behind(self, tmp_path):
        small = MemoryBank(tmp_path / "b", principal="alice", core_tokens=120)
        small.write("add", label="essay", kind="fact", body="x " * 400,
                    reason="because", source="operator")
        assert small.blocks() == []

    def test_the_refusal_names_the_way_to_make_room(self, tmp_path):
        small = MemoryBank(tmp_path / "b", principal="alice", core_tokens=120)
        _code, _out, err = small.write(
            "add", label="essay", kind="fact", body="x " * 400,
            reason="because", source="operator")
        assert "delete" in err

    def test_the_cap_is_measured_on_what_a_system_turn_would_carry(self, bank):
        """Rendered, not the sum of the bodies: the kind, the label and the
        date are bytes a prompt pays for too."""
        before = bank.core_tokens_used()
        candidate = Block(label="k", kind="fact", body="short", as_of="2026")
        after = bank.core_tokens_used(candidate)
        assert after > before
        assert bank.core_tokens == CORE_MEMORY_TOKENS

    def test_a_replace_is_measured_against_the_block_it_replaces(self,
                                                                 tmp_path):
        """Otherwise a replace of the largest block would be refused for
        the space that block was already occupying."""
        small = MemoryBank(tmp_path / "b", principal="alice", core_tokens=140)
        assert small.write("add", label="a", kind="fact", body="y " * 20,
                           reason="r", source="s")[0] == 0
        code, _out, err = small.write("replace", label="a", kind="fact",
                                      body="y " * 21, reason="r", source="s")
        assert code == 0, err


class TestAWriteHasToSayWhyAndFromWhat:
    """A sentence pinned into every future run that nobody can trace back
    to its evidence is a sentence nobody can ever check."""

    def test_no_reason_is_refused(self, bank):
        code, _out, err = bank.write("add", label="k", kind="fact",
                                     body="b", source="r3")
        assert code == 1 and "reason is required" in err

    def test_no_source_is_refused(self, bank):
        code, _out, err = bank.write("add", label="k", kind="fact",
                                     body="b", reason="why")
        assert code == 1 and "source is required" in err

    def test_a_delete_needs_a_reason_and_no_source(self, bank):
        pinned(bank)
        assert bank.write("delete", label="style")[0] == 1
        assert bank.write("delete", label="style", reason="wrong now")[0] == 0
        assert bank.blocks() == []

    def test_the_provenance_is_kept(self, bank):
        bank.run_id = "run-7"
        pinned(bank, source="r3")
        block, = bank.blocks()
        assert (block.reason, block.source, block.run_id) == (
            "the operator asked twice", "r3", "run-7")
        assert block.as_of

    def test_an_unknown_action_is_refused_naming_the_three(self, bank):
        code, _out, err = bank.write("append", label="k", reason="r",
                                     source="s")
        assert code == 1
        assert "add" in err and "replace" in err and "delete" in err

    def test_an_unknown_kind_is_refused_naming_the_four(self, bank):
        code, _out, err = bank.write("add", label="k", kind="vibe", body="b",
                                     reason="r", source="s")
        assert code == 1 and "persona" in err and "lesson" in err

    def test_adding_over_an_existing_label_is_refused(self, bank):
        pinned(bank)
        code, _out, err = pinned(bank)
        assert code == 1 and "replace" in err

    def test_replacing_a_label_that_is_not_there_is_refused(self, bank):
        code, _out, err = bank.write("replace", label="ghost", kind="fact",
                                     body="b", reason="r", source="s")
        assert code == 1 and "add" in err

    def test_deleting_a_label_that_is_not_there_is_refused(self, bank):
        code, _out, err = bank.write("delete", label="ghost", reason="r")
        assert code == 1 and "ghost" in err


class TestTheCoreSectionSaysWhatAMemoryIsWorth:
    def test_the_policy_sentence_is_there_with_nothing_pinned(self, bank):
        assert bank.core() == MEMORY_POLICY

    def test_the_policy_sentence_says_a_recalled_fact_is_dated(self, bank):
        assert "DATED" in bank.core()
        assert "re-verify" in bank.core()

    def test_it_says_nothing_is_retrieved_for_you(self, bank):
        assert "Nothing is retrieved for you" in bank.core()
        assert "memory_recall" in bank.core()


# ── redaction, on the way in ────────────────────────────────────────────────


class TestWhatIsWrittenIsScrubbedFirst:
    """A block outlives the run that wrote it, so a home path or a key
    pasted into one would be pinned into every system turn from then on."""

    @pytest.fixture(autouse=True)
    def _home(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")

    def test_a_home_path_in_a_block_body_is_rewritten(self, bank):
        bank.write("add", label="p", kind="fact",
                   body="The config is at /home/testuser/.judais-lobi/x.yml",
                   reason="r", source="operator")
        assert "/home/testuser" not in bank.core()
        assert "<home>/.judais-lobi/x.yml" in bank.core()

    def test_a_key_shaped_string_in_a_note_is_redacted(self, bank):
        bank.add_note("The endpoint key",
                      "It was rejected: sk-abcdefghijklmnopqrstuvwx")
        note, = bank.notes()
        assert "sk-abcdefghijkl" not in note.body
        assert "redacted" in note.body

    def test_a_home_path_in_a_reason_is_rewritten(self, bank):
        bank.write("add", label="p", kind="fact", body="b",
                   reason="seen in /home/testuser/log", source="operator")
        block, = bank.blocks()
        assert "<home>/log" in block.reason


# ── tier 2: notes, and the three things that rank them ──────────────────────


class TestNotesAreDistilledAndDeduplicated:
    def test_a_note_is_written_with_its_sources(self, bank):
        note = bank.add_note("Cold starts are slow", "Retry once.",
                             importance=4, sources=["run-1/2"],
                             run_id="run-1")
        assert note is not None
        assert note.sources == ["run-1/2"] and note.importance == 4
        assert note.handle == f"n{note.id}"

    def test_the_same_note_twice_is_written_once(self, bank):
        assert bank.add_note("A", "B") is not None
        assert bank.add_note("A", "B") is None
        assert len(bank.notes()) == 1

    def test_a_body_over_the_cap_is_cut(self, bank):
        note = bank.add_note("Long", "word " * 400)
        assert len(note.body) < len("word " * 400)
        assert note.body.endswith("…")

    def test_importance_outside_one_to_five_is_clamped(self, bank):
        assert bank.add_note("A", "B", importance=99).importance == 5
        assert bank.add_note("C", "D", importance=-4).importance == 1

    def test_a_note_with_no_title_is_not_written(self, bank):
        assert bank.add_note("", "body") is None
        assert bank.notes() == []


class TestEachRankingFactorMovesTheOrderOnItsOwn:
    """Held equal by construction, one at a time.

    ``relevance`` is equal for two notes that both contain the whole query
    and nothing else of interest, which is what lets the recency and
    importance cases below say anything at all.
    """

    def _two(self, bank, **over):
        first = {"title": "alpha one", "body": "first", "ts": int(time.time()),
                 "importance": 3}
        second = {"title": "alpha two", "body": "second",
                  "ts": int(time.time()), "importance": 3}
        first.update(over.get("first", {}))
        second.update(over.get("second", {}))
        for spec in (first, second):
            bank.add_note(spec.pop("title"), spec.pop("body"), **spec)
        return [note.title for note in bank.ranked_notes("alpha")]

    def test_recency_decides_when_nothing_else_differs(self, tmp_path):
        now = int(time.time())
        older = MemoryBank(tmp_path / "a", principal="p")
        assert self._two(older, first={"ts": now},
                         second={"ts": now - 30 * DAY}) \
            == ["alpha one", "alpha two"]

    def test_and_reverses_when_the_dates_swap(self, tmp_path):
        now = int(time.time())
        other = MemoryBank(tmp_path / "b", principal="p")
        assert self._two(other, first={"ts": now - 30 * DAY},
                         second={"ts": now}) \
            == ["alpha two", "alpha one"]

    def test_importance_decides_when_nothing_else_differs(self, tmp_path):
        one = MemoryBank(tmp_path / "a", principal="p")
        assert self._two(one, first={"importance": 5},
                         second={"importance": 1}) \
            == ["alpha one", "alpha two"]

    def test_and_reverses_when_the_ratings_swap(self, tmp_path):
        two = MemoryBank(tmp_path / "b", principal="p")
        assert self._two(two, first={"importance": 1},
                         second={"importance": 5}) \
            == ["alpha two", "alpha one"]

    def test_relevance_decides_when_nothing_else_differs(self, bank):
        stamp = int(time.time())
        bank.add_note("alpha widget", "one", ts=stamp)
        bank.add_note("alpha beta", "two", ts=stamp)
        order = [n.title for n in bank.ranked_notes("alpha widget")]
        assert order == ["alpha widget", "alpha beta"]

    def test_and_reverses_when_the_query_does(self, bank):
        stamp = int(time.time())
        bank.add_note("alpha widget", "one", ts=stamp)
        bank.add_note("alpha beta", "two", ts=stamp)
        order = [n.title for n in bank.ranked_notes("alpha beta")]
        assert order == ["alpha beta", "alpha widget"]

    def test_a_note_that_matches_nothing_is_not_recalled_at_all(self, bank):
        bank.add_note("something else entirely", "prose", importance=5)
        assert bank.ranked_notes("quantum chromodynamics") == []

    def test_a_fresher_note_beats_a_better_rated_stale_one(self, bank):
        """The case the two above cannot make on their own.

        With everything else equal a tie is broken by the timestamp, so a
        ranking that had **dropped** the recency term entirely would still
        order those pairs correctly.  Here recency has to do real work: the
        older note is rated three times higher, and today's low-rated one
        still comes first.  Delete ``_recency`` from :func:`score` and this
        reverses.
        """
        now = int(time.time())
        bank.add_note("alpha one", "x", importance=1, ts=now)
        bank.add_note("alpha two", "y", importance=3, ts=now - 60 * DAY)
        assert [n.title for n in bank.ranked_notes("alpha")] == [
            "alpha one", "alpha two"]

    def test_which_is_the_product_and_not_a_weighted_sum(self, bank):
        """A five-star, perfectly-matching note from six months ago must
        not out-rank a fair match from today.

        A weighted **sum** ranks it first — two of its three terms are 1.0
        and the third being ~0 barely dents the total.  The product is what
        makes a decayed note decay.  Change ``*`` to ``+`` in
        :func:`~core.memory.bank.score` and this reverses.
        """
        now = int(time.time())
        bank.add_note("alpha widget calibration", "one", importance=5,
                      ts=now - 180 * DAY)
        bank.add_note("alpha beta gamma", "two", importance=1, ts=now)
        assert [n.title for n in
                bank.ranked_notes("alpha widget calibration")] == [
            "alpha beta gamma", "alpha widget calibration"]

    def test_a_note_that_matches_nothing_at_all_never_gets_that_far(self,
                                                                    bank):
        """The zero-relevance case is answered before the score is: the
        product would make it zero anyway, and dropping it here is what
        keeps a five-star headline out of a recall about something else."""
        stamp = int(time.time())
        bank.add_note("irrelevant headline", "nothing to do with it",
                      importance=5, ts=stamp)
        bank.add_note("widget calibration", "how it is done",
                      importance=1, ts=stamp)
        assert [n.title for n in bank.ranked_notes("widget calibration")] \
            == ["widget calibration"]


class TestRecallIsBoundedTwiceOver:
    def _many(self, bank, how_many=9):
        stamp = int(time.time())
        for index in range(how_many):
            bank.add_note(f"alpha finding {index}",
                          f"a sentence about alpha, number {index}",
                          ts=stamp - index)

    def test_at_most_k_results(self, bank):
        self._many(bank)
        _code, out, _err = bank.recall(query="alpha", k=2)
        assert out.count("importance") == 2

    def test_k_is_itself_capped(self, bank):
        self._many(bank)
        _code, out, _err = bank.recall(query="alpha", k=50)
        assert out.count("importance") == 5

    def test_the_token_budget_binds_before_k_does(self, tmp_path):
        tight = MemoryBank(tmp_path / "b", principal="p", recall_tokens=30)
        self._many(tight)
        _code, out, _err = tight.recall(query="alpha", k=5)
        assert out.count("importance") < 5

    def test_what_was_cut_is_said_out_loud(self, tmp_path):
        tight = MemoryBank(tmp_path / "b", principal="p", recall_tokens=30)
        self._many(tight)
        _code, out, _err = tight.recall(query="alpha", k=5)
        assert "matched" in out and "shown" in out

    def test_a_query_is_required(self, bank):
        code, _out, err = bank.recall(query="  ")
        assert code == 1 and "query is required" in err

    def test_an_unknown_kind_is_refused(self, bank):
        code, _out, err = bank.recall(query="a", kind="everything")
        assert code == 1 and "note" in err and "run" in err

    def test_a_miss_says_nothing_is_being_withheld(self, bank):
        bank.add_note("alpha", "beta")
        code, out, _err = bank.recall(query="zeta")
        assert code == 0 and "nothing in memory matches" in out
        assert "withheld" in out

    def test_since_excludes_what_is_older(self, bank):
        old = int(time.time()) - 400 * DAY
        bank.add_note("alpha ancient", "long ago", ts=old)
        bank.add_note("alpha recent", "today")
        _code, out, _err = bank.recall(query="alpha", since="2026-01-01")
        assert "alpha recent" in out and "alpha ancient" not in out


class TestOneToolReadsTheSourceToo:
    def test_a_note_handle_reads_it_whole(self, bank):
        note = bank.add_note("Alpha", "Body.", sources=["run-1/4"],
                             run_id="run-1")
        code, out, _err = bank.recall(handle=note.handle)
        assert code == 0
        assert "run-1/4" in out and "run-1" in out

    def test_an_unknown_note_handle_is_refused(self, bank):
        code, _out, err = bank.recall(handle="n99")
        assert code == 1 and "n99" in err

    def test_a_run_handle_reads_the_run(self, tmp_path):
        runs = RunStore(tmp_path / "runs")
        run = runs.create(meta={"objective": "count the widgets",
                                "answer": "there are four",
                                "outcome": "answered"})
        bank = MemoryBank(tmp_path / "b", principal="p", runs=runs)
        code, out, _err = bank.recall(handle=run.run_id)
        assert code == 0
        assert "count the widgets" in out and "there are four" in out

    def test_an_unknown_run_handle_is_refused(self, tmp_path):
        bank = MemoryBank(tmp_path / "b", principal="p",
                          runs=RunStore(tmp_path / "runs"))
        code, _out, err = bank.recall(handle="run_nope")
        assert code == 1

    def test_with_no_run_store_the_refusal_says_so(self, bank):
        code, _out, err = bank.recall(handle="run_x")
        assert code == 1 and "no run store" in err


class TestTheEpisodicHalfIsTheRunStoreAndNotACopy:
    @pytest.fixture
    def episodic(self, tmp_path):
        runs = RunStore(tmp_path / "runs")
        runs.create(meta={"objective": "compare the widget batches",
                          "answer": "batch two is heavier",
                          "outcome": "answered"})
        runs.create(meta={"objective": "tune the sprocket",
                          "answer": "it is fine", "outcome": "answered"})
        return MemoryBank(tmp_path / "b", principal="p", runs=runs)

    def test_a_past_run_is_recalled_by_its_objective(self, episodic):
        _code, out, _err = episodic.recall(query="widget batches")
        assert "compare the widget batches" in out

    def test_the_handle_is_the_run_id(self, episodic):
        hits = episodic.ranked_runs("widget batches")
        assert hits and hits[0]["handle"].startswith("run_")

    def test_a_run_that_matches_nothing_is_not_returned(self, episodic):
        assert episodic.ranked_runs("chromodynamics") == []

    def test_kind_run_excludes_notes(self, episodic):
        episodic.add_note("widget batches note", "a distilled thing")
        _code, out, _err = episodic.recall(query="widget batches", kind="run")
        assert "widget batches note" not in out
        assert "past run" in out

    def test_kind_note_excludes_runs(self, episodic):
        episodic.add_note("widget batches note", "a distilled thing")
        _code, out, _err = episodic.recall(query="widget batches", kind="note")
        assert "widget batches note" in out and "past run" not in out

    def test_a_bank_with_no_run_store_has_no_episodic_half(self, bank):
        assert bank.ranked_runs("anything") == []


# ── the offer ───────────────────────────────────────────────────────────────


class TestTheHintIsTitlesAndNothingElse:
    def test_nothing_scoring_means_no_hint(self, bank):
        bank.add_note("alpha", "beta")
        assert bank.hint("a completely unrelated objective") == ""

    def test_a_faint_match_is_below_the_threshold_and_stays_quiet(self,
                                                                  bank):
        """The threshold is what separates the hint from a recall.

        This note *does* match — a recall for the same words returns it —
        but it shares one common word with a long objective and is rated
        1, so its score is below :data:`HINT_THRESHOLD` and the honest
        offer is silence.  Remove the threshold and the run is told about
        it unasked, which is the failure mode this tier exists to avoid.
        """
        bank.add_note("alpha", "beta", importance=1)
        objective = "alpha gamma delta epsilon zeta"
        assert bank.ranked_notes(objective)          # a recall would find it
        assert bank.hint(objective) == ""

    def test_and_the_same_note_rated_five_clears_it(self, bank):
        bank.add_note("alpha", "beta", importance=5)
        assert "alpha" in bank.hint("alpha gamma delta epsilon zeta")

    def test_an_empty_bank_means_no_hint(self, bank):
        assert bank.hint("anything at all") == ""

    def test_a_scoring_note_is_named_by_title(self, bank):
        bank.add_note("Widget calibration is manual",
                      "The rig has no autocalibration; do it by hand.")
        hint = bank.hint("calibrate the widget")
        assert "Widget calibration is manual" in hint

    def test_the_body_is_never_in_the_hint(self, bank):
        bank.add_note("Widget calibration is manual",
                      "The rig has no autocalibration; do it by hand.")
        assert "autocalibration" not in bank.hint("calibrate the widget")

    def test_at_most_three_titles(self, bank):
        for index in range(6):
            bank.add_note(f"widget fact {index}", f"about widgets {index}")
        assert bank.hint("widget").count(";") == 2

    def test_the_count_is_configurable_and_zero_turns_it_off(self, tmp_path):
        off = MemoryBank(tmp_path / "b", principal="p", hint_titles=0)
        off.add_note("widget fact", "about widgets")
        assert off.hint("widget") == ""

    def test_the_hint_stays_inside_its_budget(self, bank):
        for index in range(3):
            bank.add_note(f"widget {'long title ' * 12} {index}",
                          f"about widgets {index}")
        assert len(bank.hint("widget")) <= 150 * 4

    def test_it_names_the_tool_so_the_model_knows_what_to_do(self, bank):
        bank.add_note("Widget calibration is manual", "By hand.")
        assert "memory_recall" in bank.hint("calibrate the widget")


# ── the reflection ──────────────────────────────────────────────────────────


class TestReflectionIsOneBoundedCall:
    def test_it_writes_the_notes_the_model_returned(self, bank):
        asked = []

        def ask(messages):
            asked.append(messages)
            return json.dumps({"notes": [
                {"title": "Cold starts are slow", "body": "Retry once.",
                 "importance": 4}]})

        written = bank.reflect(objective="do a thing", answer="done",
                               ask=ask, run_id="run-1", sources=["run-1/0"])
        assert len(asked) == 1
        assert [note.title for note in written] == ["Cold starts are slow"]
        assert written[0].sources == ["run-1/0"]
        assert written[0].run_id == "run-1"

    def test_the_prompt_carries_the_objective_the_answer_and_the_evidence(
            self, bank):
        seen = {}

        def ask(messages):
            seen["text"] = messages[0]["content"]
            return "{}"

        bank.reflect(objective="count widgets", answer="four",
                     evidence="the tool said 4", ask=ask)
        assert "count widgets" in seen["text"]
        assert "four" in seen["text"]
        assert "the tool said 4" in seen["text"]

    def test_it_says_that_no_notes_is_the_usual_answer(self, bank):
        seen = {}

        def ask(messages):
            seen["text"] = messages[0]["content"]
            return "{}"

        bank.reflect(objective="o", answer="a", ask=ask)
        assert "NO notes" in seen["text"]

    def test_at_most_three_notes_however_many_come_back(self, bank):
        def ask(_messages):
            return json.dumps({"notes": [
                {"title": f"t{i}", "body": f"b{i}"} for i in range(9)]})

        assert len(bank.reflect(objective="o", answer="a", ask=ask)) == 3

    def test_prose_around_the_object_is_tolerated(self, bank):
        def ask(_messages):
            return ('Sure! Here is what I learned:\n'
                    '{"notes": [{"title": "T", "body": "B"}]}\nHope that '
                    'helps.')

        assert [n.title for n in bank.reflect(objective="o", answer="a",
                                              ask=ask)] == ["T"]

    def test_a_reply_that_is_not_json_writes_nothing_and_does_not_raise(
            self, bank):
        assert bank.reflect(objective="o", answer="a",
                            ask=lambda _m: "I have no idea.") == []

    def test_a_model_that_raises_writes_nothing_and_does_not_raise(self,
                                                                   bank):
        def ask(_messages):
            raise RuntimeError("endpoint down")

        assert bank.reflect(objective="o", answer="a", ask=ask) == []

    def test_no_model_at_all_writes_nothing(self, bank):
        assert bank.reflect(objective="o", answer="a", ask=None) == []

    def test_a_repeated_lesson_is_written_once(self, bank):
        def ask(_messages):
            return json.dumps({"notes": [{"title": "T", "body": "B"}]})

        assert len(bank.reflect(objective="o", answer="a", ask=ask)) == 1
        assert bank.reflect(objective="o", answer="a", ask=ask) == []


# ── partitions ──────────────────────────────────────────────────────────────


class TestOnePrincipalDoesNotReadAnother:
    def test_blocks_are_partitioned(self, tmp_path):
        alice = MemoryBank(tmp_path / "b", principal="alice")
        bob = MemoryBank(tmp_path / "b", principal="bob")
        pinned(alice)
        assert alice.blocks() and bob.blocks() == []
        assert "Answers are short." not in bob.core()

    def test_notes_are_partitioned(self, tmp_path):
        alice = MemoryBank(tmp_path / "b", principal="alice")
        bob = MemoryBank(tmp_path / "b", principal="bob")
        alice.add_note("alpha", "alice's note")
        assert bob.ranked_notes("alpha") == []

    def test_the_same_note_may_exist_in_two_partitions(self, tmp_path):
        alice = MemoryBank(tmp_path / "b", principal="alice")
        bob = MemoryBank(tmp_path / "b", principal="bob")
        assert alice.add_note("alpha", "shared wording") is not None
        assert bob.add_note("alpha", "shared wording") is not None

    def test_skills_are_partitioned_too(self, tmp_path):
        recon = MemoryBank(tmp_path / "b", principal="a", skill="recon")
        plain = MemoryBank(tmp_path / "b", principal="a")
        pinned(recon)
        assert plain.blocks() == []

    def test_every_partition_is_listable(self, tmp_path):
        MemoryBank(tmp_path / "b", principal="a", skill="recon").add_note(
            "x", "y")
        bank = MemoryBank(tmp_path / "b", principal="b")
        pinned(bank)
        assert set(bank.partitions()) == {("a", "recon"), ("b", "")}


class TestWhereABankLives:
    def test_unset_means_no_bank(self, monkeypatch):
        monkeypatch.delenv(MEMORY_ENV, raising=False)
        assert bank_root() is None
        assert open_bank() is None

    def test_blank_means_no_bank(self):
        assert bank_root("   ") is None

    def test_a_disable_word_means_no_bank(self):
        assert bank_root("none") is None and bank_root("off") is None

    def test_a_path_is_a_bank(self, tmp_path):
        assert bank_root(str(tmp_path)) == tmp_path

    def test_open_bank_reads_the_principal_off_the_environment(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv(PRINCIPAL_ENV, "carol")
        opened = open_bank(str(tmp_path), runs=None)
        assert opened is not None and opened.principal == "carol"

    def test_the_default_principal_is_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv(PRINCIPAL_ENV, raising=False)
        assert MemoryBank(tmp_path).principal == "default"


class TestTheOperatorSurface:
    def test_stats_counts_both_tiers(self, bank):
        pinned(bank)
        bank.add_note("a", "b")
        facts = bank.stats()
        assert facts["blocks"] == 1 and facts["notes"] == 1
        assert facts["core_cap"] == CORE_MEMORY_TOKENS

    def test_purge_takes_the_notes_and_leaves_the_blocks(self, bank):
        pinned(bank)
        bank.add_note("a", "b")
        assert bank.purge() == 1
        assert bank.notes() == [] and len(bank.blocks()) == 1

    def test_purge_takes_the_blocks_when_asked(self, bank):
        pinned(bank)
        assert bank.purge(notes=False, blocks=True) == 1
        assert bank.blocks() == []


class TestTheOperatorCli:
    """``python -m core.memory``.  Two writers, one implementation: a cap
    refused on the command line is refused in the bank's own words."""

    def _run(self, tmp_path, *argv, principal="alice"):
        return main(["--memory", str(tmp_path / "b"),
                     "--principal", principal, *argv])

    def test_add_then_blocks_shows_it(self, tmp_path, capsys):
        assert self._run(tmp_path, "add", "--label", "style",
                         "--kind", "preference", "--body", "Be brief.",
                         "--reason", "asked twice") == 0
        capsys.readouterr()
        assert self._run(tmp_path, "blocks") == 0
        out = capsys.readouterr().out
        assert "[preference] style: Be brief." in out
        assert "why: asked twice" in out
        assert "source: operator" in out

    def test_delete_removes_it(self, tmp_path, capsys):
        self._run(tmp_path, "add", "--label", "style", "--body", "b",
                  "--reason", "r")
        assert self._run(tmp_path, "delete", "--label", "style",
                         "--reason", "stale") == 0
        capsys.readouterr()
        self._run(tmp_path, "blocks")
        assert "no core memory blocks" in capsys.readouterr().out

    def test_a_refused_write_exits_nonzero(self, tmp_path, capsys):
        assert self._run(tmp_path, "delete", "--label", "ghost",
                         "--reason", "r") == 1
        assert "ghost" in capsys.readouterr().err

    def test_stats_names_the_cap(self, tmp_path, capsys):
        assert self._run(tmp_path, "stats") == 0
        assert f"/{CORE_MEMORY_TOKENS} tokens" in capsys.readouterr().out

    def test_notes_and_purge(self, tmp_path, capsys):
        MemoryBank(tmp_path / "b", principal="alice").add_note("A", "B")
        assert self._run(tmp_path, "notes") == 0
        assert "A" in capsys.readouterr().out
        assert self._run(tmp_path, "purge") == 0
        assert "deleted 1" in capsys.readouterr().out

    def test_recall_by_hand(self, tmp_path, capsys):
        MemoryBank(tmp_path / "b", principal="alice").add_note(
            "widget calibration", "by hand")
        assert self._run(tmp_path, "recall", "widget") == 0
        assert "widget calibration" in capsys.readouterr().out

    def test_the_principal_flag_partitions(self, tmp_path, capsys):
        self._run(tmp_path, "add", "--label", "s", "--body", "b",
                  "--reason", "r")
        capsys.readouterr()
        assert self._run(tmp_path, "blocks", principal="bob") == 0
        assert "no core memory blocks" in capsys.readouterr().out

    def test_no_directory_and_no_environment_is_refused(self, monkeypatch,
                                                        capsys):
        monkeypatch.delenv(MEMORY_ENV, raising=False)
        assert main(["stats"]) == 2
        assert MEMORY_ENV in capsys.readouterr().err
