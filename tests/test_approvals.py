# tests/test_approvals.py — the durable half of a gate

"""A gate that cannot be answered is not a gate, it is a stop.

The ask half has been in `core/runtime/mission.py` since 0.7 and these tests
are the other half: the request becomes a file, the decision is a write from
outside the run, and the one thing an approval does — widen a closed set by
one tool for one run — happens once and never by accident.

Every refusal here is an assertion that something did **not** happen: an
undecided request did not become a yes, a spent one did not become a second
yes, a decision signed by nobody was not recorded, and a restart sweeping the
directory refused rather than granted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.runtime import approvals as ap
from core.runtime.approvals import (
    ABANDONED, APPROVED, PENDING, REFUSED, SPENT,
    AlreadyDecided, AlreadySpent, ApprovalStore, NoDecider, NoSuchApproval,
    NotApproved, approvals_root, default_approval_store, resolve,
)


@pytest.fixture
def store(tmp_path):
    return ApprovalStore(tmp_path / "approvals")


def _asked(store, **kw):
    kw.setdefault("tool", "mcp.cancel_job")
    kw.setdefault("arguments", {"job": "j-91"})
    return store.request(**kw)


class TestTheRequest:
    def test_a_request_is_a_pending_file_on_disk(self, store):
        approval_id = _asked(store, objective="wind down j-91", run_id="r1")

        path = store.root / f"{approval_id}.json"
        assert path.exists()
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["state"] == PENDING
        assert body["tool"] == "mcp.cancel_job"
        assert body["arguments"] == {"job": "j-91"}
        assert body["objective"] == "wind down j-91"
        assert body["run_id"] == "r1"
        assert body["decided_by"] == ""
        assert body["decided_at"] == ""

    def test_the_file_says_why_it_exists_to_whoever_opens_it(self, store):
        """The record is read by a person deciding, sometimes days later and
        in a directory listing rather than in this repository."""
        approval_id = _asked(store)
        body = json.loads((store.root / f"{approval_id}.json").read_text())
        assert "will not happen unless somebody decides" in body["why_gated"]

    def test_the_arguments_are_verbatim(self, store):
        """What a person approves has to be the bytes that were proposed. A
        rewritten argument approved here is a different call."""
        approval_id = _asked(store, arguments={"path": "/etc/hosts",
                                               "force": True, "count": 3})
        assert store.get(approval_id).arguments == {
            "path": "/etc/hosts", "force": True, "count": 3}

    def test_ids_are_unique_per_request(self, store):
        assert len({_asked(store) for _ in range(8)}) == 8

    def test_two_requests_are_two_files(self, store):
        _asked(store)
        _asked(store)
        assert len(list(store.root.glob("ap_*.json"))) == 2


class TestNoCredentialReachesTheRecord:
    """The record outlives the run and is read by whoever is deciding.

    Arguments stay verbatim — that is the point of the record — but the free
    text around them is a sentence somebody typed, and sentences people type
    are where pasted tokens live. Same pass, same owner as the audit log.
    """

    def test_a_token_pasted_into_the_objective_is_not_written_down(self, store):
        approval_id = _asked(
            store,
            objective="retry with OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx")

        raw = (store.root / f"{approval_id}.json").read_text(encoding="utf-8")
        assert "sk-abcdefghijklmnopqrstuvwx" not in raw
        assert "retry with" in raw

    def test_a_token_in_the_note_is_not_written_down(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=False, decided_by="dana",
                     note="use ghp_abcdefghijklmnopqrstuvwxyz0123456789 next")

        raw = (store.root / f"{approval_id}.json").read_text(encoding="utf-8")
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in raw

    def test_this_process_env_credential_is_not_copied_in(self, store, monkeypatch):
        """The store reads nothing from the environment, and a value it was
        handed anyway is scrubbed by the same pass."""
        monkeypatch.setenv("MCP_TOKEN", "s3cr3t-token-value-0192837465")
        approval_id = _asked(
            store,
            objective="the server wanted s3cr3t-token-value-0192837465")

        raw = (store.root / f"{approval_id}.json").read_text(encoding="utf-8")
        assert "s3cr3t-token-value-0192837465" not in raw
        assert "the server wanted" in raw


class TestTheDecision:
    def test_a_decision_must_name_a_decider(self, store):
        approval_id = _asked(store)
        with pytest.raises(NoDecider) as exc:
            store.decide(approval_id, approve=True, decided_by="")
        assert "decided_by" in str(exc.value)
        assert store.get(approval_id).state == PENDING

    def test_whitespace_is_not_a_decider(self, store):
        approval_id = _asked(store)
        with pytest.raises(NoDecider):
            store.decide(approval_id, approve=True, decided_by="   ")
        assert store.get(approval_id).state == PENDING

    def test_approving_records_who_and_when(self, store):
        approval_id = _asked(store)
        decided = store.decide(approval_id, approve=True, decided_by="dana",
                               note="queue is drained")

        assert decided.state == APPROVED
        assert decided.decided_by == "dana"
        assert decided.decided_at
        assert decided.note == "queue is drained"
        assert store.get(approval_id).state == APPROVED

    def test_refusing_records_the_no(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=False, decided_by="dana",
                     note="the lease is shared")
        assert store.get(approval_id).state == REFUSED

    def test_a_refusal_stays_refused(self, store):
        """Nobody gets to ask twice until they get the answer they wanted."""
        approval_id = _asked(store)
        store.decide(approval_id, approve=False, decided_by="dana")
        with pytest.raises(AlreadyDecided) as exc:
            store.decide(approval_id, approve=True, decided_by="sam")
        assert "refused" in str(exc.value)
        assert store.get(approval_id).state == REFUSED
        assert store.get(approval_id).decided_by == "dana"

    def test_an_approval_is_answered_once(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")
        with pytest.raises(AlreadyDecided):
            store.decide(approval_id, approve=False, decided_by="dana")
        assert store.get(approval_id).state == APPROVED

    def test_deciding_something_that_does_not_exist(self, store):
        with pytest.raises(NoSuchApproval):
            store.decide("ap_deadbeefdeadbeef", approve=True, decided_by="dana")


class TestSpending:
    def test_an_approval_is_consumed_exactly_once(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")

        spent = store.consume(approval_id)
        assert spent.state == SPENT
        assert spent.spent_at
        with pytest.raises(AlreadySpent):
            store.consume(approval_id)

    def test_a_pending_request_cannot_be_consumed(self, store):
        """The last place before a gated tool is actually called, and pending
        is not approved here any more than anywhere else."""
        approval_id = _asked(store)
        with pytest.raises(NotApproved) as exc:
            store.consume(approval_id)
        assert "pending" in str(exc.value)
        assert store.get(approval_id).state == PENDING

    def test_a_refused_request_cannot_be_consumed(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=False, decided_by="dana")
        with pytest.raises(NotApproved):
            store.consume(approval_id)


class TestAbandonIsARefusal:
    def test_abandoning_resolves_as_a_refusal_and_says_why(self, store):
        approval_id = _asked(store)
        abandoned = store.abandon(approval_id)

        assert abandoned.state == ABANDONED
        assert "nothing was done" in abandoned.note
        # And it is not a route to a yes.
        with pytest.raises(NotApproved):
            store.consume(approval_id)

    def test_an_abandoned_request_cannot_then_be_decided(self, store):
        approval_id = _asked(store)
        store.abandon(approval_id)
        with pytest.raises(AlreadyDecided):
            store.decide(approval_id, approve=True, decided_by="dana")

    def test_a_persons_answer_is_not_overwritten_by_a_restart(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")
        assert store.abandon(approval_id).state == APPROVED


class TestThePendingQueue:
    def test_only_pending_records_are_listed(self, store):
        waiting = _asked(store)
        answered = _asked(store)
        store.decide(answered, approve=True, decided_by="dana")

        assert [a.approval_id for a in store.pending()] == [waiting]

    def test_an_empty_or_absent_directory_is_an_empty_queue(self, tmp_path):
        assert ApprovalStore(tmp_path / "never-written").pending() == []

    def test_one_unreadable_file_does_not_hide_the_others(self, store):
        waiting = _asked(store)
        (store.root / "ap_notjson.json").write_text("{ this is not", encoding="utf-8")
        assert [a.approval_id for a in store.pending()] == [waiting]


class TestReconcile:
    def test_a_pending_request_whose_run_is_gone_is_abandoned(self, store):
        orphan = _asked(store, run_id="r-dead")
        alive = _asked(store, run_id="r-alive")

        abandoned = store.reconcile(["r-alive"])

        assert [a.approval_id for a in abandoned] == [orphan]
        assert store.get(orphan).state == ABANDONED
        assert store.get(alive).state == PENDING

    def test_reconciling_refuses_rather_than_grants(self, store):
        orphan = _asked(store, run_id="r-dead")
        store.reconcile([])
        with pytest.raises(NotApproved):
            resolve(store, orphan)

    def test_a_decided_request_is_left_alone(self, store):
        approval_id = _asked(store, run_id="r-dead")
        store.decide(approval_id, approve=True, decided_by="dana")
        assert store.reconcile([]) == []
        assert store.get(approval_id).state == APPROVED

    def test_a_request_that_named_no_run_is_left_alone(self, store):
        """Reconciliation asks whether the run that asked is still there. A
        library caller's record never named one, and the first restart to
        sweep the directory must not refuse it on those grounds."""
        approval_id = _asked(store, run_id="")
        assert store.reconcile(["r-alive"]) == []
        assert store.get(approval_id).state == PENDING


class TestIdsArePathSafe:
    """The id arrives on a command line from whoever is holding one."""

    @pytest.mark.parametrize("bad", [
        "../../etc/passwd", "ap_../../etc/passwd", "ap_a/b", "",
        "ap_", "nope", "ap_has-a-dash", "ap_dot.json",
    ])
    def test_an_id_that_is_not_one_this_store_wrote_is_no_such_approval(
            self, store, bad):
        with pytest.raises(NoSuchApproval):
            store.get(bad)

    def test_an_absolute_id_does_not_reach_a_record_outside_the_root(
            self, store, tmp_path):
        """The one that bites.

        `root / name` with an absolute *name* is the absolute path — that is
        what `pathlib` does — so an id from a command line is a way to name
        any file on the host. Planted here as a **valid** approval so that an
        unchecked store would read it happily and answer with somebody else's
        decision, rather than merely missing a file.
        """
        planted = tmp_path / "victim.json"
        planted.write_text(json.dumps({
            "approval_id": "ap_victim0000000", "tool": "rm_rf",
            "state": APPROVED, "decided_by": "nobody"}), encoding="utf-8")

        with pytest.raises(NoSuchApproval):
            store.get(str(tmp_path / "victim"))

    def test_a_traversing_id_reads_nothing_and_writes_nothing(
            self, store, tmp_path):
        victim = tmp_path / "victim.json"
        original = json.dumps({"approval_id": "ap_victim0000000",
                               "tool": "rm_rf", "state": PENDING})
        victim.write_text(original, encoding="utf-8")
        with pytest.raises(NoSuchApproval):
            store.decide(str(tmp_path / "victim"), approve=True,
                         decided_by="dana")
        assert victim.read_text(encoding="utf-8") == original


class TestResolvingATicket:
    def test_no_id_is_no_ticket(self, store):
        assert resolve(store, "") is None
        assert resolve(store, "   ") is None
        assert resolve(None, "") is None

    def test_an_approved_record_becomes_a_ticket_for_one_tool(self, store):
        approval_id = _asked(store, tool="mcp.cancel_job")
        store.decide(approval_id, approve=True, decided_by="dana")

        ticket = resolve(store, approval_id)
        assert ticket.tool == "mcp.cancel_job"
        assert ticket.decided_by == "dana"
        assert ticket.spent is False

    @pytest.mark.parametrize("state,arrange", [
        (PENDING, lambda s, i: None),
        (REFUSED, lambda s, i: s.decide(i, approve=False, decided_by="dana")),
        (SPENT, lambda s, i: (s.decide(i, approve=True, decided_by="dana"),
                              s.consume(i))),
        (ABANDONED, lambda s, i: s.abandon(i)),
    ])
    def test_every_other_state_is_refused_and_named(self, store, state, arrange):
        approval_id = _asked(store)
        arrange(store, approval_id)
        with pytest.raises(NotApproved) as exc:
            resolve(store, approval_id)
        assert state in str(exc.value)

    def test_a_store_that_keeps_nothing_cannot_resolve_anything(self):
        with pytest.raises(NotApproved) as exc:
            resolve(None, "ap_deadbeefdeadbeef")
        assert ap.APPROVALS_ENV in str(exc.value)


class TestTheTicket:
    def test_widening_removes_exactly_one_name(self, store):
        approval_id = _asked(store, tool="b")
        store.decide(approval_id, approve=True, decided_by="dana")
        ticket = resolve(store, approval_id)

        assert ticket.widen(["a", "b", "c"]) == ["a", "c"]

    def test_spending_is_idempotent_and_marks_the_record_once(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")
        ticket = resolve(store, approval_id)

        ticket.spend()
        first = store.get(approval_id).spent_at
        ticket.spend()                       # a run that called it twice
        assert ticket.spent is True
        assert store.get(approval_id).state == SPENT
        assert store.get(approval_id).spent_at == first

    def test_a_spent_record_is_not_a_second_yes(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")
        resolve(store, approval_id).spend()

        with pytest.raises(NotApproved) as exc:
            resolve(store, approval_id)
        assert SPENT in str(exc.value)


class TestWhereTheFilesGo:
    def test_unset_is_the_default_directory_and_never_disabled(self, monkeypatch):
        monkeypatch.delenv(ap.APPROVALS_ENV, raising=False)
        assert approvals_root() == Path.cwd() / ap.APPROVALS_DIRNAME
        monkeypatch.setenv(ap.APPROVALS_ENV, "   ")
        assert approvals_root() == Path.cwd() / ap.APPROVALS_DIRNAME

    @pytest.mark.parametrize("word", ["none", "off", "NONE", "Off"])
    def test_the_two_words_turn_persistence_off(self, monkeypatch, word):
        monkeypatch.setenv(ap.APPROVALS_ENV, word)
        assert approvals_root() is None
        assert default_approval_store() is None

    def test_a_path_moves_the_directory(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ap.APPROVALS_ENV, str(tmp_path / "elsewhere"))
        store = default_approval_store()
        approval_id = _asked(store)
        assert (tmp_path / "elsewhere" / f"{approval_id}.json").exists()

    def test_constructing_a_store_is_a_decision_to_keep_records(self, monkeypatch):
        """`ApprovalStore()` with the disable word set still has a directory:
        disabling is `default_approval_store`'s answer and it says so by
        returning nothing at all, not by handing back a store nothing writes
        to."""
        monkeypatch.setenv(ap.APPROVALS_ENV, "off")
        assert ApprovalStore().root == Path.cwd() / ap.APPROVALS_DIRNAME

    def test_a_store_nobody_wrote_to_leaves_no_directory(self, tmp_path):
        ApprovalStore(tmp_path / "unused")
        assert not (tmp_path / "unused").exists()


class TestTheWriteIsAtomic:
    def test_no_temporary_file_survives_a_write(self, store):
        approval_id = _asked(store)
        store.decide(approval_id, approve=True, decided_by="dana")
        assert [p.name for p in store.root.iterdir()] == [f"{approval_id}.json"]

    def test_a_failed_write_leaves_no_half_record(self, store, monkeypatch):
        approval_id = _asked(store)

        def _boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(OSError):
            store.decide(approval_id, approve=True, decided_by="dana")
        monkeypatch.undo()

        # The previous record is intact and nothing was left staged beside it.
        assert store.get(approval_id).state == PENDING
        assert [p.name for p in store.root.iterdir()] == [f"{approval_id}.json"]
