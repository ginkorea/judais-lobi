# tests/test_cognition_replay.py — the log is the state, and closure is incremental

"""Three claims the kernel makes that reading its answers cannot check.

**That the event log is the state.**  Indexes, derivations, revisions and
contradictions are a cache of the log; the log is the record.  So the strong
form is asserted here: seeded pseudo-random sequences of every mutating call,
snapshotted, replayed into a fresh store, and the two stores compared whole —
:meth:`~core.cognition.state.CognitiveState.digest` and the frontier both.  A
property test rather than a worked example, because the interesting divergence
is always a combination nobody thought to write down.

**That replay is exact rather than best-effort.**  The wire contract tells a
consumer to drop record types it does not know, and that rule is right for a
consumer.  It is wrong here: a store rebuilt from a log with one event skipped
is a store nobody can name, and everything downstream would derive from it in
good faith.  So an unknown op is refused, and an unversioned snapshot with it.

**That closure is semi-naive.**  A naive engine returns exactly the same
propositions, so no assertion about the answer can tell the two apart.
:class:`~core.cognition.types.MatchStats` can, and the incrementality tests
read it: forty-one rules in the store, one field in the delta, and the count
of rules the engine looked at.

**That the digest still renders everything.**  Every replay assertion in this
file compares digests, which makes
:meth:`~core.cognition.state.CognitiveState.digest` the one place where
*narrowing* is invisible — drop a field and the comparisons still match and
prove strictly less.  :data:`~core.cognition.state.DIGEST_KEYS` is pinned as
literals here for that reason.

The package's standing constraints — no I/O, no clock, no import of
:mod:`core.runtime` — are asserted at the bottom against the source, because
they are the reason the shadow-attachment lane can depend on this package and
not the other way round.
"""

import ast
import random
import re
from pathlib import Path

import pytest

from core.cognition import (COUNT_KEY, DIGEST_KEYS, EVENT_OPS,
                            EVENT_SCHEMA_VERSION, EVENTS_KEY, KERNEL_KEY,
                            KERNEL_VERSION, SCHEMA_KEY, CognitiveState,
                            EvidenceAuthority, EvidenceRef, ReplayRefused,
                            RuleAuthority, deep_copy, freeze)
from core.cognition.state import ENV_CAP

PACKAGE = Path(__file__).resolve().parent.parent / "core" / "cognition"

RECEIPT = EvidenceRef(kind="receipt", locator="seq:1")
OTHER = EvidenceRef(kind="receipt", locator="seq:2")
GUESS = EvidenceRef(kind="extraction", locator="turn:1")


def json_round_trip(value):
    """Through a real encoder and back, the way a log actually travels."""
    import json

    return json.loads(json.dumps(value))


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

class TestEveryWriteIsOneEvent:
    def test_each_mutating_call_appends_exactly_one(self):
        state = CognitiveState()
        counts = []
        rid = state.add_rule("controls", ("?a", "controls", "?c"),
                             [("?a", "admin_access", "?c")])
        counts.append(len(state.events))
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        counts.append(len(state.events))
        pid = state.assert_observation(("alice", "admin_access", "acct-9"),
                                       evidence=[RECEIPT])
        counts.append(len(state.events))
        state.assert_hypothesis(("alice", "risky", True), evidence=[GUESS])
        counts.append(len(state.events))
        state.add_goal(("?who", "controls", "acct-9"))
        counts.append(len(state.events))
        state.derive()
        counts.append(len(state.events))
        state.refute(pid, evidence=[OTHER])
        counts.append(len(state.events))
        assert counts == [1, 2, 3, 4, 5, 6, 7]

    def test_the_ops_are_the_published_set(self):
        """Every op exercised in one store, so a name added to `EVENT_OPS`
        without a caller — or a caller writing an op nobody published — is a
        failure here rather than a `ReplayRefused` in somebody's session."""
        state = CognitiveState()
        state.declare_field("admin_access", "one")
        rid = state.add_rule("controls", ("?a", "controls", "?c"),
                             [("?a", "admin_access", "?c")])
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        pid = state.assert_observation(("alice", "admin_access", "acct-9"),
                                       evidence=[RECEIPT])
        state.assert_hypothesis(("alice", "risky", True), evidence=[GUESS])
        state.add_goal(("?who", "controls", "acct-9"))
        state.derive()
        other = state.assert_observation(("alice", "admin_access", "acct-1"),
                                         evidence=[OTHER])
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        state.settle(clash.id, keep=other, evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        assert {event["op"] for event in state.events} == set(EVENT_OPS)
        assert [event["n"] for event in state.events] == \
            list(range(1, len(state.events) + 1))

    def test_a_refused_call_writes_nothing(self):
        """A log with a refusal in it would replay into a store that accepted
        it, which is the one way this design could smuggle the walls open."""
        state = CognitiveState()
        with pytest.raises(Exception):
            state.assert_observation(("alice", "role", "admin"))
        with pytest.raises(Exception):
            state.add_rule("bare", ("a", "b", "c"), [])
        with pytest.raises(Exception):
            state.promote_rule("r9", RuleAuthority.SYSTEM)
        assert state.events == ()

    def test_a_flush_with_nothing_staged_writes_nothing(self):
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        state.derive()
        before = len(state.events)
        for _ in range(3):
            state.derive()
        assert len(state.events) == before

    @staticmethod
    def _two_timings(read_in_the_middle):
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        if read_in_the_middle:
            state.frontier()
        state.assert_observation(("bob", "admin_access", "acct-1"),
                                 evidence=[OTHER])
        state.derive()
        return state

    def test_a_read_with_work_outstanding_writes_one_derive(self):
        """The price of the implicit flush, pinned rather than wished away:
        **when somebody reads is part of what the log says.**

        Two callers issuing identical writes, one reading the frontier
        between them and one not, keep logs of different length. Each log
        replays to its own store exactly — that is the property the sweep
        above proves, and it is not weakened here. What is *not* true is that
        the two stores are the same store.
        """
        watched = self._two_timings(True)
        unwatched = self._two_timings(False)
        assert len(watched.events) == len(unwatched.events) + 1
        assert [e["op"] for e in watched.events].count("derive") == 2
        assert [e["op"] for e in unwatched.events].count("derive") == 1

    def test_and_the_timing_reaches_the_ids_as_well_as_the_log(self):
        """Further than the log, and this is the sharp end of it.

        Ids are assigned by insertion order, and an early flush inserts a
        *derived* proposition before the next observation arrives. So the
        same writes read at different moments hold the same claims under
        different names: `p2` is bob's observation in one store and alice's
        conclusion in the other. Anything that carries a proposition id
        across two runs — a cached obligation, a diff of two transcripts, an
        id written into a record somewhere else — is carrying something that
        only means anything inside one store's own history.
        """
        watched = self._two_timings(True)
        unwatched = self._two_timings(False)
        assert watched.digest_json() != unwatched.digest_json()
        assert [(p.triple, p.status) for p in watched.propositions()] != \
               [(p.triple, p.status) for p in unwatched.propositions()], \
            "the difference is the order ids were handed out in"

    def test_what_the_timing_does_not_reach_is_what_is_believed(self):
        """And the half that holds: the same writes give the same claims with
        the same statuses and the same proofs, whoever read and whenever.
        Content is a fact about the world; ids are a fact about this store's
        history. Obligation ids are content-addressed for exactly this
        reason, so the frontier survives the difference intact."""
        watched = self._two_timings(True)
        unwatched = self._two_timings(False)
        assert {(p.triple, p.status) for p in watched.propositions()} == \
               {(p.triple, p.status) for p in unwatched.propositions()}
        watched.add_goal(("?who", "controls", "acct-1"))
        unwatched.add_goal(("?who", "controls", "acct-1"))
        assert [o.id for o in watched.frontier()] == \
               [o.id for o in unwatched.frontier()]

    def test_the_staging_area_is_visible_before_a_read_clears_it(self):
        """Which is why `pending()` is public: the implicit flush is
        otherwise something a caller can only find out about afterwards."""
        state = CognitiveState()
        pid = state.assert_observation(("alice", "admin_access", "acct-9"),
                                       evidence=[RECEIPT])
        assert state.has_pending
        assert state.pending() == {"propositions": (pid,), "rules": ()}
        state.derive()
        assert not state.has_pending

    def test_reading_does_not_grow_the_log(self):
        """Reads flush, so a read *can* write a `derive` — once. A log that
        grew with every `frontier()` call would make the record a fact about
        how often somebody looked rather than about when."""
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        state.frontier()
        settled = len(state.events)
        for _ in range(3):
            state.frontier()
            state.contradictions()
            state.propositions()
            state.digest()
        assert len(state.events) == settled

    def test_the_snapshot_states_its_own_version(self):
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        snapshot = state.snapshot()
        assert snapshot[SCHEMA_KEY] == EVENT_SCHEMA_VERSION
        assert [event["op"] for event in snapshot[EVENTS_KEY]] == \
            ["assert_observation", "derive"]

    def test_the_snapshot_flushes_first(self):
        """A snapshot is the one read whose whole purpose is to be handed
        somewhere else. Taken with work outstanding it would replay into a
        store that did that work on its reader's first question — correct,
        and one more place where "when did somebody read" decides what a log
        looks like."""
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        assert state.has_pending
        state.snapshot()
        assert not state.has_pending
        assert state.pending() == {"propositions": (), "rules": ()}

    def test_that_version_is_the_kernels_own_number(self):
        """Not the wire contract's. They change for different reasons and at
        different rates, and one number would have made every kernel
        experiment a wire break — while the kernel is the part meant to be
        replaced. Asserted as *independence*: this constant is assigned in
        this package, not derived from the other one, so the two can move
        apart without either knowing."""
        source = (PACKAGE / "events.py").read_text(encoding="utf-8")
        assigned = re.search(r"^EVENT_SCHEMA_VERSION\s*=\s*(\d+)\s*$",
                             source, re.MULTILINE)
        assert assigned, "the event schema version is not a literal here"
        assert int(assigned.group(1)) == EVENT_SCHEMA_VERSION
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        assert not re.search(r"^\s*(from|import)\s+core\.runtime", code,
                             re.MULTILINE)

    def test_the_events_a_reader_gets_cannot_be_edited(self):
        """Read-only views rather than copies. Copying the whole log to
        answer a question about it is fine once and quadratic for the reader
        this exists for — one that reads after every write — and a view is
        free and cannot be written through, which was the only thing the
        copy was buying."""
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        with pytest.raises(TypeError):
            state.events[0]["op"] = "nonsense"
        assert state.events[0]["op"] == "assert_observation"

    def test_a_snapshot_shares_no_nested_object_with_the_store(self):
        """A shallow copy is a forgery waiting to happen. An event is a dict
        of plain data — but its `evidence` is a list of dicts and its `body`
        is a list of lists, and `dict(event)` stops at the top. So editing a
        snapshot edited the store's own record through the copy it had just
        been handed, and it looks exactly like reading."""
        state = CognitiveState()
        rid = state.add_rule("controls", ("?a", "controls", "?c"),
                             [("?a", "admin_access", "?c")],
                             RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        snapshot = state.snapshot()

        for event in snapshot[EVENTS_KEY]:
            if event["op"] == "assert_observation":
                event["evidence"][0]["kind"] = "forged"
                event["triple"][0] = "mallory"
            if event["op"] == "add_rule":
                event["body"][0][1] = "forged_field"

        assert state.proposition(
            state.claim(("alice", "admin_access", "acct-9"))
        ).evidence[0].kind == "receipt"
        assert state.rule(rid).body[0][1] == "admin_access"
        assert CognitiveState.replay(state.snapshot()).digest_json() == \
            state.digest_json()

    def test_the_live_log_is_read_only_to_the_leaves(self):
        """`MappingProxyType` froze the outermost mapping and nothing under
        it, so `events[0]["evidence"].append(...)` wrote straight through."""
        state = CognitiveState()
        rid = state.add_rule("controls", ("?a", "controls", "?c"),
                             [("?a", "admin_access", "?c")],
                             RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        assertion, = [e for e in state.events
                      if e["op"] == "assert_observation"]
        rule_event, = [e for e in state.events if e["op"] == "add_rule"]

        with pytest.raises((AttributeError, TypeError)):
            assertion["evidence"].append({"kind": "forged", "locator": "x"})
        with pytest.raises((AttributeError, TypeError)):
            assertion["evidence"][0]["kind"] = "forged"
        with pytest.raises((AttributeError, TypeError)):
            rule_event["body"][0][1] = "forged_field"

        assert state.rule(rid).body[0][1] == "admin_access"
        assert len(assertion["evidence"]) == 1

    def test_the_two_doors_of_the_copy_owner_agree_about_content(self):
        """One walk, two doors — and the graph lane imports them, so what
        they do to a record has to be the same thing said two ways."""
        record = {"op": "x", "evidence": [{"kind": "receipt"}],
                  "body": [["?a", "f", "?c"]], "n": 1, "text": None}
        mutable, frozen = deep_copy(record), freeze(record)
        mutable["evidence"][0]["kind"] = "edited"
        assert record["evidence"][0]["kind"] == "receipt"
        assert frozen["evidence"][0]["kind"] == "receipt"
        assert frozen["body"] == (("?a", "f", "?c"),)
        with pytest.raises((AttributeError, TypeError)):
            frozen["evidence"][0]["kind"] = "edited"

    def test_a_consumer_reads_forward_from_a_cursor(self):
        """The loop is BOUNDED, and that is a lesson rather than a style.

        An earlier version of this test was `while True: ... if not fresh:
        break`, which is the natural way to write a cursor drain and the
        wrong way to write a *test*. Under a mutation where `events_since`
        ignores its cursor, the drain never ends and `seen` grows by the
        whole log every pass — the process took the host's memory to 44 GB
        and was killed three times before the pattern was read. A test that
        hangs has not failed: nobody gets a red line, the run dies, and the
        mutation it was supposed to catch is scored as uncaught.

        So every iteration must make provable progress, and the bound is one
        more than the number of events there are.
        """
        state = _script(12)
        total = len(state.events)
        seen, cursor = [], 0
        for _ in range(total + 1):
            fresh = state.events_since(cursor)
            if not fresh:
                break
            assert fresh[0]["n"] == cursor + 1, \
                "events_since ignored its cursor and handed back the log"
            seen.extend(fresh)
            cursor = fresh[-1]["n"]
        else:
            raise AssertionError(
                f"the drain did not finish in {total + 1} reads; a cursor "
                "that does not advance is an unbounded loop, not a slow one")
        assert [event["n"] for event in seen] == \
            [event["n"] for event in state.events]
        assert state.events_since(total) == ()

    def test_a_cursor_is_not_negative(self):
        with pytest.raises(Exception):
            CognitiveState().events_since(-1)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _script(seed, steps=60):
    """A seeded pseudo-random sequence of writes against one store.

    Deliberately not a curated example. The divergences worth finding in a
    replay are combinations — a hypothesis promoted by a later observation
    whose conclusion is then contested by a third fact — and nobody writes
    those down in advance.
    """
    rng = random.Random(seed)
    state = CognitiveState()
    actors = ["alice", "bob", "carol"]
    accounts = ["acct-1", "acct-9"]
    fields = ["admin_access", "payment_link", "owns", "delegate"]
    # Two fields declared single-valued, so the sweep still reaches the
    # collision machinery; the other two left alone, so it also covers a
    # store where two values of one field sit side by side without comment.
    state.declare_field("admin_access", "one")
    state.declare_field("flagged", "one")
    state.add_rule("controls", ("?a", "controls", "?c"),
                   [("?a", "admin_access", "?c"), ("?a", "payment_link", "?c")],
                   RuleAuthority.DOMAIN)
    proposed = state.add_rule("by_owner", ("?a", "controls", "?c"),
                              [("?a", "owns", "?c")])
    state.add_rule("risky", ("?a", "risky", "?c"),
                   [("?a", "controls", "?c"), ("?c", "flagged", True)],
                   RuleAuthority.SYSTEM)
    promoted = False
    for _ in range(steps):
        choice = rng.randrange(8)
        if choice < 4:
            state.assert_observation(
                (rng.choice(actors), rng.choice(fields), rng.choice(accounts)),
                evidence=[rng.choice([RECEIPT, OTHER])])
        elif choice == 4:
            state.assert_observation((rng.choice(accounts), "flagged",
                                      rng.choice([True, False])),
                                     evidence=[RECEIPT])
        elif choice == 5:
            state.assert_hypothesis(
                (rng.choice(actors), rng.choice(fields), rng.choice(accounts)),
                evidence=[GUESS])
        elif choice == 6:
            open_clashes = [c for c in state.contradictions()
                            if c.kind == "value" and not c.settled]
            if open_clashes and rng.random() < 0.5:
                clash = rng.choice(open_clashes)
                state.settle(clash.id,
                             keep=rng.choice([clash.left, clash.right]),
                             evidence=[RECEIPT])
            else:
                held = [p.id for p in state.propositions()]
                if held:
                    state.refute(rng.choice(held), evidence=[OTHER])
        else:
            if not promoted and rng.random() < 0.5:
                state.promote_rule(proposed, RuleAuthority.SKILL)
                promoted = True
            else:
                state.add_goal((rng.choice(["?who"] + actors), "controls",
                                rng.choice(accounts)))
        if rng.random() < 0.3:
            state.derive()
    state.add_goal(("?who", "risky", "acct-9"))
    state.derive()
    return state


class TestAStoreIsExactlyItsLog:
    @pytest.mark.parametrize("seed", range(12))
    def test_replay_reconstructs_the_whole_store(self, seed):
        state = _script(seed)
        again = CognitiveState.replay(state.snapshot())
        assert again.digest_json() == state.digest_json()

    @pytest.mark.parametrize("seed", range(12))
    def test_replay_reconstructs_the_frontier(self, seed):
        """The digest is the store; the frontier is what the store *says to
        do*, and it is computed rather than stored. Equal digests would not
        catch an obligation walk that had become order-dependent on something
        the digest does not carry."""
        state = _script(seed)
        again = CognitiveState.replay(state.snapshot())
        assert [(o.id, o.state, o.depends_on) for o in again.frontier()] == \
               [(o.id, o.state, o.depends_on) for o in state.frontier()]
        first = state.next_obligation()
        assert (first.id if first else None) == \
            (again.next_obligation().id if again.next_obligation() else None)

    @pytest.mark.parametrize("seed", range(6))
    def test_the_script_is_worth_replaying(self, seed):
        """A property test over an empty store proves nothing. This pins that
        the generator reaches derivations, contradictions and a frontier."""
        digest = _script(seed).digest()
        assert digest["derivations"], "no closure happened"
        assert digest["contradictions"], "nothing ever collided"
        assert len(digest["propositions"]) > 5

    def test_a_bare_event_list_is_refused(self):
        """It used to be accepted, as a convenience for a consumer reading
        the log back a line at a time out of a JSONL file. That convenience
        pointed the version bypass at precisely the reader most likely to
        need the version: the one holding lines off a disk, written by some
        other release. Wrapping them is one expression."""
        state = _script(1)
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(list(state.events))
        wrapped = {SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                   COUNT_KEY: len(state.events),
                   EVENTS_KEY: [dict(e) for e in state.events]}
        assert CognitiveState.replay(wrapped).digest_json() == \
            state.digest_json()

    def test_a_reordered_log_is_refused(self):
        """`n` is the only thing in a record that can catch this. Every event
        below is still perfectly well-formed and the store they replay into is
        not the one that was written."""
        state = _script(7)
        snapshot = state.snapshot()
        events = snapshot[EVENTS_KEY]
        events[1], events[2] = events[2], events[1]
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_log_cut_in_the_middle_is_refused(self):
        state = _script(8)
        snapshot = state.snapshot()
        del snapshot[EVENTS_KEY][2]
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_log_cut_at_the_TAIL_is_refused(self):
        """The one `n` cannot catch, and the most plausible corruption there
        is: drop the last three events and 1..k-1 still number perfectly, so
        the log reads as a complete, shorter session. It is what a truncated
        write, a partial upload and a half-read file all produce. `count` is
        the only thing standing between that and a silently smaller store."""
        state = _script(8)
        snapshot = state.snapshot()
        del snapshot[EVENTS_KEY][-3:]
        assert [e["n"] for e in snapshot[EVENTS_KEY]] == \
            list(range(1, len(snapshot[EVENTS_KEY]) + 1)), \
            "the numbering is intact — that is the whole point"
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_schema_two_log_without_a_count_is_refused(self):
        state = _script(8)
        snapshot = state.snapshot()
        del snapshot[COUNT_KEY]
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_schema_one_log_is_not_asked_for_a_count(self):
        """It never carried one, and demanding it would make the
        append-only promise false for the logs it exists to protect."""
        assert CognitiveState.replay(
            json_round_trip(TestTheSchemaGrewWithoutBreakingAnOldLog.V1_LOG)
        ).propositions()

    def test_a_duplicated_event_is_refused(self):
        state = _script(9)
        snapshot = state.snapshot()
        snapshot[EVENTS_KEY].insert(3, dict(snapshot[EVENTS_KEY][2]))
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_log_with_its_numbering_intact_still_replays(self):
        """The n-check has to refuse corruption without refusing a log
        somebody legitimately re-serialised."""
        state = _script(10)
        snapshot = json_round_trip(state.snapshot())
        assert CognitiveState.replay(snapshot).digest_json() == \
            state.digest_json()

    def test_replaying_a_replay_is_the_same_store(self):
        state = _script(2)
        once = CognitiveState.replay(state.snapshot())
        twice = CognitiveState.replay(once.snapshot())
        assert twice.digest_json() == state.digest_json()
        assert [event["op"] for event in twice.events] == \
               [event["op"] for event in state.events]

    def test_an_unknown_op_is_refused_not_skipped(self):
        """The mutation this exists for: a replay that skipped what it did
        not recognise would build a plausible store out of a log it did not
        understand, and nothing downstream could tell."""
        state = _script(3)
        snapshot = state.snapshot()
        snapshot[EVENTS_KEY].insert(2, {"n": 0, "op": "believe_harder"})
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_an_unversioned_snapshot_is_refused(self):
        state = _script(4)
        snapshot = state.snapshot()
        del snapshot[SCHEMA_KEY]
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_a_newer_schema_is_refused(self):
        state = _script(5)
        snapshot = state.snapshot()
        snapshot[SCHEMA_KEY] = EVENT_SCHEMA_VERSION + 1
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    def test_an_authority_this_kernel_has_no_name_for_is_refused(self):
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        snapshot = state.snapshot()
        snapshot[EVENTS_KEY][0]["authority"] = "vibes"
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

    @pytest.mark.parametrize("events", [None, 0, "", {}, "notalist", 7])
    def test_a_schema_one_snapshot_without_a_list_of_events_is_refused(
            self, events):
        """A v1 log carries no count, so this guard is the only thing
        standing between a broken snapshot and a silent empty store. Tested
        at schema 1 deliberately: at schema 2 the count catches these first,
        and a guard only ever exercised behind another one is a guard nobody
        knows the state of."""
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: 1, EVENTS_KEY: events})

    def test_a_schema_one_snapshot_missing_the_events_key_is_refused(self):
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: 1})

    @pytest.mark.parametrize("events", [None, 0, "", {}, "notalist", 7])
    def test_a_snapshot_without_a_list_of_events_is_refused(self, events):
        """`raw.get(EVENTS_KEY) or []` was the shape here, and every one of
        these replayed to a silent, successful, EMPTY store — the one result
        no consumer can tell from a store that legitimately holds nothing,
        and the caller's `except ReplayRefused` never fires."""
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                   EVENTS_KEY: events})

    def test_a_snapshot_missing_the_events_key_entirely_is_refused(self):
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION})

    def test_an_empty_list_of_events_is_a_legitimate_empty_store(self):
        """The other half, so the refusal above is about SHAPE and not about
        emptiness: a snapshot that really carries no events replays."""
        state = CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                       COUNT_KEY: 0, EVENTS_KEY: []})
        assert state.propositions() == ()
        assert state.events == ()

    @pytest.mark.parametrize("evidence", ["notalist", 7, [7], [[]], [None],
                                          ["kind"]])
    def test_corrupt_evidence_is_refused_and_not_raised_through(self, evidence):
        """The documented handler is `except ReplayRefused`. These used to
        come out as AttributeError and TypeError from inside `from_dict` —
        straight through a handler written exactly as the docs say, as a
        crash instead of a refusal. `"notalist"` is the nastiest: a string
        is a Sequence, so it iterates, into characters."""
        log = {
            SCHEMA_KEY: EVENT_SCHEMA_VERSION,
            COUNT_KEY: 1,
            EVENTS_KEY: [{"n": 1, "op": "assert_observation",
                          "triple": ["alice", "role", "admin"], "text": None,
                          "authority": "source", "evidence": evidence}],
        }
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(log)

    # Ten shapes that are each a legitimate refusal SOMEWHERE in the kernel
    # and were each the wrong exception here. A replay has exactly one
    # failure a caller is told to catch, and an `AuthorityRefused` or an
    # `UnknownId` escaping from it goes straight through a handler written
    # as documented — a crash where a refusal was promised, and a store left
    # half built.
    BAD_EVENTS = [
        ("observation under model authority",
         {"op": "assert_observation", "triple": ["a", "b", "c"],
          "authority": "model_hypothesis", "evidence": [{"kind": "r"}]}),
        ("hypothesis under receipt authority",
         {"op": "assert_hypothesis", "triple": ["a", "b", "c"],
          "authority": "source", "evidence": [{"kind": "r"}]}),
        ("an assertion with no evidence",
         {"op": "assert_observation", "triple": ["a", "b", "c"],
          "authority": "source", "evidence": []}),
        ("neither a triple nor text",
         {"op": "assert_observation", "triple": None, "text": None,
          "authority": "source", "evidence": [{"kind": "r"}]}),
        ("a variable asserted as a fact",
         {"op": "assert_observation", "triple": ["?who", "b", "c"],
          "authority": "source", "evidence": [{"kind": "r"}]}),
        ("a non-finite value",
         {"op": "assert_observation", "triple": ["a", "b", 1e999],
          "authority": "source", "evidence": [{"kind": "r"}]}),
        ("a rule with an empty body",
         {"op": "add_rule", "name": "x", "authority": "system",
          "head": ["a", "b", "c"], "body": []}),
        ("a rule concluding about an unbound variable",
         {"op": "add_rule", "name": "x", "authority": "system",
          "head": ["?a", "b", "?mystery"], "body": [["?a", "f", "c"]]}),
        ("promoting a rule nobody added",
         {"op": "promote_rule", "rule": "r9", "authority": "domain"}),
        ("refuting a proposition nobody asserted",
         {"op": "refute", "proposition": "p9",
          "evidence": [{"kind": "r"}]}),
    ]

    @pytest.mark.parametrize(
        "event", [pytest.param(e, id=name) for name, e in BAD_EVENTS])
    def test_every_refusal_inside_a_replay_comes_out_as_ReplayRefused(self, event):
        record = dict(event)
        record["n"] = 1
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                   COUNT_KEY: 1, EVENTS_KEY: [record]})

    def test_the_refusal_names_which_event_could_not_be_applied(self):
        good = {"n": 1, "op": "assert_observation",
                "triple": ["a", "b", "c"], "text": None,
                "authority": "source",
                "evidence": [{"kind": "r", "locator": "1", "note": ""}]}
        bad = {"n": 2, "op": "refute", "proposition": "p9",
               "evidence": [{"kind": "r", "locator": "1", "note": ""}]}
        with pytest.raises(ReplayRefused) as caught:
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                   COUNT_KEY: 2, EVENTS_KEY: [good, bad]})
        assert "event 2" in str(caught.value)
        assert "refute" in str(caught.value)

    def test_a_derive_naming_an_id_the_store_never_assigned_is_refused(self):
        """No partial application anywhere: a `derive` naming a proposition
        this store never assigned describes a different store, and closing
        over the rest of it builds something plausible out of that."""
        record = {"n": 1, "op": "derive", "propositions": ["p7"],
                  "rules": []}
        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                   COUNT_KEY: 1, EVENTS_KEY: [record]})

    def test_apply_delta_refuses_an_unknown_id_directly_too(self):
        state = CognitiveState()
        with pytest.raises(Exception):
            state.apply_delta(propositions=["p7"])

    def test_the_log_is_json_safe(self):
        state = _script(6)
        again = CognitiveState.replay(json_round_trip(state.snapshot()))
        assert again.digest_json() == state.digest_json()

    def test_the_door_stamp_survives_the_round_trip(self):
        """The stamp is what stops the evidence union from erasing the wall,
        and it travels in the log — so it has to come back through a real
        encoder rather than only through an in-process replay."""
        state = CognitiveState()
        pid = state.assert_hypothesis(("alice", "role", "admin"),
                                      evidence=[GUESS],
                                      authority=EvidenceAuthority.MODEL_EXTRACTION)
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        again = CognitiveState.replay(json_round_trip(state.snapshot()))
        assert {ref.authority for ref in again.proposition(pid).evidence} == \
            {EvidenceAuthority.MODEL_EXTRACTION, EvidenceAuthority.SOURCE}


class TestTheSchemaGrewWithoutBreakingAnOldLog:
    """`declare_field` and `settle` are new in schema 2. The promise that
    makes that safe is not "we were careful": it is that an op is never
    removed and never changes meaning, so a log written under 1 reads under 2
    exactly as it did. Asserted against a hand-built version-1 snapshot —
    one this kernel did not write — because a log produced by the current
    code cannot fail this even if the promise is broken."""

    V1_LOG = {
        SCHEMA_KEY: 1,
        EVENTS_KEY: [
            {"n": 1, "op": "add_rule", "name": "controls",
             "authority": "domain", "head": ["?a", "controls", "?c"],
             "body": [["?a", "admin_access", "?c"]]},
            {"n": 2, "op": "assert_observation",
             "triple": ["alice", "admin_access", "acct-9"], "text": None,
             "authority": "source",
             # No `authority` on the ref: the stamp did not exist in 1.
             "evidence": [{"kind": "receipt", "locator": "seq:1",
                           "note": ""}]},
            {"n": 3, "op": "assert_hypothesis",
             "triple": ["alice", "risky", True], "text": None,
             "authority": "model_extraction",
             "evidence": [{"kind": "extraction", "locator": "turn:1",
                           "note": ""}]},
            {"n": 4, "op": "add_goal", "pattern": ["?who", "controls",
                                                   "acct-9"], "note": ""},
            {"n": 5, "op": "derive", "propositions": ["p1", "p2"],
             "rules": ["r1"]},
        ],
    }

    def test_a_version_one_log_still_replays(self):
        state = CognitiveState.replay(json_round_trip(self.V1_LOG))
        triples = {p.triple for p in state.propositions()}
        assert ("alice", "controls", "acct-9") in triples
        assert state.frontier() == ()

    def test_its_unstamped_evidence_is_stamped_by_the_door_it_goes_through(self):
        """Not guessed from the ref: derived from the event's own authority,
        by the same door that would have stamped it originally."""
        state = CognitiveState.replay(json_round_trip(self.V1_LOG))
        seen = state.claim(("alice", "admin_access", "acct-9"))
        ref, = state.proposition(seen).evidence
        assert ref.authority is EvidenceAuthority.SOURCE

    def test_a_version_one_log_replays_under_version_one_SEMANTICS(self):
        """The append-only promise covers ops; it does not cover DEFAULTS,
        and schema 2 turned one of them round. A v1 store treated every field
        as single-valued, so a v1 log can contain contradictions that only
        exist under that rule — and reading it under today's default would
        rebuild a *different* store from the one that was written, silently.
        So the store keeps the schema it was replayed from."""
        state = CognitiveState.replay(json_round_trip(self.V1_LOG))
        assert state.fields() == {}, "v1 had no declarations to carry"
        assert state.cardinality("admin_access") == "one", \
            "a v1 log must be read with v1's default, not today's"

    def test_the_ops_of_schema_one_are_still_all_there(self):
        assert set(EVENT_OPS) >= {
            "assert_observation", "assert_hypothesis", "add_rule",
            "promote_rule", "add_goal", "refute", "derive"}
        assert EVENT_SCHEMA_VERSION == 2

    def test_a_v1_log_contests_two_values_a_v2_store_would_leave_alone(self):
        """The divergence made concrete. The same two events replayed as v2
        leave both claims standing; as v1 they contest, because that is what
        the store that wrote them did."""
        events = [
            {"n": 1, "op": "assert_observation",
             "triple": ["job-7", "total_s", 154.0], "text": None,
             "authority": "source",
             "evidence": [{"kind": "receipt", "locator": "a", "note": ""}]},
            {"n": 2, "op": "assert_observation",
             "triple": ["job-7", "total_s", 186.0], "text": None,
             "authority": "source",
             "evidence": [{"kind": "receipt", "locator": "b", "note": ""}]},
        ]
        old = CognitiveState.replay({SCHEMA_KEY: 1, EVENTS_KEY: events})
        assert [c.kind for c in old.contradictions()] == ["value"]
        assert old.propositions(live=True) == ()

        new = CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                     COUNT_KEY: 2, EVENTS_KEY: events})
        assert new.contradictions() == ()
        assert len(new.propositions(live=True)) == 2

    def test_a_v1_log_may_re_promote_a_rule_laterally(self):
        """The second divergence: v1 accepted a lateral re-promotion and v2
        refuses it, so a v1 log can contain one and must still replay."""
        events = [
            {"n": 1, "op": "add_rule", "name": "controls",
             "authority": "skill", "head": ["?a", "controls", "?c"],
             "body": [["?a", "admin_access", "?c"]]},
            {"n": 2, "op": "promote_rule", "rule": "r1",
             "authority": "domain"},
        ]
        old = CognitiveState.replay({SCHEMA_KEY: 1, EVENTS_KEY: events})
        assert old.rule("r1").authority is RuleAuthority.DOMAIN

        with pytest.raises(ReplayRefused):
            CognitiveState.replay({SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                                   COUNT_KEY: 2, EVENTS_KEY: events})

    def test_a_replayed_v1_store_snapshots_back_as_v1(self):
        """Round trip, so the semantics a store runs under are stable rather
        than a fact about the moment it was read."""
        old = CognitiveState.replay(json_round_trip(self.V1_LOG))
        again = old.snapshot()
        assert again[SCHEMA_KEY] == 1
        assert CognitiveState.replay(again).digest_json() == old.digest_json()

    def test_a_v1_store_refuses_the_ops_that_did_not_exist_under_it(self):
        old = CognitiveState.replay(json_round_trip(self.V1_LOG))
        with pytest.raises(Exception):
            old.declare_field("total_s", "one")
        with pytest.raises(Exception):
            old.settle("c1", keep="p1", evidence=[RECEIPT])

    def test_a_snapshot_names_the_engine_that_wrote_it(self):
        """Ids are handed out by the engine's enumeration order, so two
        engines that agree about every claim can still name them
        differently. A consumer that persisted an id finds out here."""
        state = _script(13)
        snapshot = state.snapshot()
        assert snapshot[KERNEL_KEY] == KERNEL_VERSION
        assert snapshot[SCHEMA_KEY] == EVENT_SCHEMA_VERSION

    def test_an_unfamiliar_engine_is_recorded_and_not_refused(self):
        """The opposite rule from the schema version, and deliberately: a
        kernel version this build does not know says the ids may not line up,
        which is not a reason to refuse to read the events."""
        log = dict(json_round_trip(self.V1_LOG))
        log[KERNEL_KEY] = KERNEL_VERSION + 7
        assert CognitiveState.replay(log).propositions()


# ---------------------------------------------------------------------------
# What the digest renders
# ---------------------------------------------------------------------------

class TestTheDigestRendersEverything:
    """`digest()` is the comparator every replay assertion above runs
    through, which makes it the one place in this package where narrowing is
    invisible: drop a field and the digests still match, the tests still
    pass, and the property they were proving is quietly a weaker one. The key
    sets are therefore written out here as literals — the same answer as
    `DIGEST_KEYS`, arrived at separately — so a field can leave the digest
    only in an edit that says so twice. Same idiom, same hazard, as
    `GROUNDING_KEYS` and its merge rules."""

    EXPECTED = {
        "propositions": {"id", "revision", "previous", "entity", "field",
                         "value", "text", "status", "authority", "derivation",
                         "evidence", "history"},
        "rules": {"id", "name", "authority", "head", "body"},
        "derivations": {"id", "rule", "premises", "conclusion"},
        "goals": {"id", "pattern", "note"},
        "fields": {"field", "cardinality"},
        "contradictions": {"id", "kind", "left", "right", "detail",
                           "evidence", "settled", "kept"},
        "pending": {"propositions", "rules"},
    }

    def test_the_sections_are_the_ones_declared(self):
        assert set(DIGEST_KEYS) == set(self.EXPECTED)
        assert set(_script(11).digest()) == set(self.EXPECTED)

    @pytest.mark.parametrize("section", sorted(EXPECTED))
    def test_the_declared_keys_are_these_keys(self, section):
        assert set(DIGEST_KEYS[section]) == self.EXPECTED[section]

    @pytest.mark.parametrize("section", sorted(EXPECTED))
    def test_every_row_rendered_carries_them(self, section):
        digest = _script(11).digest()
        rows = digest[section]
        rows = [rows] if isinstance(rows, dict) else rows
        assert rows, f"the script produced no {section}; this proves nothing"
        for row in rows:
            assert set(row) == self.EXPECTED[section]

    def test_a_narrowed_digest_is_refused_rather_than_compared(self):
        """Not only pinned by a test — refused on the way out, so a narrowing
        cannot pass through a store that nobody happened to run this file
        against."""
        state = _script(11)
        original = dict(DIGEST_KEYS["propositions"] and DIGEST_KEYS)
        try:
            DIGEST_KEYS["propositions"] = frozenset(
                set(DIGEST_KEYS["propositions"]) | {"invented"})
            with pytest.raises(Exception):
                state.digest()
        finally:
            DIGEST_KEYS.clear()
            DIGEST_KEYS.update(original)
        assert state.digest(), "the guard was restored"


# ---------------------------------------------------------------------------
# Incrementality
# ---------------------------------------------------------------------------

def _store_with_noise(rules=40):
    """One rule that matters and `rules` that do not, over distinct fields."""
    state = CognitiveState()
    state.add_rule("controls", ("?a", "controls", "?c"),
                   [("?a", "admin_access", "?c"),
                    ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
    for index in range(rules):
        state.add_rule(f"noise{index}", ("?a", f"out{index}", "?c"),
                       [("?a", f"in{index}", "?c")], RuleAuthority.SKILL)
    state.derive()
    return state


class TestClosureIsSemiNaive:
    """A naive engine returns the same propositions. Only the counters can
    fail, so this is the one place in the package where the instrument is the
    assertion."""

    def test_a_delta_does_not_re_match_the_whole_rule_set(self):
        state = _store_with_noise()
        state.stats.reset()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        assert state.stats.rules_considered == 1, (
            "41 rules in the store and one field in the delta; a naive "
            "engine would have looked at all of them")
        assert state.stats.body_scans <= 2

    def test_the_rule_the_delta_touches_is_the_one_considered(self):
        state = _store_with_noise()
        state.stats.reset()
        state.assert_observation(("alice", "in7", "acct-9"),
                                 evidence=[RECEIPT])
        derived = state.derive()
        assert state.stats.rules_considered == 1
        assert [state.proposition(pid).field for pid in derived] == ["out7"]

    def test_a_delta_touching_nothing_matches_nothing(self):
        state = _store_with_noise()
        state.stats.reset()
        state.assert_observation(("alice", "unrelated", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        assert state.stats.rules_considered == 0
        assert state.stats.body_scans == 0

    def test_a_rule_with_a_variable_field_is_always_a_candidate(self):
        """The index buckets by literal field, so a premise whose field is a
        variable can match anything and lives in the wildcard bucket. Pinned
        because it is the case that makes the index stop helping, and a rule
        pack written that way should be a known cost rather than a mystery."""
        plain = _store_with_noise()
        plain.stats.reset()
        plain.assert_observation(("alice", "unrelated", "acct-9"),
                                 evidence=[RECEIPT])
        plain.derive()
        assert plain.stats.rules_considered == 0

        state = _store_with_noise()
        state.add_rule("anything", ("?a", "touched", "?c"),
                       [("?a", "?f", "?c")], RuleAuthority.SKILL)
        state.derive()
        state.stats.reset()
        state.assert_observation(("alice", "unrelated", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        assert state.stats.rules_considered >= 1
        assert any(p.field == "touched" for p in state.propositions())

    def test_a_promotion_scans_only_the_promoted_rule(self):
        state = _store_with_noise()
        rid = state.add_rule("late", ("?a", "late", "?c"),
                             [("?a", "admin_access", "?c")])
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        state.stats.reset()
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        derived = state.derive()
        assert state.stats.rules_considered == 1
        assert [state.proposition(pid).field for pid in derived] == ["late"]

    def test_the_cost_does_not_grow_with_the_rules_that_do_not_apply(self):
        """The shape of the claim, not one number: ten times the irrelevant
        rules, the same work."""
        small, large = _store_with_noise(4), _store_with_noise(40)
        for state in (small, large):
            state.stats.reset()
            state.assert_observation(("alice", "admin_access", "acct-9"),
                                     evidence=[RECEIPT])
            state.derive()
        assert small.stats.rules_considered == large.stats.rules_considered
        assert small.stats.body_scans == large.stats.body_scans


# ---------------------------------------------------------------------------
# The standing constraints
# ---------------------------------------------------------------------------

class TestThePackageStandsAlone:
    """The shadow-attachment lane depends on this package; this package
    depends on nothing of ours. A kernel that cannot be imported on its own
    cannot be swapped for a different one, and swapping it is the experiment.
    """

    @pytest.mark.parametrize("name", ["__init__", "types", "matching",
                                      "events", "state"])
    def test_no_module_imports_the_runtime(self, name):
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        assert not re.search(r"^\s*(from|import)\s+core\.runtime", code,
                             re.MULTILINE), f"{name}.py reaches into the runtime"

    @pytest.mark.parametrize("name", ["__init__", "types", "matching",
                                      "events", "state"])
    def test_no_io_and_no_clock(self, name):
        """Deterministic and replayable is a property of the whole package,
        not of the tests that happen to avoid these. `json` is allowed — it
        is a codec and not a file."""
        source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for banned in (r"^\s*import\s+(os|time|random|socket|pathlib)\b",
                       r"^\s*from\s+(os|time|random|socket|pathlib|datetime)\b",
                       r"\bopen\(", r"\bdatetime\.", r"\btime\.time\("):
            assert not re.search(banned, code, re.MULTILINE), \
                f"{name}.py has {banned}"

    def test_the_package_imports_with_nothing_else_loaded(self):
        """The claim under its own steam, in a fresh interpreter.

        ``core/__init__.py`` imports the agent, which imports most of the
        repository, so plain ``import core.cognition`` would prove nothing
        about this package. A stand-in ``core`` package pointing at the same
        directory skips that file and leaves the question this test is for:
        with nothing else of ours loaded, does the kernel come up? The
        printed module list is the answer and the assertion.
        """
        import subprocess
        import sys

        script = (
            "import sys, types\n"
            "pkg = types.ModuleType('core')\n"
            f"pkg.__path__ = [{str(PACKAGE.parent)!r}]\n"
            "sys.modules['core'] = pkg\n"
            "import core.cognition as c\n"
            "assert c.CognitiveState().snapshot()['event_schema']\n"
            "print(sorted(m for m in sys.modules if m.startswith('core.')))\n"
        )
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True,
                                cwd=str(PACKAGE.parent.parent), timeout=60)
        assert result.returncode == 0, result.stderr
        loaded = ast.literal_eval(result.stdout.strip())
        assert set(loaded) == {
            "core.cognition", "core.cognition.events",
            "core.cognition.matching", "core.cognition.state",
            "core.cognition.types",
        }, ("the standalone claim is the whole loaded set, not the absence of "
            f"two names somebody thought to check: {sorted(loaded)}")

    def test_the_join_cap_is_a_named_bound(self):
        """The frontier is the cheapest true thing to do next, not a proof
        that nothing else is missing. The cap is the reason, and a cap with
        no name is a magic number somebody halves in a hurry."""
        assert ENV_CAP > 0
        assert "ENV_CAP" in (PACKAGE / "state.py").read_text(encoding="utf-8")


class TestTheJoinStartsFromWhatChanged:
    """The claim semi-naive closure actually makes is that the work is
    proportional to the *delta*, and body order alone broke it whenever the
    changed premise was not premise zero: the join started from an
    unconstrained early premise and walked whole columns of the store before
    reaching the two or three propositions that had moved.

    Measured in `MatchStats.candidates_scanned` rather than in seconds. A
    wall-clock assertion is a test that fails on a busy machine; this is the
    same claim with a number that is nobody's machine's business.
    """

    @staticmethod
    def _store(actors=200):
        """A rule whose delta premise is LAST, over a store with a column.

        The delta names an entity, which is what a receipt does. That is the
        case the ordering decides: with the pinned premise first, the entity
        is bound before any other premise is looked at and the pair index
        answers each of them in one step; in body order the join starts from
        an unconstrained `(?a, admin_access, ?c)` and walks every actor in
        the store to get there.
        """
        state = CognitiveState()
        state.add_rule("risky", ("?a", "risky", "?c"),
                       [("?a", "admin_access", "?c"),
                        ("?a", "payment_link", "?c"),
                        ("?a", "flagged", True)], RuleAuthority.DOMAIN)
        for index in range(actors):
            actor, acct = f"actor-{index}", f"acct-{index}"
            state.assert_observation((actor, "admin_access", acct),
                                     evidence=[RECEIPT])
            state.assert_observation((actor, "payment_link", acct),
                                     evidence=[RECEIPT])
        state.derive()
        return state

    def test_a_delta_on_the_last_premise_does_not_walk_the_first(self):
        state = self._store()
        state.stats.reset()
        state.assert_observation(("actor-7", "flagged", True),
                                 evidence=[RECEIPT])
        derived = state.derive()
        assert len(derived) == 1
        assert state.stats.candidates_scanned < 10, (
            "400 propositions in the store and one in the delta; a join in "
            f"body order walks the whole first column "
            f"({state.stats.candidates_scanned} scanned)")

    def test_the_cost_does_not_grow_with_the_store(self):
        """The shape of the claim rather than one number: ten times the
        store, the same work for the same delta."""
        small, large = self._store(20), self._store(200)
        for state in (small, large):
            state.stats.reset()
            state.assert_observation(("actor-7", "flagged", True),
                                     evidence=[RECEIPT])
            state.derive()
        assert small.stats.candidates_scanned == \
            large.stats.candidates_scanned

    def test_a_premise_with_both_terms_bound_uses_the_pair_index(self):
        """The other half of the ordering change, and it needs its own shape
        to show: an entity with MANY fields.

        A receipt about one job yields one proposition per column, so an
        entity's record is wide. Once the delta binds the entity, every later
        premise has both its terms ground — and the pair index answers each in
        one step where the entity index walks the whole record. The rule above
        cannot tell the two apart because its actors carry three fields each;
        this one carries two hundred.
        """
        state = CognitiveState()
        state.add_rule("risky", ("?a", "risky", True),
                       [("?a", "admin_access", "acct-9"),
                        ("?a", "flagged", True)], RuleAuthority.DOMAIN)
        state.assert_observation(("actor-1", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        for index in range(200):
            state.assert_observation(("actor-1", f"col{index}", index),
                                     evidence=[RECEIPT])
        state.derive()
        state.stats.reset()
        state.assert_observation(("actor-1", "flagged", True),
                                 evidence=[RECEIPT])
        derived = state.derive()
        assert len(derived) == 1
        assert state.stats.candidates_scanned < 10, (
            "the entity carries 202 propositions and the premise named one "
            f"of them ({state.stats.candidates_scanned} scanned)")

    def test_the_premises_are_still_recorded_in_body_order(self):
        """Evaluation order is the engine's business and must not leak into
        the result: a derivation names its premises the way the rule reads."""
        state = self._store(3)
        state.assert_observation(("actor-1", "flagged", True),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        proof, = state.derivations_for(derived)
        assert [state.proposition(p).field for p in proof.premises] == \
            ["admin_access", "payment_link", "flagged"]


class TestClosureReachesFixpointAndStops:
    """Termination, asserted with a hard bound rather than by the suite not
    hanging.

    Semi-naive closure ends because two things hold together: a derivation is
    deduplicated by `(rule, premises, conclusion)`, so a cycle stops producing
    new ones; and a delta contains only propositions that are new or newly
    live, so a re-assertion of something already held adds nothing to work on.
    Break either and `apply_delta` spins — and a spinning closure does not
    fail a test, it takes the machine.

    So the bound is explicit here, and the property generator's own seeds run
    against it: the interesting arrangement is never the one written by hand.
    """

    def test_a_chain_reaches_fixpoint_in_as_many_passes_as_it_has_levels(self):
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("risky", ("?a", "risky", "?c"),
                       [("?a", "controls", "?c")], RuleAuthority.DOMAIN)
        for actor in ("alice", "bob", "carol"):
            state.assert_observation((actor, "admin_access", "acct-9"),
                                     evidence=[RECEIPT])
        state.stats.reset()
        state.derive()
        assert state.stats.delta_passes <= 4, state.stats
        assert not state.has_pending
        assert len(state.propositions()) == 9

    def test_a_cycle_stops_because_a_derivation_is_deduplicated(self):
        """Two rules that conclude each other. Without the dedup key this is
        the loop that never ends."""
        state = CognitiveState()
        state.add_rule("there", ("?a", "there", "?c"),
                       [("?a", "back", "?c")], RuleAuthority.SYSTEM)
        state.add_rule("back", ("?a", "back", "?c"),
                       [("?a", "there", "?c")], RuleAuthority.SYSTEM)
        state.assert_observation(("alice", "there", "acct-9"),
                                 evidence=[RECEIPT])
        state.stats.reset()
        state.derive()
        assert state.stats.delta_passes <= 5, state.stats
        assert len(state.derivations()) == 2

    @pytest.mark.parametrize("seed", range(14))
    def test_the_property_generator_always_settles(self, seed):
        """Every seed the replay sweep uses, held to a bound. A generator
        that produced a non-terminating store would otherwise be discovered
        by the machine running out of memory."""
        state = _script(seed)
        assert not state.has_pending, "a flush left work staged"
        assert state.stats.delta_passes < 200, state.stats
        state.stats.reset()
        state.derive()
        assert state.stats.delta_passes == 0, \
            "a settled store did more work when asked again"


class TestARepeatIsNotADelta:
    """A re-assertion of something the store already holds live — the same
    triple, the same value, a second receipt — changes nothing closure could
    act on. Staging it made the next flush re-run every rule over that field
    to produce conclusions that already existed."""

    @staticmethod
    def _store():
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        return state

    def test_re_asserting_a_held_claim_stages_nothing(self):
        state = self._store()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[OTHER])
        assert not state.has_pending
        state.stats.reset()
        state.derive()
        assert state.stats.rules_considered == 0

    def test_it_cannot_lose_a_derivation(self):
        """The reason skipping it is safe, asserted rather than assumed: a
        conclusion is deduplicated by (rule, premises, conclusion), so the
        re-run could only ever have produced proofs the store already had."""
        state = self._store()
        before = state.digest()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[OTHER])
        state.derive()
        after = state.digest()
        assert after["derivations"] == before["derivations"]
        assert len(after["propositions"]) == len(before["propositions"])

    def test_the_new_evidence_still_lands_on_the_claim(self):
        state = self._store()
        pid = state.assert_observation(("alice", "admin_access", "acct-9"),
                                       evidence=[OTHER])
        assert len(state.proposition(pid).evidence) == 2

    def test_a_promotion_into_life_is_still_a_delta(self):
        """The merge that *does* change what closure can act on: a hypothesis
        an observation has just promoted."""
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.assert_hypothesis(("alice", "admin_access", "acct-9"),
                                evidence=[GUESS])
        assert state.derive() == ()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        assert state.has_pending
        derived, = state.derive()
        assert state.proposition(derived).field == "controls"


class TestTheConfidenceReadIsLinearInTheGraph:
    """`support()` is what a mission loop calls per step, so it cannot be
    exponential in the shape of the proof — and a diamond is the shape proofs
    actually take: two rules concluding from one premise, over and over, is
    2^depth distinct paths through a graph with 2·depth nodes."""

    @staticmethod
    def _diamond(depth):
        state = CognitiveState()
        for level in range(depth):
            for side in ("l", "r"):
                state.add_rule(f"{side}{level}", (f"?a", f"s{level + 1}", "?c"),
                               [("?a", f"{side}{level}x", "?c")],
                               RuleAuthority.DOMAIN)
                state.add_rule(f"{side}{level}x", ("?a", f"{side}{level}x",
                                                   "?c"),
                               [("?a", f"s{level}", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "s0", "acct-9"), evidence=[RECEIPT])
        state.derive()
        return state

    def test_grading_a_deep_diamond_visits_each_node_once(self):
        state = self._diamond(12)
        top = state.claim(("alice", "s12", "acct-9"))
        assert top is not None, "the chain did not close"

        calls = []
        original = CognitiveState._grade

        def counted(self, pid, path, memo):
            calls.append(pid)
            return original(self, pid, path, memo)

        CognitiveState._grade = counted
        try:
            support = state.support(top)
        finally:
            CognitiveState._grade = original
        assert support.grade is EvidenceAuthority.SOURCE
        assert len(calls) < 20 * len(state.propositions()), (
            f"{len(calls)} grade calls over {len(state.propositions())} "
            "propositions — the walk is re-descending every path")

    def test_the_leaves_of_a_deep_diamond_are_gathered_once(self):
        state = self._diamond(12)
        top = state.claim(("alice", "s12", "acct-9"))
        calls = []
        original = CognitiveState._leaves

        def counted(self, pid, path, memo):
            calls.append(pid)
            return original(self, pid, path, memo)

        CognitiveState._leaves = counted
        try:
            leaves = state.support(top).evidence_leaves
        finally:
            CognitiveState._leaves = original
        assert leaves == (RECEIPT.stamped(EvidenceAuthority.SOURCE),)
        assert len(calls) < 20 * len(state.propositions())


class TestAPublicReadDoesNotScanTheStore:
    def test_query_narrows_through_the_same_index_the_join_uses(self):
        """Otherwise `query` is the one place in the package where asking a
        narrow question costs the whole store."""
        state = CognitiveState()
        for index in range(300):
            state.assert_observation((f"actor-{index}", "admin_access",
                                      f"acct-{index}"), evidence=[RECEIPT])
        state.derive()
        state.stats.reset()
        found = state.query(("actor-7", "admin_access", "?c"))
        assert [p.entity for p in found] == ["actor-7"]
        assert state.stats.candidates_scanned > 0, (
            "the read went round the index machinery entirely — which is "
            "also how it stops being counted")
        assert state.stats.candidates_scanned < 10, (
            f"300 propositions in the store, one entity asked about "
            f"({state.stats.candidates_scanned} scanned)")

    def test_query_still_answers_the_wide_question(self):
        state = CognitiveState()
        for index in range(5):
            state.assert_observation((f"actor-{index}", "admin_access",
                                      "acct-9"), evidence=[RECEIPT])
        assert len(state.query(("?a", "admin_access", "?c"))) == 5
        assert len(state.query(("?a", "?f", "acct-9"))) == 5


class TestOneWalkServesEveryReader:
    """The obligation walk is a pure function of the store, and a mission
    loop asks for the frontier and then for the next obligation every step.
    Computing it twice for one answer is the cost this cache removes; a stale
    answer is the failure it must not introduce."""

    @staticmethod
    def _store():
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c"),
                        ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        state.frontier()
        return state

    def test_asking_again_does_not_walk_again(self):
        state = self._store()
        state.stats.reset()
        for _ in range(5):
            state.frontier()
            state.next_obligation()
            state.obligations()
        assert state.stats.candidates_scanned == 0, \
            "nothing changed and the walk ran again"

    def test_a_write_invalidates_it(self):
        state = self._store()
        assert len(state.frontier()) == 1
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        assert state.frontier() == ()

    def test_a_settlement_invalidates_it_too(self):
        state = CognitiveState()
        state.declare_field("admin_access", "one")
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        first = state.assert_observation(("alice", "admin_access", "acct-9"),
                                         evidence=[RECEIPT])
        state.assert_observation(("alice", "admin_access", "acct-1"),
                                 evidence=[OTHER])
        state.add_goal(("?who", "controls", "acct-9"))
        assert state.frontier(), "both sides contested; nothing is satisfied"
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        state.settle(clash.id, keep=first, evidence=[RECEIPT])
        assert state.frontier() == ()


class TestAProofIsADagAndNotATree:
    def test_a_shared_premise_is_one_object_seen_twice(self):
        """Proofs diamond: two rules conclude from a shared premise, that
        premise has proofs of its own, and a walk that rebuilt each node per
        path did exponential work to produce a structure the reader treats as
        shared anyway."""
        state = CognitiveState()
        state.add_rule("left", ("?a", "left", "?c"),
                       [("?a", "seed", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("right", ("?a", "right", "?c"),
                       [("?a", "seed", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("both", ("?a", "both", "?c"),
                       [("?a", "left", "?c"), ("?a", "right", "?c")],
                       RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "seed", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        both, = [p for p in state.propositions() if p.field == "both"]
        step, = state.prove(both.id).steps
        left, right = step.premises
        assert left.steps[0].premises[0] is right.steps[0].premises[0]

    @staticmethod
    def _render(proof, depth=0):
        assert depth < 10, "the walk did not terminate"
        rows = ["  " * depth + proof.proposition + ("*" if proof.cyclic else "")]
        for step in proof.steps:
            for premise in step.premises:
                rows.extend(TestAProofIsADagAndNotATree._render(premise,
                                                                depth + 1))
        return rows

    def test_a_cycle_reached_two_ways_in_one_walk_is_not_cached(self):
        """The poisoning case, and it needs both a cycle and a node outside
        it that reaches the cycle by two routes.

        `d` is concluded twice — once from `a` and once from `b` — and `a`,
        `b`, `c` form a loop. Walking the first route closes the cycle on
        `a`; walking the second closes it on `b`. Where the stub falls is a
        fact about the path, so caching the first walk's answer and handing
        it to the second renders a cycle that never happened.
        """
        state = CognitiveState()
        for name, head, body in [
            ("a", ("?x", "a", "?y"), [("?x", "b", "?y")]),
            ("b", ("?x", "b", "?y"), [("?x", "c", "?y")]),
            ("c", ("?x", "c", "?y"), [("?x", "a", "?y")]),
            ("d_from_b", ("?x", "d", "?y"), [("?x", "b", "?y")]),
            ("d_from_a", ("?x", "d", "?y"), [("?x", "a", "?y")]),
        ]:
            state.add_rule(name, head, body, RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "a", "acct"), evidence=[RECEIPT])
        state.derive()
        ids = {p.field: p.id for p in state.propositions()}

        assert self._render(state.prove(ids["d"])) == [
            ids["d"],
            f"  {ids['a']}",
            f"    {ids['b']}",
            f"      {ids['c']}",
            f"        {ids['a']}*",
            f"  {ids['b']}",
            f"    {ids['c']}",
            f"      {ids['a']}",
            f"        {ids['b']}*",
        ], "the stub moved — a cached cyclic node was reused across routes"

    def test_a_node_on_a_cycle_is_never_memoised(self):
        """Its shape depends on the path that reached it — that is what
        `cyclic` records — so caching one would hand a later caller a stub
        that was true of somebody else's walk. Pinned by rendering the cycle
        and asserting where the stub falls, not by asserting `is not`."""
        state = CognitiveState()
        state.add_rule("there", ("?a", "there", "?c"),
                       [("?a", "back", "?c")], RuleAuthority.SYSTEM)
        state.add_rule("back", ("?a", "back", "?c"),
                       [("?a", "there", "?c")], RuleAuthority.SYSTEM)
        state.assert_observation(("alice", "there", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        back = state.claim(("alice", "back", "acct-9"))
        there = state.claim(("alice", "there", "acct-9"))

        def render(proof, depth=0):
            assert depth < 8, "the walk did not terminate"
            mark = "*" if proof.cyclic else ""
            rows = [f"{'  ' * depth}{proof.proposition}{mark}"]
            for step in proof.steps:
                for premise in step.premises:
                    rows.extend(render(premise, depth + 1))
            return rows

        # `back` is proved from `there`, which is observed AND also derivable
        # from `back` — so the walk meets `back` again one level down and
        # stops there, marked.
        assert render(state.prove(back)) == [back, f"  {there}",
                                             f"    {back}*"]
        # Proved from the other end, the stub falls on `there` instead: the
        # node that is a stub is a fact about the path, which is exactly why
        # it is not cached.
        assert render(state.prove(there)) == [there, f"  {back}",
                                              f"    {there}*"]

    def test_a_derived_proposition_is_born_at_revision_one(self):
        """It used to be created and then immediately revised to record the
        proof that had just made it — two revisions for one event, and a
        history saying the store changed its mind about something it had held
        for no time at all. `types.py` states the rule that broke: a proof is
        not a change of belief."""
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        prop = state.proposition(derived)
        assert prop.revision == 1
        assert prop.previous is None
        assert prop.derivation == state.derivations_for(derived)[0].id


class TestTheFrontierSaysWhenItStoppedBeingComplete:
    """A truncated join and an exhausted one look identical from the outside:
    both return a frontier and neither says anything. The counter is the
    difference, and it is here because "the frontier is a guide, not a proof
    of exhaustiveness" is only an honest sentence if a caller can find out
    which of the two it is holding."""

    def test_an_ordinary_frontier_truncates_nothing(self):
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c"),
                        ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        state.stats.reset()
        assert state.frontier()
        assert state.stats.envs_truncated == 0

    def test_a_join_past_the_cap_says_so(self):
        state = CognitiveState()
        state.add_rule("controls", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c"),
                        ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        for index in range(ENV_CAP + 5):
            state.assert_observation((f"actor-{index}", "admin_access",
                                      "acct-9"), evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        state.stats.reset()
        owed = state.frontier()
        assert state.stats.envs_truncated > 0
        assert len(owed) <= ENV_CAP, \
            "the cap bounds the work, and the counter admits it"

    def test_the_frontier_itself_carries_the_flag(self):
        """A counter a caller has to remember to read is a counter nobody
        reads. This repository's rule is that a budget exhausted is a
        recorded outcome naming the budget, so the outcome says so."""
        ordinary = CognitiveState()
        ordinary.add_rule("controls", ("?a", "controls", "?c"),
                          [("?a", "admin_access", "?c"),
                           ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        ordinary.assert_observation(("alice", "admin_access", "acct-9"),
                                    evidence=[RECEIPT])
        ordinary.add_goal(("?who", "controls", "acct-9"))
        assert ordinary.frontier().truncated is False
        assert ordinary.obligations().truncated is False

        cut = CognitiveState()
        cut.add_rule("controls", ("?a", "controls", "?c"),
                     [("?a", "admin_access", "?c"),
                      ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        for index in range(ENV_CAP + 5):
            cut.assert_observation((f"actor-{index}", "admin_access",
                                    "acct-9"), evidence=[RECEIPT])
        cut.add_goal(("?who", "controls", "acct-9"))
        assert cut.frontier().truncated is True

    def test_the_flag_survives_the_cache(self):
        cut = CognitiveState()
        cut.add_rule("controls", ("?a", "controls", "?c"),
                     [("?a", "admin_access", "?c"),
                      ("?a", "payment_link", "?c")], RuleAuthority.DOMAIN)
        for index in range(ENV_CAP + 5):
            cut.assert_observation((f"actor-{index}", "admin_access",
                                    "acct-9"), evidence=[RECEIPT])
        cut.add_goal(("?who", "controls", "acct-9"))
        assert cut.frontier().truncated is True
        assert cut.frontier().truncated is True, \
            "the second read is served from the cache and must say the same"
