# core/cognition/constraints.py — what a pack says must be true, and what is not

"""Constraints over the store's facts, checked and **recorded, never enforced**.

``ROADMAP.md`` §2.9.7 (Phase 20) admits a solver "for the classes that
deserve it — scheduling, dependency ordering, feasibility; the runtime
recognizes the problem class, the model does not have to remember to ask."
This module is the first, smallest piece of that: a pack may declare
arithmetic that must hold over the facts a run has established, and a
declaration that does not hold becomes a :class:`Violation` — a line in the
runtime's view and a record in ``reasoning.jsonl``.

**It is not a gate, and it is constitutionally incapable of being one**
(§2.9.3, the owner's ruling of 13 September 2026: *cognition-on never blocks
an answer*).  :func:`check_constraints` returns records.  It holds nothing,
refuses nothing and answers no question a mission loop waits on; a violated
constraint changes the *view* and the *log* and changes no call, no prompt
gate and no outcome.  There is no supervisor signal in v1 either — pairing a
violation with a review is a separate change with its own review, and a
checker that could raise a review is one step from a checker that can end a
run.

**Pure, like the rest of the kernel.**  A :class:`~core.cognition.state
.CognitiveState` in through its public reads, records out.  No I/O, no clock,
no randomness, nothing imported from :mod:`core.runtime`.  The one
environment-dependent thing in the package is :func:`have_z3`, and it is
argued where it is defined.

## The v1 language, and why it is this small

``require:`` is one comparison over the numeric fields of **one** bound
entity:

.. code-block:: yaml

    constraints:
      - name: share_bounded
        over: {entity: "?e"}
        require: "share <= 100"
      - name: settled_within_total
        over: {entity: "?e"}
        require: "settled + pending == total"

``+``, ``-``, ``*`` (one side of a ``*`` a constant), unary minus, parentheses
and exactly one of ``< <= == != >= >``.  That is deliberately the *linear*
fragment, and the bound is on the **language** rather than on the arithmetic:
a linear comparison over bound values is decided exactly by decimal
arithmetic with no dependency at all, which is what makes the feature work on
a box that installed nothing.  The moment a constraint needs more, it says so
in the file (``require_z3:``) rather than silently costing every deployment a
solver.

**Why a separate key and not a `solver:` flag beside `require:`.**  Three
spellings were possible and only one of them leaves a manifest readable on
its own:

* ``require_z3: "…"`` — *chosen*.  The key names the engine that will read the
  expression, so an author reading their own file knows which grammar they
  are writing and whether this manifest needs an extra installed; a refusal
  can name the key it refused; and ``grep require_z3`` over a skill library
  answers "which of our packs need the solver" exactly.
* ``solver: z3`` beside ``require:`` — rejected.  The meaning of one key would
  then depend on a sibling key, so *what language is this string in* has two
  owners and a dropped line changes the answer silently.
* a prefix inside the value (``require: "z3: share*rate <= cap"``) — rejected.
  It puts a keyword inside data, it cannot be read by the same parser that
  reads everything else in the value, and a string whose first word is an
  engine name is not a field anything can grep.

Exactly one of the two per constraint: neither is a constraint that requires
nothing, both is a constraint with two answers about which engine runs it,
and both are refused at the door.

**``require_z3:`` is an escalation and not a floor.**  It accepts the same
surface syntax plus the two things the built-in evaluator will not do —
products of two fields, and division — and it is decided by ``z3``: the
solver works in exact rationals, and ``a / b == c`` is a question decimal
arithmetic can only answer approximately.  A ``require_z3:`` constraint on a
box without ``z3-solver`` is refused **at the manifest door**, naming the
extra (:data:`SOLVER_EXTRA`), rather than loading and quietly checking
nothing.

**What v1 deliberately does NOT do**: solve.  Every value is bound before the
solver is asked, so z3 is here as an exact decision procedure over a ground
expression.  The ROADMAP's named classes — scheduling, dependency ordering,
feasibility — are questions about *unbound* variables, they need a way to
declare the variables and a way to render an UNSAT core as advice, and they
come with their own review.  What lands here is the door, the extra, and the
discipline that everything through them is advisory.

## Binding, and the one rule that matters

For each constraint, each entity whose **live** facts carry *all* the fields
the expression references is bound and checked.  A field the store does not
hold for that entity means the entity is **not bound** and yields no
violation: absence in this store is ``UNKNOWN``, never zero and never false,
and a checker that read a missing ``pending`` as ``0`` would manufacture a
violation out of a receipt that had simply not arrived yet.  The same rule
covers the two other ways a value can fail to be a number: a field the store
holds **two** live values for is ambiguous — choosing one would be deciding a
contradiction the kernel deliberately keeps open — and a field holding a
string, a boolean or ``null`` is not arithmetic.  Three shapes of "cannot
know", one answer: no violation.

Deterministic order: constraints in declaration order, entities in the
store's insertion order, which is the order every other reader of this
package walks.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal, localcontext
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.cognition.state import CognitiveState
from core.cognition.types import (CognitionError, LIVE_STATUSES, Proposition,
                                  is_variable)

__all__ = [
    "CONSTRAINT_KEYS", "COMPARATORS", "ENGINES", "LINEAR", "MAX_EXPRESSION",
    "NEGATIONS", "OVER_KEYS", "SOLVER_EXTRA", "VIOLATION_KIND", "Z3",
    "Constraint", "ConstraintMalformed", "Violation", "check_constraints",
    "have_z3", "parse_constraint",
]


#: What one entry of ``constraints:`` may say.  Closed and refused by name,
#: like :data:`core.runtime.cognition.RULE_KEYS`: a key this reader has never
#: heard of is a key an author believed was doing something.
CONSTRAINT_KEYS: Tuple[str, ...] = ("name", "over", "require", "require_z3")

#: What ``over:`` may say.  One key in v1, and a mapping rather than a bare
#: variable **because of what comes next**: the day a constraint quantifies
#: over two entities, or filters them by a premise pattern, the declaration
#: is already a mapping and the language grows a key instead of changing what
#: an existing file means.
OVER_KEYS: Tuple[str, ...] = ("entity",)

#: The two engines, and the two keys that choose them.
LINEAR = "linear"
Z3 = "z3"
ENGINES: Tuple[str, ...] = (LINEAR, Z3)

#: The key each engine is asked for by.  One mapping, so the door, the
#: refusal and the parser cannot disagree about which key means which engine.
ENGINE_KEYS: Dict[str, str] = {"require": LINEAR, "require_z3": Z3}

#: What a refusal tells an operator to install.  One spelling, the same shape
#: :func:`core.runtime.skills._require_yaml` and ``core.server`` already use —
#: the extra that carries the stack, named by the refusal that needs it.
SOLVER_EXTRA = "pip install 'judais-lobi[solver]'"

#: What a violation calls itself where contradictions name their kind.  The
#: compiled view renders violations in its CONFLICTS section and prefixes
#: each line with this, exactly as it prefixes a kernel contradiction with
#: :attr:`~core.cognition.types.Contradiction.kind`.  **Not** a member of
#: :data:`~core.cognition.types.CONTRADICTION_KINDS`: no such contradiction
#: is recorded in the store — see :func:`check_constraints`.
VIOLATION_KIND = "constraint"

#: The longest expression this parser will read.  A bound rather than a
#: judgement about what is useful: ``ast.parse`` on a pathological string is
#: the one place a manifest could cost a mission time, and a constraint
#: nobody can read in one line is a constraint nobody can review.
MAX_EXPRESSION = 500

#: The comparisons, as the file writes them.  The keys are the ``ast`` nodes
#: because ``ast`` is what reads the expression; anything not in here is
#: refused by name, which is how ``a < b < c`` and ``x in y`` arrive as
#: sentences rather than as tracebacks.
COMPARATORS: Dict[Any, str] = {
    ast.Lt: "<", ast.LtE: "<=", ast.Eq: "==", ast.NotEq: "!=",
    ast.Gt: ">", ast.GtE: ">=",
}

#: What is true when a comparison is false.  The violation sentence states
#: **what the store actually says** — ``settled 204 + pending 631 = 835 !=
#: total 631`` — rather than restating what was required, because the
#: required expression is already in the manifest and in the record beside
#: the sentence, and a reader looking at a violation wants the number.
NEGATIONS: Dict[str, str] = {
    "<": ">=", "<=": ">", "==": "!=", "!=": "==", ">": "<=", ">=": "<",
}

#: The arithmetic, by node, with the precedence the renderer needs.
_OPERATORS: Dict[Any, Tuple[str, int]] = {
    ast.Add: ("+", 1), ast.Sub: ("-", 1), ast.Mult: ("*", 2), ast.Div: ("/", 2),
}


class ConstraintMalformed(CognitionError):
    """A constraint a pack wrote that this module will not read.

    A :class:`~core.cognition.types.CognitionError` and not a ``ValueError``,
    because the fault is in the kernel's own language and this is the kernel's
    own exception family; :class:`core.runtime.cognition.RulePack` catches it
    at the manifest door and turns it into one of the problems it lists, which
    is the same trip a ``check_pattern`` refusal already makes.
    """


@dataclass(frozen=True)
class Constraint:
    """One declaration: a name, what it quantifies over, and the arithmetic.

    Parsed once, at the manifest door, and carried on
    :attr:`core.runtime.cognition.RulePack.constraints`.  The tree is the
    parser's own output and is deliberately **out of the equality and the
    repr**: two constraints read from identical YAML are the same constraint,
    and ``ast`` nodes compare by identity, so a record that included one could
    never be equal to itself read twice.
    """

    name: str
    #: The variable ``over: {entity: …}`` named.  It appears nowhere in the
    #: expression — the expression names *fields* — and is required anyway:
    #: see :data:`OVER_KEYS`.
    entity_var: str
    #: The expression exactly as the manifest wrote it.
    require: str
    #: :data:`LINEAR` or :data:`Z3`, from which key carried the expression.
    engine: str = LINEAR
    #: The fields it references, in first-appearance order.
    fields: Tuple[str, ...] = ()
    tree: Any = dataclass_field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Violation:
    """One constraint, one entity, and what the store actually says.

    Records, not verdicts.  A violation is reported in the compiled view's
    CONFLICTS section and written into ``reasoning.jsonl``; nothing reads one
    back, nothing is held against one, and a run that produces a hundred of
    them answers exactly as it would have.
    """

    #: The constraint's name, as the pack wrote it.
    constraint: str
    #: The entity it failed on.  Under the v1 harvest that string *is* the
    #: receipt handle (``mcp.ledger_entry#r3``), which is why no second
    #: citation is rendered beside it — the same argument
    #: :data:`core.cognition.compile.DERIVED` makes for not listing evidence
    #: locators on a derived line.
    entity: str
    #: What is true, in the constraint's own arithmetic: ``settled 204 +
    #: pending 631 = 835 != total 631``.
    detail: str
    #: The expression as declared, so the record says what was asked as well
    #: as what was found.
    require: str
    engine: str = LINEAR
    #: ``((field, value), …)`` in the order the expression names them.
    bindings: Tuple[Tuple[str, Any], ...] = ()
    #: The proposition ids the values came from, in ``bindings`` order — the
    #: kernel's own address for a claim, for a reader of the log who has the
    #: store and wants the proof.
    sources: Tuple[str, ...] = ()

    @property
    def key(self) -> Tuple[str, str]:
        """``(constraint, entity)`` — the identity a log dedupes on.

        Not the values.  A constraint that goes on failing on one entity is
        **one** fact about that entity, and a log that re-stated it at every
        step would be a file whose length was a function of how many steps ran
        rather than of what the run believed.
        """
        return (self.constraint, self.entity)


# ── the environment's one question ───────────────────────────────────────────


def have_z3() -> bool:
    """Whether ``z3-solver`` is importable.

    **The one environment-dependent call in this package**, and it is here
    rather than in the runtime on purpose: the expression language's
    semantics have one owner, and a design where the runtime probed for the
    solver and handed an evaluator in would put half of *what does
    ``require_z3`` mean* in a module that is allowed to open files.  Purity
    is about I/O, clocks and randomness — this is an import, it has no side
    effect a caller can observe, and the answer is the same for the life of
    a process.

    A function rather than a module-level constant so a test can state both
    worlds on one box: the refusal at the door has to be checked where the
    solver *is* installed too.
    """
    try:
        import z3                                  # noqa: F401
    except Exception:                              # pragma: no cover - env
        # `Exception` and not `ImportError`: a half-installed native wheel
        # raises on import in ways that are not import errors, and a checker
        # that let one of those out would be the optional dependency costing
        # a mission exactly what an extra exists to avoid.
        return False
    return True


# ── the door: one expression, read once ──────────────────────────────────────


def parse_constraint(name: Any, over: Any, require: Any = None,
                     require_z3: Any = None) -> Constraint:
    """One declared constraint, or a :class:`ConstraintMalformed` naming why.

    The **only** reader of the language.  The manifest door
    (:class:`core.runtime.cognition.RulePack`) checks the shape of the entry
    — that it is a mapping, that its keys are known, that its name is unique
    — and then asks this, so "would the checker take this expression" is
    answered by the checker's own parser rather than by a second, simpler
    opinion that agrees until the day it does not.  It is the same discipline
    the rule pack's dry run already keeps.

    Raises on the first fault rather than collecting: the caller is
    collecting, one message per constraint, and a partial expression has
    nothing further worth saying about it.
    """
    label = str(name or "").strip() or "?"
    var = _entity_variable(over, label)
    declared = {"require": _text(require, label, "require"),
                "require_z3": _text(require_z3, label, "require_z3")}
    keys = [key for key in ("require", "require_z3")
            if declared[key] is not None]
    if not keys:
        raise ConstraintMalformed(
            f"constraint {label!r} states neither `require:` nor "
            f"`require_z3:`; a constraint that requires nothing is a name "
            f"with no claim under it")
    if len(keys) > 1:
        raise ConstraintMalformed(
            f"constraint {label!r} states both `require:` and `require_z3:`; "
            f"one constraint is one expression in one language, and taking "
            f"either would make which engine ran it a fact about this "
            f"reader")
    key = keys[0]
    engine = ENGINE_KEYS[key]
    text = declared[key] or ""
    if engine == Z3 and not have_z3():
        raise ConstraintMalformed(
            f"constraint {label!r} uses `require_z3:`, which needs the "
            f"solver: {SOLVER_EXTRA}. The built-in `require:` language "
            f"({', '.join(sorted(NEGATIONS))} over `+ - *` on one "
            f"entity's numeric fields) needs nothing")
    tree, fields = _parse_expression(text, label, engine)
    return Constraint(name=label, entity_var=var, require=text, engine=engine,
                      fields=fields, tree=tree)


def _text(value: Any, label: str, key: str) -> Optional[str]:
    """A declared expression as a non-empty string, or ``None``.

    ``None`` for absent **and** for blank, because ``require: ""`` is a key
    an author wrote and left empty, which is the same claim as not writing
    it: nothing is required.  A number is refused rather than rendered —
    ``require: 100`` is a file that means nothing, and guessing at it is how
    a manifest gets a constraint nobody wrote.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConstraintMalformed(
            f"constraint {label!r} states `{key}:` as a "
            f"{type(value).__name__}; an expression is a string")
    return value.strip() or None


def _entity_variable(over: Any, label: str) -> str:
    """``over: {entity: "?e"}`` as the variable it names.

    A **variable** and not a literal.  A literal entity would pin a
    constraint to one entity name, and under the v1 harvest an entity name is
    ``"{tool}#{seq}"`` — a handle minted inside one run — so a manifest that
    wrote one would be writing a string that can only ever fail to match.
    Refusing says so at the door instead.
    """
    if not isinstance(over, dict):
        raise ConstraintMalformed(
            f"constraint {label!r} has no usable `over:`; it is a mapping "
            f"({', '.join(OVER_KEYS)}), as in `over: {{entity: \"?e\"}}`")
    unknown = sorted(set(map(str, over)) - set(OVER_KEYS))
    if unknown:
        raise ConstraintMalformed(
            f"constraint {label!r} sets unknown `over:` key(s): "
            f"{', '.join(unknown)}. `over:` sets {', '.join(OVER_KEYS)}")
    entity = over.get("entity")
    if not is_variable(entity):
        raise ConstraintMalformed(
            f"constraint {label!r} quantifies over {entity!r}; `over: "
            f"{{entity: …}}` names a ?variable, because an entity name is "
            f"minted inside one run and a literal one could only ever fail "
            f"to match")
    return str(entity)


def _parse_expression(text: str, label: str,
                      engine: str) -> Tuple[Any, Tuple[str, ...]]:
    """One comparison, as a whitelisted tree and the fields it names.

    Read with :mod:`ast` and then **walked against a closed set of node
    types**, which is the whole of the safety argument: nothing here is
    executed, compiled or evaluated by Python — a node kind this module does
    not name is a refusal, so a call, an attribute, a subscript, a lambda or
    a comprehension never reaches the evaluator to be worried about.  Writing
    a tokenizer and a recursive-descent parser instead would be a hundred
    lines that answer the same question less completely; what matters is that
    the accepted set is small, named, and tested from the outside.
    """
    if len(text) > MAX_EXPRESSION:
        raise ConstraintMalformed(
            f"constraint {label!r} is {len(text)} characters; the limit is "
            f"{MAX_EXPRESSION}")
    try:
        parsed = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise ConstraintMalformed(
            f"constraint {label!r} is not an expression this reader can "
            f"take ({type(exc).__name__}): {text!r}") from exc
    node = parsed.body
    if not isinstance(node, ast.Compare):
        raise ConstraintMalformed(
            f"constraint {label!r} is not a comparison; a constraint says "
            f"what must hold, as in `share <= 100`")
    if len(node.ops) != 1 or len(node.comparators) != 1:
        raise ConstraintMalformed(
            f"constraint {label!r} chains {len(node.ops)} comparisons; v1 "
            f"reads one, so that the violation can say which half failed. "
            f"Write two constraints")
    if type(node.ops[0]) not in COMPARATORS:
        raise ConstraintMalformed(
            f"constraint {label!r} compares with something that is not "
            f"{', '.join(sorted(NEGATIONS))}")
    fields: List[str] = []
    for side in (node.left, node.comparators[0]):
        _walk(side, label, engine, fields)
    if not fields:
        raise ConstraintMalformed(
            f"constraint {label!r} names no field, so it says the same thing "
            f"about every store there has ever been")
    return node, tuple(fields)


def _walk(node: Any, label: str, engine: str, fields: List[str]) -> bool:
    """Validate one operand subtree; returns whether it mentions a field.

    The return value is the linearity check: a ``*`` whose *both* sides
    mention a field is not linear, and the built-in evaluator's language says
    so rather than evaluating it — the bound is declared, so a pack that
    wants it escalates to ``require_z3:`` in writing.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)):
            raise ConstraintMalformed(
                f"constraint {label!r} uses {node.value!r}; a constant in an "
                f"expression is a number (`true`, `null` and text are not "
                f"arithmetic)")
        if not math.isfinite(node.value):
            # `1e400` parses as `inf`, and an infinity decides nothing: every
            # binding would be undecidable and the constraint would sit in the
            # pack looking like it was checking something. Refusing at the
            # door is the difference between a constraint that says nothing
            # and a constraint that silently says nothing.
            raise ConstraintMalformed(
                f"constraint {label!r} uses {node.value!r}; a constant is a "
                f"finite number, and an infinity decides nothing")
        return False
    if isinstance(node, ast.Name):
        name = node.id
        if name not in fields:
            fields.append(name)
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op,
                                                    (ast.UAdd, ast.USub)):
        return _walk(node.operand, label, engine, fields)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        symbol = _OPERATORS[type(node.op)][0]
        if engine == LINEAR and symbol == "/":
            raise ConstraintMalformed(
                f"constraint {label!r} divides, and `require:` is exact "
                f"decimal arithmetic over `+ - *`. Division is the solver's: "
                f"write it as `require_z3:` ({SOLVER_EXTRA}), which decides "
                f"it in rationals")
        left = _walk(node.left, label, engine, fields)
        right = _walk(node.right, label, engine, fields)
        if engine == LINEAR and symbol == "*" and left and right:
            raise ConstraintMalformed(
                f"constraint {label!r} multiplies two fields, and `require:` "
                f"is linear: one side of a `*` is a constant. A product of "
                f"two fields is the solver's — write it as `require_z3:`")
        return left or right
    # An operator the language does not have is named by the OPERATOR and
    # not by `BinOp`: `share ** 2` refused as "uses BinOp" is a message that
    # tells an author nothing about which half of their line to fix.
    named = type(getattr(node, "op", node)).__name__
    raise ConstraintMalformed(
        f"constraint {label!r} uses {named}, which is not part "
        f"of the expression language: a field name, a number, `+ - *`"
        + (", `/`" if engine == Z3 else "")
        + f", parentheses and one of {', '.join(sorted(NEGATIONS))}")


# ── the check ────────────────────────────────────────────────────────────────


def check_constraints(state: CognitiveState,
                      constraints: Sequence[Constraint]
                      ) -> Tuple[Violation, ...]:
    """Every constraint against every entity that binds it.  Records out.

    The whole of the checking, and it **records**: there is no branch in here
    that refuses anything, and the return value is a tuple a caller is free to
    ignore entirely (§2.9.3 — cognition-on never blocks an answer).

    Not written into the store, and that is a decision with a date on it.
    The honest kernel-native carrier would be a
    :class:`~core.cognition.types.Contradiction` of a new kind — the store
    already holds both sides of a disagreement and shows them in the view —
    but the kernel has no public door that records one (``_contradict`` is
    private, and :data:`~core.cognition.types.CONTRADICTION_KINDS` is closed),
    and a violation is in any case not quite one: a contradiction names two
    claims that disagree with each other, while a violation is a *pack's*
    arithmetic disagreeing with a set of claims that agree perfectly well
    among themselves.  So v1 keeps violations outside the kernel — the shadow
    holds them and writes one note per new one — and a kernel-native carrier
    waits for the lane that is currently rewriting :mod:`core.cognition.state`
    to land.  Nothing about the meaning changes when it does: the record
    already names the constraint, the entity, the values and the proposition
    ids.

    Deterministic: constraints in declaration order, entities in the store's
    insertion order.
    """
    declared = tuple(constraints or ())
    if not declared:
        # The common path, and free: a store with no constraints pays one
        # tuple() and no walk of its propositions at all.
        return ()
    table, order = _live_values(state)
    out: List[Violation] = []
    for constraint in declared:
        for entity in order:
            bound = _bind(table.get(entity, {}), constraint.fields)
            if bound is None:
                continue
            values = {name: value for name, (value, _pid) in bound.items()}
            holds = _holds(constraint, values)
            if holds is None or holds:
                continue
            out.append(Violation(
                constraint=constraint.name, entity=entity,
                detail=_detail(constraint, values),
                require=constraint.require, engine=constraint.engine,
                bindings=tuple((name, values[name])
                               for name in constraint.fields),
                sources=tuple(bound[name][1] for name in constraint.fields)))
    return tuple(out)


def _live_values(state: CognitiveState
                 ) -> Tuple[Dict[str, Dict[str, List[Tuple[Any, str]]]],
                            List[str]]:
    """``{entity: {field: [(value, pid), …]}}`` and the entities, in order.

    One walk of the store's live propositions for every constraint, rather
    than one :meth:`~core.cognition.state.CognitiveState.query` per constraint
    per entity: the store is walked once per step by the compiler already, and
    a checker that asked it a question per (constraint, entity) pair would be
    the quadratic shape the compiled view spent a review getting rid of.
    """
    table: Dict[str, Dict[str, List[Tuple[Any, str]]]] = {}
    order: List[str] = []
    held: Tuple[Proposition, ...] = state.propositions()
    for prop in held:
        if prop.status not in LIVE_STATUSES or prop.triple is None:
            continue
        entity, name, value = prop.triple
        if entity not in table:
            table[entity] = {}
            order.append(entity)
        table[entity].setdefault(name, []).append((value, prop.id))
    return table, order


def _bind(held: Dict[str, List[Tuple[Any, str]]], fields: Sequence[str]
          ) -> Optional[Dict[str, Tuple[Any, str]]]:
    """One entity's values for *fields*, or ``None`` where it does not bind.

    ``None`` — *not bound* — for all three ways a value can fail to be a
    number this expression can use, and the module docstring argues them:
    the field is absent (absence is ``UNKNOWN``, never zero), the store holds
    two live values for it (choosing one would be deciding a contradiction
    the kernel is deliberately keeping open), or the value is a string, a
    boolean or ``null``.
    """
    out: Dict[str, Tuple[Any, str]] = {}
    for name in fields:
        rows = held.get(name)
        if not rows or len(rows) != 1:
            return None
        value, pid = rows[0]
        if _number(value) is None:
            return None
        out[name] = (value, pid)
    return out


def _number(value: Any) -> Optional[Decimal]:
    """A kernel value as an exact decimal, or ``None``.

    ``Decimal`` for :func:`core.runtime.grounding.as_decimal`'s reason —
    ``0.1 + 0.2`` arithmetic has no business deciding whether a run violated
    what it declared — and spelled again here rather than imported, because
    this package does not import :mod:`core.runtime` and never will.  The two
    are not a divided fact: that one owns *what number is in this receipt
    text*, this one owns *what arithmetic this kernel value is worth*, and
    the values arriving here have already been through the first.

    ``bool`` is not a number: ``True == 1`` is a fact about Python and not a
    claim about a run, and the kernel keeps the two apart in
    :func:`~core.cognition.types.value_tag` for exactly that reason.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            number = Decimal(str(value))
        except (ArithmeticError, ValueError):      # pragma: no cover - NaN
            return None
        return number if number.is_finite() else None
    return None


def _holds(constraint: Constraint, values: Dict[str, Any]) -> Optional[bool]:
    """Whether *constraint* holds for these values; ``None`` if undecidable.

    ``None`` is the third answer and it is never a violation: an overflow, a
    division by zero, a solver that returns ``unknown``.  A checker that
    called any of those a violation would be reporting its own limits as the
    run's fault, and this layer's whole discipline is that what it does not
    know it does not claim.
    """
    node = constraint.tree
    symbol = COMPARATORS[type(node.ops[0])]
    if constraint.engine == Z3:
        return _holds_z3(node, symbol, values)
    try:
        with localcontext() as context:
            # A bounded context, so that a pathological constant cannot turn
            # one step's check into an unbounded computation. Fifty digits is
            # exact for everything a receipt plausibly carries, and anything
            # that overflows it raises — into the undecidable answer below
            # rather than into a wrong one.
            context.prec = 50
            left = _decimal(node.left, values)
            right = _decimal(node.comparators[0], values)
            if left is None or right is None:
                return None
            return _compare(symbol, left, right)
    except (ArithmeticError, ValueError, TypeError):   # pragma: no cover
        return None


def _compare(symbol: str, left: Decimal, right: Decimal) -> bool:
    if symbol == "<":
        return left < right
    if symbol == "<=":
        return left <= right
    if symbol == "==":
        return left == right
    if symbol == "!=":
        return left != right
    if symbol == ">":
        return left > right
    return left >= right


def _decimal(node: Any, values: Dict[str, Any]) -> Optional[Decimal]:
    """One operand subtree as a decimal, or ``None`` where it will not be.

    Division is here as well as in the solver path because the solver path
    needs it: a divisor of zero has no value, and asking z3 about an
    expression that divides by zero asks it about its own underspecified
    semantics rather than about the run.  So the pre-check that finds a zero
    divisor is this walk, and a ``require:`` expression never reaches the
    branch at all — its language has no ``/``.
    """
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.Name):
        return _number(values.get(node.id))
    if isinstance(node, ast.UnaryOp):
        inner = _decimal(node.operand, values)
        if inner is None:
            return None
        return -inner if isinstance(node.op, ast.USub) else inner
    left = _decimal(node.left, values)
    right = _decimal(node.right, values)
    if left is None or right is None:
        return None
    symbol = _OPERATORS[type(node.op)][0]
    if symbol == "+":
        return left + right
    if symbol == "-":
        return left - right
    if symbol == "*":
        return left * right
    if not right:
        return None
    return left / right


def _holds_z3(node: Any, symbol: str,
              values: Dict[str, Any]) -> Optional[bool]:
    """The comparison, decided by the solver, with every value bound.

    ``unsat`` of the *negation* and not ``simplify``: the solver deciding is
    the point of the escalation, and a simplifier returning something that is
    neither ``True`` nor ``False`` would have to be interpreted here, which is
    the second opinion this whole module is arranged to avoid.  Every variable
    is bound before the call, so the question is ground and the answer is
    exact — z3 works in rationals, which is what ``a / b == c`` needs and what
    decimal arithmetic cannot give.

    Anything the solver will not answer — ``unknown``, or a divisor that is
    zero, which is underspecified in its semantics and not a fact about the
    run — is ``None``: undecidable, never a violation.
    """
    if _decimal(node.left, values) is None \
            or _decimal(node.comparators[0], values) is None:
        # The zero-divisor (and overflow) pre-check, in the walk that already
        # knows the arithmetic. z3 would answer an underspecified question.
        return None
    try:
        import z3
    except Exception:                              # pragma: no cover - env
        # Refused at the door, so reaching here means the solver went away
        # between load and step. Undecidable, and the mission never learns.
        return None
    try:
        left = _z3_term(z3, node.left, values)
        right = _z3_term(z3, node.comparators[0], values)
        claim = _z3_compare(symbol, left, right)
        solver = z3.Solver()
        solver.add(z3.Not(claim))
        answer = solver.check()
        if answer == z3.unsat:
            return True
        if answer == z3.sat:
            return False
        return None
    except Exception:                              # pragma: no cover - solver
        return None


def _z3_term(z3: Any, node: Any, values: Dict[str, Any]) -> Any:
    """One operand subtree as a z3 rational term.

    Constants and bound values become ``RealVal`` **from their decimal
    spelling**, which is exact: ``RealVal("0.1")`` is one tenth, where a
    float is not.  That exactness is the reason a pack escalates here at all.
    """
    if isinstance(node, ast.Constant):
        return z3.RealVal(str(_number(node.value)))
    if isinstance(node, ast.Name):
        return z3.RealVal(str(_number(values.get(node.id))))
    if isinstance(node, ast.UnaryOp):
        inner = _z3_term(z3, node.operand, values)
        return -inner if isinstance(node.op, ast.USub) else inner
    left = _z3_term(z3, node.left, values)
    right = _z3_term(z3, node.right, values)
    symbol = _OPERATORS[type(node.op)][0]
    if symbol == "+":
        return left + right
    if symbol == "-":
        return left - right
    if symbol == "*":
        return left * right
    return left / right


def _z3_compare(symbol: str, left: Any, right: Any) -> Any:
    if symbol == "<":
        return left < right
    if symbol == "<=":
        return left <= right
    if symbol == "==":
        return left == right
    if symbol == "!=":
        return left != right
    if symbol == ">":
        return left > right
    return left >= right


# ── what a violation says ────────────────────────────────────────────────────


def _detail(constraint: Constraint, values: Dict[str, Any]) -> str:
    """The arithmetic that failed, as a sentence about what IS true.

    ``settled 204 + pending 631 = 835 != total 631`` — each field beside the
    value the store holds for it, each compound side followed by what it
    comes to, and the comparison **negated**, because a violation is news
    about the store and not a restatement of the manifest.  The expression as
    declared is on the record beside this string for the reader who wants
    both.

    A ``require_z3:`` constraint gets a different sentence and deliberately
    not this one: its arithmetic may be non-linear or divide, the number that
    decided it is a rational the solver held and not one this module
    computed, and a sentence that printed an approximation of it would be
    the module claiming a figure it did not use.
    """
    if constraint.engine == Z3:
        held = ", ".join(f"{name} {_show(values.get(name))}"
                         for name in constraint.fields)
        return f"`{constraint.require}` is false where {held}"
    node = constraint.tree
    symbol = COMPARATORS[type(node.ops[0])]
    return (f"{_side(node.left, values)} {NEGATIONS[symbol]} "
            f"{_side(node.comparators[0], values)}")


def _side(node: Any, values: Dict[str, Any]) -> str:
    """One side of the comparison, with its value where it has computed one.

    A bare field or a bare constant renders as itself — ``total 631``, ``100``
    — because ``total 631 = 631`` says one thing twice.  Anything with an
    operator in it renders as the arithmetic and then what it came to.
    """
    text = _expression(node, values, 0)
    if isinstance(node, (ast.Name, ast.Constant)):
        return text
    value = _decimal(node, values)
    return text if value is None else f"{text} = {_show_decimal(value)}"


def _expression(node: Any, values: Dict[str, Any], precedence: int) -> str:
    """The subtree as text, with the fields' values in it and minimal parens."""
    if isinstance(node, ast.Constant):
        return _show(node.value)
    if isinstance(node, ast.Name):
        return f"{node.id} {_show(values.get(node.id))}"
    if isinstance(node, ast.UnaryOp):
        sign = "-" if isinstance(node.op, ast.USub) else "+"
        return f"{sign}{_expression(node.operand, values, 3)}"
    symbol, level = _OPERATORS[type(node.op)]
    text = (f"{_expression(node.left, values, level)} {symbol} "
            f"{_expression(node.right, values, level + 1)}")
    return f"({text})" if level < precedence else text


def _show(value: Any) -> str:
    """A number as the file and the receipt spell it."""
    if isinstance(value, bool) or value is None:    # pragma: no cover - bound
        return repr(value)
    if isinstance(value, float) and value.is_integer():
        # `121.0` and not `121`: the store's fidelity rule is that a figure
        # renders as the type it was asserted under, which is the same
        # argument `core.cognition.compile._value` makes with `json.dumps`.
        return repr(value)
    return str(value)


def _show_decimal(value: Decimal) -> str:
    """A computed decimal, without an exponent for the sizes in reach."""
    text = format(value.normalize(), "f")
    return text
