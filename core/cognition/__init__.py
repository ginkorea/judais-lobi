# core/cognition/__init__.py — the epistemic kernel: what is believed, and why

"""The symbolic half of JUDAIS/LOBI. The runtime holds the problem.

**The thesis, stated so it can be falsified** (ROADMAP §2.9.1): *a local
language model becomes materially more capable when the runtime externalizes
problem state, deterministic inference, planning state, constraints and
verification, rather than forcing the model to perform those functions inside
its context window.*  Every harness this repository has shipped owns
*execution* state — messages, steps, receipts, budgets — while the model owns
*problem* state: what is known, what is uncertain, what follows, what
conflicts, what remains.  For a 20B that division is the expensive one.  This
package is the other side of it: the runtime, not the model, holds what is
believed, why it is believed, what contradicts it, and what is still owed.

``LOBI`` — Local Orchestrated Belief Infrastructure — is the store.
``JUDAIS`` — Judicious Unified Decision And Inference System — is the question
it answers: given what is currently represented, what should happen next.
:meth:`~core.cognition.state.CognitiveState.frontier` and
:meth:`~core.cognition.state.CognitiveState.next_obligation` are that
sentence in code, and the inversion is the point — the runtime stops asking
the model "what should I do next?" and starts telling it "resolve this."

**What this is NOT, from the owner's ruling of 13 September 2026**
(ROADMAP §2.9.3).  Evidence gating that blocks a working harness was tried in
production and partially removed — "evidence is great, but a functioning
harness is better."  So the cognitive layer is **shadow and additive from
birth**.  This package produces state and guidance, never a verdict on an
answer.  **Nothing in it may ever refuse or gate a mission**: cognition off
is byte-identical, and cognition on never blocks an answer.  There is no
refusal in here to find, because there is no call in here that a mission
loop waits on for permission.

*Additive* is the half Phase 18 spends.  :mod:`core.cognition.compile`
renders this store into one block of model input, so with
``--compiled-context`` the model **reads** what the runtime believes — and
that is still not a gate: the block is added to a turn, nothing is taken
away, no answer is held, checked or refused against it, and a compiler that
fails leaves the mission exactly as it was.

It is also deliberately small about what it does not do.  No I/O — it never
opens a file, a socket or a model.  No natural-language parsing: turning a
receipt into propositions is *extraction*, it happens outside, and its
reliability is Phase 16's number.  No
imports from :mod:`core.runtime`, on purpose and permanently: the
shadow-attachment lane depends on this package and not the other way round,
and a kernel that cannot be imported on its own cannot be swapped for a
different one.  **Deliberately replaceable: the API is the experiment.**

**Determinism is the load-bearing property.**  Every iteration is
insertion-ordered, and there is no clock and no randomness anywhere in the
package.  A store is exactly its event log (:mod:`core.cognition.events`) and
:meth:`~core.cognition.state.CognitiveState.replay` rebuilds it through the
same public methods that wrote it.  That log has a schema version **of its
own** — :data:`~core.cognition.events.EVENT_SCHEMA_VERSION`, which is not
:data:`core.runtime.contract.SCHEMA_VERSION` and must never be conflated with
it.

**But an id is not a name for a claim.**  Ids are handed out in insertion
order, and insertion order is a function of the *interleaving* of writes and
flushes — not of the writes alone.  The same assertions, with a read in the
middle, put a derived proposition into the sequence earlier and shift every
id after it.  The engine's own enumeration order counts too, which is what
:data:`~core.cognition.events.KERNEL_VERSION` records.  So ``p7`` means
something inside one store's history and nothing outside it: anything
persisting a proposition id across runs, sessions or engine versions is
persisting a fact about a run.  What *is* stable is the claim
(:meth:`~core.cognition.state.CognitiveState.claim` turns a triple back into
this store's id) and the content-addressed obligation id.

**The v1 bounds, in one place** (each is argued again where it bites):

* Rule bodies are positive conjunctions.  **No negation-as-failure** — a rule
  that fires on absence fires on this store's incompleteness, and absence is
  how this store says ``UNKNOWN``.  The positive alternative, for pack
  authors: have a deterministic tool **attest completeness as a fact** —
  ``(listing-7, complete, true)`` beside the listing it describes — and write
  the rule against that.  Then "nothing else exists" is a claim somebody
  made, with a receipt, that can be contested like any other, instead of a
  silence the engine interpreted.
* Only ``OBSERVED`` and ``DERIVED`` propositions participate in closure.  A
  ``HYPOTHESIZED`` one is stored, contradicted and reported.  Hypothetical
  closure is deferred, and the invariant it must preserve is recorded now,
  because it is the one that would be easy to lose: **a hypothetical
  derivation must never satisfy an obligation.**  The frontier exists to say
  what is still owed; a frontier that a guess can empty is a frontier that
  reports the model's confidence back to the model.
* Text-only propositions never match a rule and never contradict each other.
  This kernel does not read English.
* A derived conclusion whose every proof rests on something no longer live is
  retracted to ``CONTESTED``, naming the dead premise.  Not marked stale —
  see :mod:`core.cognition.state` for the argument and the alternative.
* Triple values are finite JSON scalars; a pattern variable is a string
  beginning with ``?``, so no literal in a pattern may.
* **A field carries many values unless somebody declares it carries one**
  (:meth:`~core.cognition.state.CognitiveState.declare_field`).  Collision
  detection is a claim about the field and nothing in a triple says which
  kind it is; the default is ``many`` because a false ``CONTESTED`` is
  destructive — it is terminal, and it takes everything derived from either
  side — while a missed one costs a signal.
* A hypothesis that disagrees with an observation is **reported and not
  acted on** — a ``"hypothesis"`` contradiction, no status moved either way.
* Obligation computation caps its join at
  :data:`~core.cognition.state.ENV_CAP` environments and *says so*
  (:attr:`~core.cognition.types.Frontier.truncated`).  The frontier is the
  cheapest true thing to do next, not a proof that nothing else is missing.
* Contesting is terminal **except through**
  :meth:`~core.cognition.state.CognitiveState.settle`: an explicit, evidenced
  call naming which side stands.  The kernel executes a settlement and never
  decides one — which side is right is a judgement about the world, and it
  belongs to whatever is attached above.
* A snapshot is a versioned mapping, and a replay refuses a log it cannot
  reconstruct exactly — including one whose sequence numbers say it has been
  reordered, truncated or added to.

The five modules: :mod:`~core.cognition.types` (the records and the closed
sets), :mod:`~core.cognition.matching` (unification, and nothing else),
:mod:`~core.cognition.events` (the log and its version),
:mod:`~core.cognition.state` (the store), and
:mod:`~core.cognition.compile` (Phase 18's *context compiler*: the store as
one bounded block of model input — a pure read, under the same
constitution, and the one thing in this package whose output a model ever
sees).

**The sibling.**  :mod:`core.cognition.graph` holds entity↔entity
*relationships* under the same constitution — pure, deterministic, replayable,
shadow and additive.  The division is one sentence: this package owns
attribute claims and derivation, that one owns topology, an edge lives there
once, and its ``as_propositions`` is a derived projection for when a rule here
needs edges as triples.  It reuses this package's
:class:`~core.cognition.types.EvidenceAuthority` and
:class:`~core.cognition.types.EvidenceRef` rather than minting its own, and
nothing here imports it: the dependency runs one way, the way every other one
in this package does.
"""

from core.cognition.compile import (BANDS, BUDGET_CHARS, CompiledView, band,
                                    compile_view, owed_line)
from core.cognition.events import (COUNT_KEY, EVENT_OPS,
                                   EVENT_SCHEMA_VERSION, EVENTS_KEY,
                                   KERNEL_KEY, KERNEL_VERSION, SCHEMA_KEY,
                                   deep_copy, freeze)
from core.cognition.matching import resolve, unify, unify_patterns
from core.cognition.state import DIGEST_KEYS, ENV_CAP, CognitiveState
from core.cognition.types import (AUTHORITY_RANK, CARDINALITIES,
                                  CONTRADICTION_KINDS,
                                  DEFAULT_CARDINALITY,
                                  HYPOTHESIS_AUTHORITIES,
                                  LIVE_STATUSES, OBSERVATION_AUTHORITIES,
                                  STATUS_RANK, TRUSTED_RULE_AUTHORITIES,
                                  AuthorityRefused, CognitionError,
                                  Contradiction, Derivation, EvidenceAuthority,
                                  EvidenceRef, Frontier, Goal, MatchStats,
                                  Obligation, ObligationState, Proof,
                                  ProofStep, Proposition,
                                  PropositionStatus, ReplayRefused, Rule,
                                  RuleAuthority, RuleMalformed, Support,
                                  UnknownId, is_variable, value_tag)

__all__ = [
    "AUTHORITY_RANK",
    "AuthorityRefused",
    "BANDS",
    "BUDGET_CHARS",
    "CognitionError",
    "CognitiveState",
    "CompiledView",
    "CARDINALITIES",
    "COUNT_KEY",
    "CONTRADICTION_KINDS",
    "Contradiction",
    "DEFAULT_CARDINALITY",
    "DIGEST_KEYS",
    "Derivation",
    "ENV_CAP",
    "EVENTS_KEY",
    "EVENT_OPS",
    "EVENT_SCHEMA_VERSION",
    "EvidenceAuthority",
    "EvidenceRef",
    "Frontier",
    "Goal",
    "HYPOTHESIS_AUTHORITIES",
    "KERNEL_KEY",
    "KERNEL_VERSION",
    "LIVE_STATUSES",
    "MatchStats",
    "OBSERVATION_AUTHORITIES",
    "Obligation",
    "ObligationState",
    "Proof",
    "ProofStep",
    "Proposition",
    "PropositionStatus",
    "ReplayRefused",
    "Rule",
    "RuleAuthority",
    "RuleMalformed",
    "SCHEMA_KEY",
    "STATUS_RANK",
    "Support",
    "TRUSTED_RULE_AUTHORITIES",
    "UnknownId",
    "band",
    "compile_view",
    "deep_copy",
    "freeze",
    "is_variable",
    "owed_line",
    "resolve",
    "unify",
    "unify_patterns",
    "value_tag",
]
