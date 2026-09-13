# core/cognition/graph/__init__.py — the topology beside the kernel: what is connected to what

"""The kernel's sibling. The runtime holds the relationships, and on whose word.

:mod:`core.cognition` holds what is *believed* — ``(entity, field, value)``
with a status and a proof.  This package holds what is *connected*: entity to
entity, under a named relation, with the authority that relationship arrived
on.  Same constitution, and it is the constitution rather than the feature
list that makes the two swappable: pure Python, no I/O, no clock, no
randomness, no import of :mod:`core.runtime`, ids from insertion order, and a
store that is exactly its event log.

**The division of labor, and it is the reason this is a separate package.**

*The kernel owns attribute claims and derivation.*  ``(alice, role, "admin")``
is a claim about the world with a status, a proof and a way to be contradicted.

*The graph owns entity↔entity relationships and topology.*  ``alice —reports_to→
bob`` is a relationship, and it lives here, **once**.
:meth:`~core.cognition.graph.store.KnowledgeGraph.as_propositions` is a
*derived projection* for the moment a kernel rule needs edges as triples — it
is computed on call, never stored, and nothing writes it into a
:class:`~core.cognition.state.CognitiveState` behind the caller's back.  **No
second owner of any fact.**

The line is not arbitrary.  The kernel treats every field as single-valued and
says so in its own docstring: ``(alice, controls, acct-1)`` and
``(alice, controls, acct-2)`` contradict there, and its suggested workaround is
to flip the multi-valued end into the entity position.  A graph does not need
the workaround — relations here are many-valued by construction, two edges out
of one node under one relation are simply two edges, and nothing in this
package ever raises a contradiction.  Deciding that two relationships cannot
both hold is a claim about the world; claims about the world are the kernel's.

**The trust boundary** (ROADMAP §2.9.7: *graph edges enter with authority,
never as silent truth*).  An edge enters carrying an
:class:`~core.cognition.types.EvidenceAuthority` — the kernel's enum, reused
and never duplicated — and evidence refs, and neither is optional and the
authority has no default.  A ``DETERMINISTIC`` or ``SOURCE`` edge (an explicit
reference, a structural relationship) and a ``MODEL_EXTRACTION`` one (a
sentence a language model read a relationship out of) are both storable and
never confusable: every read that returns edges returns their authority with
them, and :func:`~core.cognition.graph.hydrate.hydrate` can floor a whole
working set with ``min_authority`` so that a compiled context cannot contain a
guess at any depth.  Each evidence ref is stamped with the authority it
arrived on, too, so that raising an edge's authority never rubs out which of
its refs a model produced — the merge is the one place a boundary like this
quietly disappears.

**Shadow and additive, from birth.**  The same standing rule as the kernel's,
and the owner's ruling of 13 September 2026 behind it: *nothing here may ever
gate a mission*.  There is no call in this package a mission loop waits on for
permission, nothing here refuses an answer, and a run with no graph in it is
byte-identical to one with a graph nobody read.

**The ablation hook is the whole API surface.**  One constructor,
:class:`~core.cognition.graph.store.KnowledgeGraph`, and calls on the object it
returns.  No module-level state, no registry, no singleton, no import-time side
effect: an arm of an ablation instantiates a graph or does not, and nothing
else in the process can tell which.  Two graphs in one process are two
independent graphs.

**Determinism, stated as the property the tests pin.**  Ids come from
insertion order; every index is a list or a dict and iteration order is
insertion order; sets appear only where nothing is iterated out of them into
an answer.  Nothing in here reads the clock or a random source, so two runs of
the same log under different ``PYTHONHASHSEED`` values produce the same ids,
the same neighbours, the same paths and the same working sets.

Three modules: :mod:`~core.cognition.graph.store` (the records, the store and
its reads), :mod:`~core.cognition.graph.events` (the log and its own version),
:mod:`~core.cognition.graph.hydrate` (the bounded working set).
"""

from core.cognition.graph.events import (EVENTS_KEY, GRAPH_EVENT_OPS,
                                         GRAPH_EVENT_SCHEMA_VERSION,
                                         GRAPH_PACKAGE_VERSION, PACKAGE_KEY,
                                         SCHEMA_KEY)
from core.cognition.graph.hydrate import WorkingSet, hydrate
from core.cognition.graph.store import (DIGEST_KEYS, DIRECTIONS, STATS_KEYS,
                                        Edge, KnowledgeGraph, NodeKind,
                                        NodeView)

__all__ = [
    "DIGEST_KEYS",
    "DIRECTIONS",
    "EVENTS_KEY",
    "Edge",
    "GRAPH_EVENT_OPS",
    "GRAPH_EVENT_SCHEMA_VERSION",
    "GRAPH_PACKAGE_VERSION",
    "KnowledgeGraph",
    "NodeKind",
    "NodeView",
    "PACKAGE_KEY",
    "SCHEMA_KEY",
    "STATS_KEYS",
    "WorkingSet",
    "hydrate",
]
