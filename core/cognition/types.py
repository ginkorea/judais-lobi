# core/cognition/types.py — the records the kernel keeps, and the walls between them

"""The vocabulary, as immutable records and four closed sets.

Everything in this module is a frozen dataclass or an ``Enum``.  Nothing here
has a method that changes anything: the store in :mod:`core.cognition.state`
owns every mutation, and the way a record "changes" is that a *new* record is
written naming the one it replaced.  That is not fastidiousness.  A
proposition whose status can be edited in place is a proposition whose history
is gone, and the first question anyone asks of an epistemic store is not "what
do you believe" but "why, and what did you believe before."

**The four closed sets, and why each one is closed.**

:class:`PropositionStatus` — ``OBSERVED``, ``DERIVED``, ``HYPOTHESIZED``,
``REFUTED``, ``CONTESTED``.  ``UNKNOWN`` is deliberately absent, and absence
from the store is the only way this kernel says it.  A represented ``UNKNOWN``
becomes a value, a value gets compared, and somewhere downstream "we have not
established X" is read as "X is false" — the single most expensive confusion
an inference layer can make.

:class:`EvidenceAuthority` — where a proposition's support came from, carried
on the proposition itself rather than inferred from its shape.
``DETERMINISTIC`` and ``SOURCE`` are the only two that may open the
:meth:`~core.cognition.state.CognitiveState.assert_observation` door;
``MODEL_EXTRACTION``, ``MODEL_INTERPRETATION`` and ``MODEL_HYPOTHESIS`` go
through :meth:`~core.cognition.state.CognitiveState.assert_hypothesis` and
land ``HYPOTHESIZED``.  The wall exists because a wrong proposition in a store
is worse than a wrong sentence in a transcript: deterministic machinery then
derives from it with confidence.

:class:`RuleAuthority` — ``SYSTEM``, ``SKILL``, ``DOMAIN`` participate in
closure.  ``PROPOSED`` does not, ever, until
:meth:`~core.cognition.state.CognitiveState.promote_rule` is called by
somebody who is not the model.  A model may propose a rule; proposing one
never makes it true.  This is enforced structurally — the closure engine reads
:attr:`Rule.participates_in_closure` and there is no second path to it — and
not by a check somebody has to remember to write.

:class:`ObligationState` — ``OPEN``, ``BLOCKED``, ``RESOLVED``.  See
:class:`Obligation`; obligations are computed, never authored.

**v1 bounds stated where they bite.**  Triple values are restricted to
JSON scalars, patterns use ``"?name"`` strings for variables (so no literal
string in a pattern may begin with ``?``), and there is no negation in a rule
body.  Each is noted again at the type it constrains.

**Two kinds of entity, and the wall between them is spelling.**  A receipt
entity is whatever the caller above calls one call's result (the shadow spells
it ``tool#seq``); a *subject* entity is the thing receipts are about, spelled
``kind:value`` — ``job:jl-731``, ``asset:led.a41``.  A subject is
content-addressed: the same job named by two tools is one entity, which is the
whole point of :class:`Link`.  :func:`check_subject` owns the spelling, and it
refuses ``#`` inside a subject so that the two namespaces cannot meet — see
that function for why "by construction" rather than "by convention" is the
only version of this that holds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple


# ── errors ──────────────────────────────────────────────────────────────────

class CognitionError(Exception):
    """Base for everything this package refuses."""


class AuthorityRefused(CognitionError):
    """An authority was offered at a door it is not allowed through.

    Both directions are this error: model evidence at ``assert_observation``,
    and a ``PROPOSED`` rule asked to derive.
    """


class RuleMalformed(CognitionError):
    """A rule that cannot be run: empty body, or a head variable the body
    never binds (range restriction)."""


class UnknownId(CognitionError):
    """A reference to a proposition, rule or goal this store never assigned."""


class ReplayRefused(CognitionError):
    """An event log this kernel cannot reconstruct exactly.

    Deliberately louder than the wire contract's rule.  A consumer of the
    mission stream drops record types it does not know and carries on, because
    the alternative is a platform that breaks on every minor release.  A
    *replay* has the opposite duty: a state rebuilt from a log with an event
    silently skipped is a state nobody can name, and it would be indexed,
    derived from and reported as if it were the original.
    """


# ── the closed sets ─────────────────────────────────────────────────────────

class PropositionStatus(Enum):
    """What the runtime holds about a claim. ``UNKNOWN`` is not here."""

    OBSERVED = "observed"
    DERIVED = "derived"
    HYPOTHESIZED = "hypothesized"
    REFUTED = "refuted"
    CONTESTED = "contested"


class EvidenceAuthority(Enum):
    """Where support came from. Travels with the proposition, always."""

    DETERMINISTIC = "deterministic"
    SOURCE = "source"
    MODEL_EXTRACTION = "model_extraction"
    MODEL_INTERPRETATION = "model_interpretation"
    MODEL_HYPOTHESIS = "model_hypothesis"


class RuleAuthority(Enum):
    """Who stands behind a rule. Only the first three derive anything."""

    SYSTEM = "system"
    SKILL = "skill"
    DOMAIN = "domain"
    PROPOSED = "proposed"


class ObligationState(Enum):
    """``OPEN`` is workable now; ``BLOCKED`` waits on another obligation;
    ``RESOLVED`` is a premise the store already satisfies, kept so a consumer
    can render "two of three" rather than only the remainder."""

    OPEN = "open"
    BLOCKED = "blocked"
    RESOLVED = "resolved"


#: The statuses a proposition must hold to be matched by a rule body or to
#: collide with another proposition. A ``HYPOTHESIZED`` proposition is stored,
#: contradicted and reported — it does not derive. **v1 bound**: hypothetical
#: closure (deriving under an assumption, then discharging it) is Phase 18+.
LIVE_STATUSES = (PropositionStatus.OBSERVED, PropositionStatus.DERIVED)

#: The two authorities `assert_observation` accepts.
OBSERVATION_AUTHORITIES = (EvidenceAuthority.DETERMINISTIC,
                           EvidenceAuthority.SOURCE)

#: The three `assert_hypothesis` accepts. The union of the two tuples is the
#: whole enum, and nothing is in both — that is the wall, written as data.
HYPOTHESIS_AUTHORITIES = (EvidenceAuthority.MODEL_EXTRACTION,
                          EvidenceAuthority.MODEL_INTERPRETATION,
                          EvidenceAuthority.MODEL_HYPOTHESIS)

#: The rule authorities closure reads. ``PROPOSED`` is the whole remainder.
TRUSTED_RULE_AUTHORITIES = (RuleAuthority.SYSTEM, RuleAuthority.SKILL,
                            RuleAuthority.DOMAIN)

#: Strongest first. A derived proposition carries the *weakest* authority
#: among its premises: a chain is worth its worst link, and rounding that up
#: is how model extraction launders itself into a deterministic-looking fact.
AUTHORITY_RANK = {
    EvidenceAuthority.DETERMINISTIC: 5,
    EvidenceAuthority.SOURCE: 4,
    EvidenceAuthority.MODEL_EXTRACTION: 3,
    EvidenceAuthority.MODEL_INTERPRETATION: 2,
    EvidenceAuthority.MODEL_HYPOTHESIS: 1,
}

#: How a re-assertion of a claim the store already holds settles its status.
#: Observation outranks derivation outranks hypothesis, so a hypothesis later
#: observed is promoted and an observation later hypothesized is not demoted.
#: ``REFUTED`` and ``CONTESTED`` are absent on purpose: they are terminal in
#: v1, and re-asserting into one appends evidence without reviving the claim.
#: **v1 bound**: there is no contradiction *resolution* — Phase 18+.
STATUS_RANK = {
    PropositionStatus.OBSERVED: 3,
    PropositionStatus.DERIVED: 2,
    PropositionStatus.HYPOTHESIZED: 1,
}

#: Every kind of :class:`Contradiction` this kernel records. Closed, and a
#: set rather than four string literals scattered through the store, because
#: a consumer that switches on the kind has to know when a fifth arrives —
#: and because the one thing that separates them is whether they move a
#: status: ``"hypothesis"`` does not, and the other three do.
CONTRADICTION_KINDS = ("value", "refutation", "dead_premise", "hypothesis")

#: How many values one field may carry for one entity at a time.
#:
#: **``"many"`` is the default for a field nobody declared**, and that choice
#: is the opposite of the one v1 shipped with.  A false ``CONTESTED`` is
#: destructive: contesting is terminal, it takes both sides out of closure,
#: and it takes every conclusion that rested on either of them.  A *missed*
#: contradiction costs a signal nobody got.  Under the owner's ruling — the
#: cognitive layer is shadow and additive, and a working harness beats a
#: strict one — the destructive default is the wrong way round, and a rule
#: pack that wants the check says so, field by field.
CARDINALITIES = ("one", "many")

#: What an undeclared field is. See :data:`CARDINALITIES` for the argument.
DEFAULT_CARDINALITY = "many"


# ── the records ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceRef:
    """An opaque pointer the caller supplies and the kernel never follows.

    ``kind`` and ``locator`` are whatever the caller's world calls them — a
    receipt and a sequence number, a tool and a call id, a file and a line.
    The kernel stores them, carries them onto revisions, hands them back at
    the leaves of :meth:`~core.cognition.state.CognitiveState.prove`, and has
    no opinion about what they mean.  It has to be that way: the moment this
    package can dereference an evidence ref it has acquired I/O, and the
    shadow-attachment lane loses the ability to run it anywhere.

    **``authority`` is the door's stamp, not the caller's field.**  A caller
    builds a ref with three strings; the door it is handed to —
    :meth:`~core.cognition.state.CognitiveState.assert_observation` or
    :meth:`~core.cognition.state.CognitiveState.assert_hypothesis` — writes
    the authority it accepted onto every ref before storing it, overwriting
    whatever was there.  Without that, the merge erases the wall: one claim
    observed *and* hypothesized ends up holding both sets of refs in one
    tuple, and nothing in the store can say which of them a model produced.
    With it, ``prove``'s leaves still answer "how do we know this" ref by ref
    after any number of merges.

    ``None`` means unstamped, and there are two ways to be unstamped: a
    refutation's evidence (a refutation is not one of the two doors) and a
    ref decoded from an older log written before the stamp existed.  Decode
    absent as absent — never guess a door from the shape of a locator.
    """

    kind: str
    locator: str
    note: str = ""
    authority: Optional[EvidenceAuthority] = None

    def stamped(self, authority: EvidenceAuthority) -> "EvidenceRef":
        """This ref as the door records it. The door's word wins."""
        return EvidenceRef(kind=self.kind, locator=self.locator,
                           note=self.note, authority=authority)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "locator": self.locator, "note": self.note,
                "authority": (None if self.authority is None
                              else self.authority.value)}

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "EvidenceRef":
        stamp = raw.get("authority")
        try:
            door = None if stamp is None else EvidenceAuthority(stamp)
        except ValueError as exc:
            raise ReplayRefused(f"no evidence authority {stamp!r}") from exc
        return EvidenceRef(kind=str(raw.get("kind", "")),
                           locator=str(raw.get("locator", "")),
                           note=str(raw.get("note", "")),
                           authority=door)


@dataclass(frozen=True)
class Proposition:
    """One claim, at one revision.

    A proposition is a triple ``(entity, field, value)``, or free text, or
    both — and at least one.  The triple is what a receipt yields and what a
    rule can match; the text is what only prose can say, and it is here so
    that "the deployment refused for a reason the schema has no field for"
    does not have to be discarded or forced into a fake triple.  **v1 bound**:
    text propositions never match a rule body and never contradict each other.
    This kernel does no natural-language understanding, and pretending two
    sentences disagree is exactly the pretence it exists to avoid.

    ``id`` is the identity of the *claim* and is stable across revisions.
    ``revision`` counts from 1 and ``previous`` names the key of the record
    this one replaced, so the history is a chain and not a set of orphans.
    :attr:`key` (``"p3@2"``) is the identity of the *record*.

    ``derivation`` is the id of the first derivation that established this
    proposition — the proof of record.  Alternative proofs exist and are
    reachable through
    :meth:`~core.cognition.state.CognitiveState.derivations_for`; they are not
    listed here because a frozen record that grew a list every time a second
    proof arrived would be a new revision per proof, and a proof is not a
    change of belief.
    """

    id: str
    entity: Optional[str] = None
    field: Optional[str] = None
    value: Any = None
    text: Optional[str] = None
    status: PropositionStatus = PropositionStatus.OBSERVED
    authority: EvidenceAuthority = EvidenceAuthority.SOURCE
    evidence: Tuple[EvidenceRef, ...] = ()
    derivation: Optional[str] = None
    revision: int = 1
    previous: Optional[str] = None

    @property
    def key(self) -> str:
        """The identity of this record, as opposed to the claim."""
        return f"{self.id}@{self.revision}"

    @property
    def triple(self) -> Optional[Tuple[str, str, Any]]:
        if self.entity is None or self.field is None:
            return None
        return (self.entity, self.field, self.value)

    @property
    def live(self) -> bool:
        return self.status in LIVE_STATUSES

    def render(self) -> str:
        trip = self.triple
        if trip is None:
            return f"“{self.text}”"
        out = f"({trip[0]}, {trip[1]}, {trip[2]!r})"
        return out if self.text is None else f"{out} “{self.text}”"


@dataclass(frozen=True)
class Link:
    """One receipt entity and the subject it is about, at one revision.

    ``(entity, subject)`` is the identity of the *link* and is stable across
    revisions; :attr:`key` (``"l3@2"``) is the identity of the record, and
    ``previous`` names the one it replaced — the edge-identity discipline
    :mod:`core.cognition.graph` already keeps, for the same reason: re-stating
    a link unions its evidence and raises its authority, and a record that was
    edited in place would lose which of the two a given ref arrived with.

    **A link is a claim, not a rename.**  It carries evidence (the receipt
    fact that held the identifier, and a ref naming the declaration that said
    the key was an identifier) and an authority stamped at
    :meth:`~core.cognition.state.CognitiveState.link`'s own door.  A
    deterministic linker enters at ``SOURCE`` and not ``DETERMINISTIC``: the
    weakest premise under it is the platform's declaration that a key means
    identity, and rounding that up would launder a declaration into a
    measurement.

    The ``MODEL_*`` grades are permitted at the door and nothing ships that
    uses them (§2.2 reserves the rung until the extraction door is measured in
    missions).  What they already do, so that the invariant cannot be lost
    later: the projections of a model-graded link land ``HYPOTHESIZED``, so a
    *guessed* identity can never contest an observation.
    """

    id: str
    entity: str
    subject: str
    authority: EvidenceAuthority
    evidence: Tuple[EvidenceRef, ...] = ()
    revision: int = 1
    previous: Optional[str] = None

    @property
    def key(self) -> str:
        """The identity of this record, as opposed to the link."""
        return f"{self.id}@{self.revision}"

    @property
    def kind(self) -> str:
        """The subject's kind — ``job`` in ``job:jl-731``."""
        return check_subject(self.subject)[0]

    @property
    def value(self) -> str:
        """The subject's identifier — ``jl-731`` in ``job:jl-731``."""
        return check_subject(self.subject)[1]

    def render(self) -> str:
        return f"({self.entity} is {self.subject})"


@dataclass(frozen=True)
class Rule:
    """A horn clause over triple patterns.

    ``body`` is a positive conjunction and ``head`` is one pattern.
    Variables are strings beginning with ``?``; every variable in the head
    must appear in the body (range restriction), or the rule would conclude
    something it cannot name.

    **v1 bound — no negation.**  There is no negation-as-failure here and
    none is coming in without a decision of its own.  A rule that fires
    because something is *absent* from the store fires on the store's
    incompleteness, and this store is incomplete by construction: absence is
    how it says ``UNKNOWN``.  Stratified negation over a closed set of
    entities is a Phase 18+ conversation with its own evidence.
    """

    id: str
    name: str
    authority: RuleAuthority
    head: Tuple[Any, Any, Any]
    body: Tuple[Tuple[Any, Any, Any], ...]

    @property
    def participates_in_closure(self) -> bool:
        """The only question the closure engine asks about authority."""
        return self.authority in TRUSTED_RULE_AUTHORITIES


@dataclass(frozen=True)
class Derivation:
    """One node of the proof DAG: a rule and its premises made a conclusion.

    A conclusion may have several derivations — alternative proofs.  It never
    has a duplicate proposition.

    ``link`` is set on exactly one kind of derivation: a *projection*, where
    the rule is
    :data:`~core.cognition.state.PROJECTION_RULE_ID` and the second premise is
    a :class:`Link` rather than a proposition.  It is a field of its own rather
    than a fourth entry in ``premises`` because ``premises`` is read as
    proposition ids everywhere in the engine — by the retraction cascade, by
    the confidence walk, by the proof walk — and smuggling a link id into that
    tuple would be a second meaning for the one field all of them agree on.
    The link is still a premise in every sense that matters: it caps the
    conclusion's grade, its evidence is at the proof's leaves, and it is named
    on the proof step.
    """

    id: str
    rule: str
    premises: Tuple[str, ...]
    conclusion: str
    link: Optional[str] = None


@dataclass(frozen=True)
class Goal:
    """A target pattern. What the run is trying to establish."""

    id: str
    pattern: Tuple[Any, Any, Any]
    note: str = ""


@dataclass(frozen=True)
class Obligation:
    """One unresolved requirement standing between a goal and its rule.

    **Computed, never authored.**  Nobody writes an obligation down; the
    store reads goals against trusted rules against what it currently holds,
    and every premise it cannot satisfy is one of these.  That inversion is
    the point of the whole arc: the runtime stops asking the model what to do
    next and starts telling it what is missing.

    ``id`` is content-addressed — goal, rule, body position and the pattern as
    resolved so far — rather than a counter, because obligations are recomputed
    from scratch on every read and a counter would rename them each time.
    ``position`` is the computation order and is the documented tie-break for
    :meth:`~core.cognition.state.CognitiveState.next_obligation`.
    """

    id: str
    goal: str
    rule: Optional[str]
    position: int
    pattern: Tuple[Any, Any, Any]
    state: ObligationState
    depends_on: Tuple[str, ...] = ()

    def render(self) -> str:
        """The pattern as a reader meets it: ``(alice, payment_link, ?c)``.

        **Display only**, and deliberately not :func:`render_pattern`, which
        is what :attr:`id` is content-addressed with: an id has to be stable
        and unambiguous, a line a model reads has to be legible, and one
        function cannot be both.

        A variable is printed bare.  Through ``repr`` it came out as
        ``'?c'`` — quoted exactly like a literal string, in the one position
        where the difference between "this is the thing that is missing" and
        "this is a value we know" is the whole meaning of the line.  A
        literal keeps its ``repr``, so ``8`` and ``'8'`` still do not read
        the same.
        """
        return "(" + ", ".join(
            str(term) if index < 2 or is_variable(term) else repr(term)
            for index, term in enumerate(self.pattern)) + ")"


class Frontier(tuple):
    """Obligations, and whether the join that produced them was cut short.

    A ``tuple`` subclass rather than a wrapper, because the obligations are
    what a caller wants nine times out of ten and making them reach through
    an attribute for the common case would be a worse API for the sake of a
    flag.

    The flag is here because a truncated join and an exhausted one look
    identical from the outside: both return obligations and neither says
    anything.  This repository's rule is that a budget exhausted is a
    *recorded outcome naming the budget* — the harness says so when it stops
    for steps, for tokens, for wall clock — and a frontier that quietly
    stopped being complete is the same event with nobody told.

    **The flag does not survive a slice.**  ``tuple(frontier)``,
    ``frontier[:3]`` and anything else that builds a new sequence out of this
    one give back a plain ``tuple`` — that is what a ``tuple`` subclass does,
    and overriding half of ``tuple`` to carry a field most of those results
    have no claim to would be worse than saying so here.  Read
    ``.truncated`` off the object
    :meth:`~core.cognition.state.CognitiveState.obligations` or
    :meth:`~core.cognition.state.CognitiveState.frontier` handed you, before
    narrowing it.
    """

    # No `__slots__`: a tuple subclass cannot have a non-empty one, and the
    # flag has to live somewhere.

    def __new__(cls, items=(), truncated: bool = False) -> "Frontier":
        made = super().__new__(cls, items)
        made.truncated = bool(truncated)
        return made

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Frontier({tuple(self)!r}, "
                f"truncated={self.truncated!r})")


@dataclass(frozen=True)
class Support:
    """How well one proposition is held up, computed when it is asked for.

    ``grade`` is the headline and the reason this is a *read* rather than a
    field on :class:`Proposition`: it is the best authority any live proof of
    the claim can offer — the maximum, over proofs still standing, of the
    weakest premise in that proof — and it is computed from the DAG every
    time.  A stored grade goes stale the moment anything underneath it moves,
    and the move that matters is the good one: a premise first extracted from
    prose and later confirmed by a receipt lifts everything derived from it,
    and a store reporting the old number would be understating its own
    evidence for as long as nobody re-derived.

    ``contested_by`` and ``hypothesis`` are contradiction ids — the first the
    collisions that moved this claim's status, the second the model claims
    that disagree with it and deliberately moved nothing.  Kept apart because
    they mean opposite things to a reader: one says the store cannot stand
    behind this, the other says the store can and something else did not.

    ``evidence_leaves`` is every ref at the bottom of the proof, deduplicated
    and in discovery order, each still carrying the door it came through.
    """

    proposition: str
    status: PropositionStatus
    grade: Optional[EvidenceAuthority]
    contested_by: Tuple[str, ...] = ()
    hypothesis: Tuple[str, ...] = ()
    evidence_leaves: Tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True)
class Contradiction:
    """Two claims that cannot both stand, named as an object.

    ``kind`` is one of :data:`CONTRADICTION_KINDS`:

    * ``"value"`` — two *live* propositions give the same ``(entity, field)``
      different values.  Both become ``CONTESTED``.
    * ``"refutation"`` — a caller refuted one outright; ``right`` is ``None``
      because the other side is the evidence carried here.
    * ``"dead_premise"`` — a derived conclusion whose every proof rests on
      something no longer live.
    * ``"hypothesis"`` — a model's claim disagrees with what the store
      observed.  ``left`` is always the hypothesis and ``right`` the live
      proposition, whichever arrived first.  **Nothing changes status**: the
      hypothesis stays ``HYPOTHESIZED``, the observation stays live, and this
      object is the whole of the event.  It is the signal the shadow layer
      wants before any other — the model said one thing and the receipt said
      another — and it is confidence marking, not a gate.  A store that
      contested the observation here would let a wrong extraction unseat a
      receipt, which is the laundering the walls exist to stop.

    Neither side wins silently.  For the three kinds that *do* move a status,
    a store that picked the newer, or the better-authorised, or the one with
    more evidence would be doing the one thing it is least equipped to do —
    and would do it without saying so.

    ``settled`` and ``kept`` are the one deliberate exception to that
    terminality, and they can only be written by
    :meth:`~core.cognition.state.CognitiveState.settle` — an explicit,
    evidenced call naming which side stands.  ``kept`` names the claim this
    row stopped standing against: for a ``"value"`` collision that is the
    side the caller chose, and for a ``"dead_premise"`` row retired by the
    same settlement it is the conclusion that came back when its premise did.
    Both are "what survived this row", which is what a reader of a settled
    contradiction is asking.  **The kernel executes a
    settlement; it never decides one.**  Which side to keep is a judgement
    about the world, made by whatever is attached above (a deterministic
    re-read, an operator, a later receipt), and the kernel's whole claim to
    being trustworthy rests on not making it.
    """

    id: str
    kind: str
    left: str
    right: Optional[str] = None
    evidence: Tuple[EvidenceRef, ...] = ()
    detail: str = ""
    settled: bool = False
    kept: Optional[str] = None


@dataclass(frozen=True)
class ProofStep:
    """One rule application inside a :class:`Proof`.

    ``link`` names the :class:`Link` that licensed a *projection* step and is
    ``None`` for every ordinary rule.  Without it a reader walking the proof of
    a subject-level fact would see a step whose rule is ``projection`` and have
    no way to ask *which* link it rested on — which is the one question a
    wrong link makes urgent.
    """

    derivation: str
    rule: str
    rule_name: str
    premises: Tuple["Proof", ...]
    link: Optional[str] = None


@dataclass(frozen=True)
class Proof:
    """The derivation DAG under one proposition, evidence at the leaves.

    ``steps`` is one entry per derivation of this proposition and ``evidence``
    is what was filed directly against it; a node is a *leaf* when it has no
    steps, and that is a fact about the proposition rather than about its
    status.  An ``OBSERVED`` proposition normally is one — but a rule may also
    derive something the store observed independently, and then the node
    carries both its receipts and its proof.  Reading "observed" as "leaf"
    would drop that proof from the walk, which is the half of the provenance
    the store was keeping.

    ``cyclic`` marks a premise already on the path from the root.  Rules can
    describe cycles (``a :- b`` and ``b :- a``); closure terminates anyway
    because a derivation is deduplicated by ``(rule, premises, conclusion)``,
    but a naive walk of the result would not, so the walk stops and says so
    rather than recursing.
    """

    proposition: str
    status: PropositionStatus
    authority: EvidenceAuthority
    evidence: Tuple[EvidenceRef, ...] = ()
    steps: Tuple[ProofStep, ...] = ()
    cyclic: bool = False


@dataclass
class MatchStats:
    """An instrument, not state.

    Semi-naive closure is a claim about work *not* done, and a claim about
    work not done cannot be tested by reading the answer — a naive engine
    returns the same propositions.  These counters are how the incrementality
    test can fail.  They are excluded from
    :meth:`~core.cognition.state.CognitiveState.digest` and from the event
    log for the same reason: a replayed store must equal its original, and
    the original was read by somebody and the replay was not.

    ``envs_truncated`` is the odd one out and is here for the opposite
    reason: it counts a place the kernel gave an *incomplete* answer on
    purpose.  Obligation computation caps its join
    (:data:`~core.cognition.state.ENV_CAP`), and a frontier that quietly
    stopped being exhaustive looks exactly like a frontier that had nothing
    more to say.  A caller that wants to know reads this.

    ``candidates_scanned`` is the finest of them and the one a *performance*
    claim has to be made against.  ``rules_considered`` says which rules the
    engine looked at; this says how many propositions it then had to walk to
    answer them, which is where the difference between a join that starts
    from the delta and one that starts from an unconstrained premise shows
    up.  A wall-clock assertion would be a test that fails on a busy machine;
    this is the same claim with a number that is the machine's business.
    """

    delta_passes: int = 0
    rules_considered: int = 0
    body_scans: int = 0
    candidates_scanned: int = 0
    envs_truncated: int = 0

    def reset(self) -> None:
        self.delta_passes = 0
        self.rules_considered = 0
        self.body_scans = 0
        self.candidates_scanned = 0
        self.envs_truncated = 0


# ── value and pattern validation ────────────────────────────────────────────

#: What a triple's value may be. **v1 bound**, and the reason is replay:
#: every mutating call is serialized to a plain dict, and a value that does
#: not survive `json.dumps`/`json.loads` unchanged is a state that does not
#: reconstruct exactly. A caller with something richer stores a locator for
#: it in an `EvidenceRef` and puts a scalar in the triple.
VALUE_TYPES = (str, int, float, bool, type(None))


def check_value(value: Any) -> Any:
    """A triple value, or a refusal naming why it cannot be one.

    The non-finite floats are refused here and not merely discouraged, for
    two reasons that arrive in the wrong order.  The one that bites first is
    in memory: ``float("nan") != float("nan")``, so a claim keyed on a NaN is
    a claim that never equals itself — assert it twice and the store mints
    two propositions for one claim, which is the duplicate every merge rule
    in this package exists to prevent.  The one that bites later is on the
    wire: ``json.dumps`` writes bare ``NaN`` and ``Infinity``, which are not
    RFC 8259 and which a non-Python reader of the log either rejects or
    reads as something else.  Between them the two make a store that does not
    replay to itself, and a receipt carrying a NaN is a receipt whose number
    is missing — a fact about the world this kernel says by *absence*.
    """
    if not isinstance(value, VALUE_TYPES):
        raise CognitionError(
            f"a triple value must be a JSON scalar, not {type(value).__name__}")
    if isinstance(value, float) and not math.isfinite(value):
        raise CognitionError(
            f"{value!r} is not a value: it never equals itself (so one claim "
            "would become two propositions) and it is not JSON any reader "
            "outside Python will take. A number that is not there is said "
            "here by leaving the proposition out")
    return value


def value_tag(value: Any) -> str:
    """The type band a value belongs to, for claim identity and collision.

    Python says ``True == 1`` and ``hash(True) == hash(1)``, so without this
    a store told ``(job, retried, True)`` and then ``(job, retried, 1)``
    would hold *one* claim at whichever value arrived first and report no
    disagreement — a silent first-wins on exactly the extraction confusion
    this kernel is built to surface.  With it the two are different claims
    that contradict.

    ``int`` and ``float`` share a band on purpose: ``1`` and ``1.0`` are the
    same number, said twice, and a store that contested them would be
    reporting a disagreement about a rendering.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    return "str"


# ── subject entities ────────────────────────────────────────────────────────

#: What separates a subject entity's kind from its value: ``job:jl-731``.
SUBJECT_SEPARATOR = ":"

#: The character a subject may not carry, in either half. It is the one the
#: shadow's receipt entities are spelled with (``tool#seq``), and banning it
#: here is what makes the two namespaces disjoint rather than merely different
#: by habit. See :func:`check_subject`.
RECEIPT_MARKER = "#"

#: What a subject's *kind* may carry. Deliberately narrow — a kind is a word a
#: platform declares once (``job``, ``asset``, ``run``), it is read by people
#: in a compiled view, and every character admitted here is one a renderer, a
#: log reader and a pattern literal all have to survive.
SUBJECT_KIND_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_-.")

#: How long either half of a subject may be, in the idiom of
#: :data:`core.cognition.graph.store.NAME_CAP` and for the same reason: an
#: unbounded name is an unbounded key in three indexes, an unbounded string in
#: every log line, and an unbounded row in a compiled context. Generous enough
#: for a URI or a fully-qualified identifier; small enough that a payload
#: pasted into the value position is refused at the door rather than
#: discovered in a working set.
SUBJECT_CAP = 512


def check_subject(subject: Any) -> Tuple[str, str]:
    """``(kind, value)`` for a subject entity, or a refusal naming why not.

    **The one owner of what a subject is spelled like.**  Every other question
    in this package about subjects — is this string one (:func:`subject_parts`),
    may this string be a link's *entity*
    (:meth:`~core.cognition.state.CognitiveState.link`), what does a caller
    spell for a kind and a value (:func:`subject_entity`) — is this function
    asked.  A second idea of the spelling is a second namespace, and the two
    would agree until the day a tool name carried a colon.

    Four rules, and the third is the load-bearing one:

    * exactly one split, at the **first** :data:`SUBJECT_SEPARATOR`; both
      halves non-empty.  A value may itself carry ``:`` (``result:mcp://x``),
      which costs nothing because the split is at the first one and never
      ambiguous;
    * the kind is drawn from :data:`SUBJECT_KIND_CHARS`, so it cannot contain
      the separator and a kind is always exactly what precedes the first one;
    * neither half carries :data:`RECEIPT_MARKER`.  **This is what keeps
      subject entities and receipt entities disjoint by construction.**  The
      kernel does not own the spelling of a receipt entity — the shadow above
      it does — so "the two namespaces do not overlap" cannot be a promise
      about the caller's habits.  What it can be is a promise about *this*
      function: no string containing ``#`` is ever a subject, and
      :meth:`~core.cognition.state.CognitiveState.link` refuses a
      subject-spelled string in the entity position.  Between them, a
      projection can never land on an entity a receipt could be named, and a
      receipt can never be linked to itself under a second spelling;
    * neither half carries whitespace or a control character, and neither
      exceeds :data:`SUBJECT_CAP`.

    A variable spelling (``?job``) is refused with the rest: ``?`` is not in
    :data:`SUBJECT_KIND_CHARS`, so a pattern variable can never be mistaken
    for a subject of kind ``?job``.
    """
    if not isinstance(subject, str) or not subject:
        raise CognitionError(
            "a subject entity is a non-empty string spelled "
            f"'kind{SUBJECT_SEPARATOR}value', not "
            f"{type(subject).__name__}")
    kind, sep, value = subject.partition(SUBJECT_SEPARATOR)
    if not sep or not kind or not value:
        raise CognitionError(
            f"{subject!r} is not a subject: a subject is spelled "
            f"'kind{SUBJECT_SEPARATOR}value' with both halves present, "
            "because a subject with no kind is a bare string two platforms "
            "would collide on")
    if not set(kind) <= SUBJECT_KIND_CHARS:
        raise CognitionError(
            f"{kind!r} is not a subject kind: a kind carries letters, digits, "
            "'_', '-' and '.' and nothing else")
    for half, what in ((kind, "kind"), (value, "value")):
        if len(half) > SUBJECT_CAP:
            raise CognitionError(
                f"a subject's {what} is at most {SUBJECT_CAP} characters; "
                f"this one is {len(half)}")
    if RECEIPT_MARKER in value:
        raise CognitionError(
            f"{subject!r} carries {RECEIPT_MARKER!r}, which is how the layer "
            "above spells a receipt entity; subjects and receipts are "
            "disjoint by construction and not by agreement, so that a "
            "projection can never land where a receipt's own facts live")
    bad = [ch for ch in value
           if ch.isspace() or ord(ch) < 32 or ord(ch) == 127]
    if bad:
        raise CognitionError(
            f"a subject's value carries no whitespace and no control "
            f"characters; {subject!r} has {bad[0]!r}")
    return kind, value


def subject_parts(entity: Any) -> Optional[Tuple[str, str]]:
    """``(kind, value)`` if this string is spelled as a subject, else ``None``.

    The total-function face of :func:`check_subject`, for the callers asking
    *which namespace is this* rather than *give me this subject*.  It delegates
    rather than re-deciding: one owner, and the refusal messages stay in the
    one place that can explain them.
    """
    try:
        return check_subject(entity)
    except CognitionError:
        return None


def subject_entity(kind: Any, value: Any) -> str:
    """Spell a subject from its two halves, or refuse.

    The round trip is *checked* rather than assumed: a kind carrying the
    separator would spell a string that parses back as a different subject
    entirely, and a caller building one out of a declaration's kind and a
    payload's value has no reason to have thought about that.
    """
    spelled = f"{kind}{SUBJECT_SEPARATOR}{value}"
    parts = check_subject(spelled)
    if parts != (str(kind), str(value)):
        raise CognitionError(
            f"{kind!r} and {value!r} spell {spelled!r}, which reads back as "
            f"{parts[0]!r} and {parts[1]!r}; a subject's kind ends at the "
            "first separator")
    return spelled


def is_variable(term: Any) -> bool:
    """``"?actor"`` is a variable; ``"actor"`` is not."""
    return isinstance(term, str) and term.startswith("?")


def check_pattern(pattern: Sequence[Any]) -> Tuple[Any, Any, Any]:
    """Three terms, each a variable or a literal; literals validated.

    A literal string may not begin with ``?`` — that spelling is the variable
    marker, and there is no escape for it in v1.  Refusing is the honest
    option: the alternative is a literal that silently becomes a wildcard and
    a rule that fires on everything.
    """
    terms = tuple(pattern)
    if len(terms) != 3:
        raise RuleMalformed(f"a pattern is three terms, got {len(terms)}")
    out = []
    for i, term in enumerate(terms):
        if is_variable(term):
            out.append(term)
            continue
        if i < 2:
            if not isinstance(term, str) or not term:
                raise RuleMalformed(
                    "a pattern's entity and field are non-empty strings "
                    "or variables")
        else:
            check_value(term)
        out.append(term)
    return (out[0], out[1], out[2])


def render_pattern(pattern: Sequence[Any]) -> str:
    e, f, v = pattern
    return f"({e},{f},{v!r})"


def variables_in(pattern: Sequence[Any]) -> Tuple[str, ...]:
    return tuple(term for term in pattern if is_variable(term))
