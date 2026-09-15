# core/runtime/declarations.py — what a plane says its tools return

"""The plane's own word about its tools, resolved once and then quoted.

A receipt says what one call *did* return.  Nothing in this framework
has ever held what a call *would* return, which is why a runtime cannot
say which two receipts are about one thing, which call would answer an
open question, or which later call carries the product a handle stands
for.  That missing half is a **declaration**, and a declaration has two
doors:

* **the wire** — MCP ``outputSchema``, published by the server at
  ``tools/list`` and ingested by :mod:`core.tools.mcp_client` exactly as
  ``inputSchema`` is.  The plane speaking about itself, now;
* **the manifest** — a ``tools:`` block in a skill's frontmatter, read
  here and composed by :mod:`core.runtime.skills`.  The platform's
  *memory* of a plane, for a server it does not control.

**Shape is the wire's and semantics are a layer above it.**  A schema
says a key is a string; it cannot say that the string is a job's
identity, that this call establishes a verdict, or that the asset it
promises arrives later through a different tool.  Those three sentences
are the whole vocabulary here — :data:`IDENTIFIERS`, :data:`ESTABLISHES`
and :data:`PRODUCES` — and they may arrive through either door: on the
wire as ``x-`` extension keys inside ``outputSchema`` (the recommended
end state, for a server generated from typed contracts), or in the
manifest block for every server that publishes none.

**Where they disagree, the wire wins, and it is never silent.**  The
wire is the plane speaking now and the manifest is a memory of it; when
they differ the plane has changed and the memory is stale.  A manifest
may never re-declare *shape* at all where the wire published one — that
is a second copy of a fact with one owner, and a second copy drifts.
Every disagreement is a counted :class:`Discrepancy`: one console line
at the door, and one record in ``reasoning.jsonl`` so a resumed run whose
plane changed can be read back rather than guessed at.

**Declarations steer; they never gate and they never assert.**  They are
the platform's claim about its plane — SOURCE authority in the kernel's
vocabulary — and no fact enters any store because a schema said it
would.  A declaration that lies costs a hint, never a receipt: that is
the bound this layer is built to stay inside, and it is why nothing here
raises at a mission (the one door that refuses is
:meth:`ToolsBlock.from_mapping`, which runs when a *manifest* loads, long
before a mission starts).

Nothing here is rendered into the model's catalogue.  Catalogue bloat is
a measured hazard and these declarations feed the runtime, not the
prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.tools.descriptors import same_tool, tool_key

__all__ = [
    "DECLARATIONS_KEY", "DECLARATIONS_SCHEMA_VERSION", "BLOCK_KEYS",
    "DEFAULTS_KEYS", "ENTRY_KEYS", "IDENTIFIER_TERMS", "PRODUCES_KEYS",
    "ESTABLISHES", "IDENTIFIERS", "PRODUCES", "SHAPE", "VERBS", "WIRE_VERBS",
    "MANIFEST", "WIRE", "PROBLEM_SEP",
    "DeclarationError", "Discrepancy", "PlaneDeclarations", "Produced",
    "ToolDeclaration", "ToolEntry", "ToolsBlock", "properties_of",
    "read_identifiers", "thawed", "values_at",
]

#: The key the ``reasoning.jsonl`` declarations record states its own
#: version under, and the key that identifies the record.  Its own number
#: for :func:`core.runtime.cognition.header_record`'s reason: this record's
#: shape changes for its own reasons, and a reader that had to infer it
#: from the file's version would be reading two facts off one number.
DECLARATIONS_KEY = "declarations_schema"
DECLARATIONS_SCHEMA_VERSION = 1

#: Key → the kind of subject that key identifies.  The one verb an entity
#: resolver consumes: *this string is an identity, not a figure*.
IDENTIFIERS = "identifiers"

#: Fields this tool can establish about the subjects it names.  Advisory
#: vocabulary — read where a runtime asks "what would answer this", never
#: a promise the runtime enforces.
ESTABLISHES = "establishes"

#: The two-phase declaration: this call yields a handle (``on``) and the
#: real product (``field``, of ``kind``) arrives through a later call to
#: ``via``, keyed by that handle.  It creates no facts and no obligations;
#: what it adds is the runtime knowing which call would move one.
PRODUCES = "produces"

#: The three verbs, in the order a reader meets them.
VERBS: Tuple[str, ...] = (IDENTIFIERS, ESTABLISHES, PRODUCES)

#: The same three on the wire, inside ``outputSchema``.  ``x-`` because
#: that is what JSON Schema has always called a key its own vocabulary
#: does not define, and a server generated from typed contracts can emit
#: them without asking anybody's permission.
WIRE_VERBS: Mapping[str, str] = MappingProxyType(
    {f"x-{verb}": verb for verb in VERBS})

#: What a manifest entry calls the shape it is stating as a FALLBACK — for
#: a server that publishes no ``outputSchema`` at all.  Where the wire
#: published one, a manifest shape is a discrepancy and is ignored.
SHAPE = "output_schema"

#: Who a resolved declaration came from.  Two words, closed, because they
#: are written into a record a later process reads.
WIRE = "wire"
MANIFEST = "manifest"

#: What a ``tools:`` block may say.  Closed, and refused by name like
#: :data:`core.runtime.cognition.COGNITION_KEYS`: a key this reader has
#: never heard of is a key an author believed was doing something.
BLOCK_KEYS: Tuple[str, ...] = ("defaults", "entries")

#: What ``defaults:`` may say.  One verb, deliberately: an envelope's own
#: chaining handle is the case this exists for, and an ``establishes`` that
#: applied to every tool of a plane would be a sentence nobody could mean.
DEFAULTS_KEYS: Tuple[str, ...] = (IDENTIFIERS,)

#: What one entry of ``entries:`` may say.
ENTRY_KEYS: Tuple[str, ...] = ("name", IDENTIFIERS, ESTABLISHES, PRODUCES,
                               SHAPE)

#: The terms of one identifier declaration this reader consumes — what
#: :func:`read_identifiers` reads an entry's body by.  ``TERMS`` and not
#: ``KEYS``, because every other ``*_KEYS`` tuple in this module feeds
#: :func:`_closed` and this one deliberately does not: the entry body is
#: the vocabulary's **one open mapping** — this is the home of that
#: argument, and the other mentions point here.  It is open because it is
#: where a platform writes its own richer semantics beside ours: a real
#: deployment declares entries shaped
#: ``{kind: job, identifies: …, resolves_with: …}``, and a reader that
#: refused the keys it does not consume would not merely note them — on
#: the wire a problem drops the WHOLE verb (:func:`read_wire`), so the
#: refusal would silently erase a declaration the server got right.  The
#: richer keys are **ignored without fault**: no problem, no discrepancy,
#: and nothing downstream ever sees them — the resolved declaration
#: carries only ``{path: kind}``, so no platform should expect
#: ``identifies`` or ``resolves_with`` to reach a store, a view, or a
#: record.  Openness is only for what is not consumed: ``kind`` is still
#: required, still one word, and still refused by name when it is missing
#: or malformed — and on the wire that refusal still costs the whole verb.
IDENTIFIER_TERMS: Tuple[str, ...] = ("kind",)

#: What one ``produces`` entry must say — all four, because a two-phase
#: declaration missing any of them names no call anybody could make.
PRODUCES_KEYS: Tuple[str, ...] = ("kind", "field", "via", "on")

#: ``on`` is a **YAML 1.1 boolean**, and pyyaml is a YAML 1.1 parser: a
#: manifest writing ``on: job_id`` hands this reader the key ``True``.  That
#: is not an author's mistake in any sense they could act on — it is the
#: word this vocabulary uses, parsed by the loader the mission itself uses —
#: so inside a ``produces`` entry, where ``on`` is the only key it could be,
#: it is read back as that key rather than refused with a message about
#: quoting.
#:
#: Only there.  ``True`` may have been typed ``on``, ``yes`` or ``true`` and
#: ``False`` may have been ``off``, ``no`` or ``false``, so **anywhere else
#: a boolean key is a key this reader cannot name** — it says the family
#: instead (:func:`_spelled`), because quoting the Python word back at
#: somebody who wrote YAML sends them looking for a word that is not in
#: their file.
_YAML_TRUE_KEY = "on"

#: How a YAML 1.1 boolean is described back to the author who typed one.
#: Both families, because which word was written cannot be recovered.
_YAML_BOOLS: Mapping[bool, str] = MappingProxyType({
    True: "a bare `on`, `yes` or `true`",
    False: "a bare `off`, `no` or `false`",
})

#: How the problems of one refusal are laid out, and it is **not** ``"; "``:
#: :data:`core.runtime.cognition.PROBLEM_SEP`'s argument, restated here
#: rather than imported so that a pure declaration reader does not drag the
#: kernel in.  A manifest refusal is a list (``"\n  - "``) and these faults
#: are a list *inside one of its items*, so they are indented one level
#: deeper and every caller of this door ends its sentence with a colon.
PROBLEM_SEP = "\n    - "

#: What a key path may be spelled with: dotted segments, each optionally
#: ending in ``[]`` for *every element of this list*.  ``data.job_id``,
#: ``source_assets[]``, ``data.items[].id``.  The platform's envelope is
#: why a path and not a name — real fields live under ``data.*`` — and the
#: grammar is closed because a path this reader cannot walk is a
#: declaration that binds nothing while reading as though it binds.
_SEGMENT = r"[A-Za-z_][A-Za-z0-9_-]*(?:\[\])?"
_PATH = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT})*$")

#: What a subject *kind* may be spelled with.  No ``:`` and no ``#``,
#: because a subject is spelled ``kind:value`` and a receipt is spelled
#: ``tool#seq``: a kind carrying either separator would put two namespaces
#: into one string, which is the one mistake this layer cannot recover
#: from once a link has been written down.
_KIND = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


class DeclarationError(ValueError):
    """A ``tools:`` block is not usable, with every reason at once."""


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _spelled(key: Any) -> str:
    """How a key is named back to the person who typed it.

    ``repr`` for everything a reader can point at in the file, and the
    YAML 1.1 boolean families for the one thing it cannot: pyyaml hands
    back ``True`` for ``on``, ``yes`` and ``true`` alike, and a refusal
    quoting ``True`` sends an author looking for a word their file does
    not contain.  See :data:`_YAML_BOOLS`.
    """
    if isinstance(key, bool):
        return f"{_YAML_BOOLS[key]} (YAML reads it as a boolean, not a name)"
    return repr(key)


def _frozen(value: Any) -> Any:
    """*value* as something a later caller cannot edit, all the way down.

    Mappings become :class:`~types.MappingProxyType` over copies and lists
    become tuples, so a schema that arrived off a YAML load stops being the
    loader's object.  Scalars are returned as they are, which is what makes
    this cheap enough to run at every door.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _frozen(item)
                                 for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(item) for item in value)
    return value


def thawed(value: Any) -> Any:
    """The inverse of :func:`_frozen`: plain dicts and lists, all the way
    down.

    For the one caller that has to hand a schema back out as *data* — the
    composition in :mod:`core.runtime.skills`, which builds a raw block no
    skill wrote and which a reader, a YAML dump or a JSON line may see
    next.  A ``MappingProxyType`` in a mapping somebody serialises is a
    string in a file nobody can read back.
    """
    if isinstance(value, Mapping):
        return {str(key): thawed(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thawed(item) for item in value]
    return value


def _closed(raw: Mapping, allowed: Sequence[str], where: str,
            problems: List[str]) -> None:
    """Every key of *raw* this reader has never heard of, named."""
    unknown = [key for key in raw if str(key) not in allowed]
    for key in sorted(unknown, key=str):
        problems.append(
            f"{where} says {_spelled(key)}, which this reader has never "
            f"heard of; a `tools:` block may say "
            f"{', '.join(repr(k) for k in allowed)}")


# ── what a key path points at ────────────────────────────────────────────────


def values_at(payload: Any, path: str) -> Tuple[Any, ...]:
    """Every value *path* points at inside *payload*, in encounter order.

    The **walker for the grammar this module already owns** (:data:`_PATH`),
    and it lives here for that reason: a declaration's key is a path, the
    only module that says what a path may be spelled like is this one, and a
    second walker elsewhere would be free to disagree with the grammar that
    admitted the string.  :mod:`core.runtime.cognition` reads identifiers
    through it; nothing else in the package walks a declared key.

    **Not a harvester, and the difference is the whole reason it is
    allowed.**  :func:`core.runtime.grounding.harvest_fields` is this
    framework's one answer to *what fields and figures does this payload
    hold*, and it flattens: it reports a key by its **name**, wherever in a
    nested structure it was found.  That is right for a grounding check
    asking whether a figure is anywhere in the evidence, and it is wrong for
    a declaration, which says that ``data.job_id`` — and not ``meta.job_id``
    — is a job's identity.  So this function never asks what a payload
    holds; it is handed one path, anchored at the root, and answers what is
    *there*.  A plane whose envelope moved a key is then a declaration that
    binds nothing (and a discrepancy, at the door) rather than a link made
    off a same-named key somewhere else, which is the one mistake in this
    design that manufactures contradictions.

    The grammar, applied:

    * a plain segment walks into a mapping's key.  Over a list it matches
      nothing: ``data.job_id`` says the payload has a ``data`` **object**,
      and reading it as "the first element's" would be this walker
      inventing a declaration;
    * a ``[]`` segment says *every element of this list*, and over a
      non-list it matches nothing, for the same reason in the other
      direction;
    * a path this grammar would not admit matches nothing at all.  It can
      only arrive here from a door that already refused it, so the answer
      is silence rather than a second refusal message.

    Order is the payload's own: mapping insertion order and list order,
    which is what makes the result of a walk over one receipt a function of
    that receipt's bytes.
    """
    text = str(path or "")
    if not _PATH.match(text):
        return ()
    nodes: List[Any] = [payload]
    for segment in text.split("."):
        every = segment.endswith("[]")
        key = segment[:-2] if every else segment
        found: List[Any] = []
        for node in nodes:
            if not _is_mapping(node) or key not in node:
                continue
            value = node[key]
            if not every:
                found.append(value)
            elif isinstance(value, (list, tuple)):
                found.extend(value)
        nodes = found
        if not nodes:
            return ()
    return tuple(nodes)


# ── the three verbs.  ONE reader each, for both doors ────────────────────────


def read_identifiers(raw: Any, where: str,
                     problems: List[str]) -> Dict[str, str]:
    """``{key path: subject kind}``, or nothing and a reason.

    One owner, called by the manifest reader and by the wire reader, so
    that ``x-identifiers`` on a server's schema and ``identifiers:`` in a
    skill's frontmatter cannot mean two different things.  That is the
    same rule the grounding merge keeps by going through
    ``GroundingConfig`` rather than round the side of it.

    **An entry's body is the vocabulary's one open mapping**: the
    :data:`IDENTIFIER_TERMS` are read, and every richer key beside them
    (``identifies``, ``resolves_with``, whatever a platform's generator
    emits) is **ignored without fault** — the result carries only
    ``{path: kind}``, so nothing downstream ever sees the extras.  The
    whole argument, including the measured bug the alternative was, lives
    at :data:`IDENTIFIER_TERMS`.
    """
    found: Dict[str, str] = {}
    if raw is None:
        return found
    if not _is_mapping(raw):
        problems.append(
            f"{where} `{IDENTIFIERS}` holds a {type(raw).__name__}; it is a "
            f"mapping of key path -> {{kind: <subject kind>}}")
        return found
    for key, body in raw.items():
        path = _text(key)
        if not path or not _PATH.match(path):
            problems.append(
                f"{where} `{IDENTIFIERS}` names {_spelled(key)}, which is "
                f"not a key path: dotted segments, each optionally ending "
                f"in `[]` (`data.job_id`, `source_assets[]`)")
            continue
        if not _is_mapping(body):
            problems.append(
                f"{where} `{IDENTIFIERS}: {path}` holds a "
                f"{type(body).__name__}; it is a mapping stating the kind of "
                f"subject this key identifies ({{kind: job}})")
            continue
        # No `_closed` here, alone in this module: the entry body is the
        # open mapping — the argument lives at `IDENTIFIER_TERMS`, which
        # is also where the one consumed term comes from, so the constant
        # and this read cannot drift apart.
        kind = _text(body.get(IDENTIFIER_TERMS[0]))
        if not kind:
            problems.append(
                f"{where} `{IDENTIFIERS}: {path}` states no `kind`; a key "
                f"identifies a KIND of subject (job, asset, run) and a "
                f"declaration without one says only that the value matters")
            continue
        if not _KIND.match(kind):
            problems.append(
                f"{where} `{IDENTIFIERS}: {path}` states kind {kind!r}; a "
                f"kind is spelled without `:` or `#`, which separate a "
                f"subject from its value and a tool from its receipt")
            continue
        if path in found:
            problems.append(
                f"{where} `{IDENTIFIERS}` names {path!r} twice")
            continue
        found[path] = kind
    return found


def read_establishes(raw: Any, where: str,
                     problems: List[str]) -> Tuple[str, ...]:
    """The fields a tool can establish, in the order written, deduplicated."""
    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        problems.append(
            f"{where} `{ESTABLISHES}` holds a {type(raw).__name__}; it is a "
            f"list of field names this tool can establish")
        return ()
    found: List[str] = []
    for item in raw:
        name = _text(item)
        if not name or not _PATH.match(name):
            problems.append(
                f"{where} `{ESTABLISHES}` names {_spelled(item)}, which is "
                f"not a field: dotted segments, each optionally ending in "
                f"`[]`")
            continue
        if name not in found:
            found.append(name)
    return tuple(found)


@dataclass(frozen=True)
class Produced:
    """One two-phase declaration: a handle now, the product later."""

    kind: str
    field: str
    via: str
    on: str

    def as_record(self) -> Dict[str, str]:
        return {key: getattr(self, key) for key in PRODUCES_KEYS}

    @classmethod
    def from_record(cls, record: Mapping) -> "Produced":
        return cls(**{key: str(record.get(key) or "") for key in PRODUCES_KEYS})

    def sentence(self) -> str:
        return (f"{self.kind} `{self.field}` via {self.via} "
                f"keyed on {self.on}")


def read_produces(raw: Any, where: str, problems: List[str],
                  keyed_on: Optional[Sequence[str]] = None,
                  ) -> Tuple[Produced, ...]:
    """The two-phase declarations of one tool.

    *keyed_on* is the identifier key paths that tool declares, and an ``on``
    outside it is refused: a handle nothing names is a hint that can never
    fire, and the author who typed the wrong key would find out by never
    seeing the hint they wrote.

    ``None`` — and **only** ``None`` — stands the check down.  That is the
    wire's case: a schema carries whichever verbs the server chose to emit,
    and a reader that refused an ``x-produces`` because the same schema
    published no ``x-identifiers`` would be inventing a rule for somebody
    else's generator.  The manifest always passes a sequence, **empty
    included**: an entry that declares a product and no handle at all is
    the plainest form of the mistake this check exists for, and an empty
    default would have excused exactly it.
    """
    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        problems.append(
            f"{where} `{PRODUCES}` holds a {type(raw).__name__}; it is a list "
            f"of {{kind, field, via, on}} mappings")
        return ()
    found: List[Produced] = []
    for item in raw:
        if not _is_mapping(item):
            problems.append(
                f"{where} `{PRODUCES}` holds a {type(item).__name__}; each "
                f"entry is a mapping stating {', '.join(PRODUCES_KEYS)}")
            continue
        # See `_YAML_TRUE_KEY`: the loader turned a bare `on:` — or `yes:`,
        # or `true:` — into `True` before this reader ever saw it, and `on`
        # is the only key it could have been meant as here. `False` is NOT
        # mapped: no key of this entry is spelled `off`, `no` or `false`,
        # so one lands in `_closed` and is named by its family.
        item = {(_YAML_TRUE_KEY if key is True else key): value
                for key, value in item.items()}
        _closed(item, PRODUCES_KEYS, f"{where} `{PRODUCES}` entry", problems)
        values = {key: _text(item.get(key)) for key in PRODUCES_KEYS}
        missing = [key for key in PRODUCES_KEYS if not values[key]]
        if missing:
            problems.append(
                f"{where} `{PRODUCES}` entry states no "
                f"{', '.join(repr(key) for key in missing)}; a two-phase "
                f"declaration names the product (kind, field), the call that "
                f"carries it (via) and the handle it is keyed by (on), and "
                f"one missing term is a hint nobody can act on")
            continue
        if keyed_on is not None and values["on"] not in keyed_on:
            declared = (", ".join(sorted(keyed_on)) if keyed_on
                        else "neither it nor the plane declares one")
            problems.append(
                f"{where} `{PRODUCES}` is keyed on {values['on']!r}, which "
                f"this tool does not declare as an identifier ({declared}); "
                f"a handle nothing names is a hint that can never fire")
            continue
        entry = Produced(**values)
        if entry not in found:
            found.append(entry)
    return tuple(found)


# ── door 2: the manifest block ───────────────────────────────────────────────


@dataclass(frozen=True)
class ToolEntry:
    """One tool, as a manifest remembers it."""

    name: str
    identifiers: Mapping[str, str] = field(default_factory=dict)
    establishes: Tuple[str, ...] = ()
    produces: Tuple[Produced, ...] = ()
    #: The shape this entry states, for a server that publishes none.  The
    #: wire's is preferred always; see :meth:`PlaneDeclarations.build`.
    shape: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifiers",
                           MappingProxyType(dict(self.identifiers)))
        # The schema too, and it was the one leak in an object whose whole
        # promise is *read once and then quoted*: a nested mapping handed
        # straight off a YAML load is still the caller's to edit, and a
        # declaration that could be edited after the door is a declaration
        # the door did not validate. Deep because a JSON schema is nested
        # all the way down — a frozen top level over a live `properties`
        # would be the reassuring half of immutability.
        if self.shape is not None:
            object.__setattr__(self, "shape", _frozen(self.shape))


@dataclass(frozen=True)
class ToolsBlock:
    """A manifest's ``tools:`` block, read once and then quoted."""

    defaults: Mapping[str, str] = field(default_factory=dict)
    entries: Tuple[ToolEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "defaults",
                           MappingProxyType(dict(self.defaults)))

    def __bool__(self) -> bool:
        return bool(self.defaults or self.entries)

    @classmethod
    def from_mapping(cls, raw: Any) -> "ToolsBlock":
        """The block a manifest wrote, or a refusal naming every fault.

        Validated ALL THE WAY DOWN at the door, for the reason
        :meth:`core.runtime.cognition.RulePack.from_mapping` is: a
        declaration that does not stand up is an author's mistake, and the
        cheapest moment to say so is while they are looking at the file.
        Nothing here can be found later — a malformed identifier binds
        nothing, silently, for the whole life of a deployment.
        """
        problems: List[str] = []
        if raw is None:
            return cls()
        if not _is_mapping(raw):
            raise DeclarationError(
                f"{PROBLEM_SEP}a `tools:` block holds a "
                f"{type(raw).__name__}; it is a mapping "
                f"({', '.join(BLOCK_KEYS)})")
        _closed(raw, BLOCK_KEYS, "`tools:`", problems)

        defaults: Dict[str, str] = {}
        raw_defaults = raw.get("defaults")
        if raw_defaults is not None:
            if not _is_mapping(raw_defaults):
                problems.append(
                    f"`tools: defaults` holds a {type(raw_defaults).__name__};"
                    f" it is a mapping ({', '.join(DEFAULTS_KEYS)})")
            else:
                _closed(raw_defaults, DEFAULTS_KEYS, "`tools: defaults`",
                        problems)
                defaults = read_identifiers(raw_defaults.get(IDENTIFIERS),
                                            "`tools: defaults`", problems)

        entries: List[ToolEntry] = []
        raw_entries = raw.get("entries")
        #: ``tool_key`` → the spelling that claimed it, so a second entry
        #: for one tool can be refused naming BOTH names as written.
        seen: Dict[str, str] = {}
        if raw_entries is not None:
            if isinstance(raw_entries, str) or not isinstance(raw_entries,
                                                              Sequence):
                problems.append(
                    f"`tools: entries` holds a {type(raw_entries).__name__}; "
                    f"it is a list of per-tool declarations")
                raw_entries = ()
            for item in raw_entries:
                entry = cls._entry(item, defaults, seen, problems)
                if entry is not None:
                    entries.append(entry)

        if problems:
            raise DeclarationError(PROBLEM_SEP + PROBLEM_SEP.join(problems))
        return cls(defaults=defaults, entries=tuple(entries))

    @staticmethod
    def _entry(item: Any, defaults: Mapping[str, str], seen: Dict[str, str],
               problems: List[str]) -> Optional[ToolEntry]:
        if not _is_mapping(item):
            problems.append(
                f"`tools: entries` holds a {type(item).__name__}; each entry "
                f"is a mapping naming one tool")
            return None
        name = _text(item.get("name"))
        where = f"`tools: {name}`" if name else "`tools:` entry"
        if not name:
            problems.append(
                "a `tools: entries` entry states no `name`; a declaration is "
                "about one tool and the name is how a receipt finds it")
            return None
        _closed(item, ENTRY_KEYS, where, problems)
        key = tool_key(name)
        if key in seen:
            # Within ONE manifest, and refused rather than merged: two
            # entries for one tool is an author editing the wrong one for
            # the rest of the file's life, and which of them binds would be
            # a fact about listing order. Two SKILLS declaring one tool is a
            # different question and has a different answer — see
            # `core.runtime.skills._merge_tools`.
            #
            # Keyed on `tool_key` and NOT on the name as typed, because
            # that is the identity every consumer of this block uses:
            # `entry_for` and `for_tool` both match on `same_tool`, so two
            # spellings of one tool (`runs_get` and `runs.get`) let the door
            # pass a file whose entries then match a lookup TWICE — and an
            # ambiguous match binds neither. The tool would silently lose
            # every declaration it had, and the plane would collect two
            # false notes blaming it for offering nothing.
            #
            # `tool_key` and not `same_tool`, and the difference is one
            # legitimate pair: `runs_get` and `mcp.runs_get` have different
            # keys and ARE different tools — this host's own and a bridged
            # one, which the code-plane gate already tells apart — so a
            # manifest may declare both. The exact-name rule in `entry_for`
            # is what keeps that pair unambiguous, and it is why the rule
            # is *exact first, `same_tool` after*.
            problems.append(
                f"`tools:` declares one tool twice, as {seen[key]!r} and "
                f"{name!r}; those are the same tool to every lookup here "
                f"(`same_tool`), so two entries would match a receipt twice "
                f"and bind neither. Keep one spelling")
            return None
        seen[key] = name
        identifiers = read_identifiers(item.get(IDENTIFIERS), where, problems)
        keyed_on = sorted({*identifiers, *defaults})
        shape = item.get(SHAPE)
        if shape is not None and not _is_mapping(shape):
            problems.append(
                f"{where} `{SHAPE}` holds a {type(shape).__name__}; it is a "
                f"JSON-schema mapping, and only for a server that publishes "
                f"none of its own — where one is published the wire's wins")
            shape = None
        elif shape is not None and not properties_of(shape):
            # *Does this schema say anything* has ONE owner, and it is the
            # same function on both sides of the door: a manifest fallback
            # of `{}` or `{type: object}` narrows nothing, exactly as a
            # server's bare object narrows nothing, so it states no shape
            # rather than claiming one. Two answers to that question would
            # have made a manifest's empty fallback outrank a wire's empty
            # publication for no reason anybody wrote down.
            shape = None
        return ToolEntry(
            name=name,
            identifiers=identifiers,
            establishes=read_establishes(item.get(ESTABLISHES), where,
                                         problems),
            produces=read_produces(item.get(PRODUCES), where, problems,
                                   keyed_on=keyed_on),
            shape=shape,
        )

    def entry_for(self, name: str,
                  notes: Optional[List["Discrepancy"]] = None
                  ) -> Optional[ToolEntry]:
        """The entry declaring *name*, matched this framework's one way.

        :func:`~core.tools.descriptors.same_tool`, so a manifest written as
        the server advertises (``narrative_discovery``) finds the tool the
        bridge registered (``mcp.narrative_discovery``) — the same matching
        :meth:`core.runtime.skills.SkillManifest.resolve` does, for the same
        reason: an author writes one spelling and every surface derives it.
        An exact name always wins, so a plane offering both spellings binds
        the one that was named.

        **A name that matches two entries matches neither, and *that* is
        said out loud.**  The refusal is right — a coin flip about which
        subject kind a value identifies is the one mistake this layer must
        not make — but it is also the one outcome where an author's
        declarations vanish while every line of their file was accepted at
        the door: two entries pass :meth:`ToolsBlock.from_mapping` when
        their ``tool_key``s differ (``alpha.runs_get`` and
        ``zeta.runs_get``), and a plane offering the bare ``runs_get``
        matches both.  Pass *notes* — :meth:`PlaneDeclarations.build` does —
        and the lookup leaves a :class:`Discrepancy` naming the tool and the
        two spellings, so the silence becomes a console line and a record
        rather than a tool that quietly declares nothing.
        """
        for entry in self.entries:
            if entry.name == name:
                return entry
        matches = [entry for entry in self.entries
                   if same_tool(entry.name, name)]
        if len(matches) > 1 and notes is not None:
            notes.append(Discrepancy(
                tool=str(name), key="name",
                detail=f"this manifest declares "
                       f"{', '.join(repr(entry.name) for entry in matches)}, "
                       f"and all of them match this tool; an ambiguous match "
                       f"binds none of them, so nothing is declared about it "
                       f"— name the tool as this run offers it"))
        return matches[0] if len(matches) == 1 else None


# ── door 1: the wire ─────────────────────────────────────────────────────────


def properties_of(schema: Any) -> Dict[str, Any]:
    """The keys a published schema says a result carries, or nothing.

    **This is what "a bare object declares nothing" is made of**, and it is
    one function rather than a `_bare()` predicate beside it.  An absent
    schema, ``{}``, and the ``{"type": "object"}`` a generator emits for a
    return type it could not narrow all come back empty here — so no shape
    is owned, no key is ever called absent, and the tool behaves exactly as
    it did before this module existed.  Eight of one real deployment's
    adapters declare real shapes and the rest fall back to precisely that,
    so it is the ordinary case and not an error.

    A second predicate saying the same thing in its own words is the second
    answer to *does this schema say anything*, and the day the two disagree
    is the day a fallback-shaped tool starts refusing something.

    **Public, because a second reader exists now.**  Promoted out of
    ``_properties`` the way ``harvest_fields``' ``scalars`` sink was, and
    for the same reason: :mod:`core.eval.suggest` reads saved ``tools/list``
    schemas to draft a pack, and the alternative to importing this one was a
    private import across packages or a fourth spelling of *does this schema
    say anything*.
    """
    return dict(schema.get("properties") or {}) if _is_mapping(schema) else {}


def read_wire(schema: Any, tool: str,
              problems: List[str]) -> Dict[str, Any]:
    """The ``x-`` verbs a server published **and this reader could use**,
    as ``{verb: value}``.

    Never raises and never refuses the tool: a server is not a file an
    author is editing, and a mission that died because somebody's schema
    generator emitted a malformed extension key would be this layer
    breaking the thing it exists to inform.  Faults come back through
    *problems* and become discrepancies.

    **A verb only appears in the result when its read added no problem**,
    and that is the whole difference between two facts a caller must not
    confuse:

    * ``x-identifiers: {}`` — a declaration this reader understood, saying
      *this tool identifies nothing*.  It is in the result, it wins the
      verb, and it correctly overrides a manifest that thought otherwise;
    * ``x-identifiers: ["job_id"]`` — a value this reader could not use at
      all.  It is **absent** from the result, so precedence never runs for
      that verb and the manifest's answer stands.  Anything else would let
      one malformed extension key delete a platform's declarations for a
      tool while the note beside it said the key contributed nothing.

    **One bad key makes the whole verb unusable, not a smaller verb**, and
    that is the sentence worth being explicit about because the readers
    above are *partial* by construction: :func:`read_identifiers` returns
    every entry it understood and appends a problem for each one it did
    not, so ``x-identifiers: {"job_id": {"kind": "job"}, "asset": 7}``
    comes back out of it as a usable ``{job_id: job}`` beside a fault.
    Taking that half would be the worst of the three available answers — a
    server's declaration silently *replacing* a manifest's with less than
    the server said, so a plane that mistyped one key would quietly narrow
    what another door correctly declared, and the note beside it would
    describe a key rather than the loss.  So the verb is dropped whole, the
    manifest's answer for that tool stands untouched, and the discrepancy
    names what the server published.  A platform fixes one key and gets
    everything back; nothing is half-adopted in the meantime.
    """
    found: Dict[str, Any] = {}
    if not _is_mapping(schema):
        return found
    where = f"`outputSchema` of {tool}"
    for wire_key, verb in WIRE_VERBS.items():
        if wire_key not in schema:
            continue
        raw = schema.get(wire_key)
        before = len(problems)
        if verb == IDENTIFIERS:
            value: Any = read_identifiers(raw, where, problems)
        elif verb == ESTABLISHES:
            value = read_establishes(raw, where, problems)
        else:
            value = read_produces(raw, where, problems)
        if len(problems) > before:
            # **A verb this reader could not use is not a verb the server
            # spoke.** Recorded on key PRESENCE, it would have been handed
            # back empty — and precedence would then have let an unreadable
            # `x-identifiers` ERASE the manifest's identifiers for that
            # tool, silently, under a note that says the extension key
            # "contributes nothing". It has to contribute nothing to the
            # ANSWER as well as to the log, which means not being recorded
            # at all.
            #
            # This is exactly not the same event as a server declaring
            # `x-identifiers: {}` — an empty declaration this reader
            # understood, which IS the plane saying *this tool identifies
            # nothing* and does win the verb. Unusable and empty are
            # different facts about a plane, and the difference is which
            # declaration a tool ends up standing on.
            continue
        found[verb] = value
    return found


# ── the resolution ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Discrepancy:
    """One thing the two doors do not agree about, named and counted."""

    tool: str
    key: str
    detail: str

    def sentence(self) -> str:
        return f"{self.tool} · {self.key}: {self.detail}"

    def as_record(self) -> Dict[str, str]:
        return {"tool": self.tool, "key": self.key, "detail": self.detail}

    @classmethod
    def from_record(cls, record: Mapping) -> "Discrepancy":
        return cls(tool=str(record.get("tool") or ""),
                   key=str(record.get("key") or ""),
                   detail=str(record.get("detail") or ""))


@dataclass(frozen=True)
class ToolDeclaration:
    """Everything the plane and the platform say about one tool, resolved."""

    tool: str
    identifiers: Mapping[str, str] = field(default_factory=dict)
    establishes: Tuple[str, ...] = ()
    produces: Tuple[Produced, ...] = ()
    #: Who owns the shape: :data:`WIRE`, :data:`MANIFEST` or ``""`` for a
    #: tool whose shape nobody stated.  The schema itself is not carried —
    #: it is on the wire, it is large, and what this object exists to hold
    #: is the semantics.
    shape: str = ""
    #: Per verb, which door won it.  Written into the record, so a resumed
    #: run can say whether a hint came from the plane or from a memory of it.
    sources: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifiers",
                           MappingProxyType(dict(self.identifiers)))
        object.__setattr__(self, "sources",
                           MappingProxyType(dict(self.sources)))

    def __bool__(self) -> bool:
        return bool(self.identifiers or self.establishes or self.produces)

    def as_record(self) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            IDENTIFIERS: dict(self.identifiers),
            ESTABLISHES: list(self.establishes),
            PRODUCES: [item.as_record() for item in self.produces],
            "sources": dict(self.sources),
        }
        if self.shape:
            record["shape"] = self.shape
        return record

    @classmethod
    def from_record(cls, tool: str, record: Mapping) -> "ToolDeclaration":
        return cls(
            tool=tool,
            identifiers={str(key): str(value) for key, value
                         in (record.get(IDENTIFIERS) or {}).items()},
            establishes=tuple(str(item) for item
                              in (record.get(ESTABLISHES) or ())),
            produces=tuple(Produced.from_record(item) for item
                           in (record.get(PRODUCES) or ())),
            shape=str(record.get("shape") or ""),
            sources={str(key): str(value) for key, value
                     in (record.get("sources") or {}).items()},
        )


@dataclass(frozen=True)
class PlaneDeclarations:
    """The whole plane's declarations, built once at connect and immutable.

    Built where both halves are in hand — the fleet has answered
    ``tools/list`` and the manifests have composed — because precedence
    needs both and a second place that resolved it would be the second
    answer.  Afterwards it is quoted and never edited: a run whose
    declarations moved under it could not say what it steered under.
    """

    tools: Mapping[str, ToolDeclaration] = field(default_factory=dict)
    discrepancies: Tuple[Discrepancy, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))

    def __bool__(self) -> bool:
        return any(bool(declaration) for declaration in self.tools.values())

    def __len__(self) -> int:
        return len(self.tools)

    # ── building ────────────────────────────────────────────────────────

    @classmethod
    def build(cls, *, wire: Optional[Mapping[str, Any]] = None,
              manifest: Any = None,
              offered: Sequence[str] = ()) -> "PlaneDeclarations":
        """Resolve both doors into one answer, counting every disagreement.

        *offered* is every tool name this mission actually has on the
        table — the resolved set, built-ins included — and it is read for
        exactly one question: *is a declared tool absent from this run?*
        The servers are not the whole plane.  A mission runs bridged tools
        beside ``fs``, ``run_python_code`` and whatever else the bus
        carries, and a platform that declares an identifier for one of
        those is declaring something perfectly true; blaming it on the MCP
        fleet's ``tools/list`` would be a note that is simply wrong, on a
        console, at the top of every run.  Empty means *nobody said*, which
        falls back to the wire's own set rather than calling everything
        missing.

        *wire* is ``{bus tool name: outputSchema}`` for a plane that
        answered ``tools/list``; ``None`` — not ``{}`` — is a run with no
        server at all (built-in tools, an offline replay), where a
        manifest's memory cannot be stale because nothing spoke.

        *manifest* is the **composed** ``tools:`` block: a
        :class:`ToolsBlock`, the raw mapping one is read from, or ``None``.

        The rules, in one place:

        * **shape is the wire's.**  A manifest that states one for a tool
          whose server published one is ignored and noted — one fact, one
          owner, and the owner is the plane;
        * **semantics are the wire's where the wire speaks.**  Per tool per
          verb: a server's ``x-identifiers`` replaces the manifest's
          ``identifiers`` for that tool whole (and the plane's defaults with
          it), and a difference is noted.  Agreement is silent;
        * **a manifest annotation on a key the wire no longer carries binds
          nothing**, and the note says so — a key that never appears in a
          payload can never be harvested, so the declaration is kept (it
          costs nothing and it is what the author wrote) and the reader is
          told;
        * **a bare object contributes nothing and refuses nothing** — see
          :func:`properties_of`, which is where that is true rather than a
          rule restated here.
        """
        block = (manifest if isinstance(manifest, ToolsBlock)
                 else ToolsBlock.from_mapping(manifest))
        schemas = dict(wire or {})
        on_the_table = [str(name) for name in offered] or list(schemas)
        notes: List[Discrepancy] = []
        resolved: Dict[str, ToolDeclaration] = {}
        bound: List[ToolEntry] = []

        for tool in sorted(schemas):
            # `notes` passed, so a tool whose declarations two entries claim
            # at once is a counted disagreement rather than a tool that
            # silently declares nothing — see `ToolsBlock.entry_for`.
            entry = block.entry_for(tool, notes)
            if entry is not None:
                bound.append(entry)
            resolved[tool] = cls._resolve(tool, schemas[tool], block, notes,
                                          entry)

        # Entries no server published a schema for. Kept — an author wrote
        # them, and a tool the mission holds through another door is still
        # that tool — and noted only where the tool is absent from the whole
        # run: `offered` is the resolved set, built-ins included, so a
        # declaration about `fs` on a mission that has `fs` draws nothing.
        # With no server connected at all there is nothing for a memory to
        # be stale against and no note is written either way.
        for entry in block.entries:
            if any(entry is other for other in bound):
                continue
            if entry.name in resolved:
                continue
            present = any(same_tool(name, entry.name) for name
                          in on_the_table)
            if wire is not None and not present:
                notes.append(Discrepancy(
                    tool=entry.name, key="name",
                    detail="this manifest declares the tool and this run "
                           "does not offer it; the declaration binds nothing "
                           "until it does"))
            resolved[entry.name] = cls._from_manifest(entry, block)

        return cls(tools=resolved,
                   discrepancies=tuple(sorted(
                       notes, key=lambda note: (note.tool, note.key,
                                                note.detail))))

    @staticmethod
    def _from_manifest(entry: ToolEntry,
                       block: ToolsBlock) -> ToolDeclaration:
        """One entry with the plane's defaults under it, nothing else.

        The specific beats the general, which is what a default is: an
        entry restating a key the defaults also name states it for that
        tool, and no note is written because one author wrote both.
        """
        identifiers = {**dict(block.defaults), **dict(entry.identifiers)}
        sources = {verb: MANIFEST for verb in VERBS}
        return ToolDeclaration(
            tool=entry.name, identifiers=identifiers,
            establishes=entry.establishes, produces=entry.produces,
            shape=MANIFEST if entry.shape is not None else "",
            sources=sources)

    @classmethod
    def _resolve(cls, tool: str, schema: Any, block: ToolsBlock,
                 notes: List[Discrepancy],
                 entry: Optional[ToolEntry]) -> ToolDeclaration:
        base = (cls._from_manifest(entry, block) if entry is not None
                else ToolDeclaration(tool=tool,
                                     identifiers=dict(block.defaults),
                                     sources={verb: MANIFEST
                                              for verb in VERBS}))
        problems: List[str] = []
        published = read_wire(schema, tool, problems)
        for problem in problems:
            notes.append(Discrepancy(
                tool=tool, key="outputSchema",
                detail=f"the server published an extension key this reader "
                       f"could not use, so it contributes nothing: {problem}"))

        shape = base.shape
        if properties_of(schema):
            shape = WIRE
            if entry is not None and entry.shape is not None:
                notes.append(Discrepancy(
                    tool=tool, key=SHAPE,
                    detail="the server publishes an `outputSchema` and this "
                           "manifest states one as well; the wire's is used "
                           "— the plane speaks for itself, and a second copy "
                           "of a shape is a copy that drifts"))

        identifiers = dict(base.identifiers)
        establishes = base.establishes
        produces = base.produces
        sources = dict(base.sources)

        for verb, value in published.items():
            sources[verb] = WIRE
            # What the MANIFEST said about this tool, which is what the
            # wire can disagree with. The entry's own words where there is
            # an entry, and the plane's `defaults` where there is not: a
            # default is a statement about every tool, so a server that
            # names its identifiers has contradicted it only where nothing
            # more specific was ever written. Comparing entry+defaults
            # instead would make a note out of the ordinary case — an
            # envelope handle declared once for the plane, and a server
            # that speaks for itself about one tool.
            #
            # `stated` and not `entry is not None`: a plane's `defaults`
            # are a manifest declaration too.
            stated = ({IDENTIFIERS: dict(entry.identifiers),
                       ESTABLISHES: entry.establishes,
                       PRODUCES: entry.produces}[verb] if entry is not None
                      else {IDENTIFIERS: dict(block.defaults),
                            ESTABLISHES: (), PRODUCES: ()}[verb])
            if stated and cls._differs(verb, stated, value):
                notes.append(Discrepancy(
                    tool=tool, key=verb,
                    detail=f"the server declares `x-{verb}` and this manifest "
                           f"declares `{verb}`, and they differ; the wire's "
                           f"is used — the manifest is a memory of a plane "
                           f"that has changed"))
            if verb == IDENTIFIERS:
                identifiers = dict(value)
            elif verb == ESTABLISHES:
                establishes = tuple(value)
            else:
                produces = tuple(value)

        # An annotation on a key the wire does not carry. Three bounds, and
        # each one is a place a louder check would cry wolf:
        #
        # * only where the wire published properties — a bare object is not
        #   a statement that a key is absent, and reading it as one would
        #   flood a plane of fallback-shaped adapters with notes about
        #   declarations that are perfectly good;
        # * only where the manifest won the verb — a wire that declared its
        #   own identifiers cannot disagree with itself;
        # * only keys the ENTRY declared. `defaults` are a statement about
        #   the plane, and a tool that does not carry the envelope's handle
        #   is an ordinary tool, not a stale memory of one.
        if sources.get(IDENTIFIERS) == MANIFEST and properties_of(schema):
            root = set(properties_of(schema))
            entry_keys = set(entry.identifiers) if entry is not None else set()
            for path in sorted(set(identifiers) & entry_keys):
                head = path.split(".", 1)[0].removesuffix("[]")
                if head not in root:
                    notes.append(Discrepancy(
                        tool=tool, key=f"{IDENTIFIERS}: {path}",
                        detail="this manifest declares the key and the "
                               "server's `outputSchema` does not carry it; "
                               "a key that never appears can never be read, "
                               "so the declaration binds nothing"))

        return ToolDeclaration(tool=tool, identifiers=identifiers,
                               establishes=establishes, produces=produces,
                               shape=shape, sources=sources)

    @staticmethod
    def _differs(verb: str, stated: Any, published: Any) -> bool:
        """Whether the two doors said different things about one verb.

        Sets, not sequences: a server listing two fields in the other order
        has not changed its plane, and a note about that would be noise that
        teaches a reader to skip the notes.
        """
        if verb == IDENTIFIERS:
            return dict(stated) != dict(published)
        return frozenset(stated) != frozenset(published)

    # ── reading it back ─────────────────────────────────────────────────

    def for_tool(self, name: Any) -> Optional[ToolDeclaration]:
        """What is declared about *name*, or ``None``.

        Exact first and :func:`~core.tools.descriptors.same_tool` after, for
        :meth:`ToolsBlock.entry_for`'s reason.  A name that matches two
        declarations matches neither: a coin flip about which subject kind a
        value identifies is the one mistake this layer must not make.
        """
        tool = str(name or "")
        found = self.tools.get(tool)
        if found is not None:
            return found
        matches = [declaration for key, declaration in self.tools.items()
                   if same_tool(key, tool)]
        return matches[0] if len(matches) == 1 else None

    def identifiers_for(self, name: Any) -> Mapping[str, str]:
        """``{key path: kind}`` for *name*, empty where nothing is declared."""
        declaration = self.for_tool(name)
        return declaration.identifiers if declaration is not None else {}

    def as_record(self) -> Dict[str, Any]:
        """The ``reasoning.jsonl`` record: what was resolved, and what did
        not agree.

        The schemas themselves are **not** in it.  A record exists so a
        replay steers under the declarations the live run steered under, and
        that is the semantics; the shapes are the wire's, they are large,
        and writing them here would be a second copy of the plane's own
        answer inside a log that is meant to be readable.
        """
        return {
            DECLARATIONS_KEY: DECLARATIONS_SCHEMA_VERSION,
            "tools": {tool: declaration.as_record()
                      for tool, declaration in self.tools.items()},
            "discrepancies": [note.as_record()
                              for note in self.discrepancies],
        }

    @classmethod
    def from_record(cls, record: Mapping) -> "PlaneDeclarations":
        """The declarations a record holds, rebuilt.

        The other half of a replay: a resumed process reads what the first
        one resolved rather than re-resolving against a plane that may have
        moved — and where it does re-resolve, the two records sit in one
        log and the difference is readable.
        """
        if not _is_mapping(record):
            raise DeclarationError(
                f"{PROBLEM_SEP}a declarations record is a mapping, not a "
                f"{type(record).__name__}")
        version = record.get(DECLARATIONS_KEY)
        # Both ends of the range, and the lower one is not pedantry: `0`,
        # `-1` and a missing key all read as *this is not a record written
        # by any version of this writer*, and a reader that took them for
        # version 1 would rebuild hints out of a line it had no business
        # interpreting. `bool` is refused explicitly because `True` is an
        # `int` in Python and would otherwise pass as version 1 — the same
        # guard `read_reasoning` keeps on its own header.
        if (not isinstance(version, int) or isinstance(version, bool)
                or not 1 <= version <= DECLARATIONS_SCHEMA_VERSION):
            raise DeclarationError(
                f"{PROBLEM_SEP}declarations schema {version!r} is not one "
                f"this reader can take (1..{DECLARATIONS_SCHEMA_VERSION})")
        return cls(
            tools={str(tool): ToolDeclaration.from_record(str(tool), body)
                   for tool, body in (record.get("tools") or {}).items()},
            discrepancies=tuple(Discrepancy.from_record(item) for item
                                in (record.get("discrepancies") or ())))

    # ── what an operator is told ────────────────────────────────────────

    def describe(self) -> str:
        """One line: what was declared, and by how many doors."""
        declared = [tool for tool, body in self.tools.items() if body]
        wire = sum(1 for tool in declared
                   if WIRE in self.tools[tool].sources.values())
        identifiers = sum(len(self.tools[tool].identifiers)
                          for tool in declared)
        return (f"{len(declared)} tool(s) declared "
                f"({wire} from the wire), {identifiers} identifier(s)")
