# core/cognition/state.py — the store: single writer, incremental, replayable

"""What is believed, why, what contradicts it, and what is still owed.

One class, :class:`CognitiveState`.  It is the only thing in this package that
changes, and it changes in exactly ten ways —
:meth:`~CognitiveState.assert_observation`,
:meth:`~CognitiveState.assert_hypothesis`, :meth:`~CognitiveState.add_rule`,
:meth:`~CognitiveState.promote_rule`, :meth:`~CognitiveState.add_goal`,
:meth:`~CognitiveState.refute`, :meth:`~CognitiveState.declare_field`,
:meth:`~CognitiveState.settle`, :meth:`~CognitiveState.link` and
:meth:`~CognitiveState.apply_delta` — each of which appends exactly one event
and does nothing else that a replay cannot reproduce.  Everything else on the
class is a read.

**Projection, and why linking does not rewrite anything.**  A
:meth:`~CognitiveState.link` says one entity is about one subject; it edits no
proposition.  What it does is license one built-in rule inside closure
(:data:`PROJECTION_RULE`): for every live triple of a linked entity, the same
field and value are *derived* about the subject, with the receipt fact as the
premise and the link named on the derivation.  Rewriting the receipt's facts
onto the subject was the alternative and it destroys the thing the store is
for — a proposition's entity is where it was seen, its history is the record
of that, and two receipts merged into one entity can no longer say which of
them said what.  Projection instead reuses every mechanism already here:
rules join across receipts because a subject is an ordinary entity their
variables bind; a field declared ``one`` contests **at the subject**, where
two receipts really do disagree, while both receipts stay live because a
receipt does not disagree with itself; :meth:`prove` walks from the subject's
fact to the receipt's; and a refuted receipt fact kills its projection through
the retraction cascade below, with no new code path.  The costs are stated
where they are paid: roughly double the propositions for a linked entity, and
a closure that must be order-independent, because a link can arrive before or
after the facts it projects.

**Single writer.**  There is no lock here and there is not meant to be one.
A store two things write to is a store whose insertion order depends on
scheduling, and insertion order is where every id in this package comes from.
When Phase 20's derived swarm arrives, children return *evidence* and the
parent commits it — that constraint is in the roadmap because it is this
paragraph.

**Incremental, and the reason it is testable.**  :meth:`apply_delta` matches
only the rule bodies a delta can touch, and cascades from what that produced.
Naive closure would return the same propositions, so correctness cannot tell
the two apart; :class:`~core.cognition.types.MatchStats` can, and
``tests/test_cognition_replay.py`` reads it.

**Lazy, and what the implicit flush costs.**  An assertion stages its
proposition and does not derive.  :meth:`derive` flushes the staging area,
and every read that depends on closure calls it first — so a caller never
sees a half-closed store, and a caller batching twenty receipts pays for one
closure pass rather than twenty.

That convenience has a price, and it is named here rather than explained
away: **id assignment is a function of the interleaving of writes and
flushes, not of the writes.**  Two callers issuing identical assertions, one
reading the frontier between them and one not, keep logs of different length
— and because ids are handed out in insertion order, the early flush inserts
a *derived* proposition before the next observation arrives, so the same
claims end up under different names.  The engine's own enumeration order is
the second half of the same fact, and
:data:`~core.cognition.events.KERNEL_VERSION` is what records it.

What each log does still do exactly is replay to its own store; that is
unweakened, and the property sweep covers it.  What the timing never reaches
is *what is believed*: the same writes give the same claims, the same
statuses and the same proofs, and the frontier is identical because
obligation ids are content-addressed.  So a proposition id means something
inside one store's own history and nowhere else, and anything treating the
log as a canonical byte string (a diff, a hash, a corpus guard) has to know
that both of these move.

The alternative was an explicit-flush API, rejected because a store read
half-closed is a wrong answer where a forgotten ``derive()`` is a silent one.
Instead: the dependence is a pinned, tested property
(``tests/test_cognition_replay.py``), :meth:`pending` and
:attr:`has_pending` let a caller see the staging area, and the rule for a
caller that wants a stable log is one line — call :meth:`derive` at one
defined point per turn and read only after it.

**The retraction rule, chosen and written down.**  When a premise dies
(``REFUTED`` by a caller, or ``CONTESTED`` by a collision), every derived
conclusion whose *every* derivation now rests on something dead is retracted
to ``CONTESTED``, with a :class:`~core.cognition.types.Contradiction` of kind
``"dead_premise"`` naming the conclusion and the premise that died.  It
cascades.  The alternative considered and rejected for v1 was a separate
``STALE`` marker that left the conclusion live and flagged — fewer statuses is
worth more than the extra nuance here, and ``CONTESTED`` already means "two
things cannot both stand and the store is not picking," which is exactly the
situation.  Phase 18+ may want the distinction back when a conclusion with one
dead proof and one live proof needs a different word from one with no proof at
all; today the first case is not retracted at all, because it still has a live
derivation, and that is the case the extra status would mostly have been for.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.cognition.events import (COUNT_KEY, EVENT_OPS, EVENT_SCHEMA_VERSION,
                                   EVENTS_KEY, KERNEL_KEY, KERNEL_VERSION,
                                   SCHEMA_KEY, check_snapshot, decode_evidence,
                                   decode_pattern, deep_copy, encode_evidence,
                                   encode_pattern, freeze)
from core.cognition.matching import (Bindings, resolve, shares_variable, unify,
                                     unify_patterns)
from core.cognition.types import (AUTHORITY_RANK, CARDINALITIES,
                                  CONTRADICTION_KINDS, DEFAULT_CARDINALITY,
                                  HYPOTHESIS_AUTHORITIES,
                                  OBSERVATION_AUTHORITIES,
                                  STATUS_RANK, AuthorityRefused,
                                  CognitionError, Contradiction, Derivation,
                                  EvidenceAuthority, EvidenceRef, Frontier,
                                  Goal, Link, MatchStats, Obligation,
                                  ObligationState, Proof, Proposition,
                                  PropositionStatus, ProofStep, ReplayRefused,
                                  Rule, RuleAuthority, RuleMalformed, Support,
                                  UnknownId, check_pattern, check_subject,
                                  check_value, is_variable, render_pattern,
                                  subject_parts, value_tag, variables_in)

#: **v1 bound.**  Obligation computation joins a rule body against the store
#: and a rule with several matches per premise branches.  Beyond this many
#: partial environments per goal-rule pair the join stops extending and works
#: with what it has.  The frontier is a *guide* — the cheapest true thing to
#: do next — and not a proof that nothing else is missing; a cap that makes it
#: slightly less complete is better than an unbounded join inside a read a
#: mission loop calls every step.  Closure itself is not capped: a derivation
#: is a claim about truth and truncating it would make the store wrong rather
#: than incomplete.
ENV_CAP = 256

#: The id the projection's derivations name. It carries a ``:``, and every
#: rule a caller adds is ``rN``, so the two can never collide — the same
#: separator that keeps subjects out of the receipt namespace keeps the
#: engine's own rule out of the caller's.
PROJECTION_RULE_ID = "sys:projection"

#: The one rule this engine owns, written out so that a proof step can name
#: something and a reader can see what it claims.
#:
#: **It is built in because it cannot be written down.**  Its second premise is
#: a :class:`~core.cognition.types.Link`, not a triple, and a rule's body is
#: triples — so the head variable ``?subject`` is bound by nothing the body can
#: state and :meth:`CognitiveState.add_rule` would refuse this clause for
#: range restriction, correctly.  Holding it here rather than inserting it into
#: every store's rule set also means a store that never links is byte-identical
#: to the one the last release built: the rule is part of the *engine*, like
#: the retraction cascade, and a digest that rendered it would be rendering the
#: code.
PROJECTION_RULE = Rule(id=PROJECTION_RULE_ID, name="projection",
                       authority=RuleAuthority.SYSTEM,
                       head=("?subject", "?field", "?value"),
                       body=(("?entity", "?field", "?value"),))

#: A memo miss. `None` is a real grade result — "this claim has none" —
#: so a memo that used it as the miss marker would recompute every
#: ungraded proposition on every lookup.
_UNSET = object()

#: Every field :meth:`CognitiveState.digest` renders, per section.
#:
#: Module level and enforced on the way out, in the idiom
#: :data:`core.runtime.grounding.GROUNDING_KEYS` established for the same
#: hazard: a *second* reader of a shape exists, and two hand-kept ideas of
#: "the fields there are" drift silently.  Here the second reader is every
#: replay assertion in the suite.  They all compare digests, so a digest that
#: stopped rendering ``authority``, or ``previous``, or the evidence on a
#: contradiction, would go on passing while proving strictly less — and the
#: narrowing would show up as nothing at all.  Pinned here, and pinned again
#: as literals in ``tests/test_cognition_replay.py``, so a field can leave
#: the digest only in an edit that says so twice.
DIGEST_KEYS = {
    "propositions": frozenset({
        "id", "revision", "previous", "entity", "field", "value", "text",
        "status", "authority", "derivation", "evidence", "history"}),
    "rules": frozenset({"id", "name", "authority", "head", "body"}),
    "derivations": frozenset({"id", "rule", "premises", "conclusion",
                              "link"}),
    "links": frozenset({"id", "revision", "previous", "entity", "subject",
                        "authority", "evidence", "history"}),
    "goals": frozenset({"id", "pattern", "note"}),
    "fields": frozenset({"field", "cardinality"}),
    "contradictions": frozenset({
        "id", "kind", "left", "right", "detail", "evidence", "settled",
        "kept"}),
    "pending": frozenset({"propositions", "rules", "links"}),
}


class CognitiveState:
    """The store. See the module docstring for the rules it keeps."""

    # ── construction ────────────────────────────────────────────────────────

    def __init__(self, schema: int = EVENT_SCHEMA_VERSION) -> None:
        # Which schema's SEMANTICS this store runs under. A fresh store is
        # the current one; a store rebuilt from an older log keeps that log's,
        # because `replay` has to reproduce what the log meant when it was
        # written and not what those same events would mean today. See
        # `replay` for the two places the versions actually differ.
        self._schema = int(schema)
        self._events: List[dict] = []
        # Read-only views of the same dicts, built once at append time. The
        # log used to be deep-copied on every `.events` access — 120ms at
        # 100k events, and quadratic for a consumer that reads after each
        # write. A proxy costs nothing to make and cannot be edited, which
        # was the only reason to copy.
        self._readonly: List[Mapping[str, Any]] = []

        # Propositions: `_props` holds the live revision of every claim,
        # `_history` every revision in order. Both keyed by the claim id, which
        # is stable across revisions — the record id is `Proposition.key`.
        self._props: Dict[str, Proposition] = {}
        self._history: Dict[str, List[Proposition]] = {}
        # Claim identity. The key carries the value's TYPE BAND as well as the
        # value, because Python hashes `True` and `1` the same and a dict
        # would quietly file them as one claim — see `types.value_tag`.
        self._claim_key: Dict[tuple, str] = {}

        # Indexes. Lists, not sets: a proposition id enters each one exactly
        # once, and a list preserves the insertion order every deterministic
        # iteration in this file depends on.
        self._by_entity: Dict[str, List[str]] = {}
        self._by_field: Dict[str, List[str]] = {}
        self._by_entity_field: Dict[Tuple[str, str], List[str]] = {}

        self._rules: Dict[str, Rule] = {}
        self._rules_by_field: Dict[Optional[str], List[str]] = {}

        self._derivations: Dict[str, Derivation] = {}
        self._derivation_keys: set = set()
        self._by_premise: Dict[str, List[str]] = {}
        self._by_conclusion: Dict[str, List[str]] = {}

        # Links, and the same three-index shape a proposition gets: the live
        # revision, the whole chain, and the identity of the *link* — which is
        # the pair, not the id, so the same pair stated twice is one record
        # whose evidence unions.
        self._links: Dict[str, Link] = {}
        self._link_history: Dict[str, List[Link]] = {}
        self._link_key: Dict[Tuple[str, str], str] = {}
        self._links_by_entity: Dict[str, List[str]] = {}
        self._links_by_subject: Dict[str, List[str]] = {}

        self._goals: Dict[str, Goal] = {}
        self._cardinality: Dict[str, str] = {}
        self._contradictions: Dict[str, Contradiction] = {}
        # `(kind, left, right)` → id. A collision found twice is one
        # contradiction: a hypothesis re-asserted against the same
        # observation, or a claim refuted twice, must not grow the ledger.
        self._contradiction_keys: Dict[tuple, str] = {}

        # Ordered SETS, spelled as dicts. They were lists, and every one of
        # the four things done to them — append-if-absent, remove, iterate —
        # is O(n) on a list, so a flush of n staged propositions cost O(n²)
        # and a ten-thousand-receipt store never finished building.
        self._pending_props: Dict[str, None] = {}
        self._pending_rules: Dict[str, None] = {}
        self._pending_links: Dict[str, None] = {}

        self._counters = {"p": 0, "r": 0, "d": 0, "g": 0, "c": 0, "l": 0}
        self.stats = MatchStats()
        # Bumped by anything that could change what the goals owe. The
        # obligation walk is a pure function of the store, so one computation
        # serves every reader at the same epoch — `frontier()` followed by
        # `next_obligation()` used to walk the rules twice for one answer.
        self._epoch = 0
        self._obligations: Optional[Tuple[int, Frontier]] = None

    # ── the event log ───────────────────────────────────────────────────────

    def _append(self, op: str, **fields: Any) -> dict:
        assert op in EVENT_OPS, op  # a typo here would be a log nobody replays
        event = {"n": len(self._events) + 1, "op": op}
        event.update(fields)
        self._events.append(event)
        self._readonly.append(freeze(event))
        self._epoch += 1
        return event

    @property
    def events(self) -> Tuple[Mapping[str, Any], ...]:
        """The log, oldest first, as read-only views a reader cannot edit.

        Views rather than copies.  Copying every event on every access read
        the whole log to answer a question about it, which is fine once and
        quadratic for the consumer this exists for — one that reads after
        each write.  :meth:`events_since` is the call that consumer should
        make; this one is for the reader that wants all of it.
        """
        return tuple(self._readonly)

    def events_since(self, n: int) -> Tuple[Mapping[str, Any], ...]:
        """Events numbered above ``n``, oldest first.

        The cursor is the ``n`` on the last event a caller has seen, so the
        first call is ``events_since(0)`` and each next one passes back the
        last ``n`` it got — the same shape the run store's ``seq`` uses, for
        the same reason and with the same failure to avoid: a reader that
        re-reads the whole log to find the tail turns an append into an O(n)
        operation and a session into a quadratic one.
        """
        if n < 0:
            raise CognitionError(f"a cursor is not negative: {n!r}")
        return tuple(self._readonly[n:])

    def pending(self) -> dict:
        """The staging area: what the next flush would derive from.

        Public because the implicit flush is otherwise invisible.  A caller
        that wants a log it can compare byte for byte needs to be able to ask
        whether there is anything outstanding before it reads.
        """
        return {"propositions": tuple(self._pending_props),
                "rules": tuple(self._pending_rules),
                "links": tuple(self._pending_links)}

    @property
    def has_pending(self) -> bool:
        """Whether the next read would append a ``derive`` event."""
        return bool(self._pending_props or self._pending_rules
                    or self._pending_links)

    def snapshot(self) -> dict:
        """The whole state as one JSON-safe dict: a version and its events.

        Flushes first.  A snapshot is the one read whose whole purpose is to
        be handed somewhere else, and a snapshot taken with work outstanding
        replays into a store that then does that work on its reader's first
        question — correct, and one more place where "when did somebody read"
        decides what a log looks like.  Consistency with every other read is
        worth more here than a paragraph explaining why this one differs.
        """
        self.derive()
        return {SCHEMA_KEY: self._schema,
                KERNEL_KEY: KERNEL_VERSION,
                COUNT_KEY: len(self._events),
                EVENTS_KEY: [deep_copy(event) for event in self._events]}

    @classmethod
    def replay(cls, events: Any) -> "CognitiveState":
        """Rebuild a store from a snapshot or a bare event list.

        Every op is applied through the same public method that wrote it.
        There is no second application path — a replay that reconstructed the
        indexes directly would be a second implementation of the engine, and
        the day the two disagreed the replay would be the one nobody checked.

        **Replay is version-aware, and that is what keeps the append-only
        promise honest.**  :mod:`core.cognition.events` promises that an op
        never changes meaning, and it does not — but two *defaults* around
        them did, and a log is only reconstructed correctly if it is read
        under the rules in force when it was written.  A schema-1 log
        therefore replays with schema-1 semantics, in exactly two places:

        * an undeclared field is single-valued (schema 2 made it ``many``, and
          a v1 store contested values a v2 store leaves standing), and
        * a rule may be re-promoted laterally (schema 2 refuses it).

        Schema 3 changed no default, so a schema-2 log replays under schema-3
        code exactly as it did; what the resulting store keeps is the *floor*
        — it refuses :meth:`link`, because a store whose log says it never
        linked anything cannot be handed a link without its history stopping
        being an explanation of it.

        Both were things a v1 store really did, so a v1 log can contain their
        consequences, and reading it under today's rules would silently
        produce a *different* store from the one that was written.  The
        resulting store keeps that schema — it snapshots back as what it is,
        so a round trip is exact — and refuses the ops that did not exist
        under it.
        """
        version, records = check_snapshot(events)
        state = cls(schema=version)
        for index, record in enumerate(records):
            try:
                state._apply_event(record)
            except ReplayRefused:
                raise
            except CognitionError as exc:
                # Everything this package refuses is a CognitionError, and a
                # replay has exactly one failure a caller is told to catch.
                # An `AuthorityRefused` or an `UnknownId` escaping from here
                # went straight through a handler written as documented — a
                # crash where a refusal was promised, and a store left half
                # built.
                raise ReplayRefused(
                    f"event {index + 1} ({record.get('op')!r}) cannot be "
                    f"applied: {exc}") from exc
        return state

    def _require_schema(self, needed: int, op: str) -> None:
        if self._schema < needed:
            raise CognitionError(
                f"{op!r} arrived in schema {needed} and this store is "
                f"running schema-{self._schema} semantics; a store rebuilt "
                "from an older log keeps that log's rules, and mixing the "
                "two would give it a history it cannot explain")

    def _apply_event(self, record: Mapping[str, Any]) -> None:
        op = record["op"]
        if op in ("assert_observation", "assert_hypothesis"):
            triple = record.get("triple")
            call = (self.assert_observation if op == "assert_observation"
                    else self.assert_hypothesis)
            call(tuple(triple) if triple is not None else None,
                 text=record.get("text"),
                 evidence=decode_evidence(record.get("evidence", ())),
                 authority=_authority(record.get("authority")))
        elif op == "add_rule":
            self.add_rule(name=record.get("name", ""),
                          head=decode_pattern(record.get("head")),
                          body=[decode_pattern(item)
                                for item in record.get("body", ())],
                          authority=_rule_authority(record.get("authority")))
        elif op == "promote_rule":
            self.promote_rule(record.get("rule"),
                              _rule_authority(record.get("authority")))
        elif op == "add_goal":
            self.add_goal(decode_pattern(record.get("pattern")),
                          note=record.get("note", ""))
        elif op == "refute":
            self.refute(record.get("proposition"),
                        evidence=decode_evidence(record.get("evidence", ())))
        elif op == "declare_field":
            self.declare_field(record.get("field"),
                               record.get("cardinality"))
        elif op == "settle":
            self.settle(record.get("contradiction"), record.get("keep"),
                        evidence=decode_evidence(record.get("evidence", ())))
        elif op == "link":
            self.link(record.get("entity"), record.get("subject"),
                      evidence=decode_evidence(record.get("evidence", ())),
                      authority=_authority(record.get("authority")))
        elif op == "derive":
            # `links` is absent from every schema-2 `derive` and means the
            # empty list — the only thing a log written before links existed
            # could have meant.
            self.apply_delta(propositions=record.get("propositions", ()),
                             rules=record.get("rules", ()),
                             links=record.get("links", ()))
        else:  # pragma: no cover — check_snapshot closed the set already
            raise ReplayRefused(f"no way to apply {op!r}")

    # ── writing: propositions ───────────────────────────────────────────────

    def assert_observation(self, triple: Optional[Sequence[Any]] = None, *,
                           text: Optional[str] = None,
                           evidence: Iterable[EvidenceRef] = (),
                           authority: EvidenceAuthority =
                           EvidenceAuthority.SOURCE) -> str:
        """Record something the world showed us. Returns the claim id.

        ``authority`` must be ``DETERMINISTIC`` or ``SOURCE``.  This is one
        half of the wall: model output does not get in here under any
        spelling, so no amount of extraction confidence can produce an
        ``OBSERVED`` proposition.
        """
        if authority not in OBSERVATION_AUTHORITIES:
            raise AuthorityRefused(
                f"{authority.name} is model authority and an observation is "
                "not a thing a model can make; assert_hypothesis is the door "
                f"for it (observations accept "
                f"{', '.join(a.name for a in OBSERVATION_AUTHORITIES)})")
        return self._assert(triple, text, evidence, authority,
                            PropositionStatus.OBSERVED, "assert_observation")

    def assert_hypothesis(self, triple: Optional[Sequence[Any]] = None, *,
                          text: Optional[str] = None,
                          evidence: Iterable[EvidenceRef] = (),
                          authority: EvidenceAuthority =
                          EvidenceAuthority.MODEL_HYPOTHESIS) -> str:
        """Record something a model offered. Lands ``HYPOTHESIZED``.

        The other half of the wall, and the softer one: the authority must be
        a ``MODEL_*`` value, because a caller reaching for this method with a
        receipt in hand has confused the two doors and should be told so
        rather than have its deterministic evidence quietly downgraded.
        """
        if authority not in HYPOTHESIS_AUTHORITIES:
            raise AuthorityRefused(
                f"{authority.name} is not model authority; a hypothesis "
                "carries how the model produced it "
                f"({', '.join(a.name for a in HYPOTHESIS_AUTHORITIES)}), and "
                "evidence this good belongs at assert_observation")
        return self._assert(triple, text, evidence, authority,
                            PropositionStatus.HYPOTHESIZED,
                            "assert_hypothesis")

    def _assert(self, triple, text, evidence, authority, status, op) -> str:
        entity, field, value = _split(triple)
        text = None if text is None else str(text)
        if triple is None and text is None:
            raise CognitionError(
                "a proposition is a triple, or text, or both — not neither")
        refs = tuple(evidence)
        for ref in refs:
            if not isinstance(ref, EvidenceRef):
                raise CognitionError(
                    f"evidence is EvidenceRef, not {type(ref).__name__}")
        if not refs:
            raise CognitionError(
                "a proposition with no evidence is a claim with no receipt; "
                "the store exists so that every one of them traces to "
                "something, and there is no exception for a small one")
        # The door stamps. Unconditionally, over whatever the caller put
        # there: a ref's authority says which door it came through, and a
        # caller able to write it could file model output under SOURCE by
        # constructing the ref rather than by choosing the method.
        refs = tuple(ref.stamped(authority) for ref in refs)
        pid, _new = self._ingest(entity, field, value, text, status, authority,
                                 refs, derivation=None, stage=True)
        self._append(op,
                     triple=(None if triple is None
                             else encode_pattern((entity, field, value))),
                     text=text,
                     authority=authority.value,
                     evidence=encode_evidence(refs))
        return pid

    def refute(self, proposition: str,
               evidence: Iterable[EvidenceRef] = ()) -> str:
        """Mark a claim ``REFUTED`` and record the contradiction.

        Returns the contradiction's id.  The refutation is a first-class
        object like any other collision: one side is the proposition, the
        other side is the evidence that unseated it, and both are on the
        record.  Conclusions that rested on it are re-examined.

        **Idempotent in the store.**  The same refutation sent twice — a
        retry, a replayed step, a caller that did not keep track — writes its
        event both times and changes nothing the second time: no fresh
        revision, no second contradiction.  A ledger that grew a row per
        delivery would be counting messages and reporting them as
        disagreements.

        A ``HYPOTHESIZED`` proposition may be refuted, and that is the useful
        case rather than an oversight: "the model said this and it is wrong"
        is exactly what a shadow layer wants on the record.  The evidence
        refs are *not* stamped with a door, because a refutation is not one
        of the two doors.

        Anything that rested on the claim is re-examined either way; with
        nothing changed there is nothing resting on it that was not already
        retracted.
        """
        prop = self._props.get(proposition)
        if prop is None:
            raise UnknownId(f"no proposition {proposition!r}")
        refs = tuple(evidence)
        if not refs:
            raise CognitionError(
                "a refutation with no evidence is an opinion; name what "
                "unseated the claim")
        self._append("refute", proposition=proposition,
                     evidence=encode_evidence(refs))
        changes: Dict[str, Any] = {}
        if prop.status is not PropositionStatus.REFUTED:
            changes["status"] = PropositionStatus.REFUTED
        merged = _merge_evidence(prop.evidence, refs)
        if merged != prop.evidence:
            changes["evidence"] = merged
        if changes:
            self._revise(proposition, **changes)
        cid = self._contradict("refutation", proposition, None, refs,
                               f"{prop.render()} refuted")
        self._retract_dependents([proposition])
        return cid

    def settle(self, contradiction: str, keep: str,
               evidence: Iterable[EvidenceRef] = ()) -> str:
        """Pick a side of a value collision, with evidence. Returns the id.

        **The one deliberate exception to contesting being terminal**, and it
        is reachable only through this call.  The kept side returns to the
        status it held before the collision and re-enters the delta, so
        closure re-derives whatever rested on it; the other side becomes
        ``REFUTED``; the contradiction is marked ``settled`` and names which
        side was kept.  Conclusions that were retracted only because the kept
        side died come back with it.

        **The kernel executes a settlement and never decides one.**  Which
        side stands is a judgement about the world — a deterministic re-read,
        an operator, a later receipt — and it is made by whatever is attached
        above.  That separation is the whole reason a store that refuses to
        pick can be trusted: the moment this method took a policy argument,
        the kernel would be choosing between two receipts on a heuristic, in
        a place nobody would look.

        Only ``"value"`` collisions can be settled.  A refutation names one
        proposition and has no second side to choose; a ``"dead_premise"``
        retraction is settled by settling whatever killed the premise; a
        ``"hypothesis"`` report never moved anything, so there is nothing to
        undo.
        """
        self._require_schema(2, "settle")
        clash = self._contradictions.get(contradiction)
        if clash is None:
            raise UnknownId(f"no contradiction {contradiction!r}")
        if clash.kind != "value":
            raise CognitionError(
                f"{contradiction!r} is a {clash.kind!r}, and settling means "
                "choosing between two claims that cannot both stand; only a "
                "value collision has two such sides")
        if clash.settled:
            raise CognitionError(
                f"{contradiction!r} was already settled in favour of "
                f"{clash.kept!r}; a second settlement would be the store "
                "changing its mind with no record of having done so")
        if keep not in (clash.left, clash.right):
            raise CognitionError(
                f"{keep!r} is not party to {contradiction!r} "
                f"({clash.left!r} against {clash.right!r})")
        refs = tuple(evidence)
        if not refs:
            raise CognitionError(
                "a settlement with no evidence is a preference; name what "
                "decided it")
        loser = clash.right if keep == clash.left else clash.left
        self._append("settle", contradiction=contradiction, keep=keep,
                     evidence=encode_evidence(refs))
        self._contradictions[contradiction] = Contradiction(
            id=clash.id, kind=clash.kind, left=clash.left, right=clash.right,
            evidence=_merge_evidence(clash.evidence, refs),
            detail=clash.detail, settled=True, kept=keep)
        self._revise(keep, status=self._status_before_contest(keep))
        self._revise(loser, status=PropositionStatus.REFUTED,
                     evidence=_merge_evidence(self._props[loser].evidence,
                                              refs))
        self._pending_props[keep] = None
        revived = self._revive_dependents(keep)
        self._retract_dependents([loser])
        # **A revival is an arrival.** The kept side is live again and so is
        # everything that came back with it, and the store has not looked at
        # any of them since. With three values on a single-valued field the
        # third never collided — it arrived when the first two had already
        # contested each other and there was nothing live to disagree with —
        # so settling in favour of the first puts two live values on a field
        # that may hold one. Measuring the revived claims is what closes it.
        for pid in [keep] + list(revived):
            self._collide(pid)
        return contradiction

    def _status_before_contest(self, pid: str) -> PropositionStatus:
        """The last status this claim held that was not ``CONTESTED``.

        Read out of the revision history rather than guessed from the shape
        of the proposition, which is what the history is for: an observation
        that was contested comes back ``OBSERVED``, a conclusion comes back
        ``DERIVED``, and neither is inferred from whether it happens to have
        a derivation attached now.
        """
        for revision in reversed(self._history[pid]):
            if revision.status is not PropositionStatus.CONTESTED:
                return revision.status
        return PropositionStatus.OBSERVED  # pragma: no cover - see _collide

    def _revive_dependents(self, revived: str) -> Tuple[str, ...]:
        """Bring back what fell only because the settled side had died.

        The mirror of :meth:`_retract_dependents`, and bounded the same way:
        a conclusion comes back only if some derivation of it now has every
        premise live, and the ``dead_premise`` contradiction that recorded
        its fall is marked settled so the ledger does not keep asserting
        something the store has stopped believing.
        """
        work = deque([revived])
        seen = {revived}
        restored: List[str] = []
        while work:
            back = work.popleft()
            for did in list(self._by_premise.get(back, ())):
                conclusion = self._derivations[did].conclusion
                prop = self._props[conclusion]
                if prop.status is not PropositionStatus.CONTESTED:
                    continue
                alive = any(
                    all(self._props[premise].live
                        for premise in self._derivations[other].premises)
                    for other in self._by_conclusion.get(conclusion, ()))
                if not alive:
                    continue
                if self._status_before_contest(conclusion) is not \
                        PropositionStatus.DERIVED:
                    continue
                self._revise(conclusion, status=PropositionStatus.DERIVED)
                restored.append(conclusion)
                for clash in list(self._contradictions.values()):
                    if (clash.kind == "dead_premise" and not clash.settled
                            and clash.left == conclusion):
                        self._contradictions[clash.id] = Contradiction(
                            id=clash.id, kind=clash.kind, left=clash.left,
                            right=clash.right, evidence=clash.evidence,
                            detail=clash.detail, settled=True,
                            kept=conclusion)
                if conclusion not in seen:
                    seen.add(conclusion)
                    work.append(conclusion)
        return tuple(restored)

    # ── writing: links ──────────────────────────────────────────────────────

    def link(self, entity: str, subject: str, *,
             evidence: Iterable[EvidenceRef],
             authority: EvidenceAuthority) -> str:
        """Claim that one entity is *about* one subject. Returns the link id.

        ``subject`` is spelled ``kind:value``
        (:func:`~core.cognition.types.check_subject`) and is content-addressed:
        the same job named by two tools is one entity, which is the entire
        mechanism.  ``entity`` is whatever the layer above calls a receipt, and
        it may **not** be subject-spelled — see the refusals below.

        **A first-class claim, with the same two obligations every claim in
        this store has.**  ``evidence`` is required and non-empty (the receipt
        fact that carried the identifier, and a ref naming the declaration that
        said the key *was* an identifier), and ``authority`` is stamped onto
        every ref at this door, over whatever the caller put there, exactly as
        the two assertion doors do.  There is no default authority, on purpose
        and permanently: a caller that does not say how it knows two receipts
        are about one thing has not said it, and "probably deterministic" is
        the guess this whole package exists to refuse.

        A deterministic linker passes ``SOURCE``.  ``DETERMINISTIC`` is
        accepted but is almost always wrong for one: the weakest premise under
        a declared link is the platform's *declaration*, and grading the link
        above it would launder a platform's word into a measurement.  The
        ``MODEL_*`` grades are accepted too and nothing in this release passes
        one; what they already do is described on
        :class:`~core.cognition.types.Link` and enforced in :meth:`_project` —
        their projections land ``HYPOTHESIZED``, so a guessed identity can
        never contest an observation.

        **Idempotent on the pair.**  The same ``(entity, subject)`` stated
        again is the same link: its evidence unions, its authority rises to the
        strongest offered, and a fresh revision is written only if something
        changed — the edge-identity discipline of
        :mod:`core.cognition.graph`.  The *event* is written either way, as
        :meth:`refute`'s is and for the same reason: the log is what a replay
        applies, and a call that changed nothing has to be in it for the
        replay to reach the same store by the same route.  An upgraded link
        re-measures its
        projections (a model's guess later confirmed by a declaration promotes
        what it projected) without minting a second proof of anything.

        **Four refusals, and each one is a hole somebody would otherwise
        find.**

        * An ``entity`` the store holds nothing about.  A link is a claim that
          *this receipt* is about that subject; a receipt this store never saw
          is not a receipt, the subject would be born with nothing to project,
          and the log would name an entity its own events cannot explain.
        * A subject-spelled ``entity``.  This is the namespace wall, and it
          does two jobs at once: it keeps a receipt from being linked under a
          second spelling, and it makes "a projection never re-projects"
          structural rather than a rule somebody has to remember — a subject
          can never be the *source* end of a link, so a projected fact can
          never project again.  Chaining subjects is a Phase 20 graph question
          with its own evidence; in v1 it is refused with its reason.
        * A self-link.  It is the same refusal as the one above (the entity
          would have to be subject-spelled to equal the subject), which is why
          there is no second check: one wall, not two that can drift apart.
        * Evidence that is empty or is not
          :class:`~core.cognition.types.EvidenceRef`.

        **What is deliberately *not* a refusal:** a second subject for one
        entity.  One receipt legitimately names a job *and* an asset, and its
        facts project onto both.
        """
        self._require_schema(3, "link")
        if not isinstance(entity, str) or not entity:
            raise CognitionError("a link's entity is a non-empty string")
        check_subject(subject)
        if subject_parts(entity) is not None:
            raise CognitionError(
                f"{entity!r} is spelled as a subject, and a subject is never "
                "the near end of a link: it is what receipts are about, not a "
                "thing that is about something else. A projection that could "
                "project again would let one declaration walk a chain nobody "
                "declared")
        if entity not in self._by_entity:
            raise UnknownId(
                f"this store holds nothing about {entity!r}, so there is "
                "nothing for a link to be a claim about; assert what the "
                "receipt showed before saying what it was about")
        if not isinstance(authority, EvidenceAuthority):
            raise CognitionError(
                f"a link's authority is an EvidenceAuthority, not "
                f"{type(authority).__name__}")
        refs = tuple(evidence)
        for ref in refs:
            if not isinstance(ref, EvidenceRef):
                raise CognitionError(
                    f"evidence is EvidenceRef, not {type(ref).__name__}")
        if not refs:
            raise CognitionError(
                "a link with no evidence is a guess about identity, which is "
                "the one mistake in this design that manufactures "
                "contradictions; name the receipt field and the declaration")
        refs = tuple(ref.stamped(authority) for ref in refs)
        self._append("link", entity=entity, subject=subject,
                     authority=authority.value, evidence=encode_evidence(refs))
        held = self._link_key.get((entity, subject))
        if held is not None:
            self._merge_link(held, authority, refs)
            return held
        self._counters["l"] += 1
        lid = f"l{self._counters['l']}"
        record = Link(id=lid, entity=entity, subject=subject,
                      authority=authority, evidence=refs)
        self._links[lid] = record
        self._link_history[lid] = [record]
        self._link_key[(entity, subject)] = lid
        self._links_by_entity.setdefault(entity, []).append(lid)
        self._links_by_subject.setdefault(subject, []).append(lid)
        self._pending_links[lid] = None
        return lid

    def _merge_link(self, lid: str, authority: EvidenceAuthority,
                    refs: Tuple[EvidenceRef, ...]) -> None:
        """Union the evidence, take the strongest authority, revise if changed.

        A link whose authority rose re-enters the delta, because the grade of
        every fact it projected is capped by it: a link first guessed and later
        declared lifts what it carried, and a store that left the projections
        at the old grade would be understating its own evidence for as long as
        nobody looked.
        """
        held = self._links[lid]
        merged = _merge_evidence(held.evidence, refs)
        stronger = (authority if AUTHORITY_RANK[authority]
                    > AUTHORITY_RANK[held.authority] else held.authority)
        if merged == held.evidence and stronger is held.authority:
            return
        fresh = Link(id=held.id, entity=held.entity, subject=held.subject,
                     authority=stronger, evidence=merged,
                     revision=held.revision + 1, previous=held.key)
        self._links[lid] = fresh
        self._link_history[lid].append(fresh)
        if stronger is not held.authority:
            self._pending_links[lid] = None

    # ── writing: fields, rules and goals ────────────────────────────────────

    def declare_field(self, field: str, cardinality: str) -> str:
        """Say whether one entity may hold one value of this field, or many.

        ``"one"`` turns on collision detection for the field;  ``"many"`` is
        what every undeclared field already is.  See :meth:`_collide` for why
        that is the default and why the asymmetry decides it.

        Re-declaring the same cardinality is a no-op.  Re-declaring a
        *different* one is refused: propositions have already been contested
        (or not) under the old answer, and quietly changing it would leave a
        store whose ledger cannot be explained by its own rules.  A field
        that needs a different answer is a modelling change, and it belongs
        in a fresh store rather than half-applied to this one.
        """
        if cardinality not in CARDINALITIES:
            raise CognitionError(
                f"{cardinality!r} is not a cardinality; "
                f"{' or '.join(repr(c) for c in CARDINALITIES)}")
        self._require_schema(2, "declare_field")
        if not isinstance(field, str) or not field:
            raise CognitionError("a field is a non-empty string")
        held = self._cardinality.get(field)
        if held is not None and held != cardinality:
            raise CognitionError(
                f"{field!r} was declared {held!r} and propositions have been "
                f"measured against that; it cannot become {cardinality!r} "
                "half way through a store's life")
        self._cardinality[field] = cardinality
        self._append("declare_field", field=field, cardinality=cardinality)
        if cardinality == "one":
            # **The declaration applies to what the store already holds.**
            # Refusing to declare over an occupied field was the alternative
            # and it makes pack-load order fragile in the one arrangement
            # that is normal: a resume replays the session's observations and
            # the skill's rule pack is loaded *after* it, so the declaration
            # almost always arrives second. A pack whose collision checks
            # depended on having been loaded first would work in development
            # and stop working on the first resume.
            #
            # Insertion order, so the result is a function of the store and
            # not of the dict's iteration: the earliest proposition is the
            # one still standing when the later ones collide with it.
            for pid in list(self._by_field.get(field, ())):
                self._collide(pid)
        return field

    def cardinality(self, field: Optional[str]) -> str:
        """What a field was declared, or the default for this store's schema.

        Schema 1 had no declarations and treated every field as single-valued;
        schema 2 turned the default round (see :meth:`_collide`). A store
        replayed from a v1 log keeps the v1 default, because a v1 log can
        contain contradictions that only exist under it.
        """
        default = DEFAULT_CARDINALITY if self._schema >= 2 else "one"
        if field is None:
            return default
        return self._cardinality.get(field, default)

    # ── writing: rules and goals ────────────────────────────────────────────

    def add_rule(self, name: str, head: Sequence[Any],
                 body: Sequence[Sequence[Any]],
                 authority: RuleAuthority = RuleAuthority.PROPOSED) -> str:
        """Store a horn clause. Default authority is ``PROPOSED``.

        The default is the wall's shape: a caller that does not say who stands
        behind a rule has not said it is trusted, and the store treats silence
        as the model's voice rather than its own.
        """
        head_pattern = check_pattern(head)
        body_patterns = tuple(check_pattern(item) for item in body)
        if not body_patterns:
            raise RuleMalformed(
                f"rule {name!r} has an empty body; a rule with no premises is "
                "an observation, and observations come with evidence")
        bound = {var for pattern in body_patterns
                 for var in variables_in(pattern)}
        loose = [var for var in variables_in(head_pattern) if var not in bound]
        if loose:
            raise RuleMalformed(
                f"rule {name!r} concludes about {', '.join(loose)}, which its "
                "body never binds; it cannot name what it would derive")
        self._counters["r"] += 1
        rid = f"r{self._counters['r']}"
        rule = Rule(id=rid, name=str(name), authority=authority,
                    head=head_pattern, body=body_patterns)
        self._rules[rid] = rule
        for pattern in body_patterns:
            key = None if is_variable(pattern[1]) else pattern[1]
            bucket = self._rules_by_field.setdefault(key, [])
            if rid not in bucket:
                bucket.append(rid)
        self._append("add_rule", name=rule.name, authority=authority.value,
                     head=encode_pattern(head_pattern),
                     body=[encode_pattern(item) for item in body_patterns])
        if rule.participates_in_closure:
            self._pending_rules[rid] = None
        return rid

    def promote_rule(self, rule: str, authority: RuleAuthority) -> str:
        """Give a ``PROPOSED`` rule an authority that derives.

        The explicit call the wall is made of.  A model may write a rule into
        this store all day; until somebody who is not the model names an
        authority for it, it matches nothing and concludes nothing.  Promoting
        *to* ``PROPOSED`` is refused, because that is not a promotion and a
        method that accepted it would be a way to spell "trust me" twice.

        **Only from ``PROPOSED``.**  A rule that already has an authority is
        not promoted by this method — ``SKILL`` to ``DOMAIN`` is a *lateral*
        move, it re-labels who stands behind a clause that is already
        deriving, and its derivations carry the old label.  There is no
        re-authorisation in v1: a rule that needs a different owner is a
        different rule, added under it.  Left open, this method would be the
        way a caller quietly restamped somebody else's clause as its own.
        """
        existing = self._rules.get(rule)
        if existing is None:
            raise UnknownId(f"no rule {rule!r}")
        if authority == RuleAuthority.PROPOSED:
            raise AuthorityRefused(
                "promote_rule names the authority that stands behind the "
                "rule; PROPOSED is the absence of one")
        if existing.authority is not RuleAuthority.PROPOSED \
                and self._schema >= 2:
            raise AuthorityRefused(
                f"rule {rule!r} already stands on "
                f"{existing.authority.name}; promotion is PROPOSED to "
                "trusted and nothing else, and re-labelling a clause that is "
                "already deriving is not a promotion. Add the rule again "
                "under the authority that wants it")
        self._rules[rule] = Rule(id=existing.id, name=existing.name,
                                 authority=authority, head=existing.head,
                                 body=existing.body)
        self._append("promote_rule", rule=rule, authority=authority.value)
        self._pending_rules[rule] = None
        return rule

    def add_goal(self, pattern: Sequence[Any], note: str = "") -> str:
        """Name a target pattern. Obligations are computed from it."""
        target = check_pattern(pattern)
        self._counters["g"] += 1
        gid = f"g{self._counters['g']}"
        self._goals[gid] = Goal(id=gid, pattern=target, note=str(note))
        self._append("add_goal", pattern=encode_pattern(target),
                     note=str(note))
        return gid

    # ── the engine ──────────────────────────────────────────────────────────

    def derive(self) -> Tuple[str, ...]:
        """Flush the staging area. Returns the ids newly derived.

        This is the whole of ``derive``: the work happens in
        :meth:`apply_delta`, and everything staged since the last flush is the
        delta.  A flush with nothing staged does nothing and writes nothing.
        """
        return self.apply_delta(propositions=tuple(self._pending_props),
                                rules=tuple(self._pending_rules),
                                links=tuple(self._pending_links))

    def apply_delta(self, propositions: Sequence[str] = (),
                    rules: Sequence[str] = (),
                    links: Sequence[str] = ()) -> Tuple[str, ...]:
        """Semi-naive closure over a delta, to fixpoint. One ``derive`` event.

        ``propositions`` are ids that have just become live; ``rules`` are
        ids that have just become trusted; ``links`` are ids that have just
        been made or whose authority has just risen.  For a proposition delta
        only the rules with a body premise on one of the delta's *fields* are
        considered, and each such rule is joined once per body position that
        the delta can fill — the pinned position draws from the delta, every
        other position from the store.  That is what makes the work
        proportional to what changed.  For a rule delta the rule is joined
        against the whole store once, which is the only honest thing to do
        with a clause nobody had run before.

        **Projection runs from both ends of the delta, and that is the whole
        of order-independence.**  A link in the delta projects the facts its
        entity already holds; a fact in the delta projects onto the subjects
        its entity is already linked to.  Neither direction is the "normal"
        one — the shadow above links a receipt at the moment it harvests it,
        and which of the two lands first is a detail of a loop nobody should
        have to think about — so a store that only handled one would give a
        different answer for the same mission depending on the order of two
        calls in one step.  ``tests/test_cognition_kernel.py`` holds the two
        orders to the same digest.

        Re-deriving something the store already holds adds a
        :class:`~core.cognition.types.Derivation` — an alternative proof — and
        never a second proposition.  Termination rests on that: derivations
        are deduplicated by ``(rule, premises, conclusion)``, so a cycle stops
        producing new ones and the loop ends.  A projection is deduplicated by
        the same key with the link in it, and its conclusions land on subject
        entities, which can never be the near end of a link — so projection
        adds no cycle of its own.
        """
        unknown = ([pid for pid in propositions if pid not in self._props]
                   + [rid for rid in rules if rid not in self._rules]
                   + [lid for lid in links if lid not in self._links])
        if unknown:
            # Silently dropping them was a PARTIAL application: a `derive`
            # event naming a proposition this store never assigned is a log
            # that does not describe this store, and closing over the rest
            # builds something plausible out of it.
            raise UnknownId(
                f"apply_delta was given {unknown!r}, which this store never "
                "assigned; a delta is not applied in part")
        prop_delta = list(propositions)
        rule_delta = list(rules)
        link_delta = list(links)
        if not prop_delta and not rule_delta and not link_delta:
            return ()
        self._append("derive", propositions=list(propositions),
                     rules=list(rules), links=list(links))
        for pid in propositions:
            self._pending_props.pop(pid, None)
        for rid in rules:
            self._pending_rules.pop(rid, None)
        for lid in links:
            self._pending_links.pop(lid, None)

        derived: List[str] = []
        while prop_delta or rule_delta or link_delta:
            self.stats.delta_passes += 1
            produced: List[str] = []
            for rid in rule_delta:
                rule = self._rules[rid]
                if not rule.participates_in_closure:
                    continue
                self.stats.rules_considered += 1
                produced.extend(self._run(rule, None, None))
            if prop_delta:
                live = [pid for pid in prop_delta
                        if self._props[pid].live and self._props[pid].field]
                fields = []
                for pid in live:
                    name = self._props[pid].field
                    if name not in fields:
                        fields.append(name)
                for rid in self._candidate_rules(fields):
                    rule = self._rules[rid]
                    if not rule.participates_in_closure:
                        continue
                    self.stats.rules_considered += 1
                    for position, pattern in enumerate(rule.body):
                        pool = [pid for pid in live
                                if unify(pattern,
                                         self._props[pid].triple) is not None]
                        if pool:
                            produced.extend(self._run(rule, position, pool))
            if prop_delta or link_delta:
                produced.extend(self._project(prop_delta, link_delta))
            derived.extend(produced)
            prop_delta = produced
            rule_delta = []
            link_delta = []
        return tuple(derived)

    def _project(self, facts: Sequence[str],
                 links: Sequence[str]) -> List[str]:
        """The built-in rule: every live triple of a linked entity, at its
        subject.

        Both directions of the delta in one walk, deduplicated on the
        ``(link, fact)`` pair so that a step which carries *both* a new link
        and new facts on its entity does the work once and in one order.  The
        pairs are enumerated links-first and then facts-first, each in
        insertion order, which is what makes the two arrival orders produce
        the same store and not merely the same beliefs.

        Three bounds, each stated where it is applied:

        * **only live triples.**  A hypothesis does not project — it would
          arrive at the subject as something a rule could join, which is
          exactly the promotion the authority walls exist to stop — and
          neither does a contested or refuted fact.  When a hypothesis is
          later observed it becomes live, enters the delta, and projects then.
        * **text does not project** (v1 bound).  A text proposition has no
          entity at all in this store, so there is nothing to project it
          *from*; a proposition carrying both a triple and text projects the
          triple alone, because the text is prose about the receipt and this
          kernel does not read English well enough to know whether it is also
          prose about the subject.
        * **a model-graded link projects hypotheses.**  The status is
          ``DERIVED`` only if the link came through an observation-grade door;
          otherwise the projection lands ``HYPOTHESIZED``, which keeps it out
          of closure and out of every contest.  A guessed identity can report
          a disagreement with a receipt and can never win one.

        The authority is the weaker of the fact's and the link's, which is the
        same rule :meth:`_run` applies to a derivation's premises — a chain is
        worth its worst link, and here the link *is* one.
        """
        pairs: List[Tuple[str, str]] = []
        for lid in links:
            for pid in self._by_entity.get(self._links[lid].entity, ()):
                pairs.append((lid, pid))
        for pid in facts:
            prop = self._props[pid]
            if prop.entity is None:
                continue
            for lid in self._links_by_entity.get(prop.entity, ()):
                pairs.append((lid, pid))
        out: List[str] = []
        seen: set = set()
        for lid, pid in pairs:
            if (lid, pid) in seen:
                continue
            seen.add((lid, pid))
            prop = self._props[pid]
            if prop.triple is None or not prop.live:
                continue
            link = self._links[lid]
            status = (PropositionStatus.DERIVED
                      if link.authority in OBSERVATION_AUTHORITIES
                      else PropositionStatus.HYPOTHESIZED)
            authority = min((prop.authority, link.authority),
                            key=lambda a: AUTHORITY_RANK[a])
            conclusion = (link.subject, prop.field, prop.value)
            key = (PROJECTION_RULE_ID, (pid,), conclusion, lid)
            proof = key not in self._derivation_keys
            did = None
            if proof:
                # Allocated before the ingest and handed to it, so a projected
                # proposition is born at revision 1 — the same reason `_run`
                # does it in that order.
                self._counters["d"] += 1
                did = f"d{self._counters['d']}"
            # An upgraded link re-ingests without a second proof: the merge
            # rules lift the status and the authority of what it already
            # projected, and a proof is not a change of belief.
            cid, is_new = self._ingest(conclusion[0], conclusion[1],
                                       conclusion[2], None, status, authority,
                                       (), derivation=did, stage=False)
            if proof:
                self._derivations[did] = Derivation(
                    id=did, rule=PROJECTION_RULE_ID, premises=(pid,),
                    conclusion=cid, link=lid)
                self._derivation_keys.add(key)
                self._by_conclusion.setdefault(cid, []).append(did)
                bucket = self._by_premise.setdefault(pid, [])
                if did not in bucket:
                    bucket.append(did)
            if is_new:
                out.append(cid)
        return out

    def _candidate_rules(self, fields: Sequence[str]) -> List[str]:
        """Rules whose body mentions one of these fields, plus the wildcards.

        Insertion order, deduplicated.  A rule whose body premise has a
        *variable* field can match anything and lives in the ``None`` bucket,
        so it is always a candidate — correct, and the reason a rule pack of
        wholly-variable premises would lose the benefit of this index.
        """
        out: Dict[str, None] = {}
        for name in list(fields) + [None]:
            for rid in self._rules_by_field.get(name, ()):
                out[rid] = None
        return sorted(out, key=lambda rid: int(rid[1:]))

    def _run(self, rule: Rule, position: Optional[int],
             pool: Optional[Sequence[str]]) -> List[str]:
        """Join one rule body and ingest every conclusion it licenses.

        **The pinned premise is evaluated first**, and the rest follow in body
        order with its bindings already in hand.  Body order alone was wrong
        by an order of magnitude whenever the pin was not premise zero: the
        join started from an unconstrained early premise and scanned whole
        columns of the store before ever reaching the two or three
        propositions that had actually changed.  Starting from the delta
        makes the work proportional to the delta, which is the entire claim
        semi-naive closure makes.

        Premises are still *recorded* in body order — a derivation names its
        premises the way the rule reads, not the way the engine happened to
        walk them — so the evaluation order is invisible in the result.  What
        it does change is the order conclusions are enumerated in, and
        therefore which ``pN`` each gets; that is the whole of why
        :data:`~core.cognition.events.KERNEL_VERSION` exists.
        """
        self.stats.body_scans += 1
        width = len(rule.body)
        if position is None:
            order = range(width)
        else:
            order = [position] + [i for i in range(width) if i != position]
        envs: List[Tuple[Bindings, Dict[int, str]]] = [({}, {})]
        for index in order:
            pattern = rule.body[index]
            draw = pool if index == position else None
            nxt: List[Tuple[Bindings, Dict[int, str]]] = []
            for bindings, chosen in envs:
                for pid in self._matches(pattern, bindings, draw):
                    extended = unify(pattern, self._props[pid].triple, bindings)
                    if extended is not None:
                        picked = dict(chosen)
                        picked[index] = pid
                        nxt.append((extended, picked))
            envs = nxt
            if not envs:
                return []
        out: List[str] = []
        for bindings, chosen in envs:
            premises = tuple(chosen[i] for i in range(width))
            conclusion = resolve(rule.head, bindings)
            authority = min((self._props[pid].authority for pid in premises),
                            key=lambda a: AUTHORITY_RANK[a])
            key = (rule.id, premises, conclusion)
            if key in self._derivation_keys:
                continue
            # The derivation id is allocated BEFORE the proposition and
            # handed to it, so a derived proposition is born at revision 1.
            # It used to be born, then immediately revised to record the
            # proof that had just made it — two revisions for one event, and
            # a history saying the store changed its mind about something it
            # had held for no time at all. `types.py` states the rule this
            # broke in as many words: a proof is not a change of belief.
            self._counters["d"] += 1
            did = f"d{self._counters['d']}"
            pid, is_new = self._ingest(conclusion[0], conclusion[1],
                                       conclusion[2], None,
                                       PropositionStatus.DERIVED, authority,
                                       (), derivation=did, stage=False)
            self._derivations[did] = Derivation(id=did, rule=rule.id,
                                                premises=premises,
                                                conclusion=pid)
            self._derivation_keys.add(key)
            self._by_conclusion.setdefault(pid, []).append(did)
            for premise in premises:
                bucket = self._by_premise.setdefault(premise, [])
                if did not in bucket:
                    bucket.append(did)
            if is_new:
                out.append(pid)
        return out

    def _matches(self, pattern, bindings: Bindings,
                 pool: Optional[Sequence[str]]) -> List[str]:
        """Live triple propositions a pattern could match, insertion order.

        The index is chosen by what the pattern has *ground* after the
        bindings so far are applied: entity first because it is the most
        selective, then field, then everything.  A pinned pool skips the
        index — that is the delta, and it is already small — but **not the
        liveness check**, and the difference is a bug this file had.

        The pool is filtered when the pass *starts*.  Closure then runs
        several rules against it, and a conclusion produced early in the pass
        can collide with something and leave both sides ``CONTESTED`` — so a
        proposition that was live when the pool was built is not necessarily
        live when the fourth rule reaches it.  Returning it anyway derived
        conclusions from a contested premise, and because those conclusions
        were built *after* the retraction cascade had already run, nothing
        came back to retract them: a live ``DERIVED`` proposition whose only
        proof rested on something the store had already refused to believe,
        with no ``dead_premise`` contradiction anywhere on the record.
        """
        if pool is not None:
            found = [pid for pid in pool
                     if self._props[pid].live and self._props[pid].triple]
            self.stats.candidates_scanned += len(found)
            return found
        entity, field, _value = resolve(pattern, bindings)
        entity_known = not is_variable(entity)
        field_known = not is_variable(field)
        if entity_known and field_known:
            # The pair index. It was maintained from the first commit and
            # read by nothing — `_collide` used it and the join did not — so
            # a premise with both terms bound scanned the whole entity's
            # column to find the one field it wanted. With the pinned premise
            # now evaluated first, this is the common case rather than the
            # rare one: the delta binds the entity, and every premise after
            # it arrives here already ground.
            candidates = self._by_entity_field.get((entity, field), ())
        elif entity_known:
            candidates = self._by_entity.get(entity, ())
        elif field_known:
            candidates = self._by_field.get(field, ())
        else:
            candidates = list(self._props)
        found = [pid for pid in candidates
                 if self._props[pid].live and self._props[pid].triple]
        self.stats.candidates_scanned += len(found)
        return found

    # ── the store's internals ───────────────────────────────────────────────

    def _ingest(self, entity, field, value, text, status, authority, evidence,
                derivation, stage: bool) -> Tuple[str, bool]:
        """Add or merge a claim. Returns ``(id, entered_the_delta)``.

        The second element is *not* "was new": it is "is this now available to
        closure when it was not before", which is true for a fresh live
        proposition and also for a held hypothesis that an observation has
        just promoted.  A merge that promotes a claim into life is a delta,
        and treating it as "not new" was the shape of the first bug this
        engine had.

        The merge rules, in one place because there is one place a claim can
        be settled: status takes the stronger of the two by
        :data:`~core.cognition.types.STATUS_RANK` unless the held one is
        terminal, authority takes the stronger, evidence unions.  So an
        observation of something already hypothesized promotes it, a
        hypothesis about something already observed does not demote it, and a
        rule deriving something already observed leaves it ``OBSERVED`` while
        still recording the derivation.
        """
        key = (("triple", entity, field, value_tag(value), value)
               if entity is not None else ("text", text))
        held = self._claim_key.get(key)
        if held is not None:
            prop = self._props[held]
            changes: Dict[str, Any] = {}
            if prop.status in STATUS_RANK and status in STATUS_RANK:
                if STATUS_RANK[status] > STATUS_RANK[prop.status]:
                    changes["status"] = status
            if AUTHORITY_RANK[authority] > AUTHORITY_RANK[prop.authority]:
                changes["authority"] = authority
            merged = _merge_evidence(prop.evidence, evidence)
            if merged != prop.evidence:
                changes["evidence"] = merged
            if text is not None and prop.text is None:
                changes["text"] = text
            if derivation is not None and prop.derivation is None:
                changes["derivation"] = derivation
            was_live = prop.live
            if changes:
                self._revise(held, **changes)
            became_live = self._props[held].live and not was_live
            # **Only a claim that just became live is a delta.** A
            # re-assertion of something the store already holds live —
            # the same triple, the same value, a second receipt — changes
            # nothing closure could act on, and staging it made the next
            # flush re-run every rule over that field for no conclusion. It
            # cannot lose a derivation: a conclusion is deduplicated by
            # (rule, premises, conclusion), so the re-run could only ever
            # have produced proofs the store already had.
            if stage and became_live:
                self._pending_props[held] = None
            if became_live:
                self._collide(held)
            return held, became_live

        if entity is not None:
            check_value(value)
        self._counters["p"] += 1
        pid = f"p{self._counters['p']}"
        prop = Proposition(id=pid, entity=entity, field=field, value=value,
                           text=text, status=status, authority=authority,
                           evidence=tuple(evidence), derivation=derivation)
        self._props[pid] = prop
        self._history[pid] = [prop]
        self._claim_key[key] = pid
        if entity is not None:
            self._by_entity.setdefault(entity, []).append(pid)
            self._by_field.setdefault(field, []).append(pid)
            self._by_entity_field.setdefault((entity, field), []).append(pid)
        if stage:
            self._pending_props[pid] = None
        # Every new triple proposition is measured against what the store
        # already holds, hypotheses included — a model's claim disagreeing
        # with a receipt is a signal whether or not it moves a status.
        # A re-assertion never reaches here: same value is the same claim and
        # merges above, so arriving as a new proposition IS the disagreement.
        self._collide(pid)
        return pid, True

    def _revise(self, pid: str, **changes: Any) -> Proposition:
        """Write a new revision. The old one stays reachable, by key."""
        old = self._props[pid]
        fresh = Proposition(
            id=old.id,
            entity=changes.get("entity", old.entity),
            field=changes.get("field", old.field),
            value=changes.get("value", old.value),
            text=changes.get("text", old.text),
            status=changes.get("status", old.status),
            authority=changes.get("authority", old.authority),
            evidence=changes.get("evidence", old.evidence),
            derivation=changes.get("derivation", old.derivation),
            revision=old.revision + 1,
            previous=old.key,
        )
        self._props[pid] = fresh
        self._history[pid].append(fresh)
        return fresh

    def _collide(self, pid: str) -> None:
        """Measure one proposition against everything else about its field.

        Two outcomes, and only one of them moves a status.

        **Live against live** is the collision this store is named for: two
        propositions giving one ``(entity, field)`` different values, both
        contested, nothing winning.

        **A hypothesis against a live proposition** is a *report*.  The
        hypothesis stays ``HYPOTHESIZED``, the observation stays live, and a
        ``"hypothesis"`` contradiction names the pair — left the hypothesis,
        right the observation, whichever arrived first, so a consumer reads
        one shape and not two.  This is the first signal the shadow layer
        wants (the model said one thing, the receipt said another) and it
        must never be more than a signal: contest the observation here and a
        wrong extraction has unseated a receipt, which is the laundering the
        authority walls exist to prevent.  Marking confidence, not gating.

        The hypothesis reports are recorded before any contesting, so that a
        live proposition arriving into a disagreement is still live when it is
        compared with the model's version of it.

        **Only for a field somebody declared single-valued.**  Both outcomes
        above rest on "these two cannot both be true", which is a claim about
        the *field* — right for ``total_s`` and wrong for ``controls`` — and
        nothing in a triple says which it is.  So
        :meth:`declare_field` says, and a field nobody declared is
        :data:`~core.cognition.types.DEFAULT_CARDINALITY`, which is ``many``.

        That default is the opposite of the one the first version shipped
        with, and the argument for turning it round is asymmetry.  Contesting
        is terminal: it takes both sides out of closure and everything
        derived from either of them, permanently — so a *false* contradiction
        on a multi-valued field does not merely report a disagreement that
        is not there, it can take an entity out of the store's reasoning
        altogether.  A *missed* contradiction costs a signal nobody got.
        Under the owner's ruling — this layer is shadow and additive, and a
        working harness beats a strict one — the destructive failure is the
        one to default away from.  A pack that wants the check declares it,
        field by field, and gets it exactly where it means something.
        """
        prop = self._props[pid]
        if prop.triple is None:
            return
        if self.cardinality(prop.field) != "one":
            return
        mine = (value_tag(prop.value), prop.value)
        others = [other for other in
                  self._by_entity_field.get((prop.entity, prop.field), ())
                  if other != pid
                  and (value_tag(self._props[other].value),
                       self._props[other].value) != mine]

        # The report first, while both sides still hold the status they
        # arrived with.
        if prop.status is PropositionStatus.HYPOTHESIZED:
            for other in others:
                if self._props[other].live:
                    self._disagree(pid, other)
                elif self._props[other].status is \
                        PropositionStatus.HYPOTHESIZED:
                    # Two model claims about one field, disagreeing. This was
                    # dismissed as "the model being uncertain, which is not
                    # news" — and that was wrong about what a shadow layer is
                    # for. Two *extractors* disagreeing over one receipt is
                    # the cheapest available sign that the extraction step is
                    # where a mission is going wrong, and it is there before
                    # any receipt arrives to settle it. Recorded like every
                    # other disagreement and moving nothing: neither claim
                    # outranks the other and the store has no receipt to
                    # prefer either.
                    #
                    # The pair is CANONICALISED, and that is not cosmetic.
                    # Every other disagreement has a side that fixes the
                    # orientation — the hypothesis goes left, the observation
                    # right — and this one does not, so `(H1, H2)` and
                    # `(H2, H1)` are two different dedup keys for one fact.
                    # Nothing notices while each claim arrives once; a late
                    # `declare_field` walks the field and re-measures every
                    # proposition on it, meeting the pair from both ends, and
                    # writes the same disagreement twice.
                    self._disagree(*self._ordered(pid, other))
        elif prop.live:
            for other in others:
                if self._props[other].status is \
                        PropositionStatus.HYPOTHESIZED:
                    self._disagree(other, pid)

        if not prop.live:
            return
        clashing = [other for other in others if self._props[other].live]
        if not clashing:
            return
        for other in clashing:
            self._contradict(
                "value", pid, other, (),
                f"{prop.render()} against {self._props[other].render()}")
            self._revise(other, status=PropositionStatus.CONTESTED)
        self._revise(pid, status=PropositionStatus.CONTESTED)
        self._retract_dependents([pid] + clashing)

    @staticmethod
    def _ordered(left: str, right: str) -> Tuple[str, str]:
        """One orientation for a pair with no natural one: insertion order.

        Ids are handed out in insertion order, so the earlier claim goes
        first — which makes the row a fact about the store rather than about
        which end of the pair a walk happened to reach first.
        """
        return ((left, right) if int(left[1:]) <= int(right[1:])
                else (right, left))

    def _disagree(self, hypothesis: str, observed: str) -> None:
        """Record a model's claim against the store's, and change nothing.

        For a hypothesis against an observation the argument names say what
        they mean. For two hypotheses the caller canonicalises first (see
        :meth:`_ordered`), and then ``left`` is simply the earlier claim.
        """
        self._contradict(
            "hypothesis", hypothesis, observed, (),
            f"{self._props[hypothesis].render()} was offered against "
            f"{self._props[observed].render()}")

    def _contradict(self, kind: str, left: str, right: Optional[str],
                    evidence: Tuple[EvidenceRef, ...], detail: str) -> str:
        """Record a collision once. The same pair found again is the same one.

        Deduplicated on ``(kind, left, right)``.  Three of the four kinds
        cannot recur on their own — a value collision leaves both sides
        contested and out of the running — but a ``"hypothesis"`` report can:
        the hypothesis stays hypothesized and the observation stays live, so
        every re-assertion measures them against each other again.  A ledger
        that grew a row per delivery would be counting retries and calling
        them disagreements.
        """
        assert kind in CONTRADICTION_KINDS, kind
        key = (kind, left, right)
        existing = self._contradiction_keys.get(key)
        if existing is not None and not self._contradictions[existing].settled:
            return existing
        # A SETTLED row is history — it records a disagreement somebody
        # resolved, with the evidence they resolved it on. If the same pair
        # collides again the store is finding out something new, and folding
        # that into the old row would overwrite the settlement with the fact
        # that it did not hold. Fresh row; the settled one stays as it was.
        self._counters["c"] += 1
        cid = f"c{self._counters['c']}"
        self._contradictions[cid] = Contradiction(
            id=cid, kind=kind, left=left, right=right,
            evidence=tuple(evidence), detail=detail)
        self._contradiction_keys[key] = cid
        return cid

    def _retract_dependents(self, dead: Sequence[str]) -> None:
        """The retraction rule, cascading. See the module docstring."""
        work = deque(dead)
        seen = set(work)
        while work:
            gone = work.popleft()
            for did in list(self._by_premise.get(gone, ())):
                conclusion = self._derivations[did].conclusion
                prop = self._props[conclusion]
                if prop.status != PropositionStatus.DERIVED:
                    continue
                proofs = self._by_conclusion.get(conclusion, ())
                alive = any(
                    all(self._props[premise].live
                        for premise in self._derivations[other].premises)
                    for other in proofs)
                if alive:
                    continue
                self._contradict(
                    "dead_premise", conclusion, gone, (),
                    f"{prop.render()} rests on {self._props[gone].render()}, "
                    f"which is {self._props[gone].status.value}")
                self._revise(conclusion, status=PropositionStatus.CONTESTED)
                if conclusion not in seen:
                    seen.add(conclusion)
                    work.append(conclusion)

    # ── reading ─────────────────────────────────────────────────────────────

    def proposition(self, pid: str) -> Proposition:
        """The live revision of one claim."""
        self.derive()
        prop = self._props.get(pid)
        if prop is None:
            raise UnknownId(f"no proposition {pid!r}")
        return prop

    def history(self, pid: str) -> Tuple[Proposition, ...]:
        """Every revision of one claim, oldest first, the live one last."""
        self.derive()
        if pid not in self._history:
            raise UnknownId(f"no proposition {pid!r}")
        return tuple(self._history[pid])

    def propositions(self, *, status: Optional[PropositionStatus] = None,
                     live: bool = False) -> Tuple[Proposition, ...]:
        """Live revisions, insertion order."""
        self.derive()
        out = [prop for prop in self._props.values()
               if (status is None or prop.status == status)
               and (not live or prop.live)]
        return tuple(out)

    def query(self, pattern: Sequence[Any], *,
              live: bool = True) -> Tuple[Proposition, ...]:
        """Propositions matching a pattern, insertion order.

        The public door onto the matching the closure engine already does.
        Without it every caller that wants "what does the store hold about
        this entity" writes its own scan, and the first one to get the
        liveness filter wrong gets a plausible answer built out of retracted
        claims.  ``live=False`` asks for the dead ones too, which is a
        question about history rather than about belief.
        """
        self.derive()
        target = check_pattern(pattern)
        if live:
            # The same index choice the join makes, for the same reason: a
            # public read that scanned every proposition would be the one
            # place in the package where asking a narrow question costs the
            # whole store.
            candidates = self._matches(target, {}, None)
        else:
            candidates = [pid for pid, prop in self._props.items()
                          if prop.triple is not None]
        return tuple(self._props[pid] for pid in candidates
                     if unify(target, self._props[pid].triple) is not None)

    def claim(self, triple: Sequence[Any]) -> Optional[str]:
        """The id this store holds a triple under, or ``None``.

        The store owns the triple-to-id fact — it is the key the merge rules
        are written against — and a caller that rebuilt it from a scan would
        be keeping a second copy of the one thing that decides whether two
        assertions are one claim.  The harvester the shadow lane will write
        needs exactly this and nothing more.
        """
        self.derive()
        entity, field, value = _split(triple)
        if entity is None:
            raise CognitionError("claim() takes a triple; text has no key")
        return self._claim_key.get(
            ("triple", entity, field, value_tag(value), value))

    def rule(self, rid: str) -> Rule:
        self.derive()
        return self._rule_of(rid)

    def _rule_of(self, rid: str) -> Rule:
        """A rule by id, the engine's own included.

        :data:`PROJECTION_RULE` is not in ``_rules`` — it is part of the
        engine and no store authored it — but a projection's derivation names
        it, so every reader that turns a derivation back into a rule comes
        through here.  A ``KeyError`` out of :meth:`prove` would be the shape
        of that omission, which is why there is one lookup and not two.
        """
        if rid == PROJECTION_RULE_ID:
            return PROJECTION_RULE
        existing = self._rules.get(rid)
        if existing is None:
            raise UnknownId(f"no rule {rid!r}")
        return existing

    def rules(self) -> Tuple[Rule, ...]:
        """The rules somebody added. The engine's own is not one of them.

        :data:`PROJECTION_RULE` is reachable by id through :meth:`rule` and is
        deliberately absent here: this read answers "what has this store been
        told", and an engine built-in appearing in it would be the code
        describing itself as content — in every store, identically, forever.
        """
        self.derive()
        return tuple(self._rules.values())

    def links(self) -> Tuple[Link, ...]:
        """Every link, live revision, in the order they were first made."""
        self.derive()
        return tuple(self._links.values())

    def link_record(self, lid: str) -> Link:
        """The live revision of one link."""
        self.derive()
        held = self._links.get(lid)
        if held is None:
            raise UnknownId(f"no link {lid!r}")
        return held

    def links_for(self, entity: str) -> Tuple[Link, ...]:
        """Every subject this entity has been claimed to be about.

        More than one is ordinary: a receipt that names a job *and* the asset
        it produced is about both, and its facts project onto each.
        """
        self.derive()
        return tuple(self._links[lid]
                     for lid in self._links_by_entity.get(entity, ()))

    def linked_to(self, subject: str) -> Tuple[Link, ...]:
        """Every entity claimed to be about this subject.

        The read a consumer rendering a subject wants: the receipts behind it,
        which is what turns a contested subject fact into "these two calls
        disagree" rather than "the store is unhappy".
        """
        self.derive()
        return tuple(self._links[lid]
                     for lid in self._links_by_subject.get(subject, ()))

    def goals(self) -> Tuple[Goal, ...]:
        self.derive()
        return tuple(self._goals.values())

    def fields(self) -> Mapping[str, str]:
        """Every field somebody declared, and what they declared it.

        Undeclared fields are absent rather than listed as ``"many"``:
        absence is how this package says "nobody has said", everywhere else,
        and :meth:`cardinality` is the call that turns absence into the
        default.
        """
        self.derive()
        return dict(self._cardinality)

    def derivations(self) -> Tuple[Derivation, ...]:
        self.derive()
        return tuple(self._derivations.values())

    def derivations_for(self, pid: str) -> Tuple[Derivation, ...]:
        """Every proof of one conclusion — the alternatives included."""
        self.derive()
        return tuple(self._derivations[did]
                     for did in self._by_conclusion.get(pid, ()))

    def contradictions(self) -> Tuple[Contradiction, ...]:
        """Every collision on the record, in the order they were found."""
        self.derive()
        return tuple(self._contradictions.values())

    def contradictions_for(self, pid: str) -> Tuple[Contradiction, ...]:
        """Every collision naming one proposition, on either side."""
        self.derive()
        if pid not in self._props:
            raise UnknownId(f"no proposition {pid!r}")
        return tuple(clash for clash in self._contradictions.values()
                     if pid in (clash.left, clash.right))

    # ── confidence ──────────────────────────────────────────────────────────

    def support(self, pid: str) -> Support:
        """How well one claim is held up, computed from the DAG right now.

        ``grade`` is the best any *live* proof can do: the maximum, over
        proofs still standing, of the weakest premise in that proof.  It is
        computed rather than stored, and the case that decides it is the
        happy one.  A proposition derived from something the model extracted
        carries ``MODEL_EXTRACTION``; a receipt arrives later and promotes
        that premise to ``SOURCE``; every conclusion under it is now
        better-supported than it was, and nothing re-derived, because
        nothing needed to.  A stored grade would still be reporting the old
        number — the store understating its own evidence, quietly, for as
        long as nobody happened to run closure again.

        A claim with no live proof and no live status has no grade at all
        (``None``).  That is not "poorly supported": it is the store
        declining to grade something it has stopped believing, and a caller
        that renders ``None`` as a low number has turned a refusal into an
        opinion.
        """
        self.derive()
        if pid not in self._props:
            raise UnknownId(f"no proposition {pid!r}")
        prop = self._props[pid]
        clashes = self.contradictions_for(pid)
        return Support(
            proposition=pid,
            status=prop.status,
            grade=self._grade(pid, set(), {})[0],
            contested_by=tuple(clash.id for clash in clashes
                               if clash.kind != "hypothesis"),
            hypothesis=tuple(clash.id for clash in clashes
                             if clash.kind == "hypothesis"),
            evidence_leaves=self._leaves(pid, set(), {})[0],
        )

    def _grade(self, pid: str, path: set,
               memo: Dict[str, Optional[EvidenceAuthority]]
               ) -> Tuple[Optional[EvidenceAuthority], bool]:
        """The grade, and whether the walk under it met a cycle.

        Memoised the way :meth:`_prove` is, and for the same reason and with
        the same exception. Proofs diamond — two rules concluding from one
        premise, repeatedly, is 2^depth paths through 2·depth nodes — and
        this is the call a mission loop makes every step, so re-descending
        each path is the difference between linear and unusable. A node on a
        cycle is NOT cached: its answer is a fact about the path that reached
        it, and handing that to a later caller would be cache poisoning.
        """
        prop = self._props[pid]
        if pid in path:
            return None, True
        if prop.status is PropositionStatus.HYPOTHESIZED:
            # Graded by the model step that produced it, not refused a grade.
            # A hypothesis IS supported — by a model, badly — and reporting
            # `None` conflated "the store will not stand behind this" with
            # "the store has stopped believing this", which are the two
            # things a confidence read exists to keep apart. The `hypothesis`
            # field already says which kind of claim it is.
            return prop.authority, False
        if not prop.live:
            return None, False
        held = memo.get(pid, _UNSET)
        if held is not _UNSET:
            return held, False
        best: Optional[EvidenceAuthority] = None
        if prop.evidence or not self._by_conclusion.get(pid):
            best = prop.authority
        touched_cycle = False
        for did in self._by_conclusion.get(pid, ()):
            premises = self._derivations[did].premises
            if not all(self._props[p].live for p in premises):
                continue
            grades = []
            # A projection's second premise is a link, and it caps the grade
            # like any other: a fact read off a receipt at SOURCE, carried to
            # a subject by a link the model guessed, is worth the guess. Taken
            # live from the link rather than from the conclusion's stored
            # authority, for the reason this whole method is a read — a link
            # whose authority rose lifts everything it projected, and nothing
            # re-derived because nothing needed to.
            held_link = self._derivations[did].link
            if held_link is not None:
                grades.append(self._links[held_link].authority)
            for premise in premises:
                grade, cyclic = self._grade(premise, path | {pid}, memo)
                touched_cycle = touched_cycle or cyclic
                grades.append(grade)
            if any(grade is None for grade in grades):
                continue
            weakest = min(grades, key=lambda a: AUTHORITY_RANK[a])
            if best is None or AUTHORITY_RANK[weakest] > AUTHORITY_RANK[best]:
                best = weakest
        if not touched_cycle:
            memo[pid] = best
        return best, touched_cycle

    def _leaves(self, pid: str, path: set,
                memo: Dict[str, Tuple[EvidenceRef, ...]]
                ) -> Tuple[Tuple[EvidenceRef, ...], bool]:
        """Every ref at the bottom of the proof. Memoised like :meth:`_grade`."""
        prop = self._props[pid]
        if pid in path:
            return (), True
        held = memo.get(pid)
        if held is not None:
            return held, False
        out: List[EvidenceRef] = list(prop.evidence)
        touched_cycle = False
        for did in self._by_conclusion.get(pid, ()):
            # The link's own evidence is a leaf of the proof: it is what
            # answers "why do we think this receipt was about this job", which
            # is the question a wrong subject fact makes urgent and the one
            # the receipt's refs cannot answer.
            held_link = self._derivations[did].link
            if held_link is not None:
                for ref in self._links[held_link].evidence:
                    if ref not in out:
                        out.append(ref)
            for premise in self._derivations[did].premises:
                refs, cyclic = self._leaves(premise, path | {pid}, memo)
                touched_cycle = touched_cycle or cyclic
                for ref in refs:
                    if ref not in out:
                        out.append(ref)
        settled = tuple(out)
        if not touched_cycle:
            memo[pid] = settled
        return settled, touched_cycle

    def summarize(self, pids: Iterable[str]) -> dict:
        """One reading over several claims, for a caller about to answer.

        ``floor_grade`` is the *weakest* grade in the set, because a claim
        assembled out of several propositions is only as good as its worst
        one — the same rule a single derivation already follows for its
        premises, applied one level up. ``contested`` and ``hypothesized``
        name the ids rather than counting them: a count tells a reader
        something is wrong and a name tells them where.
        """
        self.derive()
        supports = [self.support(pid) for pid in pids]
        graded = [item.grade for item in supports if item.grade is not None]
        return {
            "floor_grade": (min(graded, key=lambda a: AUTHORITY_RANK[a])
                            if graded else None),
            "contested": tuple(item.proposition for item in supports
                               if item.status is PropositionStatus.CONTESTED),
            "hypothesized": tuple(
                item.proposition for item in supports
                if item.status is PropositionStatus.HYPOTHESIZED),
        }

    def prove(self, pid: str) -> Proof:
        """The derivation DAG under a proposition, evidence at the leaves.

        **A DAG, not a tree.**  A proposition reached by two routes is one
        :class:`~core.cognition.types.Proof` object appearing twice, not two
        equal ones built twice — which matters because proofs diamond: two
        rules conclude from a shared premise, that premise has its own two
        proofs, and a walk that rebuilt each node per path did exponential
        work to produce a structure the reader treats as shared anyway.

        Nodes on a cycle are *not* memoised.  Their shape depends on the path
        that reached them — that is what ``cyclic`` records — so caching one
        would hand a later caller a stub that was true of somebody else's
        walk.
        """
        self.derive()
        if pid not in self._props:
            raise UnknownId(f"no proposition {pid!r}")
        proof, _cyclic = self._prove(pid, (), {})
        return proof

    def _prove(self, pid: str, path: Tuple[str, ...],
               memo: Dict[str, Proof]) -> Tuple[Proof, bool]:
        prop = self._props[pid]
        if pid in path:
            return Proof(proposition=pid, status=prop.status,
                         authority=prop.authority, evidence=prop.evidence,
                         steps=(), cyclic=True), True
        held = memo.get(pid)
        if held is not None:
            return held, False
        steps = []
        touched_cycle = False
        for did in self._by_conclusion.get(pid, ()):
            derivation = self._derivations[did]
            rule = self._rule_of(derivation.rule)
            premises = []
            for premise in derivation.premises:
                proof, cyclic = self._prove(premise, path + (pid,), memo)
                touched_cycle = touched_cycle or cyclic
                premises.append(proof)
            steps.append(ProofStep(derivation=did, rule=rule.id,
                                   rule_name=rule.name,
                                   premises=tuple(premises),
                                   link=derivation.link))
        made = Proof(proposition=pid, status=prop.status,
                     authority=prop.authority, evidence=prop.evidence,
                     steps=tuple(steps))
        if not touched_cycle:
            memo[pid] = made
        return made, touched_cycle

    # ── obligations ─────────────────────────────────────────────────────────

    def obligations(self) -> Frontier:
        """Every requirement the goals imply, ``RESOLVED`` ones included.

        **Computed once per epoch.**  The walk is a pure function of the
        store, so a caller asking for the frontier and then for the next
        obligation used to pay for it twice — and a mission loop asks every
        step.  The cache is invalidated by anything that changes the store;
        it is not an optimisation a caller has to know about, and there is no
        way to see a stale answer through it.

        Computed from goals, trusted rules and what the store holds — read the
        class docstring for why nothing authors these.  A goal the store
        already satisfies contributes nothing at all: it is not a requirement
        any more, and listing its premises as resolved would put a finished
        goal on the frontier's ledger for no reader's benefit.

        Order is: goal insertion, then rule insertion, then body position,
        then the order environments were discovered.  That whole chain is
        deterministic, which is what makes :meth:`frontier` reproducible and
        :meth:`next_obligation`'s tie-break meaningful.
        """
        self.derive()
        if self._obligations is not None and self._obligations[0] == self._epoch:
            return self._obligations[1]
        before = self.stats.envs_truncated
        out: Dict[str, Obligation] = {}
        for goal in self._goals.values():
            if self._satisfied(goal.pattern, {}):
                continue
            matching = [rule for rule in self._rules.values()
                        if rule.participates_in_closure
                        and unify_patterns(rule.head, goal.pattern) is not None]
            if not matching:
                self._record_obligation(out, goal, None, 0, goal.pattern, ())
                continue
            for rule in matching:
                head = unify_patterns(rule.head, goal.pattern) or {}
                self._obligations_for(out, goal, rule, head)
        computed = Frontier(out.values(),
                            truncated=self.stats.envs_truncated > before)
        self._obligations = (self._epoch, computed)
        return computed

    def _obligations_for(self, out: Dict[str, Obligation], goal: Goal,
                         rule: Rule, head: Bindings) -> None:
        """Partially evaluate one rule body against the store.

        Each premise is tried under the bindings the satisfied premises so far
        have produced.  A premise with matches extends the environments and is
        recorded ``RESOLVED``; a premise with none is recorded as an
        obligation and the environments carry on unchanged, so a later premise
        is still stated as concretely as the store allows.  The carried-on
        environment is why a rule's premise *order* decides how ground an
        obligation's pattern is — declared order, and a rule pack that wants
        a different one says so by writing the body differently.
        """
        envs: List[Tuple[Bindings, Tuple[str, ...]]] = [(dict(head), ())]
        for position, pattern in enumerate(rule.body):
            nxt: List[Tuple[Bindings, Tuple[str, ...]]] = []
            for bindings, blockers in envs:
                found = [pid for pid in self._matches(pattern, bindings, None)
                         if unify(pattern, self._props[pid].triple,
                                  bindings) is not None]
                if found:
                    self._record_obligation(out, goal, rule, position,
                                            resolve(pattern, bindings), (),
                                            ObligationState.RESOLVED)
                    for pid in found:
                        extended = unify(pattern, self._props[pid].triple,
                                         bindings)
                        if extended is None:
                            continue
                        if len(nxt) >= ENV_CAP:
                            self.stats.envs_truncated += 1
                            break
                        nxt.append((extended, blockers))
                else:
                    unresolved = resolve(pattern, bindings)
                    deps = tuple(
                        oid for oid in blockers
                        if shares_variable(out[oid].pattern, unresolved))
                    oid = self._record_obligation(out, goal, rule, position,
                                                  unresolved, deps)
                    nxt.append((bindings, blockers + (oid,)))
            # No second cap here: the satisfied branch stops appending at
            # ENV_CAP and the unsatisfied branch adds one env per env, so
            # `nxt` cannot exceed it. A `nxt[:ENV_CAP]` slice was doing
            # nothing and a second truncation counter beside it could never
            # fire — a guard that cannot trip reads as protection and is not.
            envs = nxt
            if not envs:
                return

    def _record_obligation(self, out: Dict[str, Obligation], goal: Goal,
                           rule: Optional[Rule], position: int,
                           pattern: Sequence[Any],
                           depends_on: Tuple[str, ...],
                           state: Optional[ObligationState] = None) -> str:
        oid = (f"{goal.id}/{rule.id if rule else '-'}/{position}/"
               f"{render_pattern(pattern)}")
        if oid in out:
            return oid
        if state is None:
            state = (ObligationState.BLOCKED if depends_on
                     else ObligationState.OPEN)
        out[oid] = Obligation(id=oid, goal=goal.id,
                              rule=rule.id if rule else None,
                              position=position, pattern=tuple(pattern),
                              state=state, depends_on=depends_on)
        return oid

    def frontier(self) -> Frontier:
        """The unresolved obligations — the proof frontier, in order.

        Carries :attr:`~core.cognition.types.Frontier.truncated` through from
        the walk: a frontier that was cut short at :data:`ENV_CAP` says so,
        because a truncated frontier and a complete one are otherwise the
        same object and the difference is whether "nothing else is missing"
        is a finding or an artefact.
        """
        computed = self.obligations()
        return Frontier((item for item in computed
                         if item.state != ObligationState.RESOLVED),
                        truncated=computed.truncated)

    def ranked_frontier(self) -> Frontier:
        """The frontier in priority order — cheapest true thing first.

        Priority is **fewest unresolved dependencies, then computation
        order**.  Because ``OPEN`` means exactly "no unresolved dependency",
        every ``OPEN`` obligation sorts ahead of every ``BLOCKED`` one without
        the sort having to know the difference — the dependency count is the
        only key, and the state is what that count already said.  The
        tie-break is the computation order documented on
        :meth:`obligations`, and not, deliberately, anything about how
        interesting an obligation looks: a frontier that reordered itself on a
        heuristic would stop being reproducible on the day that heuristic
        changed.

        **The whole ranking lives here**, and :meth:`next_obligation` is its
        first element.  It was the other way round — the sort inside
        ``next_obligation``, with every other consumer left to re-spell it —
        until a second reader appeared: Phase 19's compiled ``OWED`` section
        renders the frontier *in the order the runtime would work it*, and
        two spellings of one ordering is the shape that drifts.  Carries
        :attr:`~core.cognition.types.Frontier.truncated` through, for
        :meth:`frontier`'s reason.
        """
        computed = self.frontier()
        return Frontier(
            (item for _position, item in
             sorted(enumerate(computed),
                    key=lambda pair: (len(pair[1].depends_on), pair[0]))),
            truncated=computed.truncated)

    def next_obligation(self) -> Optional[Obligation]:
        """The cheapest true thing to do next, or ``None``.

        The head of :meth:`ranked_frontier`, which owns the ordering and
        argues it.
        """
        ranked = self.ranked_frontier()
        return ranked[0] if ranked else None

    def _satisfied(self, pattern: Sequence[Any], bindings: Bindings) -> bool:
        for pid in self._matches(pattern, bindings, None):
            if unify(pattern, self._props[pid].triple, bindings) is not None:
                return True
        return False

    # ── comparison ──────────────────────────────────────────────────────────

    def digest(self) -> dict:
        """A JSON-safe rendering of the whole store, for comparison.

        Used by the replay tests, and by anything that needs to say two stores
        are the same one.  :class:`~core.cognition.types.MatchStats` is not in
        here: it counts what the engine did, not what the store holds, and a
        replayed store legitimately did less work than the one that was read
        from along the way.

        **Checked against :data:`DIGEST_KEYS` on the way out.**  This method
        is the comparator every replay assertion in the suite runs through,
        which makes it the one place in the package where *narrowing* is
        invisible: drop a field here and the digests still match, the tests
        still pass, and the property they were proving has quietly become a
        weaker one.  A field this method stops rendering therefore has to be
        a field somebody deleted from the list above too, in the same edit,
        with the same reason.
        """
        self.derive()
        digested = {
            "propositions": [
                {"id": prop.id, "revision": prop.revision,
                 "previous": prop.previous, "entity": prop.entity,
                 "field": prop.field, "value": prop.value, "text": prop.text,
                 "status": prop.status.value,
                 "authority": prop.authority.value,
                 "derivation": prop.derivation,
                 "evidence": encode_evidence(prop.evidence),
                 "history": [item.key for item in self._history[prop.id]]}
                for prop in self._props.values()],
            "rules": [{"id": rule.id, "name": rule.name,
                       "authority": rule.authority.value,
                       "head": encode_pattern(rule.head),
                       "body": [encode_pattern(item) for item in rule.body]}
                      for rule in self._rules.values()],
            "derivations": [{"id": item.id, "rule": item.rule,
                             "premises": list(item.premises),
                             "conclusion": item.conclusion,
                             "link": item.link}
                            for item in self._derivations.values()],
            "links": [
                {"id": item.id, "revision": item.revision,
                 "previous": item.previous, "entity": item.entity,
                 "subject": item.subject, "authority": item.authority.value,
                 "evidence": encode_evidence(item.evidence),
                 "history": [rev.key for rev in self._link_history[item.id]]}
                for item in self._links.values()],
            "goals": [{"id": goal.id, "pattern": encode_pattern(goal.pattern),
                       "note": goal.note} for goal in self._goals.values()],
            "fields": [{"field": name, "cardinality": how}
                       for name, how in self._cardinality.items()],
            "contradictions": [
                {"id": item.id, "kind": item.kind, "left": item.left,
                 "right": item.right, "detail": item.detail,
                 "evidence": encode_evidence(item.evidence),
                 "settled": item.settled, "kept": item.kept}
                for item in self._contradictions.values()],
            "pending": {"propositions": list(self._pending_props),
                        "rules": list(self._pending_rules),
                        "links": list(self._pending_links)},
        }
        _check_digest_keys(digested)
        return digested

    def digest_json(self) -> str:
        return json.dumps(self.digest(), sort_keys=True)


# ── small helpers ───────────────────────────────────────────────────────────

def _check_digest_keys(digested: Mapping[str, Any]) -> None:
    """Every section rendered, every field in it named by :data:`DIGEST_KEYS`."""
    if set(digested) != set(DIGEST_KEYS):
        missing = sorted(set(DIGEST_KEYS) - set(digested))
        extra = sorted(set(digested) - set(DIGEST_KEYS))
        raise CognitionError(
            f"digest sections do not match DIGEST_KEYS (missing {missing}, "
            f"unexpected {extra})")
    for section, expected in DIGEST_KEYS.items():
        rows = digested[section]
        rows = [rows] if isinstance(rows, Mapping) else rows
        for row in rows:
            if set(row) != set(expected):
                missing = sorted(set(expected) - set(row))
                extra = sorted(set(row) - set(expected))
                raise CognitionError(
                    f"digest section {section!r} renders the wrong fields "
                    f"(missing {missing}, unexpected {extra}); a digest that "
                    "renders less compares less, and every replay assertion "
                    "in the suite would go on passing")


def _split(triple: Optional[Sequence[Any]]):
    if triple is None:
        return None, None, None
    items = tuple(triple)
    if len(items) != 3:
        raise CognitionError(f"a triple is three terms, got {len(items)}")
    entity, field, value = items
    if not isinstance(entity, str) or not entity:
        raise CognitionError("a triple's entity is a non-empty string")
    if not isinstance(field, str) or not field:
        raise CognitionError("a triple's field is a non-empty string")
    if is_variable(entity) or is_variable(field) or is_variable(value):
        raise CognitionError(
            "a proposition is ground; '?name' is the variable spelling and "
            "belongs in a rule or a goal, not in something asserted")
    return entity, field, check_value(value)


def _merge_evidence(held: Tuple[EvidenceRef, ...],
                    fresh: Iterable[EvidenceRef]) -> Tuple[EvidenceRef, ...]:
    """Union, order-preserving. Identical refs are one ref."""
    out = list(held)
    for ref in fresh:
        if ref not in out:
            out.append(ref)
    return tuple(out)


def _authority(raw: Any) -> EvidenceAuthority:
    try:
        return EvidenceAuthority(raw)
    except ValueError as exc:
        raise ReplayRefused(f"no evidence authority {raw!r}") from exc


def _rule_authority(raw: Any) -> RuleAuthority:
    try:
        return RuleAuthority(raw)
    except ValueError as exc:
        raise ReplayRefused(f"no rule authority {raw!r}") from exc
