# tests/test_control.py — the channel a platform steers a running mission by

"""Commands coming IN, and the three ways they must not go wrong.

`core/runtime/mission_stream.py` had one job — say what happened — and this
module has the harder one, because it takes bytes from outside the process
and acts on them. Three properties, and every test here is one of them:

**It cannot break the run.** A line that is not JSON, an object that is not a
command, a word nobody declares, an `inject` with nothing in it, a decision
signed by nobody: each is dropped with one sentence and the channel carries
on. A control channel that could kill a mission would be a worse lever than
no lever at all.

**It delivers to the right place.** `poll(only=…)` exists because the loop
drains mid-step looking for `cancel_step`, and an injection swallowed there
would be an operator's instruction the model was never shown — delivered to
nobody, with nothing saying so. `wait_for` keeps what it did not want for the
same reason.

**It decides nothing.** `cancel` is applied here because a stop must not wait
for the loop; everything else is queued for the loop to apply where it
chooses, and a `gate_decision` is a message this module carries, never a
verdict it reaches.

Real threads and real pipes throughout: the queue is crossed by a thread in
production, and a test that hand-fed the parser would prove nothing about the
thing that actually runs.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time

import pytest

from core.budgets import Cancellation
from core.runtime import control as ctl
from core.runtime.control import (
    CANCEL, CANCEL_STEP, COMMANDS, GATE_DECISION, INJECT, ControlChannel,
    parse_command,
)


def line(**payload) -> str:
    return json.dumps(payload) + "\n"


def channel(*lines, cancel=None, said=None):
    """A channel over a stream that already holds every line it will get.

    The reader thread runs for real and finishes at end-of-file, which is
    what a writer closing its end looks like.
    """
    said = [] if said is None else said
    return ControlChannel(io.StringIO("".join(lines)), cancel=cancel,
                          warn=said.append)


def settled(chan, want=1, seconds=2.0):
    """Wait until *want* commands have crossed the thread, or give up.

    Polling rather than sleeping a fixed amount: a fixed sleep is a test
    that passes on a fast machine and flakes on a loaded one.
    """
    got = []
    until = time.monotonic() + seconds
    while len(got) < want and time.monotonic() < until:
        got.extend(chan.poll())
        if len(got) < want:
            time.sleep(0.005)
    return got


def arrived(chan, seconds=2.0):
    """Wait until the reader has read everything and stopped.

    For the tests that must NOT poll first: `poll()` drains, so a test of
    `poll(only=…)` cannot use it to synchronise without eating the thing it
    is about to look for.
    """
    until = time.monotonic() + seconds
    while not chan.finished and time.monotonic() < until:
        time.sleep(0.005)
    return chan


def quiet(chan, seconds=0.3):
    """Everything the channel produces in *seconds*, which may be nothing."""
    until = time.monotonic() + seconds
    got = []
    while time.monotonic() < until:
        got.extend(chan.poll())
        time.sleep(0.005)
    return got


# ── the vocabulary is closed, and validated in one place ────────────────────


class TestTheVocabularyIsClosedAndChecked:
    def test_the_four_words_and_no_others(self):
        assert COMMANDS == ("inject", "cancel", "cancel_step",
                            "gate_decision")

    def test_an_inject_carries_its_text_and_nothing_else(self):
        command, complaint, _once = parse_command(
            {"control": "inject", "text": "look at the second corpus",
             "at": "2026-08-16T10:00:00Z", "who": "dana"})
        assert complaint == ""
        # `at` and `who` are IGNORED rather than carried: a field this
        # harness passes through without understanding is a field somebody
        # will one day expect it to act on.
        assert command == {"control": INJECT,
                           "text": "look at the second corpus"}

    def test_an_inject_with_no_text_is_refused(self):
        command, complaint, _once = parse_command({"control": "inject"})
        assert command is None and "no 'text'" in complaint

    def test_an_inject_of_whitespace_is_refused(self):
        command, complaint, _once = parse_command(
            {"control": "inject", "text": "   "})
        assert command is None and complaint

    def test_cancel_and_cancel_step_need_nothing(self):
        for word in (CANCEL, CANCEL_STEP):
            command, complaint, _once = parse_command({"control": word})
            assert (command, complaint) == ({"control": word}, "")

    def test_a_gate_decision_is_normalized_whole(self):
        command, complaint, _once = parse_command(
            {"control": "gate_decision", "approval_id": " ap_1 ",
             "approve": True, "decided_by": " dana ", "note": "ok by me",
             "at": "whenever"})
        assert complaint == ""
        assert command == {"control": GATE_DECISION, "approval_id": "ap_1",
                           "approve": True, "decided_by": "dana",
                           "note": "ok by me"}

    def test_a_gate_decision_with_no_approval_id_is_refused(self):
        command, complaint, _once = parse_command(
            {"control": "gate_decision", "approve": True,
             "decided_by": "dana"})
        assert command is None and "approval_id" in complaint

    @pytest.mark.parametrize("approve", ["yes", 1, None, "true"])
    def test_approve_must_be_a_real_boolean(self, approve):
        """There is no default. An omission would have to mean yes or no,
        and both readings are wrong."""
        command, complaint, _once = parse_command(
            {"control": "gate_decision", "approval_id": "ap_1",
             "approve": approve, "decided_by": "dana"})
        assert command is None and "approve" in complaint

    @pytest.mark.parametrize("who", ["", "   ", None, 7])
    def test_a_decision_signed_by_nobody_is_refused(self, who):
        """The same refusal `ApprovalStore.decide` makes, made one layer
        earlier so a waiting run keeps waiting for one it can record."""
        command, complaint, _once = parse_command(
            {"control": "gate_decision", "approval_id": "ap_1",
             "approve": True, "decided_by": who})
        assert command is None
        assert "decided_by" in complaint and "nobody" in complaint

    def test_an_unknown_word_is_refused_by_name_and_deduplicated(self):
        command, complaint, once = parse_command({"control": "pause"})
        assert command is None
        assert "'pause'" in complaint
        # A platform with a typo sends that typo on every command; a
        # hundred identical lines would bury the one that mattered.
        assert once == "word:pause"

    def test_something_that_is_not_an_object_at_all(self):
        command, complaint, _once = parse_command(["cancel"])
        assert command is None and "not a JSON object" in complaint

    def test_an_object_with_no_control_word(self):
        command, complaint, _once = parse_command({"text": "hello"})
        assert command is None and "no 'control' word" in complaint


# ── the thread, the queue, and what a bad line costs ────────────────────────


class TestTheReaderThread:
    def test_a_line_crosses_the_thread_and_arrives(self):
        chan = channel(line(control="inject", text="second corpus"))
        assert settled(chan) == [{"control": INJECT,
                                  "text": "second corpus"}]

    def test_the_order_they_were_sent_in_is_the_order_they_arrive(self):
        chan = channel(line(control="inject", text="one"),
                       line(control="inject", text="two"),
                       line(control="inject", text="three"))
        assert [c["text"] for c in settled(chan, want=3)] == \
            ["one", "two", "three"]

    def test_a_malformed_line_is_dropped_and_the_next_one_still_lands(self):
        """The whole point. A control channel that could crash a mission
        would be a worse lever than no lever."""
        said = []
        chan = channel("{not json at all\n",
                       line(control="inject", text="still here"),
                       said=said)
        assert [c["text"] for c in settled(chan)] == ["still here"]
        assert any("not JSON" in message for message in said)

    def test_every_malformed_line_says_so_once(self):
        said = []
        chan = channel("nonsense\n", "more nonsense\n",
                       line(control="inject", text="x"), said=said)
        settled(chan)
        assert len([m for m in said if "not JSON" in m]) == 2

    def test_one_unknown_word_is_reported_once_however_often_it_arrives(self):
        said = []
        chan = channel(*[line(control="pause")] * 5,
                       line(control="inject", text="x"), said=said)
        settled(chan)
        assert len([m for m in said if "'pause'" in m]) == 1

    def test_two_different_unknown_words_are_both_reported(self):
        said = []
        chan = channel(line(control="pause"), line(control="rewind"),
                       line(control="inject", text="x"), said=said)
        settled(chan)
        assert len([m for m in said if "unknown command" in m]) == 2

    def test_blank_lines_are_not_lines(self):
        said = []
        chan = channel("\n", "   \n", line(control="cancel_step"), said=said)
        assert settled(chan) == [{"control": CANCEL_STEP}]
        assert said == []

    def test_a_command_that_is_dropped_reaches_nobody(self):
        chan = channel(line(control="inject"), line(control="pause"))
        assert quiet(chan) == []

    def test_the_channel_says_when_the_writer_has_gone(self):
        chan = channel(line(control="cancel_step"))
        settled(chan)
        until = time.monotonic() + 2.0
        while not chan.finished and time.monotonic() < until:
            time.sleep(0.005)
        assert chan.finished


# ── cancel is applied here, because a stop must not wait for the loop ───────


class TestCancelIsThrownFromTheReader:
    def test_the_switch_is_thrown_without_the_loop_asking(self):
        """The same lever SIGTERM's handler pulls, reached by another road:
        a stop that waited for a drain point would be a stop the operator
        watches not happening while a model call is in flight."""
        switch = Cancellation()
        chan = channel(line(control="cancel"), cancel=switch)
        until = time.monotonic() + 2.0
        while not switch.is_set() and time.monotonic() < until:
            time.sleep(0.005)
        assert switch.is_set()

    def test_it_records_control_rather_than_sigterm_as_the_cause(self):
        """A platform asked the MISSION to stop, not the process to die of
        a signal nobody sent — `exit_as_signalled` must not fire."""
        from core.runtime.mission_stream import SIGTERM_CAUSE

        switch = Cancellation()
        chan = channel(line(control="cancel"), cancel=switch)
        until = time.monotonic() + 2.0
        while not switch.is_set() and time.monotonic() < until:
            time.sleep(0.005)
        assert switch.cause == ctl.CONTROL_CAUSE != SIGTERM_CAUSE

    def test_it_is_not_also_queued_for_the_loop(self):
        """One owner. A cancel the loop also had to interpret would be two
        places that decide what stopping means."""
        switch = Cancellation()
        chan = channel(line(control="cancel"), cancel=switch)
        assert quiet(chan) == []

    def test_a_bare_threading_event_works_too(self):
        event = threading.Event()
        chan = channel(line(control="cancel"), cancel=event)
        until = time.monotonic() + 2.0
        while not event.is_set() and time.monotonic() < until:
            time.sleep(0.005)
        assert event.is_set()

    def test_a_cancel_with_nothing_to_throw_says_so_instead_of_shrugging(self):
        said = []
        chan = channel(line(control="cancel"), said=said)
        until = time.monotonic() + 2.0
        while not said and time.monotonic() < until:
            time.sleep(0.005)
        assert any("no cancellation to throw" in m for m in said)


# ── poll and wait_for: taking only what you came for ────────────────────────


class TestPollAndWaitKeepWhatTheyDidNotWant:
    def test_poll_drains_everything_by_default(self):
        chan = channel(line(control="inject", text="a"),
                       line(control="cancel_step"))
        assert len(settled(chan, want=2)) == 2
        assert chan.poll() == []

    def test_poll_of_one_kind_leaves_the_others_where_they_were(self):
        """The mid-step drain. An injection swallowed here would be an
        instruction the model was never shown, with nothing saying so."""
        chan = arrived(channel(line(control="inject", text="a"),
                               line(control="cancel_step"),
                               line(control="inject", text="b")))
        assert chan.poll(only=(CANCEL_STEP,)) == [{"control": CANCEL_STEP}]
        assert [c["text"] for c in chan.poll()] == ["a", "b"]

    def test_wait_for_returns_the_matching_command(self):
        chan = channel(line(control="gate_decision", approval_id="ap_1",
                            approve=True, decided_by="dana"))
        found = chan.wait_for(
            lambda c: c.get("approval_id") == "ap_1", 2.0)
        assert found["approve"] is True and found["decided_by"] == "dana"

    def test_wait_for_keeps_the_commands_it_passed_over(self):
        chan = channel(line(control="inject", text="meanwhile"),
                       line(control="gate_decision", approval_id="ap_2",
                            approve=False, decided_by="dana"))
        found = chan.wait_for(lambda c: c.get("approval_id") == "ap_2", 2.0)
        assert found is not None
        assert [c["text"] for c in chan.poll()] == ["meanwhile"]

    def test_wait_for_ignores_a_decision_for_another_gate(self):
        chan = channel(line(control="gate_decision", approval_id="ap_other",
                            approve=True, decided_by="dana"))
        assert chan.wait_for(
            lambda c: c.get("approval_id") == "ap_mine", 0.3) is None

    def test_wait_for_gives_up_when_the_writer_has_gone(self):
        """Nothing is coming. Waiting out the whole window for a writer
        that closed would hold a person at a gate nobody can answer."""
        chan = channel()
        started = time.monotonic()
        assert chan.wait_for(lambda c: True, 30.0) is None
        assert time.monotonic() - started < 5.0

    def test_wait_for_gives_up_when_the_run_is_cancelled(self, tmp_path):
        switch = Cancellation()
        path = tmp_path / "ctl"
        os.mkfifo(path)
        chan = ControlChannel.open(str(path), cancel=switch)
        try:
            threading.Timer(0.05, lambda: switch.cancel("test")).start()
            started = time.monotonic()
            assert chan.wait_for(lambda c: True, 30.0) is None
            assert time.monotonic() - started < 5.0
        finally:
            chan.close()

    def test_a_command_that_arrives_late_is_still_waited_for(self, tmp_path):
        """A real pipe, written to after the wait began — which is the only
        arrangement the production one is ever in."""
        path = tmp_path / "ctl"
        os.mkfifo(path)
        chan = ControlChannel.open(str(path))
        try:
            def answer():
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(line(control="gate_decision",
                                      approval_id="ap_9", approve=True,
                                      decided_by="dana"))
            threading.Timer(0.05, answer).start()
            found = chan.wait_for(
                lambda c: c.get("approval_id") == "ap_9", 5.0)
            assert found is not None and found["decided_by"] == "dana"
        finally:
            chan.close()


# ── the three spec forms ────────────────────────────────────────────────────


class TestOpeningIt:
    def test_no_spec_is_no_channel(self):
        assert ControlChannel.open("") is None
        assert ControlChannel.open("   ") is None
        assert ControlChannel.open(None) is None

    def test_the_fd_form_reads_an_inherited_descriptor(self):
        """What a platform uses: the parent keeps the write end and the
        mission never has a path on disk to race anybody for."""
        read_fd, write_fd = os.pipe()
        os.write(write_fd, line(control="inject", text="over the pipe")
                 .encode())
        os.close(write_fd)
        chan = ControlChannel.open(f"fd:{read_fd}")
        try:
            assert [c["text"] for c in settled(chan)] == ["over the pipe"]
            assert chan.spec == f"fd:{read_fd}"
        finally:
            chan.close()

    def test_a_bad_fd_spec_says_so_at_the_door(self):
        with pytest.raises(ValueError) as exc:
            ControlChannel.open("fd:nine")
        assert "needs a number" in str(exc.value)

    def test_the_path_form_reads_a_file(self, tmp_path):
        path = tmp_path / "commands.ndjson"
        path.write_text(line(control="inject", text="from a file"),
                        encoding="utf-8")
        chan = ControlChannel.open(str(path))
        try:
            assert [c["text"] for c in settled(chan)] == ["from a file"]
        finally:
            chan.close()

    def test_a_path_that_is_not_there_is_refused_at_the_door(self, tmp_path):
        with pytest.raises(OSError):
            ControlChannel.open(str(tmp_path / "nope"))

    def test_a_fifo_opens_without_waiting_for_a_writer(self, tmp_path):
        """A plain read-only open of a FIFO BLOCKS until somebody opens the
        other end, so a mission whose platform connects a moment later
        would not start; and opening it before any writer and reading gives
        an immediate end-of-file, so the reader would finish before the
        first command was written. Neither happens."""
        path = tmp_path / "ctl"
        os.mkfifo(path)
        chan = ControlChannel.open(str(path))
        try:
            assert not chan.finished
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(line(control="inject", text="late"))
            assert [c["text"] for c in settled(chan)] == ["late"]
        finally:
            chan.close()

    def test_closing_it_twice_is_not_an_error(self, tmp_path):
        path = tmp_path / "ctl"
        os.mkfifo(path)
        chan = ControlChannel.open(str(path))
        chan.close()
        chan.close()
        assert chan.closed
