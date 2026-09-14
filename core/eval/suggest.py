# core/eval/suggest.py — draft a pack from a plane's schemas and its receipts

"""The generator proposes; a person declares.

``ROADMAP.md`` §2.9 / the subject-spine design §2.4: the cost a platform
pays for the cognitive layer is **authoring** — somebody has to sit down
with a plane of forty tools and write which keys are identities and which
fields hold one value.  That afternoon of pack archaeology is what keeps
``cognition:`` and ``tools:`` blocks empty, and an empty block is a
frontier that never fires and machinery nobody is paying off.

This subcommand turns the afternoon into a **review pass**.  It reads two
sources, drafts one YAML page, and writes nothing anybody loads.

**The honest hierarchy, and it is the point of the whole feature.**  A
line marked ``schema:`` comes from the plane's own published contract —
an ``enum`` a server declared, a key it named ``job_id``.  A line marked
``observed:`` is *induced* from receipts that happened to be recorded:
the absence of a second value is **not** evidence that a field is
single-valued, it is evidence that nobody has seen the second one yet.
So schema-derived lines are better grounded than induced ones, every line
carries its evidence count, and **neither is auto-committed** — a model
may propose; proposing never makes it true, and that generalises to every
inference tool this project builds, this one included.

**What it will not do.**  It never writes into a skill directory
(:func:`skill_directory_above` refuses the path, and the refusal names
the ``SKILL.md`` it found): a draft that landed beside a manifest would be
a suggestion one ``git add`` away from being a declaration, which is
exactly the auto-commit this design refuses.  It spends no model, dials no
server, and reads no clock — two runs over one corpus produce **byte-
identical** drafts, because a suggestion whose text moved between runs is
a diff nobody can review.

**Two sources, and where each one is read from.**

*Schemas* come from a **saved** ``tools/list`` response — a file.  Not a
connected fleet: the plumbing that connects one is asynchronous, needs a
live server and a token, and every one of those is the opposite of what
the paragraph above promises.  A platform that wants its live plane in
here saves the response first, which it can do with any MCP client it
already has.

*Receipts* come from run directories' ``tools.jsonl``, found with
:func:`core.eval.context.run_shaped` — the one bounded walk this harness
has for *where are the runs under here*.  The payload read is the
dispatch's ``stdout``, through :func:`~core.runtime.grounding.json_blocks`,
because **that is the door the shadow harvests through**
(:func:`core.runtime.cognition.observations_of`): a draft suggesting
cardinality for a field the store will never name would be a page of
lines that bind nothing.

**Two spellings, because there are two blocks.**  A ``cognition:
cardinality:`` line names a **field**, bare, because
:func:`~core.runtime.grounding.harvest_fields` flattens a payload and a
field is the key name it reports.  A ``tools: identifiers:`` line names a
**key path** (``data.job_id``, ``source_assets[]``), because
:mod:`core.runtime.declarations` walks paths.  One walk in this module
produces both, and the bare names it reports are checked against
``harvest_fields``' own in the tests rather than assumed.

**Nothing here re-decides what a declaration is.**  Every identifier
candidate is run through :func:`~core.runtime.declarations.read_identifiers`
— the same reader the wire and the manifest go through — and a candidate
it will not take is dropped rather than printed.  That is what makes the
promise *the draft loads* keep itself: :meth:`Draft.problems` asks the two
real doors, :class:`~core.runtime.cognition.RulePack` and
:class:`~core.runtime.declarations.ToolsBlock`, and a draft that does not
pass them is an error and not a page.

**Honest bounds.**  A field that held one value in eleven receipts is a
field nobody has seen contested, which is a weaker sentence than *this
field holds one value* and is the sentence the comment prints.  The store
holds numeric figures in v1, so a ``one`` on a string-valued field binds
nothing **yet** — it is still worth drafting, because cardinality is what
will bite at the subject level once linking lands.  And a plane whose
adapters publish bare objects contributes no schema lines at all, which
is the ordinary case for most of a real deployment's tools and degrades
to exactly the induced half.

One consequence of all that is visible on the page and is left visible on
purpose: a server advertising ``runs_get`` that a bridge registered as
``mcp.runs_get`` gets **two entries**, one from each source, because
:meth:`~core.runtime.declarations.ToolsBlock.entry_for` treats those two
spellings as possibly-different tools (this host's own and a bridged one)
and a generator that merged them would be guessing which one a platform's
manifest should say.  Keeping one spelling is the first thing a reviewer
of this page does, and the header already told them to prune.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from core.durable import atomic_write_text
from core.eval.context import run_shaped
from core.runtime.declarations import (DeclarationError, ToolsBlock,
                                       properties_of, read_identifiers)
from core.runtime.grounding import MAX_DEPTH, json_blocks
from core.runtime.replay import TOOL_LOG
from core.skills.library import MANIFEST_FILE

__all__ = [
    "CARDINALITY", "DEFAULT_IDENTIFIER", "DISTINCT_SHARE", "HEADER",
    "IDENTIFIER", "ID_SUFFIXES", "MIN_RECEIPTS", "OBSERVED", "SCHEMA",
    "SKILL_DEPTH", "SOURCES", "TOOL_LOG", "UUID_FORMAT",
    "Draft", "Evidence", "Receipt", "Suggestion", "SuggestRefused",
    "add_parser", "from_args", "from_observations", "from_schemas",
    "kind_of", "page_check_stood_down", "read_receipts", "read_schemas",
    "skill_directory_above", "suggest",
]

#: The two sources, and the words a line is marked with.  Closed, because
#: the mark is the whole hierarchy: a reader pruning this page decides
#: differently about a line the plane declared and a line we induced.
SCHEMA = "schema"
OBSERVED = "observed"

#: In the order a reader should trust them.  ``SCHEMA`` first, and that is
#: not cosmetic: it is the order :func:`suggest` merges in, so where both
#: sources propose one key the schema's sentence is the one that leads.
SOURCES: Tuple[str, ...] = (SCHEMA, OBSERVED)

#: The three places a suggestion can land, which are three different
#: blocks of the draft.
CARDINALITY = "cardinality"            # `cognition: cardinality:`
IDENTIFIER = "identifier"              # `tools: entries: … identifiers:`
DEFAULT_IDENTIFIER = "envelope"        # `tools: defaults: identifiers:`

#: The suffixes that make a key name look like a handle.  Two, and both
#: are in the design's own worked example (``job_id``, ``result_ref``).  A
#: longer list is a generator guessing harder, and every extra guess is a
#: line somebody has to prune.
ID_SUFFIXES: Tuple[str, ...] = ("_id", "_ref")

#: The JSON Schema ``format`` that says *this string is an identity* without
#: the name having to.
UUID_FORMAT = "uuid"

#: How many receipts a field must have been seen in before it is drafted at
#: all.  One receipt showing one value is not evidence about a second
#: receipt; it is the sample size at which induction has said nothing.
MIN_RECEIPTS = 2

#: How varied a key's values must be before a value shared under it is read
#: as an identity rather than a status.  ``state`` holds ``"completed"`` in
#: half the receipts of two different tools and is not a join key; an asset
#: id is very nearly one value per receipt.  Distinct values over
#: observations, and the floor is stated rather than tuned.
#:
#: **Both of its errors, named.**  It is a proxy for identity and it is
#: wrong in both directions, so neither is left for a reader to discover:
#:
#: * it MISSES the design's own worked example.  ``job_id`` holding
#:   ``"jl-1"`` in two receipts of two tools is a real join and one
#:   distinct value, so ``len(seen) >= 2`` suppresses it and **nothing is
#:   drafted**.  A corpus of one job is a corpus that cannot tell an
#:   identity from a constant, and inventing the line anyway would be this
#:   module guessing where it promised to count;
#: * it ADMITS a varied status.  Ten distinct dispatch states shared across
#:   two tools pass this floor and draft as an identifier candidate. High
#:   cardinality is the *converse* of the status argument, not a proof of
#:   identity — nothing in a corpus can supply that proof, which is the
#:   whole reason the page is reviewed. The comment prints the distinct
#:   count and the observation count beside every such line, so the reader
#:   pruning it is looking at the same two numbers this floor looked at.
DISTINCT_SHARE = 0.5

#: How far up from an ``--out`` path a ``SKILL.md`` is looked for.  Bounded
#: like every other walk in this harness, and generous enough to catch a
#: pack's ``fixtures/`` and ``templates/`` sub-directories without walking
#: a whole filesystem on a relative path.
SKILL_DEPTH = 8

#: The header, verbatim, and the first line of it is the sentence this
#: feature exists to print.  A tuple because a test asserts the sentence and
#: not a paragraph's worth of prose around it.
HEADER: Tuple[str, ...] = (
    "DRAFT — nothing here is loaded; review, prune, ship in a skill.",
    "",
    "Two sources, and they are NOT equally good:",
    "  schema:   the plane's own published contract, read back. Better",
    "            grounded — a server said this about itself.",
    "  observed: INDUCED from recorded receipts. The absence of a second",
    "            value is not evidence that a field holds one; it is",
    "            evidence that nobody has seen the second one yet. Every",
    "            such line carries the number of receipts behind it.",
    "",
    "Neither is auto-committed.",
    "A model may propose; proposing never makes it true — and a generator",
    "is no different.",
)


class SuggestRefused(RuntimeError):
    """A source cannot be read, or an output path must not be written."""


# ── keeping a comment on its own line ────────────────────────────────────────

def _comment_safe(text: Any) -> str:
    """One fragment of a provenance comment, guaranteed to stay on its line.

    **This is a correctness owner, not a cosmetic one.**  Every fragment of
    a comment comes out of recorded data — a tool name off ``tools.jsonl``,
    a key path off a payload, a value a server returned — and a JSON key is
    allowed to contain a newline.  One unescaped newline splits the comment
    and everything after it is parsed as YAML, which is how this generator
    could print a page that does not load while every candidate in it had
    passed :func:`~core.runtime.declarations.read_identifiers`: a key
    :func:`_only_declarable` had already dropped still reached the page
    through *another* line's comment.

    ``json.dumps`` without its quotes: ordinary names come back byte-for-
    byte (``mcp.runs_get`` is ``mcp.runs_get``) and every line break, tab
    and control character comes back as an escape.  One behaviour and no
    branch, because a function that escaped *sometimes* would be a function
    nobody could reason about at the one call site that mattered.

    It is the belt.  :meth:`Draft.problems` is the braces: it re-reads the
    rendered page and compares it to the blocks it was built from, so a
    fragment this function ever fails to protect is an error rather than a
    page.
    """
    return json.dumps(str(text))[1:-1]


# ── where a draft may not go ─────────────────────────────────────────────────

def skill_directory_above(path: Any) -> Optional[Path]:
    """The skill directory *path* would land inside, or ``None``.

    A bounded walk up from *path* looking for :data:`MANIFEST_FILE` —
    ``SKILL.md``, and the name comes from :mod:`core.skills.library`, which
    is the one module that knows a pack's shape.  A pack keeps
    ``fixtures/`` and ``templates/`` under it, so the walk climbs rather
    than checking only the parent.

    Why this exists at all: the whole feature is *proposing never makes it
    true*, and a draft written beside a manifest is one ``git add`` from
    being a declaration nobody reviewed.  The refusal is the boundary drawn
    where it can still be enforced.
    """
    here = Path(path).expanduser()
    here = here if here.is_dir() else here.parent
    try:
        here = here.resolve()
    except OSError:                               # pragma: no cover - defensive
        return None
    for _ in range(SKILL_DEPTH):
        if (here / MANIFEST_FILE).is_file():
            return here
        if here.parent == here:
            break
        here = here.parent
    return None


def _refuse_skill_path(path: Path) -> None:
    found = skill_directory_above(path)
    if found is not None:
        raise SuggestRefused(
            f"{path} is inside the skill at {found} (it holds "
            f"{MANIFEST_FILE}). This subcommand drafts; it never declares, "
            f"and a draft written into a skill is one `git add` from being "
            f"a declaration nobody reviewed. Write it somewhere else and "
            f"paste the lines you agree with.")


# ── the guess ────────────────────────────────────────────────────────────────

def kind_of(path: str) -> str:
    """A subject kind guessed from a key path.  Mechanical, and a guess.

    Last segment, without its ``[]``; then a :data:`ID_SUFFIXES` suffix off
    the end; then the last underscore-separated word; then a plural ``s``,
    because an element of ``source_assets[]`` is one asset.  That rule
    reproduces the design's own worked examples — ``job_id`` → ``job``,
    ``corpus_asset_id`` → ``asset``, ``result_ref`` → ``result``,
    ``source_assets[]`` → ``asset`` — which is the whole argument for it.

    The last of those is a **guess this generator never gets to make on its
    own**: a bare ``source_assets[]`` carries no ``_id``/``_ref`` suffix and
    no ``format: uuid``, so :func:`_handle_shaped` never nominates it and it
    reaches no page.  It is here because the rule has to be right for the
    key a plane really publishes — ``source_assets[].asset_id`` — and
    because a reader comparing this list to the design should not go looking
    for a line that cannot appear.

    It is *not* validated here.  A kind this spelling cannot carry is
    dropped by :func:`~core.runtime.declarations.read_identifiers`, which is
    the one owner of what a kind may be spelled with; a second check here
    would be the second answer.
    """
    segment = str(path or "").split(".")[-1]
    segment = segment[:-2] if segment.endswith("[]") else segment
    for suffix in ID_SUFFIXES:
        if len(segment) > len(suffix) and segment.lower().endswith(suffix):
            segment = segment[:-len(suffix)]
            break
    word = segment.rsplit("_", 1)[-1]
    if len(word) > 1 and word.endswith("s"):
        word = word[:-1]
    return word.lower()


def _handle_shaped(path: str, node: Any) -> str:
    """Why this key looks like an identity, or ``""`` for *it does not*.

    The returned string is the evidence sentence, so the reason a line is
    on the page and the reason it was kept have exactly one author.
    """
    segment = str(path or "").split(".")[-1]
    segment = segment[:-2] if segment.endswith("[]") else segment
    if isinstance(node, Mapping) and str(node.get("format") or "") == UUID_FORMAT:
        return f"`format: {UUID_FORMAT}`"
    for suffix in ID_SUFFIXES:
        if len(segment) > len(suffix) and segment.lower().endswith(suffix):
            return f"name ends in `{suffix}`"
    return ""


# ── what a suggestion is ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Evidence:
    """One reason a line is on the page, and how much of it there is.

    *count* is never decorative.  For a schema line it is how many tools
    published the thing; for an induced line it is how many receipts were
    behind it, which is the number the header's second paragraph is about.
    """

    source: str
    count: int
    detail: str

    def sentence(self) -> str:
        return f"{self.source}: {self.detail}"


@dataclass(frozen=True)
class Suggestion:
    """One drafted line: where it goes, what it says, and why."""

    block: str
    tool: str
    key: str
    value: str
    evidence: Tuple[Evidence, ...] = ()

    @property
    def slot(self) -> Tuple[str, str, str]:
        """What two suggestions must not both own — a YAML key, once."""
        return (self.block, self.tool, self.key)

    @property
    def count(self) -> int:
        """The strongest evidence count behind this line."""
        return max((item.count for item in self.evidence), default=0)

    @property
    def sources(self) -> Tuple[str, ...]:
        """Which sources proposed it, in :data:`SOURCES` order."""
        held = {item.source for item in self.evidence}
        return tuple(name for name in SOURCES if name in held)

    def comment(self) -> str:
        """The provenance comment, without its ``#``."""
        return " · ".join(item.sentence() for item in self.evidence)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "block": self.block, "tool": self.tool, "key": self.key,
            "value": self.value, "count": self.count,
            "sources": list(self.sources),
            "evidence": [{"source": item.source, "count": item.count,
                          "detail": item.detail} for item in self.evidence],
        }


@dataclass(frozen=True)
class Receipt:
    """One recorded dispatch, reduced to what this module reads."""

    tool: str
    #: ``(key path, scalar)`` for every scalar leaf of the payload, in
    #: encounter order.
    leaves: Tuple[Tuple[str, Any], ...] = ()


# ── reading the two sources ──────────────────────────────────────────────────

def read_schemas(path: Any) -> Dict[str, Dict[str, Any]]:
    """``{tool name: outputSchema}`` out of a saved ``tools/list``.

    Three shapes are taken, because three are what a person actually has
    on disk: the response itself (``{"tools": [...]}``), the bare list of
    tool descriptors, and a mapping of name → schema for somebody who has
    already pulled the schemas out.  ``outputSchema`` is the wire's
    spelling and ``output_schema`` is this framework's for the same key
    (:attr:`core.tools.mcp_client.ToolSpec.output_schema`); both are read,
    and the wire's wins where a file carries both, which is the same
    precedence :class:`~core.runtime.declarations.PlaneDeclarations` keeps.

    A tool with no output schema is **kept, empty**: it is a real tool of
    this plane that declares nothing, and the counts printed beside the
    draft say how much of the plane spoke.
    """
    raw = _load_json(path)
    # The response's envelope, and only when it holds a LIST. A plane with
    # a tool actually named `tools` would otherwise have its whole mapping
    # replaced by that one tool's schema — quietly, and with a page drawn
    # from it.
    if isinstance(raw, Mapping) and isinstance(raw.get("tools"), list):
        raw = raw.get("tools")
    found: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, Mapping):
        for name, schema in raw.items():
            tool = str(name or "").strip()
            if tool:
                found[tool] = dict(schema) if isinstance(schema, Mapping) else {}
        return found
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise SuggestRefused(
            f"{path} is not a tools/list: a mapping with `tools`, a list of "
            f"tool descriptors, or a mapping of name -> outputSchema")
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        tool = str(item.get("name") or "").strip()
        if not tool:
            continue
        schema = item.get("outputSchema")
        if not isinstance(schema, Mapping):
            schema = item.get("output_schema")
        found[tool] = dict(schema) if isinstance(schema, Mapping) else {}
    return found


def _load_json(path: Any) -> Any:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SuggestRefused(f"--schemas: {exc}") from exc
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SuggestRefused(f"{path} is not JSON: {exc}") from exc


def _leaves(node: Any, prefix: str = "",
            depth: int = MAX_DEPTH) -> Iterable[Tuple[str, Any]]:
    """``(key path, scalar)`` for every scalar leaf of a payload.

    Paths are spelled the way a declaration is — dotted, with ``[]`` for
    *every element of this list* — because a path this module printed that
    :mod:`core.runtime.declarations` could not walk would be a line that
    reads as though it binds.  Bounded at
    :data:`~core.runtime.grounding.MAX_DEPTH`, which is that module's
    answer to *how deep a payload is walked* and not a second one.
    """
    if depth <= 0:
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            yield from _leaves(value, f"{prefix}.{name}" if prefix else name,
                               depth - 1)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _leaves(item, f"{prefix}[]" if prefix else "", depth - 1)
        return
    if prefix:
        yield prefix, node


def read_receipts(roots: Sequence[Any]) -> List[Receipt]:
    """Every recorded dispatch under each of *roots*, in a stable order.

    ``run_shaped`` finds the run directories — the harness's one bounded
    walk for that — and a root that does not exist contributes nothing
    rather than raising: a corpus that is half there is still a corpus, and
    the counts say how much of it was read.

    The catalogue line (``call`` 0) is skipped: it is the plane a run was
    offered, not a call it made, and reading it as a receipt would put a
    tool's own input schema into the induced half.
    """
    found: List[Receipt] = []
    for root in roots:
        for directory in run_shaped(Path(root)):
            log = directory / TOOL_LOG
            if not log.is_file():
                continue
            try:
                lines = log.read_text(encoding="utf-8").splitlines()
            except OSError:                       # pragma: no cover - defensive
                continue
            for line in lines:
                receipt = _receipt(line)
                if receipt is not None:
                    found.append(receipt)
    return found


def _receipt(line: str) -> Optional[Receipt]:
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, Mapping):
        return None
    tool = str(record.get("tool") or "").strip()
    if not tool:                                  # the catalogue line
        return None
    result = record.get("result")
    text = (result.get("stdout") if isinstance(result, Mapping)
            else result)
    leaves: List[Tuple[str, Any]] = []
    for block in json_blocks(text):
        leaves += list(_leaves(block))
    return Receipt(tool=tool, leaves=tuple(leaves))


# ── the schema half ──────────────────────────────────────────────────────────

def _schema_paths(schema: Any, prefix: str = "",
                  depth: int = MAX_DEPTH) -> List[Tuple[str, Mapping]]:
    """``(key path, property schema)`` for everything a schema declares.

    Through :func:`~core.runtime.declarations.properties_of`, so *does this
    schema say anything* has the one answer it has everywhere else: a bare
    ``{"type": "object"}`` contributes nothing here exactly as it declares
    nothing there.
    """
    out: List[Tuple[str, Mapping]] = []
    if depth <= 0:
        return out
    # In the schema's own order, deliberately. The page's order has ONE
    # owner — the sort in :func:`suggest` — and a second sort here would be
    # a second answer to *what order is this page in* that no test could
    # ever tell apart from the first.
    for name, node in properties_of(schema).items():
        key = str(name)
        path = f"{prefix}.{key}" if prefix else key
        body = node if isinstance(node, Mapping) else {}
        out.append((path, body))
        out += _schema_paths(body, path, depth - 1)
        items = body.get("items")
        if isinstance(items, Mapping):
            out += _schema_paths(items, f"{path}[]", depth - 1)
    return out


def from_schemas(schemas: Mapping[str, Any]) -> List[Suggestion]:
    """The lines a plane's own contract supports.  Better grounded, and
    still suggestions: *identity* is a semantic claim only a platform can
    own, and an ``enum`` is a statement about a value's domain and not
    about how many of them one entity holds.
    """
    out: List[Suggestion] = []
    walked = {tool: _schema_paths(schemas.get(tool))
              for tool in sorted(schemas)}

    # `cardinality:` is a statement about a FIELD, and the block is one per
    # pack rather than one per tool — so an enum met under three tools is
    # one line carrying three, and not three lines the loader would refuse
    # as one field declared twice.
    enums: Dict[str, List[Tuple[str, int]]] = {}
    for tool in sorted(walked):
        for path, body in walked[tool]:
            values = body.get("enum")
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                continue
            if len(values) < 2:
                # A one-value enum says the key is a constant, which is a
                # statement about the value and not about multiplicity.
                continue
            enums.setdefault(_field_of(path), []).append((tool, len(values)))
    for name in sorted(enums):
        seen = sorted(enums[name])
        where = ", ".join(f"{_comment_safe(tool)} ({size})"
                          for tool, size in seen)
        out.append(Suggestion(
            block=CARDINALITY, tool="", key=name, value="one",
            evidence=(Evidence(SCHEMA, len(seen),
                               f"enum in the outputSchema of {where}"),)))

    # An envelope key is one every tool of the plane carries. `result_ref`
    # is the design's own example, and a key like it belongs in `defaults:`
    # rather than repeated under every entry — which is what `defaults:`
    # exists for.
    shared = _shared_paths(walked)
    speaking = sum(1 for tool in walked if walked[tool])
    for path in sorted(shared):
        node = shared[path]
        why = _handle_shaped(path, node)
        if not why:
            # A key every tool carries and nothing says is a handle is an
            # envelope field, not an identity. `handling_summary` is on
            # every one of a real deployment's results and joins nothing.
            continue
        out.append(Suggestion(
            block=DEFAULT_IDENTIFIER, tool="", key=path, value=kind_of(path),
            evidence=(Evidence(SCHEMA, speaking,
                               f"{why}, in the outputSchema of all "
                               f"{speaking} tools that publish one"),)))

    for tool in sorted(walked):
        for path, body in walked[tool]:
            if path in shared:
                continue
            why = _handle_shaped(path, body)
            if not why:
                continue
            out.append(Suggestion(
                block=IDENTIFIER, tool=tool, key=path, value=kind_of(path),
                evidence=(Evidence(
                    SCHEMA, 1,
                    f"{why}, in the outputSchema of "
                    f"{_comment_safe(tool)}"),)))
    return out


def _field_of(path: str) -> str:
    """The bare field name a path ends in — what ``harvest_fields`` calls
    it, and therefore what a ``cardinality:`` line has to say."""
    segment = str(path or "").split(".")[-1]
    return segment[:-2] if segment.endswith("[]") else segment


def _shared_paths(walked: Mapping[str, Sequence[Tuple[str, Mapping]]]
                  ) -> Dict[str, Mapping]:
    """The key paths every tool *that publishes a shape* declares.

    Two bounds, and each is a case that would otherwise be wrong:

    * a plane of one tool has no envelope — *every tool carries it* is a
      sentence about a plane, and one tool is not one;
    * a tool whose schema is a bare object does not **veto** the envelope.
      Most of a real deployment's adapters publish exactly that
      (:func:`~core.runtime.declarations.properties_of` is the one owner of
      *this schema declares nothing*), and intersecting an empty set into
      the others would delete the envelope from every plane that has one.
    """
    speaking = {tool: paths for tool, paths in walked.items() if paths}
    if len(speaking) < 2:
        return {}
    common: Optional[set] = None
    bodies: Dict[str, Mapping] = {}
    for tool in sorted(speaking):
        here = {path for path, _ in speaking[tool]}
        for path, body in speaking[tool]:
            bodies.setdefault(path, body)
        common = here if common is None else (common & here)
    return {path: bodies[path] for path in sorted(common or ())}


# ── the induced half ─────────────────────────────────────────────────────────

def from_observations(receipts: Sequence[Receipt], *,
                      min_receipts: int = MIN_RECEIPTS) -> List[Suggestion]:
    """The lines recorded receipts *suggest*, with the count that induced
    each one.

    Two inductions, and both are stated as inductions:

    * a field that held **one** value in every receipt it appeared in is a
      ``one`` candidate — evidence: the number of receipts.  It is not a
      proof, because the receipts nobody recorded are the ones that would
      have contained the second value;
    * a string seen under **two different tools' keys** is a cross-receipt
      identifier candidate — evidence: the value and both places.  Bounded
      by :data:`DISTINCT_SHARE`, because a key whose values repeat across
      receipts is a status and not an identity, and a draft that proposed
      ``state`` as a join key would manufacture the contradictions the
      whole linking design exists to avoid.
    """
    per_field: Dict[str, List[int]] = {}          # field -> distinct per receipt
    per_path: Dict[Tuple[str, str], Dict[str, int]] = {}
    values: Dict[str, Dict[Tuple[str, str], int]] = {}

    for receipt in receipts:
        here: Dict[str, set] = {}
        for path, value in receipt.leaves:
            here.setdefault(_field_of(path), set()).add(_hashable(value))
            slot = (receipt.tool, path)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                per_path.setdefault(slot, {})
                per_path[slot][text] = per_path[slot].get(text, 0) + 1
                values.setdefault(text, {})
                values[text][slot] = values[text].get(slot, 0) + 1
        for name, seen in here.items():
            per_field.setdefault(name, []).append(len(seen))

    out: List[Suggestion] = []
    for name in sorted(per_field):
        counts = per_field[name]
        if len(counts) < min_receipts or max(counts) != 1:
            continue
        out.append(Suggestion(
            block=CARDINALITY, tool="", key=name, value="one",
            evidence=(Evidence(OBSERVED, len(counts),
                               f"{len(counts)} receipts, one value each "
                               f"(induced: no second value has been seen, "
                               f"which is not the same as none existing)"),)))

    identities = {slot for slot, seen in per_path.items() if _varied(seen)}
    joins: Dict[Tuple[str, str], Tuple[str, Tuple[str, str]]] = {}
    for text in sorted(values):
        slots = sorted(slot for slot in values[text] if slot in identities)
        if len({tool for tool, _ in slots}) < 2:
            continue
        for slot in slots:
            other = next(s for s in slots if s != slot)
            joins.setdefault(slot, (text, other))
    for slot in sorted(joins):
        tool, path = slot
        text, (other_tool, other_path) = joins[slot]
        seen = per_path[slot]
        out.append(Suggestion(
            block=IDENTIFIER, tool=tool, key=path, value=kind_of(path),
            evidence=(Evidence(
                OBSERVED, sum(seen.values()),
                f"'{_comment_safe(text)}' seen under "
                f"{_comment_safe(tool)}.{_comment_safe(path)} and "
                f"{_comment_safe(other_tool)}.{_comment_safe(other_path)}; "
                f"{len(seen)} distinct value(s) "
                f"in {sum(seen.values())} observation(s) (induced)"),)))
    # `observation(s)` and not `receipt(s)`: one receipt carrying a list
    # holds this path once per element, and a count that called those three
    # receipts would be a figure the header's promise does not cover.
    return out


def _hashable(value: Any) -> Any:
    """A scalar as something a set can hold.  Payload leaves are scalars by
    construction, and a value that somehow is not is compared by its text
    rather than crashing a draft."""
    try:
        hash(value)
    except TypeError:                             # pragma: no cover - defensive
        return repr(value)
    return value


def _varied(seen: Mapping[str, int]) -> bool:
    """Whether a key's values look like identities rather than a status.

    See :data:`DISTINCT_SHARE`.  Two or more distinct values, and enough of
    them relative to how often the key was seen.
    """
    observations = sum(seen.values())
    return len(seen) >= 2 and len(seen) >= DISTINCT_SHARE * observations


# ── the draft ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Draft:
    """One page of suggestions, and everything needed to render it twice.

    Deterministic by construction: the suggestions are sorted, no clock is
    read and nothing is sampled, so the same corpus in any order produces
    the same bytes.
    """

    suggestions: Tuple[Suggestion, ...] = ()
    tools_read: int = 0
    schemas_read: int = 0
    receipts_read: int = 0

    def __bool__(self) -> bool:
        return bool(self.suggestions)

    def of(self, block: str) -> Tuple[Suggestion, ...]:
        return tuple(item for item in self.suggestions if item.block == block)

    # ── what the loaders would see ──────────────────────────────────────

    def as_mapping(self) -> Dict[str, Any]:
        """The two blocks, as the two loaders take them.

        The renderer writes *this*, so the YAML on the page and the mapping
        the tests hand to :class:`~core.runtime.cognition.RulePack` and
        :class:`~core.runtime.declarations.ToolsBlock` are one object and
        cannot drift.
        """
        cognition: Dict[str, Any] = {}
        cardinality = {item.key: item.value for item in self.of(CARDINALITY)}
        if cardinality:
            cognition[CARDINALITY] = cardinality

        tools: Dict[str, Any] = {}
        defaults = {item.key: {"kind": item.value}
                    for item in self.of(DEFAULT_IDENTIFIER)}
        if defaults:
            tools["defaults"] = {"identifiers": defaults}
        entries: List[Dict[str, Any]] = []
        for tool in sorted({item.tool for item in self.of(IDENTIFIER)}):
            identifiers = {item.key: {"kind": item.value}
                           for item in self.of(IDENTIFIER)
                           if item.tool == tool}
            entries.append({"name": tool, "identifiers": identifiers})
        if entries:
            tools["entries"] = entries
        return {"cognition": cognition, "tools": tools}

    def problems(self) -> Tuple[str, ...]:
        """What the real doors say about this draft, in their own words.

        Asked of :class:`~core.runtime.cognition.RulePack` and
        :class:`~core.runtime.declarations.ToolsBlock` rather than of a
        validator written here: a generator that checked its own work with
        its own rules would pass every draft it could produce, including
        the ones a manifest will refuse.

        **And then asked of the PAGE.**  The blocks are what this object
        holds; the page is what a person pastes, and the two are not the
        same artefact.  A comment fragment that broke its own line used to
        make the second un-loadable while the first passed every door —
        every candidate in it had gone through ``read_identifiers``, and a
        key :func:`_only_declarable` had dropped still reached the page
        inside *another* line's comment.  So the rendered bytes are read
        back and compared to the mapping they were built from, which is the
        only check that can see that class of fault at all.

        Stands down, and says so through :func:`page_check_stood_down`,
        where pyyaml is not installed: it is an optional extra here, and a
        generator that refused to draft because it could not re-read its
        own page would be worse than one that drafts and says what it could
        not verify.
        """
        # Imported here and not at the top: `core.runtime.cognition` pulls
        # the kernel in, and a harness subcommand that reads two files
        # should not pay for the cognitive core to print its `--help`.
        from core.runtime.cognition import RulePack

        blocks = self.as_mapping()
        found: List[str] = []
        try:
            RulePack.from_mapping(blocks["cognition"])
        except ValueError as exc:
            found.append(f"the `cognition:` block: {exc}")
        try:
            ToolsBlock.from_mapping(blocks["tools"])
        except DeclarationError as exc:
            found.append(f"the `tools:` block: {exc}")

        yaml = _yaml()
        if yaml is None:
            return tuple(found)
        page = self.to_yaml()
        try:
            reread = yaml.safe_load(page)
        except Exception as exc:                  # noqa: BLE001 - any parse
            # `Exception` and not `yaml.YAMLError`: the point of this check
            # is the fault nobody predicted, and a narrow `except` here
            # would be this guard deciding in advance which of those it is
            # willing to notice.
            found.append(f"the rendered page is not YAML: {exc}")
            return tuple(found)
        if _as_blocks(reread) != blocks:
            found.append(
                f"the rendered page parses back to something other than the "
                f"blocks it was built from: {_as_blocks(reread)!r} where "
                f"{blocks!r} was drafted")
        return tuple(found)

    # ── rendering ───────────────────────────────────────────────────────

    def to_yaml(self) -> str:
        """The draft, with one provenance comment per line.

        Hand-rendered rather than dumped, because a dumper drops comments
        and the comments are the feature: a line without its evidence is a
        declaration, and this page has none of those.  Every scalar goes
        through :func:`json.dumps`, which is a YAML double-quoted scalar —
        so a key spelled ``on`` stays the string ``on`` rather than becoming
        the YAML 1.1 boolean this project has already been bitten by.
        """
        lines = [f"# {line}".rstrip() for line in HEADER]
        lines.append("#")
        lines.append(f"# read: {self.tools_read} tool(s) from a saved "
                     f"tools/list ({self.schemas_read} with a published "
                     f"outputSchema), {self.receipts_read} recorded "
                     f"receipt(s).")
        lines.append("")

        cardinality = self.of(CARDINALITY)
        lines.append("cognition:")
        if cardinality:
            lines.append("  cardinality:")
            for item in cardinality:
                lines.append(f"    {_scalar(item.key)}: {_scalar(item.value)}"
                             f"   # {item.comment()}")
        else:
            lines.append("  # nothing suggested a `one`.")
        lines.append("")

        defaults = self.of(DEFAULT_IDENTIFIER)
        entries = self.of(IDENTIFIER)
        lines.append("tools:")
        if defaults:
            lines.append("  defaults:")
            lines.append("    identifiers:")
            for item in defaults:
                lines.append(
                    f"      {_scalar(item.key)}: {{kind: {_scalar(item.value)}}}"
                    f"   # {item.comment()}")
        if entries:
            lines.append("  entries:")
            for tool in sorted({item.tool for item in entries}):
                lines.append(f"    - name: {_scalar(tool)}")
                lines.append("      identifiers:")
                for item in entries:
                    if item.tool != tool:
                        continue
                    lines.append(
                        f"        {_scalar(item.key)}: "
                        f"{{kind: {_scalar(item.value)}}}"
                        f"   # {item.comment()}")
        if not defaults and not entries:
            lines.append("  # nothing looked like an identifier.")
        return "\n".join(lines) + "\n"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tools_read": self.tools_read,
            "schemas_read": self.schemas_read,
            "receipts_read": self.receipts_read,
            "header": list(HEADER),
            "suggestions": [item.as_dict() for item in self.suggestions],
            "blocks": self.as_mapping(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)


def _scalar(value: Any) -> str:
    """One YAML scalar, always quoted.  See :meth:`Draft.to_yaml`."""
    return json.dumps(str(value))


def _yaml():
    """pyyaml, or ``None``.  The optional extra, asked for the same way
    :func:`core.runtime.skills._require_yaml` asks — except that nothing
    here *needs* it, so ``None`` is an answer and not a refusal."""
    try:
        import yaml
    except ImportError:                           # pragma: no cover - extra
        return None
    return yaml


def page_check_stood_down() -> bool:
    """Whether :meth:`Draft.problems` could not re-read the page it drew.

    A separate question from *are there problems*, and asked separately so
    that "no problems" and "no problems I was able to look for" are never
    the same answer on a console.
    """
    return _yaml() is None


def _as_blocks(loaded: Any) -> Dict[str, Any]:
    """A parsed page as the mapping :meth:`Draft.as_mapping` would have
    built, so the two can be compared at all.

    One normalisation, and it earns its place: a block whose body is a
    comment (``cognition:`` with nothing suggested under it) parses as
    ``None`` and is built here as ``{}``.  Both loaders take both — that is
    checked — so the difference is a fact about pyyaml and not about the
    draft, and a comparison that called it a fault would fire on every
    empty page.
    """
    body = loaded if isinstance(loaded, Mapping) else {}
    return {name: dict(body.get(name) or {}) for name in ("cognition", "tools")}


# ── putting the two halves together ──────────────────────────────────────────

def suggest(*, schemas: Optional[Mapping[str, Any]] = None,
            receipts: Sequence[Receipt] = (),
            min_receipts: int = MIN_RECEIPTS) -> Draft:
    """Both sources into one draft, schema-first and sorted.

    **Where both propose one key, the schema's sentence leads and the
    induced one is kept beside it.**  Not dropped: two sources agreeing is
    worth more than either, and a reader pruning the page should be able to
    see that they did.  Where they disagree about a *value* — which cannot
    happen today, because ``one`` is the only cardinality drafted and
    :func:`kind_of` is a pure function of the key — the schema's value
    stands and the induced sentence says what it would have said instead,
    so the page can never carry one key twice.
    """
    schemas = dict(schemas or {})
    proposed = (from_schemas(schemas)
                + from_observations(receipts, min_receipts=min_receipts))

    merged: Dict[Tuple[str, str, str], Suggestion] = {}
    for item in proposed:
        held = merged.get(item.slot)
        if held is None:
            merged[item.slot] = item
            continue
        extra = item.evidence
        if item.value != held.value:
            extra = tuple(
                Evidence(one.source, one.count,
                         f"would have said '{_comment_safe(item.value)}' "
                         f"instead — {one.detail}")
                for one in item.evidence)
        merged[item.slot] = Suggestion(
            block=held.block, tool=held.tool, key=held.key, value=held.value,
            evidence=held.evidence + extra)

    kept = _only_declarable(merged.values())
    return Draft(
        suggestions=tuple(sorted(kept, key=lambda item: item.slot)),
        tools_read=len(schemas),
        schemas_read=sum(1 for name in schemas
                         if properties_of(schemas[name])),
        receipts_read=len(receipts))


def _only_declarable(items: Iterable[Suggestion]) -> List[Suggestion]:
    """Every suggestion the real reader will take, and no others.

    :func:`~core.runtime.declarations.read_identifiers` is asked about each
    identifier candidate — the same function the wire and the manifest go
    through — so a key path or a guessed kind it will not take is dropped
    here rather than printed onto a page whose promise is that it loads.
    A payload can carry a key called ``2024`` or ``a b``; a declaration
    cannot name one.
    """
    kept: List[Suggestion] = []
    for item in items:
        if item.block == CARDINALITY:
            if str(item.key).strip():
                kept.append(item)
            continue
        problems: List[str] = []
        read = read_identifiers({item.key: {"kind": item.value}},
                                "a draft", problems)
        if not problems and read:
            kept.append(item)
    return kept


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``suggest-pack`` on :func:`core.eval.run._parser`'s
    subparsers.

    From here, the way ``measure``, ``ablation``, ``extraction``,
    ``corpus``, ``registry`` and ``context`` register themselves.  Without
    ``common``: a draft is read off a saved schema file and recorded
    receipts, so there is no suite to grade, no half to hold out and **no
    model to spend** — it is the sixth subcommand that needs none.
    """
    parser = subs.add_parser(
        "suggest-pack",
        help="draft a `cognition:`/`tools:` pack from a saved tools/list "
             "and recorded receipts — advisory, never loaded")
    parser.add_argument("--schemas", type=Path, metavar="PATH",
                        help="a saved MCP tools/list response; the better "
                             "grounded half, because the plane declared it")
    parser.add_argument("--runs", action="append", default=[], type=Path,
                        metavar="DIR",
                        help="a run directory or a directory of them, read "
                             "for tools.jsonl; repeatable. The INDUCED half")
    parser.add_argument("--min-receipts", type=int, default=MIN_RECEIPTS,
                        metavar="N",
                        help=f"how many receipts a field must be seen in "
                             f"before it is drafted at all (default "
                             f"{MIN_RECEIPTS})")
    parser.add_argument("--out", type=Path, metavar="FILE",
                        help="write the draft here as well as to stdout; "
                             "refused for any path inside a skill")
    parser.add_argument("--json", action="store_true",
                        help="print the suggestions as JSON instead of the "
                             "draft")
    return parser


def from_args(args: argparse.Namespace) -> int:
    """``suggest-pack`` as :func:`core.eval.run.main` reaches it."""
    if args.schemas is None and not args.runs:
        print("suggest-pack: nothing to read — pass --schemas PATH (a saved "
              "tools/list) or --runs DIR (recorded receipts), or both",
              file=sys.stderr)
        return 2
    try:
        if args.out is not None:
            # Before anything is read, because a refusal that arrives after
            # the work is a refusal that cost what it was meant to save.
            _refuse_skill_path(args.out)
        schemas = ({} if args.schemas is None
                   else read_schemas(args.schemas))
        receipts = read_receipts(args.runs)
    except SuggestRefused as exc:
        print(f"suggest-pack: {exc}", file=sys.stderr)
        return 2

    draft = suggest(schemas=schemas, receipts=receipts,
                    min_receipts=args.min_receipts)
    problems = draft.problems()
    if problems:
        # Not a page. A draft the loaders refuse is this module's bug, and
        # printing it anyway would hand somebody lines to paste that their
        # manifest will then reject at the door.
        print("suggest-pack: the draft does not load, which is a fault in "
              "this generator and not in your plane:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    if page_check_stood_down():
        # Said out loud, because "no problems" and "no problems I could
        # look for" must never read the same on a console.
        print("suggest-pack: pyyaml is not installed, so the rendered page "
              "could not be read back and checked against the blocks it was "
              "drawn from; the two loaders passed it. "
              "pip install 'judais-lobi[mission]'", file=sys.stderr)

    text = draft.to_json() if args.json else draft.to_yaml()
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.out, draft.to_yaml())

    if not draft.tools_read and not draft.receipts_read:
        print("suggest-pack: no tool declared a shape and no receipt was "
              "recorded — a draft is read off evidence, and there was none",
              file=sys.stderr)
        return 2
    if not draft:
        print("suggest-pack: the sources were read and suggested nothing. "
              "That is an answer: no enum, no id-shaped key, no value "
              "shared across two tools.", file=sys.stderr)
    return 0
