# core/cognition/state.py — the store: single writer, incremental, replayable

"""What is believed, why, what contradicts it, and what is still owed.

One class, :class:`CognitiveState`.  It is the only thing in this package that
changes, and it changes in exactly seven ways —
:meth:`~CognitiveState.assert_observation`,
:meth:`~CognitiveState.assert_hypothesis`, :meth:`~CognitiveState.add_rule`,
:meth:`~CognitiveState.promote_rule`, :meth:`~CognitiveState.add_goal`,
:meth:`~CognitiveState.refute` and :meth:`~CognitiveState.apply_delta` — each
of which appends exactly one event and does nothing else that a replay cannot
reproduce.  Everything else on the class is a read.

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
away: **when somebody reads is part of what the log says, and part of which
id each proposition gets.**  Two callers issuing identical writes, one
reading the frontier between them and one not, keep logs of different length
— and because ids are handed out in insertion order, the early flush inserts
a *derived* proposition before the next observation arrives, so the same
claims end up under different names.

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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.cognition.events import (EVENT_OPS, EVENT_SCHEMA_VERSION, EVENTS_KEY,
                                   SCHEMA_KEY, check_snapshot, decode_evidence,
                                   decode_pattern, encode_evidence,
                                   encode_pattern)
from core.cognition.matching import (Bindings, resolve, shares_variable, unify,
                                     unify_patterns)
from core.cognition.types import (AUTHORITY_RANK, CONTRADICTION_KINDS,
                                  HYPOTHESIS_AUTHORITIES,
                                  OBSERVATION_AUTHORITIES,
                                  STATUS_RANK, AuthorityRefused,
                                  CognitionError, Contradiction, Derivation,
                                  EvidenceAuthority, EvidenceRef, Goal,
                                  MatchStats, Obligation, ObligationState,
                                  Proof, Proposition, PropositionStatus,
                                  ProofStep, ReplayRefused, Rule,
                                  RuleAuthority, RuleMalformed, UnknownId,
                                  check_pattern, check_value, is_variable,
                                  render_pattern, value_tag, variables_in)

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
    "derivations": frozenset({"id", "rule", "premises", "conclusion"}),
    "goals": frozenset({"id", "pattern", "note"}),
    "contradictions": frozenset({
        "id", "kind", "left", "right", "detail", "evidence"}),
    "pending": frozenset({"propositions", "rules"}),
}


class CognitiveState:
    """The store. See the module docstring for the rules it keeps."""

    # ── construction ────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._events: List[dict] = []

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

        self._goals: Dict[str, Goal] = {}
        self._contradictions: Dict[str, Contradiction] = {}
        # `(kind, left, right)` → id. A collision found twice is one
        # contradiction: a hypothesis re-asserted against the same
        # observation, or a claim refuted twice, must not grow the ledger.
        self._contradiction_keys: Dict[tuple, str] = {}

        self._pending_props: List[str] = []
        self._pending_rules: List[str] = []

        self._counters = {"p": 0, "r": 0, "d": 0, "g": 0, "c": 0}
        self.stats = MatchStats()

    # ── the event log ───────────────────────────────────────────────────────

    def _append(self, op: str, **fields: Any) -> dict:
        assert op in EVENT_OPS, op  # a typo here would be a log nobody replays
        event = {"n": len(self._events) + 1, "op": op}
        event.update(fields)
        self._events.append(event)
        return event

    @property
    def events(self) -> Tuple[dict, ...]:
        """The log, oldest first. Copies, so a reader cannot edit history."""
        return tuple(dict(event) for event in self._events)

    def pending(self) -> dict:
        """The staging area: what the next flush would derive from.

        Public because the implicit flush is otherwise invisible.  A caller
        that wants a log it can compare byte for byte needs to be able to ask
        whether there is anything outstanding before it reads.
        """
        return {"propositions": tuple(self._pending_props),
                "rules": tuple(self._pending_rules)}

    @property
    def has_pending(self) -> bool:
        """Whether the next read would append a ``derive`` event."""
        return bool(self._pending_props or self._pending_rules)

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
        return {SCHEMA_KEY: EVENT_SCHEMA_VERSION,
                EVENTS_KEY: [dict(event) for event in self._events]}

    @classmethod
    def replay(cls, events: Any) -> "CognitiveState":
        """Rebuild a store from a snapshot or a bare event list.

        Every op is applied through the same public method that wrote it.
        There is no second application path — a replay that reconstructed the
        indexes directly would be a second implementation of the engine, and
        the day the two disagreed the replay would be the one nobody checked.
        """
        records = check_snapshot(events)
        state = cls()
        for record in records:
            state._apply_event(record)
        return state

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
        elif op == "derive":
            self.apply_delta(propositions=record.get("propositions", ()),
                             rules=record.get("rules", ()))
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
            self._pending_rules.append(rid)
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
        if existing.authority is not RuleAuthority.PROPOSED:
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
        if rule not in self._pending_rules:
            self._pending_rules.append(rule)
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
                                rules=tuple(self._pending_rules))

    def apply_delta(self, propositions: Sequence[str] = (),
                    rules: Sequence[str] = ()) -> Tuple[str, ...]:
        """Semi-naive closure over a delta, to fixpoint. One ``derive`` event.

        ``propositions`` are ids that have just become live; ``rules`` are
        ids that have just become trusted.  For a proposition delta only the
        rules with a body premise on one of the delta's *fields* are
        considered, and each such rule is joined once per body position that
        the delta can fill — the pinned position draws from the delta, every
        other position from the store.  That is what makes the work
        proportional to what changed.  For a rule delta the rule is joined
        against the whole store once, which is the only honest thing to do
        with a clause nobody had run before.

        Re-deriving something the store already holds adds a
        :class:`~core.cognition.types.Derivation` — an alternative proof — and
        never a second proposition.  Termination rests on that: derivations
        are deduplicated by ``(rule, premises, conclusion)``, so a cycle stops
        producing new ones and the loop ends.
        """
        prop_delta = [pid for pid in propositions if pid in self._props]
        rule_delta = [rid for rid in rules if rid in self._rules]
        if not prop_delta and not rule_delta:
            return ()
        self._append("derive", propositions=list(propositions),
                     rules=list(rules))
        for pid in propositions:
            if pid in self._pending_props:
                self._pending_props.remove(pid)
        for rid in rules:
            if rid in self._pending_rules:
                self._pending_rules.remove(rid)

        derived: List[str] = []
        while prop_delta or rule_delta:
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
            derived.extend(produced)
            prop_delta = produced
            rule_delta = []
        return tuple(derived)

    def _candidate_rules(self, fields: Sequence[str]) -> List[str]:
        """Rules whose body mentions one of these fields, plus the wildcards.

        Insertion order, deduplicated.  A rule whose body premise has a
        *variable* field can match anything and lives in the ``None`` bucket,
        so it is always a candidate — correct, and the reason a rule pack of
        wholly-variable premises would lose the benefit of this index.
        """
        out: List[str] = []
        for name in list(fields) + [None]:
            for rid in self._rules_by_field.get(name, ()):
                if rid not in out:
                    out.append(rid)
        return sorted(out, key=lambda rid: int(rid[1:]))

    def _run(self, rule: Rule, position: Optional[int],
             pool: Optional[Sequence[str]]) -> List[str]:
        """Join one rule body and ingest every conclusion it licenses."""
        self.stats.body_scans += 1
        envs: List[Tuple[Bindings, Tuple[str, ...]]] = [({}, ())]
        for index, pattern in enumerate(rule.body):
            draw = pool if (position is not None and index == position) else None
            nxt: List[Tuple[Bindings, Tuple[str, ...]]] = []
            for bindings, premises in envs:
                for pid in self._matches(pattern, bindings, draw):
                    extended = unify(pattern, self._props[pid].triple, bindings)
                    if extended is not None:
                        nxt.append((extended, premises + (pid,)))
            envs = nxt
            if not envs:
                return []
        out: List[str] = []
        for bindings, premises in envs:
            conclusion = resolve(rule.head, bindings)
            authority = min((self._props[pid].authority for pid in premises),
                            key=lambda a: AUTHORITY_RANK[a])
            key = (rule.id, premises, conclusion)
            if key in self._derivation_keys:
                continue
            pid, is_new = self._ingest(conclusion[0], conclusion[1],
                                       conclusion[2], None,
                                       PropositionStatus.DERIVED, authority,
                                       (), derivation=None, stage=False)
            self._counters["d"] += 1
            did = f"d{self._counters['d']}"
            self._derivations[did] = Derivation(id=did, rule=rule.id,
                                                premises=premises,
                                                conclusion=pid)
            self._derivation_keys.add(key)
            self._by_conclusion.setdefault(pid, []).append(did)
            for premise in premises:
                bucket = self._by_premise.setdefault(premise, [])
                if did not in bucket:
                    bucket.append(did)
            if self._props[pid].derivation is None:
                self._revise(pid, derivation=did)
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
            return [pid for pid in pool
                    if self._props[pid].live and self._props[pid].triple]
        entity, field, _value = resolve(pattern, bindings)
        if not is_variable(entity):
            candidates = self._by_entity.get(entity, ())
        elif not is_variable(field):
            candidates = self._by_field.get(field, ())
        else:
            candidates = list(self._props)
        return [pid for pid in candidates
                if self._props[pid].live and self._props[pid].triple]

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
            if stage and held not in self._pending_props:
                self._pending_props.append(held)
            became_live = self._props[held].live and not was_live
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
            self._pending_props.append(pid)
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

        **v1 bound, and the sharpest one in the package: every field is
        treated as single-valued.**  ``(alice, controls, acct-1)`` and
        ``(alice, controls, acct-2)`` collide, which is right for
        ``total_s`` and wrong for ``controls``.  There is no cardinality
        declaration in v1 because inventing one before a rule pack exists
        would be guessing at its shape; the workaround a rule pack has today
        is to put the multi-valued end in the *entity* position
        (``(acct-1, controlled_by, alice)``), and the real fix — a
        ``functional``/``set`` flag on a field, declared by whoever declares
        the rules — is a Phase 18+ decision with a rule pack to design
        against.

        **And the operational consequence, because it compounds:** contesting
        is terminal in v1.  So a genuinely multi-valued field does not merely
        report a spurious disagreement once — every value poisons every other
        one, permanently, and whatever a rule derived from any of them goes
        with it.  One such field in a rule pack can take an entity out of
        closure altogether.  Until cardinality exists, the multi-valued end
        goes in the entity position.
        """
        prop = self._props[pid]
        if prop.triple is None:
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

    def _disagree(self, hypothesis: str, observed: str) -> None:
        """Record a model's claim against the store's, and change nothing."""
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
        if existing is not None:
            return existing
        self._counters["c"] += 1
        cid = f"c{self._counters['c']}"
        self._contradictions[cid] = Contradiction(
            id=cid, kind=kind, left=left, right=right,
            evidence=tuple(evidence), detail=detail)
        self._contradiction_keys[key] = cid
        return cid

    def _retract_dependents(self, dead: Sequence[str]) -> None:
        """The retraction rule, cascading. See the module docstring."""
        work = list(dead)
        seen = set(work)
        while work:
            gone = work.pop(0)
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

    def rule(self, rid: str) -> Rule:
        existing = self._rules.get(rid)
        if existing is None:
            raise UnknownId(f"no rule {rid!r}")
        return existing

    def rules(self) -> Tuple[Rule, ...]:
        return tuple(self._rules.values())

    def goals(self) -> Tuple[Goal, ...]:
        return tuple(self._goals.values())

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

    def prove(self, pid: str) -> Proof:
        """The derivation DAG under a proposition, evidence at the leaves."""
        self.derive()
        if pid not in self._props:
            raise UnknownId(f"no proposition {pid!r}")
        return self._prove(pid, ())

    def _prove(self, pid: str, path: Tuple[str, ...]) -> Proof:
        prop = self._props[pid]
        if pid in path:
            return Proof(proposition=pid, status=prop.status,
                         authority=prop.authority, evidence=prop.evidence,
                         steps=(), cyclic=True)
        steps = []
        for did in self._by_conclusion.get(pid, ()):
            derivation = self._derivations[did]
            rule = self._rules[derivation.rule]
            steps.append(ProofStep(
                derivation=did, rule=rule.id, rule_name=rule.name,
                premises=tuple(self._prove(premise, path + (pid,))
                               for premise in derivation.premises)))
        return Proof(proposition=pid, status=prop.status,
                     authority=prop.authority, evidence=prop.evidence,
                     steps=tuple(steps))

    # ── obligations ─────────────────────────────────────────────────────────

    def obligations(self) -> Tuple[Obligation, ...]:
        """Every requirement the goals imply, ``RESOLVED`` ones included.

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
        return tuple(out.values())

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
            if len(nxt) > ENV_CAP:
                self.stats.envs_truncated += 1
            envs = nxt[:ENV_CAP]
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

    def frontier(self) -> Tuple[Obligation, ...]:
        """The unresolved obligations — the proof frontier, in order."""
        return tuple(item for item in self.obligations()
                     if item.state != ObligationState.RESOLVED)

    def next_obligation(self) -> Optional[Obligation]:
        """The cheapest true thing to do next, or ``None``.

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
        """
        ranked = sorted(enumerate(self.frontier()),
                        key=lambda pair: (len(pair[1].depends_on), pair[0]))
        return ranked[0][1] if ranked else None

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
                             "conclusion": item.conclusion}
                            for item in self._derivations.values()],
            "goals": [{"id": goal.id, "pattern": encode_pattern(goal.pattern),
                       "note": goal.note} for goal in self._goals.values()],
            "contradictions": [
                {"id": item.id, "kind": item.kind, "left": item.left,
                 "right": item.right, "detail": item.detail,
                 "evidence": encode_evidence(item.evidence)}
                for item in self._contradictions.values()],
            "pending": {"propositions": list(self._pending_props),
                        "rules": list(self._pending_rules)},
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
