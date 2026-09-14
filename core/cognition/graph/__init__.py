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

Four modules: :mod:`~core.cognition.graph.store` (the records, the store and
its reads), :mod:`~core.cognition.graph.events` (the log and its own version),
:mod:`~core.cognition.graph.hydrate` (the bounded working set), and
:mod:`~core.cognition.graph.harvest` (where the edges come from: the kernel's
own links, translated and never guessed, plus the seeds an owed line implies
and the bounds this release hydrates at).
"""

from core.cognition.graph.events import COUNT_KEY as GRAPH_COUNT_KEY
from core.cognition.graph.events import EVENTS_KEY as EVENTS_KEY
# The qualified spelling of the same key, for a SIBLING module to import:
# the kernel exports its own `EVENTS_KEY`, the two values coincide today,
# and a caller that builds a GRAPH envelope out of the KERNEL's constant
# is correct only until one of the two packages moves its spelling — at
# which point the bug is silent, because the value was never wrong, only
# its owner.  `EVENTS_KEY` stays for callers inside this package, where
# there is no second key to confuse it with; this is the same rule the
# two header keys above already keep.
from core.cognition.graph.events import EVENTS_KEY as GRAPH_EVENTS_KEY
from core.cognition.graph.events import GRAPH_EVENT_OPS, GRAPH_EVENT_SCHEMA_VERSION
from core.cognition.graph.events import GRAPH_PACKAGE_VERSION
from core.cognition.graph.events import PACKAGE_KEY as GRAPH_PACKAGE_KEY
# The facade spells both header keys with the package's own prefix. Inside
# `events` they are `SCHEMA_KEY` and `PACKAGE_KEY`, the way the kernel spells
# its own; on the way out they are qualified, because a caller that imports
# `SCHEMA_KEY` from one sibling and then from the other gets one name holding
# two different strings and no error anywhere — the shadow lane reads both
# logs and is exactly the caller this would happen to.
from core.cognition.graph.events import SCHEMA_KEY as GRAPH_SCHEMA_KEY
from core.cognition.graph.harvest import (HOP_BOUND, LINK_RELATION, MAX_EDGES,
                                          MAX_NODES, LinkHarvest, seeds_from,
                                          working_set)
from core.cognition.graph.hydrate import WorkingSet, hydrate
from core.cognition.graph.store import (DIGEST_KEYS, DIRECTIONS, EDGE_KEYS,
                                        KIND_KEYS, NAME_CAP, STATS_KEYS, Edge,
                                        KnowledgeGraph, NodeKind, NodeView)

__all__ = [
    "DIGEST_KEYS",
    "DIRECTIONS",
    "EDGE_KEYS",
    "EVENTS_KEY",
    "GRAPH_COUNT_KEY",
    "GRAPH_EVENTS_KEY",
    "Edge",
    "GRAPH_EVENT_OPS",
    "GRAPH_EVENT_SCHEMA_VERSION",
    "GRAPH_PACKAGE_KEY",
    "GRAPH_PACKAGE_VERSION",
    "GRAPH_SCHEMA_KEY",
    "HOP_BOUND",
    "KIND_KEYS",
    "KnowledgeGraph",
    "LINK_RELATION",
    "LinkHarvest",
    "MAX_EDGES",
    "MAX_NODES",
    "NAME_CAP",
    "NodeKind",
    "NodeView",
    "STATS_KEYS",
    "WorkingSet",
    "hydrate",
    "seeds_from",
    "working_set",
]
