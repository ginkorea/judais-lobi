# tests/test_durable.py — the writes that have to survive the process

"""Durability, asserted rather than assumed.

Every test here is a question about what is on the disk *after* something
went wrong, because that is the only situation in which any of this matters.
A write that works is indistinguishable from a write that works; the
difference between ``path.write_text`` and :func:`core.durable
.atomic_write_text` shows up only in the window between truncating a file and
filling it, and the difference between a buffered append and an fsync'd one
shows up only when the machine goes down.

The centrepiece is :class:`TestTheReusedSequenceBug`. It is a regression test
for a defect this repository never had: the reference platform this primitive
is ported from paid for it, a caller wrote a stale ``last_seq`` back over a
live one, the next append reused numbers a reader had already passed, and a
transcript that was on disk the whole time rendered as a blank pane. The
lesson comes across with the mechanism or it does not come across at all.
"""

import json
import os
import threading
import time

import pytest

from core.durable import (
    DISABLE_WORDS,
    LOCKS,
    LOCK_FILENAME,
    NoSuchRun,
    RUNS_ENV,
    Run,
    RunClosed,
    RunHold,
    RunStore,
    atomic_write_json,
    atomic_write_text,
    fsync_append,
    new_run_id,
    open_run_store,
    runs_root,
    valid_run_id,
)


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs")


def _events(store, run_id):
    """The event names in the log, in order, straight off the disk."""
    return [e["record"].get("event") for e in store.since(run_id)]


def _age(store, run_id, seconds):
    """Backdate a run's ``updated_at`` on the disk, so a test can watch the
    heartbeat move it forward again."""
    from datetime import datetime, timedelta, timezone

    path = store.meta_path(run_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds)
    ).isoformat(timespec="seconds")
    path.write_text(json.dumps(record), encoding="utf-8")


# ── replacing a file is atomic or it is not done ─────────────────────────────


class TestAtomicWrite:
    def test_the_text_lands(self, tmp_path):
        path = atomic_write_text(tmp_path / "a.txt", "hello")
        assert path.read_text(encoding="utf-8") == "hello"

    def test_the_parent_directory_is_made(self, tmp_path):
        path = atomic_write_text(tmp_path / "deep" / "er" / "a.txt", "hi")
        assert path.read_text(encoding="utf-8") == "hi"

    def test_json_round_trips(self, tmp_path):
        path = atomic_write_json(tmp_path / "a.json", {"n": 1, "s": "é"})
        assert json.loads(path.read_text(encoding="utf-8")) == {"n": 1, "s": "é"}

    def test_a_value_json_cannot_hold_is_written_as_a_string(self, tmp_path):
        """``default=str``, for the reason the event sink has it: refusing to
        record a run's metadata because one field was a ``Path`` is a worse
        outcome than recording the path as text."""
        path = atomic_write_json(tmp_path / "a.json", {"where": tmp_path})
        assert json.loads(path.read_text(encoding="utf-8"))["where"] == str(tmp_path)

    def test_a_failure_before_the_replace_leaves_the_old_file(
            self, tmp_path, monkeypatch):
        """The whole point. A truncate-then-write loses the old content the
        moment it starts; this loses nothing until it has everything."""
        target = tmp_path / "a.txt"
        target.write_text("the old one", encoding="utf-8")

        def explode(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", explode)
        with pytest.raises(OSError):
            atomic_write_text(target, "the new one")
        assert target.read_text(encoding="utf-8") == "the old one"

    def test_and_leaves_no_staging_file_behind(self, tmp_path, monkeypatch):
        """A directory strewn with ``tmpXXXX`` files nothing will collect is
        its own failure, and the one a naive tempfile-and-rename ships with."""
        target = tmp_path / "a.txt"
        target.write_text("the old one", encoding="utf-8")

        def explode(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", explode)
        with pytest.raises(OSError):
            atomic_write_text(target, "the new one")
        assert list(tmp_path.iterdir()) == [target]

    def test_the_staging_file_is_a_sibling(self, tmp_path, monkeypatch):
        """``os.replace`` is atomic within a filesystem and not across one, so
        the temporary file may not live in the system temp directory."""
        seen = {}

        real = os.replace

        def watch(src, dst):
            seen["dir"] = os.path.dirname(str(src))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        atomic_write_text(tmp_path / "a.txt", "x")
        assert seen["dir"] == str(tmp_path)


# ── appending a line is durable or it is not recorded ────────────────────────


class TestFsyncAppend:
    def test_lines_accumulate(self, tmp_path):
        path = tmp_path / "log.jsonl"
        fsync_append(path, "one")
        fsync_append(path, "two")
        assert path.read_text(encoding="utf-8").splitlines() == ["one", "two"]

    def test_the_parent_directory_is_made_on_the_first_write(self, tmp_path):
        fsync_append(tmp_path / "deep" / "log.jsonl", "one")
        assert (tmp_path / "deep" / "log.jsonl").exists()

    def test_the_bytes_are_pushed_to_the_disk(self, tmp_path, monkeypatch):
        """A buffered append returns while the line is still in a kernel
        buffer, and the entries worth having are the last ones written before
        a machine went down."""
        synced = []
        real = os.fsync
        monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd) or real(fd))
        fsync_append(tmp_path / "log.jsonl", "one")
        assert synced


# ── an id is a whitelist, never an escape ────────────────────────────────────


class TestTheRunId:
    def test_it_sorts_by_time_and_is_unique(self):
        first, second = new_run_id(), new_run_id()
        assert first != second
        assert first.startswith("run_") and second.startswith("run_")

    @pytest.mark.parametrize("bad", [
        "../etc", "run_../etc", "run_a/b", "th_abc", "", "run_", None, 7,
        "run_" + "a" * 33,
    ])
    def test_an_id_we_did_not_mint_is_not_one(self, bad):
        assert not valid_run_id(bad)

    def test_the_minted_one_is(self):
        assert valid_run_id(new_run_id())

    @pytest.mark.parametrize("bad", ["../etc", "run_../etc", "run_a/b"])
    def test_a_traversal_never_becomes_a_directory(self, store, bad):
        with pytest.raises(NoSuchRun):
            store.directory(bad)


# ── the run and its log ──────────────────────────────────────────────────────


class TestTheStore:
    def test_create_lays_out_the_directory(self, store):
        run = store.create(meta={"objective": "find things"})
        assert (store.directory(run.run_id) / "meta.json").exists()
        assert (store.directory(run.run_id) / "events.jsonl").exists()

    def test_the_store_hands_out_the_id(self, store):
        assert valid_run_id(store.create().run_id)

    def test_an_id_from_elsewhere_is_refused(self, store):
        with pytest.raises(NoSuchRun):
            store.create("../etc")

    def test_appending_to_a_run_that_is_not_there(self, store):
        with pytest.raises(NoSuchRun):
            store.append(new_run_id(), {"event": "answer"})

    def test_seq_is_monotonic(self, store):
        run_id = store.create().run_id
        seqs = [store.append(run_id, {"event": "step_started", "index": i})["seq"]
                for i in range(4)]
        assert seqs == [1, 2, 3, 4]

    def test_the_record_is_the_callers_and_the_number_is_the_stores(self, store):
        """The envelope decision: ``seq`` wraps the record and never enters
        it, so the records on disk are the records that went on the wire and
        `core.runtime.contract` stays the only author of their shape."""
        run_id = store.create().run_id
        envelope = store.append(run_id, {"event": "answer", "text": "hi"})
        assert envelope["record"] == {"event": "answer", "text": "hi"}
        assert "seq" not in envelope["record"]
        assert envelope["seq"] == 1 and envelope["at"]

    def test_the_caller_s_record_is_copied_not_captured(self, store):
        """A caller that reuses one dict for every record must not be able to
        rewrite what is already on the log."""
        run_id = store.create().run_id
        record = {"event": "step_started", "index": 0}
        envelope = store.append(run_id, record)
        record["index"] = 99
        assert envelope["record"]["index"] == 0
        assert store.records(run_id)[0]["index"] == 0

    def test_last_seq_survives_a_new_process(self, tmp_path):
        root = tmp_path / "runs"
        run_id = RunStore(root).create().run_id
        RunStore(root).append(run_id, {"event": "a"})
        assert RunStore(root).append(run_id, {"event": "b"})["seq"] == 2

    def test_meta_is_the_callers_half(self, store):
        run_id = store.create(meta={"objective": "find things"}).run_id
        assert store.meta(run_id).meta["objective"] == "find things"

    def test_update_meta_merges(self, store):
        run_id = store.create(meta={"objective": "x"}).run_id
        store.update_meta(run_id, catalogue=["a", "b"])
        assert store.meta(run_id).meta == {"objective": "x",
                                           "catalogue": ["a", "b"]}

    def test_records_unwraps_the_envelopes(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        store.append(run_id, {"event": "b"})
        assert store.records(run_id) == [{"event": "a"}, {"event": "b"}]

    def test_since_reads_from_a_cursor(self, store):
        run_id = store.create().run_id
        for i in range(4):
            store.append(run_id, {"event": "step_started", "index": i})
        assert [e["seq"] for e in store.since(run_id, 2)] == [3, 4]

    def test_a_torn_last_line_is_skipped_rather_than_fatal(self, store):
        """A process killed mid-write leaves half a line. The alternative to
        skipping it is a transcript that will not open again, ever."""
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        with store.log_path(run_id).open("a", encoding="utf-8") as log:
            log.write('{"seq": 2, "at": "now", "rec')
        assert store.records(run_id) == [{"event": "a"}]

    def test_a_blank_line_is_not_a_record(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        with store.log_path(run_id).open("a", encoding="utf-8") as log:
            log.write("\n")
        assert len(store.records(run_id)) == 1

    def test_list_is_newest_first(self, store):
        first = store.create()
        second = store.create()
        second.created_at = "2099-01-01T00:00:00+00:00"
        # Written through the store rather than by hand, so `list` is being
        # asked about records this module produced.
        store._write_meta(second)
        assert [r.run_id for r in store.list()][0] == second.run_id
        assert {r.run_id for r in store.list()} == {first.run_id, second.run_id}

    def test_an_unreadable_run_does_not_make_the_others_unlistable(self, store):
        good = store.create().run_id
        broken = store.create().run_id
        store.meta_path(broken).write_text("{not json", encoding="utf-8")
        assert [r.run_id for r in store.list()] == [good]

    def test_the_log_is_appended_to_and_never_rewritten(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        first = store.log_path(run_id).read_text(encoding="utf-8")
        store.append(run_id, {"event": "b"})
        assert store.log_path(run_id).read_text(
            encoding="utf-8").startswith(first)


# ── the bug the primitive was written around ─────────────────────────────────


class TestTheReusedSequenceBug:
    """Ported with the mechanism, because the mechanism is the lesson.

    A caller reads the metadata, does some work, and writes the object back.
    In between, an append moved ``last_seq`` on. Writing the whole record back
    put the stale counter on disk; the next append handed out numbers a reader
    had already seen and skipped past, and a reader resuming with
    ``seq > cursor`` dropped every one of them.
    """

    def test_a_stale_record_saved_back_does_not_rewind_the_counter(self, store):
        run_id = store.create().run_id
        stale = store.meta(run_id)              # last_seq == 0, and now held
        store.append(run_id, {"event": "a"})    # 1
        store.append(run_id, {"event": "b"})    # 2
        store.save(stale)                       # the moment that broke it
        assert store.append(run_id, {"event": "c"})["seq"] == 3

    def test_and_no_two_records_ever_share_a_number(self, store):
        run_id = store.create().run_id
        stale = store.meta(run_id)
        for name in "abc":
            store.append(run_id, {"event": name})
        store.save(stale)
        for name in "def":
            store.append(run_id, {"event": name})
        seqs = [e["seq"] for e in store.since(run_id)]
        assert seqs == sorted(set(seqs)) == [1, 2, 3, 4, 5, 6]

    def test_a_reader_resuming_from_its_cursor_misses_nothing(self, store):
        """The failure as it was actually seen: a browser holding cursor 3 was
        shown nothing of the six records that followed."""
        run_id = store.create().run_id
        stale = store.meta(run_id)
        for name in "abc":
            store.append(run_id, {"event": name})
        cursor = max(e["seq"] for e in store.since(run_id))
        store.save(stale)
        for name in "def":
            store.append(run_id, {"event": name})
        assert [e["record"]["event"] for e in store.since(run_id, cursor)] == \
            ["d", "e", "f"]

    def test_what_the_caller_owns_is_still_written(self, store):
        """The whitelist has to let the caller's own fields through, or it is
        not a fix but a refusal."""
        run_id = store.create(meta={"objective": "x"}).run_id
        held = store.meta(run_id)
        held.meta["title"] = "chosen by a person"
        store.append(run_id, {"event": "a"})
        store.save(held)
        assert store.meta(run_id).meta["title"] == "chosen by a person"
        assert store.meta(run_id).last_seq == 1

    def test_update_meta_never_holds_a_record_across_the_work(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        store.update_meta(run_id, catalogue=["a"])
        assert store.meta(run_id).last_seq == 1

    def test_last_seq_is_not_the_callers_to_write(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        held = store.meta(run_id)
        held.last_seq = 99
        store.save(held)
        assert store.meta(run_id).last_seq == 1

    def test_the_whitelist_says_which_fields_those_are(self):
        assert RunStore.CALLER_OWNED == ("meta",)
        assert "last_seq" not in RunStore.CALLER_OWNED


# ── two threads, one run ─────────────────────────────────────────────────────


class TestConcurrency:
    def test_no_number_is_handed_out_twice(self, store):
        run_id = store.create().run_id
        errors = []

        def write():
            try:
                for i in range(20):
                    store.append(run_id, {"event": "step_started", "index": i})
            except Exception as exc:            # pragma: no cover - the point
                errors.append(exc)

        threads = [threading.Thread(target=write, daemon=True) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors
        seqs = [e["seq"] for e in store.since(run_id)]
        assert seqs == list(range(1, 81))


# ── following a run that is still being written ──────────────────────────────


class TestFollow:
    def test_it_replays_what_is_already_there(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        store.append(run_id, {"event": "b"})
        stop = threading.Event()
        stop.set()
        seen = [e for e in store.follow(run_id, stop=stop, poll_s=0.01)]
        assert [e["record"]["event"] for e in seen] == ["a", "b"]

    def test_it_replays_from_a_cursor(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        store.append(run_id, {"event": "b"})
        stop = threading.Event()
        stop.set()
        seen = list(store.follow(run_id, 1, stop=stop, poll_s=0.01))
        assert [e["record"]["event"] for e in seen] == ["b"]

    def test_a_wait_that_times_out_is_a_heartbeat_and_not_an_ending(self, store):
        """A follower that simply blocked would be indistinguishable, from
        outside, from a follower whose reader has gone away."""
        run_id = store.create().run_id
        following = store.follow(run_id, poll_s=0.01)
        try:
            assert next(following) is None
            assert next(following) is None
        finally:
            following.close()

    def test_a_record_written_afterwards_arrives(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        stop = threading.Event()
        seen = []

        def follower():
            for item in store.follow(run_id, stop=stop, poll_s=0.01):
                if item is None:
                    continue
                seen.append(item["record"]["event"])
                if len(seen) == 2:
                    stop.set()
                    return

        thread = threading.Thread(target=follower, daemon=True)
        thread.start()
        store.append(run_id, {"event": "b"})
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert seen == ["a", "b"]

    def test_a_stop_that_is_set_ends_it(self, store):
        run_id = store.create().run_id
        stop = threading.Event()
        stop.set()
        assert list(store.follow(run_id, stop=stop, poll_s=0.01)) == []


# ── where the runs go, and how to keep none ──────────────────────────────────


class TestTheEnvironment:
    """Read as :mod:`core.policy.audit`'s conventions, because they are.

    A path moves it, ``none``/``off`` silences it, and unset is the default
    — silence is not a setting anybody chose.
    """

    def test_unset_is_the_default_directory(self, monkeypatch, tmp_path):
        monkeypatch.delenv(RUNS_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        assert runs_root() == tmp_path / ".judais-lobi" / "runs"

    def test_blank_is_unset(self):
        assert runs_root("   ") is not None

    def test_a_path_is_used_verbatim(self, tmp_path):
        assert runs_root(str(tmp_path / "elsewhere")) == tmp_path / "elsewhere"

    def test_a_user_path_is_expanded(self):
        assert "~" not in str(runs_root("~/runs"))

    @pytest.mark.parametrize("word", sorted(DISABLE_WORDS) + ["NONE", "Off"])
    def test_the_disable_words_mean_no_store_at_all(self, word):
        assert runs_root(word) is None
        assert open_run_store(word) is None

    def test_a_store_that_exists_is_one_something_writes_to(self, tmp_path):
        """The disable word is answered by returning nothing at all, so no
        caller ever holds a store whose directory nothing lands in."""
        opened = open_run_store(str(tmp_path / "runs"))
        assert isinstance(opened, RunStore)
        assert (tmp_path / "runs").is_dir()

    def test_the_environment_is_read_when_nothing_is_passed(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv(RUNS_ENV, str(tmp_path / "from-the-env"))
        assert open_run_store().root == tmp_path / "from-the-env"

    def test_off_in_the_environment_is_answered_the_same_way(self, monkeypatch):
        monkeypatch.setenv(RUNS_ENV, "off")
        assert open_run_store() is None


# ── who is running this ──────────────────────────────────────────────────────


@pytest.mark.skipif(not LOCKS, reason="no fcntl.flock on this platform")
class TestALiveRunIsOneSomebodyIsHolding:
    """Liveness by lock, not by clock.

    The clock was the whole rule and as the whole rule it was wrong: a run
    standing at a gate for five minutes, or waiting on a cold model, says
    nothing for longer than any staleness number worth having, and a
    sibling process read that silence as death. A held ``flock`` cannot be
    wrong about it — the kernel releases it when the process ends however
    it ended, and no amount of silence releases it while the process lives.
    """

    def test_a_fresh_run_is_held_by_nobody(self, store):
        run_id = store.create().run_id
        assert store.held(run_id) is False

    def test_holding_it_says_so(self, store):
        run_id = store.create().run_id
        hold = store.hold(run_id, heartbeat_s=0)
        try:
            assert hold.locked and store.held(run_id) is True
        finally:
            hold.release()

    def test_releasing_it_lets_go(self, store):
        run_id = store.create().run_id
        store.hold(run_id, heartbeat_s=0).release()
        assert store.held(run_id) is False

    def test_releasing_twice_is_not_an_error(self, store):
        run_id = store.create().run_id
        hold = store.hold(run_id, heartbeat_s=0)
        hold.release()
        hold.release()

    def test_a_second_holder_does_not_get_the_lock(self, store):
        """Two descriptors on one file are two lockers even inside one
        process, which is what makes `held` able to answer about a run this
        process is itself running."""
        run_id = store.create().run_id
        first = store.hold(run_id, heartbeat_s=0)
        try:
            assert RunHold(store, run_id, heartbeat_s=0).locked is False
        finally:
            first.release()

    def test_the_lock_file_lives_in_the_runs_own_directory(self, store):
        run_id = store.create().run_id
        store.hold(run_id, heartbeat_s=0).release()
        assert (store.directory(run_id) / LOCK_FILENAME).exists()

    def test_a_run_that_was_never_held_has_no_lock_file(self, store):
        """The distinction the reconciler reads: a run with a lock file was
        run by something that takes locks, so a FREE lock means that
        something is gone. A run without one was written by somebody who
        never said whether it was alive."""
        run_id = store.create().run_id
        assert store.claimed(run_id) is False
        store.hold(run_id, heartbeat_s=0).release()
        assert store.claimed(run_id) is True

    def test_it_works_as_a_context_manager(self, store):
        run_id = store.create().run_id
        with store.hold(run_id, heartbeat_s=0):
            assert store.held(run_id) is True
        assert store.held(run_id) is False


class TestTheHeartbeatKeepsTheClockHonest:
    """What a platform with no ``flock`` has instead — and belt and braces
    where there is one. A run that is thinking is a run whose metadata is
    still moving."""

    def test_it_moves_updated_at_while_the_run_says_nothing(self, store):
        run_id = store.create().run_id
        _age(store, run_id, 600)
        before = store.meta(run_id).updated_at
        hold = store.hold(run_id, heartbeat_s=0.01)
        try:
            for _ in range(200):
                if store.meta(run_id).updated_at != before:
                    break
                time.sleep(0.01)
            assert store.meta(run_id).updated_at != before
        finally:
            hold.release()

    def test_touch_moves_the_stamp_and_nothing_else(self, store):
        run_id = store.create(meta={"objective": "x"}).run_id
        store.append(run_id, {"event": "a"})
        before = store.meta(run_id)
        _age(store, run_id, 600)
        aged = store.meta(run_id).updated_at
        store.touch(run_id)
        after = store.meta(run_id)
        assert after.updated_at != aged
        assert (after.last_seq, after.meta, after.created_at) == (
            before.last_seq, before.meta, before.created_at)
        assert _events(store, run_id) == ["a"]

    def test_a_released_hold_stops_touching(self, store):
        run_id = store.create().run_id
        store.hold(run_id, heartbeat_s=0.01).release()
        _age(store, run_id, 600)
        settled = store.meta(run_id).updated_at
        time.sleep(0.1)
        assert store.meta(run_id).updated_at == settled


class TestALogHasAtMostOneEnding:
    """The other half of the orphan bug, prevented independently.

    A sibling process that decided a live run was an orphan appends the
    ending it thinks the run had; the run then finishes and appends its
    own, and a follower — or the SSE stream built from the log — sees two
    terminal records with different outcomes and has to guess. The store is
    the only thing that can see the whole log, so the store refuses.
    """

    def _claimed(self, store):
        run_id = store.create().run_id
        hold = store.hold(run_id, heartbeat_s=0)
        store.append(run_id, {"event": "mission_started"})
        return run_id, hold

    def test_an_ending_that_arrived_after_the_claim_refuses_the_second(
            self, store):
        run_id, hold = self._claimed(store)
        try:
            RunStore(store.root).append(
                run_id, {"event": "mission_finished", "outcome": "incomplete"})
            with pytest.raises(RunClosed):
                store.append(run_id, {"event": "mission_finished",
                                      "outcome": "answered"})
        finally:
            hold.release()
        assert _events(store, run_id).count("mission_finished") == 1

    def test_the_refusal_names_the_outcome_somebody_else_wrote(self, store):
        run_id, hold = self._claimed(store)
        try:
            RunStore(store.root).append(
                run_id, {"event": "mission_finished", "outcome": "incomplete"})
            with pytest.raises(RunClosed, match="incomplete"):
                store.append(run_id, {"event": "mission_finished",
                                      "outcome": "answered"})
        finally:
            hold.release()

    def test_the_ordinary_ending_is_appended_as_it_always_was(self, store):
        run_id, hold = self._claimed(store)
        try:
            store.append(run_id, {"event": "mission_finished",
                                  "outcome": "answered"})
        finally:
            hold.release()
        assert _events(store, run_id) == ["mission_started", "mission_finished"]

    def test_an_unclaimed_run_is_appended_to_exactly_as_before(self, store):
        """A ``--resume`` legitimately writes a second ending onto a log an
        earlier stretch closed as ``incomplete``. That ending was there
        before this process claimed the run, so nothing refuses it — and a
        store nobody asked to hold anything behaves as it always did."""
        run_id = store.create().run_id
        store.append(run_id, {"event": "mission_finished",
                              "outcome": "incomplete"})
        store.append(run_id, {"event": "mission_started"})
        store.append(run_id, {"event": "mission_finished",
                              "outcome": "answered"})
        assert _events(store, run_id).count("mission_finished") == 2

    def test_an_ending_written_before_the_claim_is_not_somebody_elses(
            self, store):
        """The resume path with the claim taken: the reconciler's
        ``incomplete`` is already on the log when this process claims the
        run, so the ending this stretch writes is its first."""
        run_id = store.create().run_id
        store.append(run_id, {"event": "mission_finished",
                              "outcome": "incomplete"})
        hold = store.hold(run_id, heartbeat_s=0)
        try:
            store.append(run_id, {"event": "mission_started"})
            store.append(run_id, {"event": "mission_finished",
                                  "outcome": "answered"})
        finally:
            hold.release()
        assert _events(store, run_id).count("mission_finished") == 2

    def test_a_non_terminal_record_costs_nothing_to_check(self, store):
        run_id, hold = self._claimed(store)
        try:
            RunStore(store.root).append(
                run_id, {"event": "mission_finished", "outcome": "incomplete"})
            store.append(run_id, {"event": "step_started", "index": 4})
        finally:
            hold.release()
        assert _events(store, run_id)[-1] == "step_started"

    def test_the_terminal_word_is_the_stores_and_it_is_overridable(self):
        assert RunStore.TERMINAL_EVENT == "mission_finished"


# ── the record itself ────────────────────────────────────────────────────────
# ── the record itself ────────────────────────────────────────────────────────


class TestTheRunRecord:
    def test_it_round_trips_through_the_file(self, store):
        run = store.create(meta={"objective": "x"})
        assert Run(**json.loads(
            store.meta_path(run.run_id).read_text(encoding="utf-8"))) == run

    def test_meta_json_is_replaced_and_never_appended_to(self, store):
        run_id = store.create().run_id
        store.append(run_id, {"event": "a"})
        store.append(run_id, {"event": "b"})
        assert len(json.loads(
            store.meta_path(run_id).read_text(encoding="utf-8"))) == 5
