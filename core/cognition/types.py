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
    """

    id: str
    rule: str
    premises: Tuple[str, ...]
    conclusion: str


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
        e, f, v = self.pattern
        return f"({e}, {f}, {v!r})"


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
    """

    id: str
    kind: str
    left: str
    right: Optional[str] = None
    evidence: Tuple[EvidenceRef, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class ProofStep:
    """One rule application inside a :class:`Proof`."""

    derivation: str
    rule: str
    rule_name: str
    premises: Tuple["Proof", ...]


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
    """

    delta_passes: int = 0
    rules_considered: int = 0
    body_scans: int = 0
    envs_truncated: int = 0

    def reset(self) -> None:
        self.delta_passes = 0
        self.rules_considered = 0
        self.body_scans = 0
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
