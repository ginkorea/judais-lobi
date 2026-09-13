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
answer.  **Nothing in it may ever refuse or gate a mission**, and nothing in
it is on the answer path: cognition off is byte-identical, and cognition on
never blocks an answer.  There is no refusal in here to find, because there is
no call in here that a mission loop waits on for permission.

It is also deliberately small about what it does not do.  No I/O — it never
opens a file, a socket or a model.  No natural-language parsing: turning a
receipt into propositions is *extraction*, it happens outside, and its
reliability is Phase 16's number.  No context compiling — Phase 18.  No
imports from :mod:`core.runtime`, on purpose and permanently: the
shadow-attachment lane depends on this package and not the other way round,
and a kernel that cannot be imported on its own cannot be swapped for a
different one.  **Deliberately replaceable: the API is the experiment.**

**Determinism is the load-bearing property.**  Ids are assigned by insertion
order, every iteration is insertion-ordered, and there is no clock and no
randomness anywhere in the package.  A store is exactly its event log
(:mod:`core.cognition.events`) and
:meth:`~core.cognition.state.CognitiveState.replay` rebuilds it through the
same public methods that wrote it.  That log has a schema version **of its
own** — :data:`~core.cognition.events.EVENT_SCHEMA_VERSION`, which is not
:data:`core.runtime.contract.SCHEMA_VERSION` and must never be conflated with
it.

**The v1 bounds, in one place** (each is argued again where it bites):

* Rule bodies are positive conjunctions.  **No negation-as-failure** — a rule
  that fires on absence fires on this store's incompleteness, and absence is
  how this store says ``UNKNOWN``.
* Only ``OBSERVED`` and ``DERIVED`` propositions participate in closure.  A
  ``HYPOTHESIZED`` one is stored, contradicted and reported; hypothetical
  closure is Phase 18+.
* Text-only propositions never match a rule and never contradict each other.
  This kernel does not read English.
* A derived conclusion whose every proof rests on something no longer live is
  retracted to ``CONTESTED``, naming the dead premise.  Not marked stale —
  see :mod:`core.cognition.state` for the argument and the alternative.
* Triple values are JSON scalars; a pattern variable is a string beginning
  with ``?``, so no literal in a pattern may.
* **Every field is single-valued.**  Two live propositions giving one
  ``(entity, field)`` different values contradict.  Right for ``total_s``,
  wrong for ``controls``; there is no cardinality declaration yet and
  :meth:`~core.cognition.state.CognitiveState._collide` carries the
  workaround and the Phase 18+ fix.
* Obligation computation caps its join at
  :data:`~core.cognition.state.ENV_CAP` environments.  The frontier is the
  cheapest true thing to do next, not a proof that nothing else is missing.
* There is no contradiction *resolution*.  Contesting is terminal in v1.

The five modules: :mod:`~core.cognition.types` (the records and the closed
sets), :mod:`~core.cognition.matching` (unification, and nothing else),
:mod:`~core.cognition.events` (the log and its version),
:mod:`~core.cognition.state` (the store).
"""

from core.cognition.events import (EVENT_OPS, EVENT_SCHEMA_VERSION, EVENTS_KEY,
                                   SCHEMA_KEY)
from core.cognition.matching import resolve, unify, unify_patterns
from core.cognition.state import ENV_CAP, CognitiveState
from core.cognition.types import (AUTHORITY_RANK, HYPOTHESIS_AUTHORITIES,
                                  LIVE_STATUSES, OBSERVATION_AUTHORITIES,
                                  STATUS_RANK, TRUSTED_RULE_AUTHORITIES,
                                  AuthorityRefused, CognitionError,
                                  Contradiction, Derivation, EvidenceAuthority,
                                  EvidenceRef, Goal, MatchStats, Obligation,
                                  ObligationState, Proof, ProofStep,
                                  Proposition, PropositionStatus,
                                  ReplayRefused, Rule, RuleAuthority,
                                  RuleMalformed, UnknownId, is_variable)

__all__ = [
    "AUTHORITY_RANK",
    "AuthorityRefused",
    "CognitionError",
    "CognitiveState",
    "Contradiction",
    "Derivation",
    "ENV_CAP",
    "EVENTS_KEY",
    "EVENT_OPS",
    "EVENT_SCHEMA_VERSION",
    "EvidenceAuthority",
    "EvidenceRef",
    "Goal",
    "HYPOTHESIS_AUTHORITIES",
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
    "TRUSTED_RULE_AUTHORITIES",
    "UnknownId",
    "is_variable",
    "resolve",
    "unify",
    "unify_patterns",
]
