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

from core.cognition import (DIGEST_KEYS, EVENT_OPS, EVENT_SCHEMA_VERSION,
                            EVENTS_KEY, SCHEMA_KEY, CognitiveState,
                            EvidenceAuthority, EvidenceRef, ReplayRefused,
                            RuleAuthority)
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
        state = CognitiveState()
        rid = state.add_rule("controls", ("?a", "controls", "?c"),
                             [("?a", "admin_access", "?c")])
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        pid = state.assert_observation(("alice", "admin_access", "acct-9"),
                                       evidence=[RECEIPT])
        state.assert_hypothesis(("alice", "risky", True), evidence=[GUESS])
        state.add_goal(("?who", "controls", "acct-9"))
        state.derive()
        state.refute(pid, evidence=[OTHER])
        assert {event["op"] for event in state.events} == set(EVENT_OPS)
        assert [event["n"] for event in state.events] == list(range(1, 8))

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

    def test_the_events_a_reader_gets_are_copies(self):
        state = CognitiveState()
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        state.events[0]["op"] = "nonsense"
        assert state.events[0]["op"] == "assert_observation"


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
                   EVENTS_KEY: list(state.events)}
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

    def test_a_truncated_log_is_refused(self):
        state = _script(8)
        snapshot = state.snapshot()
        del snapshot[EVENTS_KEY][2]
        with pytest.raises(ReplayRefused):
            CognitiveState.replay(snapshot)

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
        "contradictions": {"id", "kind", "left", "right", "detail",
                           "evidence"},
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
