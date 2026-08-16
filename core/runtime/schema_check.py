# core/runtime/schema_check.py — are these the arguments the tool declared?

"""One owner for *"do these arguments match the schema the tool published"*.

A mission dispatches whatever the model named with whatever the model
wrote.  Until now the only thing between a wrong argument and a remote
server was the server itself: the call went out, something on the far end
refused it, and the mission spent a whole turn — on a 59 tok/s local model,
an eighth of its budget — learning that ``limit`` is an integer.  The tool
already **said** that: :attr:`~core.tools.descriptors.ToolDescriptor
.input_schema` is carried whole across the MCP bridge precisely so the
harness can read it, and the mission's catalogue already renders a summary
of it into the prompt.  This module is the other half — the same schema
read back on the way *out*.

**What it can catch.**  Exactly what the schema states: a required argument
that is missing, a value whose JSON type is not the declared one, a value
outside a declared ``enum``.  Those are the shape errors, and under the
native protocol (:data:`~core.runtime.mission.NATIVE_PROTOCOL`) they are
nearly the only mistakes left — constrained decoding already guarantees the
arguments parse and the tool name exists, so what remains is a well-formed
object with the wrong contents.

**What it cannot catch, and this is the honest half.**  A value of the
right *type* that is wrong in *kind* passes here and always will.  The
measured failure on the reference deployment — a mission that spent two of
four turns because ``uv pip install …`` was handed to the tool that runs
**Python**, and then again as a subprocess install — is a string where a
string was declared.  No schema in that catalogue said otherwise, so no
schema check refuses it; what refuses it is a better tool description, a
narrower tool set, or a grounding rule, and pretending this module covers
it would be worse than not having it.  The same goes for anything the
schema does not state: cross-field rules, a path that must be inside the
workspace, an id that must exist, a ``format`` nobody declared.

**Optional dependency, and a floor without it.**  ``jsonschema`` is in the
``mission`` extra, and when it is importable it is what runs — the whole
draft, including nested objects, ``$ref`` and every keyword.  When it is
not, the fallback below checks ``required``, ``type`` and ``enum`` at the
top level and says nothing about anything else.  Deliberately lenient: a
harness that refused a call because its own miniature validator did not
understand a keyword would be inventing a refusal the tool never asked
for, and a mission that cannot call a tool it is allowed to call is a
worse failure than an argument the server would have rejected anyway.

The sentence a violation produces is written **once**, here, for both
engines.  It names the tool, the field and the rule, and it ends with the
tool's own argument summary — a refusal that teaches the schema at the
turn it binds is the one that costs a single turn instead of three.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.tools.descriptors import summarize_input_schema

try:                                            # pragma: no cover - import
    import jsonschema as _jsonschema
except Exception:                               # pragma: no cover - import
    _jsonschema = None

__all__ = ["check", "engine", "JSONSCHEMA", "BUILTIN"]

#: What :func:`engine` answers when the real validator is installed.
JSONSCHEMA = "jsonschema"

#: …and when it is not, and the floor below is doing the checking.
BUILTIN = "builtin"


def engine() -> str:
    """Which validator this process will use, :data:`JSONSCHEMA` or
    :data:`BUILTIN`.

    Readable so a caller — a test, a deployment's doctor script — can say
    which of the two guarantees it is actually getting, rather than
    inferring it from whether a refusal happened to mention a nested field.
    """
    return JSONSCHEMA if _jsonschema is not None else BUILTIN


def check(tool: str, schema: Optional[Dict[str, Any]],
          arguments: Any) -> str:
    """The first violation as one sentence, or ``""`` when there is none.

    A string rather than an exception or a ``(bool, reason)`` pair: every
    caller does the same thing with it — refuse the dispatch and hand the
    sentence to the model — and a falsy return is the ordinary case, which
    is the one worth reading at a glance.

    A tool with no schema is not checked, and that is not a hole: it is a
    tool that never said what it takes, and a harness that invented a rule
    for it would be refusing calls on its own authority.
    """
    if not isinstance(schema, dict) or not schema:
        return ""
    if not isinstance(arguments, Mapping):
        # The loop refuses a non-object `arguments` before it gets here;
        # this is the library caller's version of the same refusal.
        return _sentence(
            tool, f"the arguments must be a JSON object, not a "
                  f"{type(arguments).__name__}", schema)
    if _jsonschema is not None:
        return _with_jsonschema(tool, schema, dict(arguments))
    return _builtin(tool, schema, dict(arguments))


# ── the sentences, written once for both engines ─────────────────────────────


def _sentence(tool: str, detail: str, schema: Dict[str, Any]) -> str:
    """The whole refusal: what is wrong, that nothing ran, and the schema.

    The last clause is the teaching one.  The recorded lesson of 10 August
    2026 is that a rule stated in the refusal *at the turn it binds* is
    learned by a 20B model where the same rule 2,000 tokens upstream in a
    persona is not, so the argument summary rides every violation rather
    than being left in the catalogue the model has already scrolled past.
    """
    summary = summarize_input_schema(schema)
    where = f" {tool} takes: {summary}." if summary else ""
    return (f"{tool} was NOT called: {detail}. Nothing ran and nothing "
            f"changed.{where} Fix the arguments and call it again.")


def _missing(tool: str, field: str, schema: Dict[str, Any]) -> str:
    return _sentence(tool, f"the required argument {field!r} is missing",
                     schema)


def _wrong_type(tool: str, field: str, expected: Any, value: Any,
                schema: Dict[str, Any]) -> str:
    want = (" or ".join(str(k) for k in expected)
            if isinstance(expected, (list, tuple)) else str(expected))
    return _sentence(
        tool,
        f"the argument {field!r} must be {want}, and {value!r} is a "
        f"{_json_type_name(value)}", schema)


def _bad_enum(tool: str, field: str, allowed: Sequence[Any], value: Any,
              schema: Dict[str, Any]) -> str:
    return _sentence(
        tool,
        f"the argument {field!r} must be one of "
        f"{'|'.join(str(v) for v in allowed)}, and {value!r} is not",
        schema)


def _other(tool: str, field: str, message: str,
           schema: Dict[str, Any]) -> str:
    where = f"the argument {field!r} " if field else ""
    return _sentence(tool, f"{where}{message}", schema)


# ── the real validator ───────────────────────────────────────────────────────


def _with_jsonschema(tool: str, schema: Dict[str, Any],
                     arguments: Dict[str, Any]) -> str:
    """The whole draft, rendered into this module's own sentences.

    The *errors* are jsonschema's and the *words* are this module's, so a
    violation reads the same whichever engine found it and a deployment
    that installs the extra does not get a differently-worded refusal for
    the same mistake.

    A schema this library cannot even compile is not a violation of
    anything — it is a tool that published something odd — so it is
    reported as no violation rather than as a refused call.
    """
    try:
        validator = _jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(arguments),
                        key=lambda e: (list(e.absolute_path), str(e.message)))
    except Exception:                           # pragma: no cover - defensive
        return ""
    if not errors:
        return ""
    error = errors[0]
    field = ".".join(str(part) for part in error.absolute_path)
    if error.validator == "required":
        return _missing(tool, _quoted(error.message) or field, schema)
    if error.validator == "type":
        return _wrong_type(tool, field, error.validator_value,
                           error.instance, schema)
    if error.validator == "enum":
        return _bad_enum(tool, field, error.validator_value or (),
                         error.instance, schema)
    return _other(tool, field, str(error.message), schema)


def _quoted(message: str) -> str:
    """``'q' is a required property`` → ``q``.

    jsonschema reports a missing property on the *object*, so the name is
    only in the message.  Read out rather than guessed at: a refusal that
    said "a required argument is missing" without saying which one is the
    refusal that costs a second turn.
    """
    text = str(message)
    for quote in ("'", '"'):
        if text.startswith(quote) and quote in text[1:]:
            return text[1:text.index(quote, 1)]
    return ""


# ── the floor, for an install without the extra ──────────────────────────────


def _builtin(tool: str, schema: Dict[str, Any],
             arguments: Dict[str, Any]) -> str:
    """``required``, ``type`` and ``enum``, at the top level, leniently.

    Every keyword this does not know is a keyword it says nothing about.
    That is the whole design: the cost of a missed violation is one turn
    spent on a refusal the server would have given anyway, and the cost of
    an invented one is a tool the mission may call and cannot.
    """
    required = schema.get("required")
    if isinstance(required, (list, tuple)):
        for name in required:
            if str(name) not in arguments:
                return _missing(tool, str(name), schema)

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return ""
    for name, spec in properties.items():
        if name not in arguments or not isinstance(spec, dict):
            continue
        value = arguments[name]
        kinds = _declared_types(spec)
        if kinds and not any(_is_type(value, kind) for kind in kinds):
            return _wrong_type(tool, str(name), kinds, value, schema)
        enum = spec.get("enum")
        if isinstance(enum, (list, tuple)) and enum and value not in enum:
            return _bad_enum(tool, str(name), enum, value, schema)
    return ""


def _declared_types(spec: Dict[str, Any]) -> List[str]:
    """Every JSON type *spec* allows, or ``[]`` for "it did not say".

    ``anyOf``/``oneOf`` is the shape a FastMCP optional argument takes —
    ``[{type: string}, {type: null}]`` — and reading only ``type`` there
    would find nothing and check nothing.  A branch with no ``type`` of its
    own makes the whole union unknowable, and unknowable means unchecked.
    """
    kind = spec.get("type")
    if isinstance(kind, str):
        return [kind]
    if isinstance(kind, (list, tuple)):
        return [str(k) for k in kind]
    for key in ("anyOf", "oneOf"):
        branches = spec.get(key)
        if not isinstance(branches, (list, tuple)) or not branches:
            continue
        kinds: List[str] = []
        for branch in branches:
            if not isinstance(branch, dict):
                return []
            inner = _declared_types(branch)
            if not inner:
                return []
            kinds.extend(inner)
        return kinds
    return []


def _is_type(value: Any, kind: str) -> bool:
    """Whether *value* is JSON's *kind*.

    ``bool`` is tested before ``int`` because in Python it *is* an ``int``,
    and a schema that said ``integer`` did not mean ``True``.
    """
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (isinstance(value, (int, float))
                and not isinstance(value, bool))
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, (list, tuple))
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "null":
        return value is None
    # A word this floor has never heard of. See the docstring: unknown is
    # unchecked, never refused.
    return True


def _json_type_name(value: Any) -> str:
    """What JSON would call *value*'s type, for the refusal's second half."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__
