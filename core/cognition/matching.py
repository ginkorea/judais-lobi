# core/cognition/matching.py — unification, and nothing else

"""Pattern against fact, pattern against pattern, and a binding environment.

Four functions and a type alias.  They are separate from
:mod:`core.cognition.state` because both the closure engine and the obligation
computation use them and neither should own them — one owner per fact, and the
fact here is what it means for ``("?actor", "controls", "?c")`` to match
``("alice", "controls", "acct-9")``.

A binding environment is a plain ``dict`` from variable name to literal.  It
is copied rather than mutated on every extension, which is the slow choice and
the right one at this size: an environment that is undone by backtracking is a
class of bug that does not announce itself, and this package's whole claim is
that its results are reproducible.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.cognition.types import is_variable

#: Variable name → literal. Ordinary dict; ordering follows insertion, which
#: follows body position, which is declared. Deterministic all the way down.
Bindings = Dict[str, Any]

Pattern = Tuple[Any, Any, Any]


def resolve(pattern: Sequence[Any], bindings: Mapping[str, Any]) -> Pattern:
    """The pattern with every bound variable replaced by its literal.

    Unbound variables stay as themselves, which is what makes a partly
    resolved pattern a usable obligation: ``("?actor", "payment_link",
    "acct-9")`` says exactly what is missing and exactly what is known.
    """
    out = []
    for term in pattern:
        out.append(bindings[term] if is_variable(term) and term in bindings
                   else term)
    return (out[0], out[1], out[2])


def unify(pattern: Sequence[Any], fact: Sequence[Any],
          bindings: Optional[Mapping[str, Any]] = None) -> Optional[Bindings]:
    """Match a pattern against a ground triple; return extended bindings.

    ``None`` means no match — distinct from ``{}``, which is a match that
    bound nothing.  A variable already bound must agree with what it is bound
    to; that repeated-variable check is the whole of the join, and dropping it
    would let ``("?a", "same_as", "?a")`` match two different entities.
    """
    out: Bindings = dict(bindings or {})
    for term, value in zip(pattern, fact):
        if is_variable(term):
            seen = out.get(term, _MISSING)
            if seen is _MISSING:
                out[term] = value
            elif seen != value:
                return None
        elif term != value:
            return None
    return out


def unify_patterns(head: Sequence[Any],
                   target: Sequence[Any]) -> Optional[Bindings]:
    """Match a rule head against a goal pattern, both of which may have
    variables.

    Only the *head's* variables are bound, and only to the target's literals.
    A target variable meeting a head literal is a match that binds nothing —
    the goal was asking for anything in that position and the rule answers
    with something specific, which is exactly the case
    ``("?actor", "controls", "?c")`` against ``("?x", "controls", "acct-9")``.

    **v1 bound**: this is one-way and does not bind the target's variables.
    A full two-way unification would let a goal constrain a rule's head
    variable, which changes what an obligation *means* — a question for the
    phase that has a measurement to settle it with.
    """
    out: Bindings = {}
    for term, want in zip(head, target):
        if is_variable(want):
            continue
        if is_variable(term):
            seen = out.get(term, _MISSING)
            if seen is _MISSING:
                out[term] = want
            elif seen != want:
                return None
        elif term != want:
            return None
    return out


def shares_variable(left: Sequence[Any], right: Sequence[Any]) -> bool:
    """Whether two unresolved patterns have a variable in common.

    This is how an obligation learns it is blocked: the premise it needs
    cannot even be *stated* concretely until an earlier unsatisfied premise
    binds the variable they share.
    """
    lhs = {term for term in left if is_variable(term)}
    return any(is_variable(term) and term in lhs for term in right)


class _Missing:
    __slots__ = ()


_MISSING = _Missing()
