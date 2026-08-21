# core/runtime/grounding.py — does the answer cite anything that exists?

"""Score a mission answer against what its own tools returned.

The coding side of this package has :class:`~core.judge.judge.CompositeJudge`:
tiers with opinions, a composite, and — the part that matters — a tier
that could not answer says so instead of guessing a midpoint.  The
mission side had nothing.  Citation discipline was one sentence in the
protocol prompt and one rule in a persona file, and both of those are
requests.  An invented identifier looks exactly like a real one:
``labels.7a19c4e2.taxonomy9f.b31c`` is either the label set the run
consumed or a plausible arrangement of hex, and no reader can tell which
from the answer alone.

So the check is mechanical: **every identifier-shaped token in the
answer has to appear in a tool output of this run.**  Not of any run, not
of the model's training — this one, in this transcript, in a result the
store kept whole.

What is *not* here is the grammar.  What an identifier looks like, which
literals to ignore, whether figures are checked too — all of that is
content, and it arrives from the skill manifest's ``grounding:`` block.
A validator built without one has no opinion and says so; it never
reports an answer as grounded because it had no pattern to fail it with.
That is the ``UNKNOWN``-not-``0.5`` lesson from the judge, and the
consequence of getting it wrong here is larger: a fabricated
"grounded" is a governance claim.

The remedy is graduated on purpose.  An unsupported claim gets **one
repair turn** naming the exact tokens, because the commonest cause is a
transcription slip the model can fix by looking again.  A second failure
does not get another turn and does not get suppressed: the answer is
kept and an explicit caveat is appended naming what could not be
supported.  Deleting the answer would hide the finding; passing it
silently would launder it.

**A check reports three states, not two.**  Measured 10 Aug 2026, the
first run with the manifests' ``grounding:`` blocks switched on: six of
the first ten missions reported ``grounded: identifiers — 0/0 supported
by a tool result in this run``, among them ``what_shape_is_the_catalogue``
and ``what_can_this_pool_run``, both of which should have been naming
assets.  *The control was satisfied by silence* — a check that extracted
zero tokens had nothing unsupported, so it passed.  A model that learns
that writes no identifiers.

So the verdict is :data:`NOTHING_CONSIDERED`, :data:`SUPPORTED` or
:data:`UNSUPPORTED` (and :data:`UNCONFIGURED` for a check that could not
run at all), and *whether saying nothing is acceptable* is not the
harness's call.  ``absence_is_an_answer`` is a legitimate mission whose
correct answer cites nothing; ``run_inspection`` drafting a finding with
no figures in it is a failure.  The difference is content, like the
grammar, so it arrives in the manifest as ``must_cite:`` — a per-check
minimum the skill declares for itself.

The other half of that is :class:`ClaimGroundingCheck`, because a
minimum on prose only asks for more prose.  A skill whose figures matter
requires them a second time as a **claim table** — ``{"value": 0.7446,
"path": "gate.confidence"}`` — and those are verified by walking the path
into the payload the mission received rather than by matching text.  With
a floor of three claims, *say nothing checkable* is no longer the cheapest
way past a fabrication check.
"""

from __future__ import annotations

import dataclasses
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import (
    Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

from core.runtime.reading import ReadingCheck, ReadingReport
from core.runtime.results import SourcedEvidence, walk_path
from core.runtime.skills import code_plane_tools
from core.tools.descriptors import same_tool, tool_key


#: ``prompt -> reply``.  What a tier that needs a model is handed, and the
#: whole of what it may know about one: no client, no model name, no
#: streaming.  :class:`~core.runtime.reading.ReadingCheck` takes the same
#: shape for the same reason — a tier that could reach a client could pick a
#: model, and which model verifies a governed draft is a deployment's
#: decision and not a check's.
Ask = Callable[[str], str]


class GroundingMisdeclared(TypeError):
    """A check subclass is unusable, with every reason in one message."""


# ---------------------------------------------------------------------------
# The verdicts.  Three for a check that ran, one for a check that did not.
# ---------------------------------------------------------------------------

#: The check could not run — no grammar for it in the manifest.  Not a pass
#: and not a failure: no opinion.  ``UNKNOWN``, not ``0.5``.
UNCONFIGURED = "unconfigured"

#: The check ran and the answer stated **nothing of its kind**.  Whether
#: that is acceptable is the skill's declaration (``must_cite``), not this
#: module's: reporting a corpus is not held is a correct answer with no
#: identifiers in it, and drafting a finding with no figures is not.
NOTHING_CONSIDERED = "nothing_considered"

#: The check ran, the answer stated things of its kind, and every one of
#: them came back from a tool in this run.  **The only verdict that is a
#: positive result**, and the one ``0/0`` used to be indistinguishable from.
SUPPORTED = "supported"

#: At least one stated thing appears in no tool output of this run.
UNSUPPORTED = "unsupported"

#: The closed vocabulary, so a consumer can assert it knows all of them.
VERDICTS: Tuple[str, ...] = (
    UNCONFIGURED, NOTHING_CONSIDERED, SUPPORTED, UNSUPPORTED,
)

#: ``must_cite: true`` means every configured check, and is stored as a
#: minimum against this name.  An explicit check name always wins over it.
ANY_CHECK = "*"

#: The fenced block a claim table is written in.  Module level because two
#: checks need it and for opposite reasons: :class:`ClaimGroundingCheck`
#: reads it, and every *prose* check has to not — a table of
#: ``{"path": "gate.confidence"}`` is full of dotted lower-case tokens that
#: an identifier grammar matches, and a report that flags a field path the
#: skill asked for is a report its reader learns to skip.
CLAIM_BLOCK = re.compile(r"```claims\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _string_list(raw: Any) -> Tuple[str, ...]:
    """A manifest list of strings, or ``()``.  A bare string is one item."""
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Sequence):
        return ()
    return tuple(str(item).strip() for item in raw if str(item or "").strip())

#: A fenced code block, any language tag or none.  Non-greedy, so two
#: blocks in one answer are two matches and the prose between them keeps
#: full scrutiny.
FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)

#: Inline code.  Bounded to one line: a stray backtick in prose must not
#: swallow the rest of the answer as "code".
INLINE_CODE = re.compile(r"`[^`\n]+`")


def prose_only(answer: str) -> str:
    """*answer* with its code removed, leaving the prose the checks read.

    **Code is not a claim.**  Prose asserts facts about the world and has
    to ground in a tool result of this run; code is a proposed
    computation, and its grounding is the result of *running* it — which,
    when it happens, arrives as a tool result and grounds the prose that
    cites it (see ``MissionResultStore.evidence_texts``).

    Measured August 2026 on TAIPAN's hosted mission pane (gpt-oss-20b):
    asked to "plot sin, cos and tan using python", the agent wrote correct
    matplotlib code and the validator flagged the ANSWER as fabricated —
    ``np.linspace`` and ``plt.subplots`` match the dotted identifier
    grammar exactly the way an invented asset id does, and ``0.01``-style
    literals match the figure grammar the way an invented run score does.
    No tool returns matplotlib's API, so every such token was reported as
    invented and a correct answer shipped under a "not supported by its
    tools" banner.  A check that flags working code teaches its reader to
    skip the report, which un-catches the fabrications it exists for.

    An unterminated fence is still code: the model opened a block and ran
    out of tokens before closing it, and everything after the opening
    fence is the code it was writing, not prose that resumed.  Flagging a
    truncated script's identifiers would reintroduce the failure above in
    exactly the messiest transcripts.
    """
    return INLINE_CODE.sub(" ", unfenced(answer))


def unfenced(answer: str) -> str:
    """*answer* with its fenced code removed and its inline code kept.

    The half of :func:`prose_only` that every check wants, split out
    because two of them want **only** that half: a backticked field name
    is the grammar :class:`FieldAttributionCheck` reads, and a backticked
    tool name is the grammar :class:`SubjectGroundingCheck` reads, and
    both would be deleted before extraction by the inline-code pass.
    One owner of the fence rule — including the unterminated one — so a
    check that keeps its backticks cannot also quietly keep a truncated
    script.
    """
    text = FENCED_CODE.sub(" ", answer or "")
    head, fence, _unclosed = text.partition("```")
    if fence:
        text = head
    return text


#: Characters a language model reaches for in prose and a payload never
#: contains, mapped to the ASCII a tool result is written in. The soft hyphen
#: is deleted rather than mapped: it is an invisible line-break hint and not a
#: hyphen anybody wrote.
#:
#: Measured 10 August 2026 on ``what_can_this_pool_run``: the answer carried
#: **17** U+2011 non-breaking hyphens — ``paraphrase‑multilingual‑mpnet‑base‑v2``
#: for a model whose id is spelled with U+002D everywhere in the catalogue.
#: A substring test between those two strings fails on every one of them, so
#: an identifier read correctly out of a tool result and typed back with
#: prettier punctuation is reported as invented. That is the worst possible
#: false positive: it teaches the reader that the check is noise, on the one
#: mission where the answer was right.
_TYPOGRAPHIC = {
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2015: "-", 0x2212: "-", 0x00AD: "",
    0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
    0x00A0: " ", 0x202F: " ", 0x2009: " ",
}


def typographic_plain(text: str) -> str:
    """*text* with a model's punctuation replaced by a payload's.

    Applied to the answer **and** to the evidence, in ``GroundingCheck.check``,
    so that every check compares content rather than typography and none of
    them can be written to forget. Normalising only one side would be worse
    than normalising neither: it would turn a real match into a miss in
    exactly the direction that flatters the check.
    """
    return str(text or "").translate(_TYPOGRAPHIC)


def _flattened(text: Any) -> str:
    """One evidence text, typography flattened, provenance kept.

    :func:`typographic_plain` returns a plain ``str`` — every ``str``
    method does — so the one line in :meth:`GroundingCheck.check` that
    normalises the evidence is also the line where a
    :class:`~core.runtime.results.SourcedEvidence` would quietly become an
    ordinary string and a check would stop being able to ask which call
    produced it.  Rebuilding it here keeps the normalisation exactly where
    the class docstring says it happens — once, before extraction, on both
    sides — and costs every other check nothing: what they receive is
    still a ``str`` with the same characters in it.

    Evidence with no provenance stays a plain ``str``, which is what a
    library caller hands in and what the staged path unions together.
    """
    plain = typographic_plain(str(text or ""))
    tool = getattr(text, "tool", "")
    arguments = getattr(text, "arguments", "")
    if not (tool or arguments or getattr(text, "sent", False)):
        return plain
    return SourcedEvidence(plain, tool=tool,
                           sent=bool(getattr(text, "sent", False)),
                           arguments=typographic_plain(str(arguments)))


@dataclass(frozen=True)
class Plane:
    """A named family of tools, and the phrases that claim to have used it.

    **Data, not code.**  Which tools constitute "the SDK" on a platform, and
    which sentences an answer writes when it says it used one, are both
    content — a framework that hard-coded either would be deciding what a
    deployment's planes are called.  The manifest declares them; this is the
    shape they arrive in.
    """

    name: str
    #: Tool names, matched with :func:`plane_matches` so every spelling of an
    #: offered tool counts and a trailing ``*`` is a family (``catalog_*``).
    tools: Tuple[str, ...] = ()
    #: Phrases whose presence in the prose is a claim to have used this plane.
    #: Matched case-insensitively as substrings, because a model writes
    #: "I used the SDK" and "we used the SDK to" and both are the claim.
    claims: Tuple[str, ...] = ()


def plane_matches(spec: str, called: str) -> bool:
    """Whether the tool *called* is one the plane spec *spec* names.

    Two forms, and the wildcard is the reason this is not just
    :func:`~core.tools.descriptors.same_tool`.  An exact name is compared
    with ``same_tool``, so every spelling and namespacing of one tool
    counts.  A trailing ``*`` names a family — ``catalog_*`` is every
    catalogue tool a server advertises, whatever its suffix — and matches
    on the reduced key, so ``mcp.catalog_search_assets`` is in the
    ``catalog_*`` family and ``xcatalog_search`` is not.
    """
    spec = str(spec or "").strip()
    if not spec.endswith("*"):
        return same_tool(spec, called)
    stem = tool_key(spec.rstrip("*"))
    key = tool_key(called)
    if not stem or not key:
        return False
    return (key == stem or key.startswith(f"{stem}.")
            or key.endswith(f".{stem}") or f".{stem}." in key)


@dataclass(frozen=True)
class GroundingConfig:
    """The content half: what counts as a claim, and how strict to be.

    Built from a skill manifest's ``grounding:`` block.  Every field is
    optional and an absent one disables the check that needs it — the
    harness supplies no default grammar, because a default grammar is
    the harness deciding what a platform's identifiers look like.
    """

    #: Regex matching an identifier-shaped token in the answer.
    identifier_pattern: Optional[str] = None
    #: Regex matching a figure, when figures are checked at all.
    number_pattern: Optional[str] = None
    #: Whether the answer carries a ``claims`` table — every figure emitted
    #: a second time as ``{"value": ..., "path": ...}`` into what a tool
    #: returned. The skill's ``output_format`` has to ask for one; this is
    #: the half that checks it arrived and is true.
    claim_table: bool = False
    #: Literals that match a pattern but are not claims — placeholders,
    #: field names, the platform's own word for "none".
    #:
    #: **Tool names do not belong here.** They are derived instead, from
    #: the set the mission actually offered — see :meth:`offering`.
    ignore: Tuple[str, ...] = ()
    #: The tools this mission offered, as the bus resolved them. Set by
    #: :meth:`offering` at run time and never authored in a manifest.
    tools_offered: Tuple[str, ...] = ()
    #: Repair turns before the caveat. Zero goes straight to the caveat.
    max_repairs: int = 1
    #: ``(check name, minimum)`` pairs: how many things of that kind an
    #: answer under this skill must state before it can be called grounded.
    #: Empty means silence is acceptable here — which is a *declaration*
    #: now, not the absence of one.
    must_cite: Tuple[Tuple[str, int], ...] = ()
    #: Whether the field-misreading tier runs.  **Off** unless a manifest
    #: says ``reading: true``, because it is the one tier that spends model
    #: calls, and a framework that turned it on by default would be
    #: charging every deployment for a check nobody asked for.  It also
    #: needs a reader — see :meth:`GroundingValidator.from_config`'s ``ask``
    #: — and says so rather than passing when there is none.
    reading: bool = False
    #: Whether a second opinion is asked of a critic when the mechanical
    #: verdict is bad enough to earn one.  **Off** by default and, unlike
    #: every other field here, not a check: it is read by the mission loop
    #: (:mod:`core.critic.mission`) and its answer is surfaced beside
    #: :attr:`GroundingReport.grounded`, never inside it.
    critic: bool = False
    #: Named tool families and the phrases that claim them.  Empty means no
    #: plane-claim check, like every other grammar here.
    planes: Tuple[Plane, ...] = ()
    #: Which tools' results may ground a **figure**.  Empty — the default —
    #: means every result in the run does, which is what every manifest
    #: written before this key said and still means.
    #:
    #: Set, it is the answer to a defect measured on the coding pack (lane
    #: N, 18 August 2026): a plane whose tools emit diagnostics grounds
    #: almost any small integer.  ``patch apply`` returns a ``match_count``,
    #: byte offsets and a hash, so ``feature_two_files.bad`` — which writes
    #: "3 passed" having never run the tests — came back ``grounded: true``.
    #: The figure was *in the evidence*; it had simply never been measured
    #: by anything that measures test counts.
    #:
    #: ``figures_from: [verify]`` says which tool measures the quantity this
    #: skill's ``number_pattern`` describes, and a figure grounds against
    #: that tool's results and nothing else.  It applies to figures ONLY:
    #: identifiers keep the whole evidence set, because a file path
    #: legitimately arrives from ``repo_map``, from ``fs`` or from a patch
    #: result, and scoping those would flag true tokens — the 10 August
    #: lesson on :meth:`offering`.
    #:
    #: Matched with :func:`~core.tools.descriptors.same_tool`, so a bridged
    #: spelling (``mcp.verify``) of a named tool is the named tool.
    figures_from: Tuple[str, ...] = ()

    def offering(self, tools: Sequence[str]) -> "GroundingConfig":
        """This config, told which tools the mission put on the table.

        **The name of a tool the model was offered is never an invented
        identifier.** It is a word the harness itself put in the prompt,
        and a check that flags it is asking the model to cite the
        catalogue it was handed.

        On 10 August 2026 that is exactly what happened.
        ``absence_is_an_answer`` turn 3: the identifier check flagged
        ``mcp.catalog_search_assets`` — the tool's own wire name, in a
        sentence saying truthfully which tool had been used — as an
        ungrounded asset id. The manifest's ``ignore`` list did carry a
        spelling of that tool. It carried ``catalog.search_assets``, the
        dotted one, because a person had typed it. The repair turn that
        followed deleted the sentence, and the mission answered with
        nothing citable at all: ``0/0``, and ``grounded: True``.

        So the list is derived rather than typed, from the resolved
        offered set, and matched with
        :func:`~core.tools.descriptors.tool_key` so **every** spelling of
        an offered tool is covered — including a convention nobody has
        invented yet. A hand-written list can only ever carry the
        spellings its author happened to think of, which is the property
        that made this a two-turn defect instead of a typo.

        Returns a new config; the manifest's own ``ignore`` is untouched,
        because prose noise (``e.g``, ``report_view.json``) is a genuine
        authoring decision and this is not.
        """
        return dataclasses.replace(
            self, tools_offered=tuple(str(t) for t in tools if str(t or "").strip()))

    def minimum_for(self, check: str) -> int:
        """How many tokens *check* must consider, or ``0`` for no floor.

        An explicit name beats the ``must_cite: true`` wildcard, so a skill
        can require citations generally and still say ``figures: 0`` for the
        one kind its answers legitimately omit.
        """
        wildcard = 0
        for name, minimum in self.must_cite:
            if name == check:
                return minimum
            if name == ANY_CHECK:
                wildcard = minimum
        return wildcard

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> Optional["GroundingConfig"]:
        """Read a manifest's ``grounding:`` block, or ``None``.

        Refuses an unusable regex here rather than at the end of an
        11,000-second mission, and refuses an unknown key rather than
        ignoring it: a manifest that misspelled ``identifier_pattern``
        would otherwise produce a validator with no opinion and a report
        that looks like a clean one.
        """
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"a grounding block is a mapping, not a {type(raw).__name__}"
            )

        known = {"identifier_pattern", "number_pattern", "ignore",
                 "max_repairs", "must_cite", "claim_table", "reading",
                 "critic", "planes", "figures_from"}
        problems: List[str] = []
        unknown = sorted(set(raw) - known)
        if unknown:
            problems.append(
                f"unknown key(s): {', '.join(unknown)}. A grounding block sets "
                f"{', '.join(sorted(known))}"
            )

        for key in ("identifier_pattern", "number_pattern"):
            pattern = raw.get(key)
            if pattern is None:
                continue
            try:
                re.compile(str(pattern))
            except re.error as exc:
                problems.append(f"`{key}` is not a usable regex: {exc}")

        ignore = raw.get("ignore") or ()
        if isinstance(ignore, str) or not isinstance(ignore, Sequence):
            problems.append("`ignore` is a list of literal strings")
            ignore = ()

        figures_from = raw.get("figures_from") or ()
        if isinstance(figures_from, str) or not isinstance(figures_from, Sequence):
            problems.append(
                "`figures_from` is a list of tool names — the tools whose "
                "results may ground a figure under this skill"
            )
            figures_from = ()
        elif figures_from and not raw.get("number_pattern"):
            # The same rule `_read_planes` enforces one field down: a
            # declaration that can never bind is a typo and not leniency.
            # Scoping a check that is switched off reads, in a report, as
            # a skill that narrowed its figures — and narrows nothing.
            problems.append(
                "`figures_from` without a `number_pattern`: figures are not "
                "checked at all unless a manifest asks for them, so this "
                "scope can never bind"
            )

        repairs = raw.get("max_repairs", 1)
        if isinstance(repairs, bool) or not isinstance(repairs, int) or repairs < 0:
            problems.append(f"`max_repairs` is a count of turns, got {repairs!r}")
            repairs = 1

        must_cite, cite_problems = cls._read_must_cite(raw.get("must_cite"))
        problems.extend(cite_problems)

        claim_table = raw.get("claim_table", False)
        if not isinstance(claim_table, bool):
            problems.append(
                f"`claim_table` is {claim_table!r}; it is true or false — "
                f"whether this skill's answers carry a claim table. What the "
                f"table looks like belongs in the skill's `output_format`"
            )
            claim_table = False

        reading = raw.get("reading", False)
        if not isinstance(reading, bool):
            problems.append(
                f"`reading` is {reading!r}; it is true or false — whether "
                f"this skill's figures are read back to a reader to check "
                f"the FIELD each was taken from, not just that the value is "
                f"in the evidence"
            )
            reading = False
        if reading and not claim_table:
            problems.append(
                "`reading: true` needs `claim_table: true`. The tier reads "
                "the claim table for the path each figure came from; with no "
                "table it has no path to ask about, so it would report a "
                "clean pass having checked nothing"
            )

        critic = raw.get("critic", False)
        if not isinstance(critic, bool):
            problems.append(
                f"`critic` is {critic!r}; it is true or false — whether an "
                f"answer this skill could not ground earns a second opinion "
                f"from a critic. Which critic is a deployment's decision and "
                f"is not settled here"
            )
            critic = False

        planes, plane_problems = cls._read_planes(raw.get("planes"))
        problems.extend(plane_problems)

        if problems:
            raise ValueError("unusable grounding block:\n  - " + "\n  - ".join(problems))

        return cls(
            identifier_pattern=(
                str(raw["identifier_pattern"])
                if raw.get("identifier_pattern") else None
            ),
            number_pattern=(
                str(raw["number_pattern"]) if raw.get("number_pattern") else None
            ),
            claim_table=claim_table,
            ignore=tuple(str(item) for item in ignore),
            max_repairs=repairs,
            must_cite=must_cite,
            reading=reading,
            critic=critic,
            planes=planes,
            figures_from=_string_list(figures_from),
        )

    @staticmethod
    def _read_planes(raw: Any) -> Tuple[Tuple[Plane, ...], List[str]]:
        """``planes:`` as :class:`Plane` objects, plus every problem with it.

        The shape is a mapping of plane name to ``{tools: [...],
        claims: [...]}``.  Both halves are required and the refusal says
        which is missing, because each of them fails silently on its own:
        a plane with no ``claims`` can never fire and reports a clean pass
        forever, and a plane with no ``tools`` fails every claim about it
        whatever the run actually called.  Those are the two ways a
        plane-claim check looks governed and is not, which is the same
        rule :meth:`GroundingValidator._audit_must_cite` enforces one level
        up: a declaration that can never bind is a typo, not leniency.
        """
        if raw is None:
            return (), []
        if not isinstance(raw, Mapping):
            return (), [
                f"`planes` is a {type(raw).__name__}; it is a mapping of "
                f"plane name to {{tools: [...], claims: [...]}}"
            ]

        problems: List[str] = []
        planes: List[Plane] = []
        for name, body in raw.items():
            name = str(name or "").strip()
            if not name:
                problems.append("`planes` names an empty plane")
                continue
            if not isinstance(body, Mapping):
                problems.append(
                    f"`planes: {name}` is a {type(body).__name__}; it is "
                    f"{{tools: [...], claims: [...]}}. A bare list of tools "
                    f"has no phrases to recognise a claim by, so the check "
                    f"could never fire"
                )
                continue
            unknown = sorted(set(body) - {"tools", "claims"})
            if unknown:
                problems.append(
                    f"`planes: {name}` has unknown key(s): "
                    f"{', '.join(unknown)}. A plane sets claims, tools"
                )
            tools = _string_list(body.get("tools"))
            claims = _string_list(body.get("claims"))
            if not tools:
                problems.append(
                    f"`planes: {name}` names no `tools`, so every claim to "
                    f"have used it fails whatever this run called"
                )
            if not claims:
                problems.append(
                    f"`planes: {name}` names no `claims`, so nothing in an "
                    f"answer can ever be recognised as claiming it and the "
                    f"check never binds"
                )
            planes.append(Plane(name=name, tools=tools, claims=claims))

        return tuple(planes), problems

    @staticmethod
    def _read_must_cite(
        raw: Any,
    ) -> Tuple[Tuple[Tuple[str, int], ...], List[str]]:
        """``must_cite:`` in any of its three spellings, plus problems.

        * absent or ``false`` — nothing is required, and an answer that
          cites nothing is reported as having cited nothing rather than as
          having passed;
        * ``true`` — every configured check must consider at least one
          thing;
        * ``[identifiers]`` — those checks must, at least one each;
        * ``{claims: 3}`` — that check must consider at least three, which
          is how a drafting skill states a schema minimum.

        The names are **not** validated here.  Which checks exist is known
        to :meth:`GroundingValidator.from_config`, and validating a name
        against a hard-coded list in this method is how the list and the
        checks drift apart.
        """
        if raw is None or raw is False:
            return (), []
        if raw is True:
            return ((ANY_CHECK, 1),), []

        problems: List[str] = []
        pairs: List[Tuple[str, int]] = []

        if isinstance(raw, Mapping):
            items = list(raw.items())
        elif isinstance(raw, str) or not isinstance(raw, Sequence):
            return (), [
                f"`must_cite` is a {type(raw).__name__}; it is true, a list of "
                f"check names, or a mapping of check name to a minimum count"
            ]
        else:
            items = [(entry, 1) for entry in raw]

        for name, minimum in items:
            name = str(name or "").strip()
            if not name:
                problems.append("`must_cite` names an empty check")
                continue
            if isinstance(minimum, bool) or not isinstance(minimum, int):
                problems.append(
                    f"`must_cite: {name}` is {minimum!r}; it is a count of "
                    f"things an answer has to state"
                )
                continue
            if minimum < 0:
                problems.append(
                    f"`must_cite: {name}` is {minimum}; a negative minimum is "
                    f"not a lenient one, it is a typo"
                )
                continue
            pairs.append((name, minimum))

        return tuple(pairs), problems


@dataclass(frozen=True)
class CheckResult:
    """One check's opinion, or its explicit lack of one.

    Three states for a check that ran — see :attr:`verdict` — because two
    were not enough.  With two, ``0/0`` and ``3/3`` were the same answer,
    and the first is the one a model can always produce.
    """

    check: str
    #: False means *this check could not run*. It is not a pass.
    configured: bool = True
    considered: Tuple[str, ...] = ()
    unsupported: Tuple[str, ...] = ()
    detail: str = ""
    #: How many things of this kind the *skill* said an answer must state.
    #: Zero is the harness's default and means the skill declared nothing;
    #: it is not the harness deciding that silence is fine.
    minimum: int = 0
    #: What this check says in the repair turn, when the validator's generic
    #: wording would be **wrong** for it rather than merely vaguer.
    #:
    #: "These appear in your answer and in no tool output" is the right
    #: sentence for an invented identifier and a false one for a misread
    #: field — ``total_s: 80.847`` is in the evidence, at a real path, and a
    #: repair turn that told the model otherwise would send it looking for a
    #: transcription slip that is not there.  A check with its own words
    #: supplies them here and the generic paragraph skips it; empty means
    #: the generic wording is correct and there is one owner of it.
    repair: str = ""
    #: What this check says about the WAY OUT, said alongside whichever
    #: finding sentence was used — the generic paragraph or :attr:`repair`.
    #:
    #: The distinction is the one the reference deployment paid for on 19
    #: August 2026.  Asked for a top-five share "with the working shown",
    #: a model summed five scores **in prose**, divided by a field that
    #: holds a wall clock, and asserted 121.2%.  The figures check flagged
    #: the sum, the quotient and the percentage correctly and spent the
    #: repair turn saying so — and the repair turn said only *call a tool
    #: that returns them, or rewrite the answer without them*, which is a
    #: finding and not a direction.  The model re-asserted.  What it was
    #: never told is the one thing that fixes that class of answer:
    #: **arithmetic belongs on the computation plane**, and this platform
    #: had already declared which tools that is
    #: (:attr:`GroundingConfig.figures_from`).
    #:
    #: Separate from :attr:`repair` because they compose rather than
    #: replace: ``repair`` exists for a check whose finding the generic
    #: sentence states WRONGLY, and a direction is owed whichever sentence
    #: stated the finding.
    remedy: str = ""
    #: The same, for the caveat appended when a repair turn did not fix it.
    caveat: str = ""

    @property
    def verdict(self) -> str:
        """One of :data:`VERDICTS`. What this check actually found."""
        if not self.configured:
            return UNCONFIGURED
        if self.unsupported:
            return UNSUPPORTED
        if not self.considered:
            return NOTHING_CONSIDERED
        return SUPPORTED

    @property
    def cited_enough(self) -> bool:
        """Whether the answer stated as much as the skill requires.

        Always true where a skill declared no minimum — the requirement is
        content and its absence is not this module's to invent.
        """
        return len(self.considered) >= self.minimum

    @property
    def grounded(self) -> bool:
        """True only when the check ran, found nothing unsupported, **and**
        the answer stated at least what its skill requires it to state.

        An answer that cites nothing is grounded here only because some
        skill said citing nothing is acceptable for it.  Under a skill that
        said otherwise it is a failure, and under every skill it is a
        :data:`NOTHING_CONSIDERED` verdict rather than a clean pass.
        """
        return self.configured and not self.unsupported and self.cited_enough


@dataclass(frozen=True)
class GroundingReport:
    """What every check said, and what was done about it."""

    results: Tuple[CheckResult, ...] = ()
    repairs: int = 0
    caveat: str = ""

    @property
    def ran(self) -> bool:
        """Whether any check was configured well enough to have an opinion."""
        return any(r.configured for r in self.results)

    @property
    def unsupported(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for result in self.results:
            for token in result.unsupported:
                if token not in seen:
                    seen.append(token)
        return tuple(seen)

    @property
    def silent(self) -> Tuple[str, ...]:
        """Checks that ran and found **nothing in the answer to check**.

        Reported separately from :attr:`grounded` on purpose.  Where the
        skill allows it, an answer citing nothing is still a legitimate
        answer — and a reader has to be able to see that nothing was
        actually verified, which is the fact ``0/0 supported`` hid.
        """
        return tuple(
            r.check for r in self.results
            if r.configured and not r.considered
        )

    @property
    def uncited(self) -> Tuple[str, ...]:
        """Checks whose skill required a citation and did not get one."""
        return tuple(
            r.check for r in self.results
            if r.configured and not r.cited_enough
        )

    @property
    def grounded(self) -> bool:
        """Every configured check passed.

        A report where nothing was configured is **not** grounded: it is
        a report with no opinion, and callers ask :attr:`ran` first.

        A report where every check ran and considered nothing **can** be
        grounded — but only under a skill that declared silence acceptable,
        and even then :attr:`silent` names the checks that had nothing to
        do.  ``grounded and not silent`` is the answer that was actually
        verified; the pair is what the ``0/0`` hole collapsed into one bit.
        """
        return self.ran and all(
            r.grounded for r in self.results if r.configured
        )

    @property
    def verified(self) -> bool:
        """Grounded, and **something was actually checked** to say so.

        *Any* configured check having considered something, not every one:
        a draft that quotes figures and names no asset is a normal answer,
        and demanding both would make this false so often that nobody would
        read it.  What was not checked is named in :attr:`silent`; what this
        separates is a verified answer from an empty one.
        """
        return self.grounded and any(
            r.considered for r in self.results if r.configured
        )


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

class GroundingCheck(ABC):
    """One way of asking whether an answer's claims came from a tool.

    A subclass supplies :meth:`extract` — which tokens in the answer are
    claims of its kind — and may narrow :meth:`text`, :meth:`supported`
    and :meth:`unconfigured`.  :meth:`check` is the template and is
    **final**, because it is a statement about ORDER and the first step
    is the one a re-implementation drops:

    * *configuration before extraction* — a check with no grammar has no
      opinion, and must report that rather than extracting nothing and
      reporting a clean pass.  An empty ``unsupported`` list produced by
      a check that never ran is indistinguishable, downstream, from a
      genuinely grounded answer;
    * *ignores before support* — a configured literal is removed from
      consideration, not counted as supported by something.  The two look
      the same in a verdict and read very differently in a report;
    * *evidence is prepared once, before the tokens are tested* — a
      subclass that normalises evidence (stripping thousands separators,
      say) does it once per check and not once per token, because the
      evidence of a mission is the largest thing in reach and the tokens
      are the smallest;
    * *the verdict is built from the survivors* — every check hands back
      the same shape, so a caller can list unsupported tokens across
      checks without knowing which check found which.

    What a subclass declares is checked at **class creation**, and every
    problem is collected into one message.
    """

    #: Names the check in the report and in the repair turn.
    name: str = ""

    _REQUIRED: Tuple[str, ...] = ("extract",)
    _FINAL: Tuple[str, ...] = ("check",)

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        if getattr(cls, "abstract", False):  # an intermediate base is fine
            return
        problems: List[str] = []
        if not cls.name:
            problems.append(
                "`name` is empty; it labels this check in the report and in "
                "the repair turn sent back to the model, and an unnamed check "
                "produces a refusal nobody can act on"
            )
        for attr in cls._REQUIRED:
            if getattr(cls, attr, None) is getattr(GroundingCheck, attr, None):
                problems.append(
                    f"does not implement `{attr}`; the base's stub refuses "
                    f"rather than inventing an answer"
                )
        for attr in cls._FINAL:
            if attr in cls.__dict__:
                problems.append(
                    f"overrides `{attr}`, which is final. It is a statement "
                    f"about ORDER — configuration before extraction, ignores "
                    f"before support — and a re-implementation is how a check "
                    f"that never ran reports an answer as grounded. Override "
                    f"`extract`, `supported` or `unconfigured` instead"
                )
        if problems:
            raise GroundingMisdeclared(
                f"{cls.__name__} is not a usable GroundingCheck:\n  - "
                + "\n  - ".join(problems)
            )

    def __init__(self, config: GroundingConfig, *, ask: Optional[Ask] = None):
        self._config = config
        self._ignore = frozenset(config.ignore)
        #: ``prompt -> reply``, or ``None`` where nobody supplied one.  Every
        #: check takes it and one uses it: :class:`ReadingGroundingCheck` is
        #: the tier that spends a model call, and handing it in through the
        #: same constructor every check has is what keeps
        #: :meth:`GroundingValidator.from_config` from having to know which
        #: check is which.
        self._ask = ask
        #: Which tools this run actually dispatched.  Set by
        #: :meth:`observing` immediately before :meth:`check`, and empty
        #: until then — see that method for why it is not on the config.
        self._called: Tuple[str, ...] = ()
        #: How many dispatches this run made, or ``None`` for *nobody
        #: said*.  See :meth:`observing`; ``None`` is never read as zero.
        self._calls: Optional[int] = None
        #: The rows the earlier checks produced this pass.  See
        #: :meth:`observing`.
        self._so_far: Tuple["CheckResult", ...] = ()
        #: The tools this mission offered. Compared with
        #: :func:`~core.tools.descriptors.same_tool`, so every spelling of
        #: one is covered. See :meth:`GroundingConfig.offering` for why
        #: this is derived and the manifest's ``ignore`` list is not.
        self._offered = tuple(config.tools_offered)
        self._minimum = config.minimum_for(self.name)

    @property
    def config(self) -> GroundingConfig:
        return self._config

    def observing(self, called: Sequence[str], *,
                  calls: Optional[int] = None,
                  so_far: Sequence["CheckResult"] = ()) -> None:
        """Told what this run did, before :meth:`check` runs.

        Not on :class:`GroundingConfig`, and the difference is the point:
        the config is the *skill's declaration*, read once at the door
        before a single tool has been called, and a run-time fact written
        into it would make the same validator answer differently on its
        second mission.  ``tools_offered`` is on the config because what
        was **offered** is settled before the run starts;  what was
        **called** is not.

        One owner of the list: the mission's own result store, which
        recorded every dispatch as it happened.  Re-deriving it by reading
        the conversation back would be a second owner, and the second owner
        is the one that goes stale the day a call is made somewhere the
        messages do not show it.

        *calls* is **how many** dispatches there were, and it is a separate
        fact from *called* rather than ``len(called)``: that list is the
        distinct tools of one store, and the staged path unions several
        stores' lists together.  ``None`` — the default — means *nobody
        said*, and it is not zero: a library caller and a fresh
        :class:`GroundingValidator` supply neither, and a check that read
        their silence as "this run called nothing" would report a finding
        about a run it knows nothing about.  :class:`SubjectGroundingCheck`
        is the check that needs it and reports :data:`UNCONFIGURED` without
        it.

        *so_far* is the rows the checks BEFORE this one produced, in
        :data:`DEFAULT_CHECKS` order.  One check reads them — again
        :class:`SubjectGroundingCheck`, whose question is partly *did
        anything else in this answer have something to check* — and it
        reads the rows rather than re-extracting the answer with the other
        checks' grammars, which would be a second owner of every grammar
        in the block.
        """
        self._called = tuple(
            str(name) for name in called if str(name or "").strip())
        self._calls = calls
        self._so_far = tuple(so_far)

    # ── the template. FINAL. ────────────────────────────────────────────

    def check(self, answer: str, evidence: Sequence[str]) -> CheckResult:
        """Run this check.  See the class docstring."""
        problems = self.unconfigured()
        if problems:
            return CheckResult(
                check=self.name,
                configured=False,
                detail="; ".join(problems),
            )

        # BOTH SIDES, and here rather than in a subclass, so no check can be
        # comparing typography instead of content. See `typographic_plain`.
        answer = typographic_plain(answer or "")
        evidence = [_flattened(text) for text in evidence]

        considered: List[str] = []
        for token in self.extract(self.text(answer)):
            token = str(token)
            if token and token not in considered and not self.ignored(token):
                considered.append(token)

        prepared = list(self.prepare(evidence))
        unsupported = [t for t in considered if not self.supported(t, prepared)]
        return CheckResult(
            check=self.name,
            configured=True,
            considered=tuple(considered),
            unsupported=tuple(unsupported),
            detail=self._detail(len(considered), len(unsupported)),
            minimum=self._minimum,
            repair=self.repair_words(unsupported),
            remedy=self.remedy_words(unsupported),
            caveat=self.caveat_words(unsupported),
        )

    def _detail(self, stated: int, failed: int) -> str:
        """The one line a reader sees.  ``0/0 supported`` is not one of them.

        The old wording read ``0/0 supported by a tool result in this run``
        for an answer that cited nothing, which is true and is why six
        missions looked checked when nothing had been.  An answer with
        nothing in it now says so in words.
        """
        if not stated:
            detail = f"nothing to check — the answer states no {self.name}"
        else:
            detail = (
                f"{stated - failed}/{stated} supported by a tool result "
                f"in this run"
            )
        if self._minimum:
            met = "met" if stated >= self._minimum else "NOT met"
            detail += (
                f"; this skill requires at least {self._minimum} "
                f"({met})"
            )
        return detail

    # ── what a subclass supplies ────────────────────────────────────────

    @abstractmethod
    def extract(self, answer: str) -> Iterable[str]:
        """The tokens in *answer* this check is responsible for."""
        raise NotImplementedError

    def text(self, answer: str) -> str:
        """The part of the answer this check reads.  Prose, by default.

        Two kinds of non-prose are removed before extraction, for two
        different reasons:

        * **code**, fenced or inline — code is a proposed computation and
          not a claim, and its identifiers (``np.linspace``) and literals
          (``0.01``) match the grammars exactly the way inventions do.
          See :func:`prose_only` and the August 2026 mission-pane failure
          recorded on it.
        * **the claim table** — a machine-readable annex the skill asked
          for, verified by walking its paths, not by pattern-matching
          them.  Left in, its ``"path": "gate.confidence"`` entries are
          dotted lower-case tokens an identifier grammar matches, so a
          draft that did exactly what its skill required would be
          reported as inventing identifiers.  :class:`ClaimGroundingCheck`
          reads the table instead — it overrides this method, which is
          why the fence-stripping lives here and not in :meth:`check`.
          (The table's own fence means :func:`prose_only` already removes
          it; the point stands on its own and is kept stated.)
        """
        return prose_only(CLAIM_BLOCK.sub(" ", answer))

    def unconfigured(self) -> List[str]:
        """Why this check cannot run, or an empty list."""
        return []

    def repair_words(self, failed: Sequence[str]) -> str:
        """This check's own sentence for the repair turn, or ``""``.

        Empty by default, which means the validator's generic wording is
        correct for this check and there is exactly one copy of it.  See
        :attr:`CheckResult.repair`.
        """
        return ""

    def remedy_words(self, failed: Sequence[str]) -> str:
        """This check's direction out, or ``""``.  See :attr:`CheckResult.remedy`.

        Empty by default: most findings name their own fix — an invented
        identifier is fixed by quoting the real one — and a paragraph
        repeating that in other words is a paragraph a model skims.
        """
        return ""

    def caveat_words(self, failed: Sequence[str]) -> str:
        """The same, for the caveat.  See :attr:`CheckResult.caveat`."""
        return ""

    def ignored(self, token: str) -> bool:
        """A literal the manifest named, or **any spelling of an offered tool**.

        The second half is derived rather than authored, and it is not a
        convenience: a token the harness itself wrote into the prompt is
        not something the model can be asked to have got from a tool
        result. See :meth:`GroundingConfig.offering`.
        """
        return token in self._ignore or any(
            same_tool(token, offered) for offered in self._offered)

    def prepare(self, evidence: Sequence[str]) -> Sequence[str]:
        """The evidence in whatever form :meth:`supported` compares against."""
        return evidence

    def supported(self, token: str, evidence: Sequence[str]) -> bool:
        return any(token in text for text in evidence)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic
        return f"<{type(self).__name__} {self.name}>"


class IdentifierGroundingCheck(GroundingCheck):
    """Every identifier-shaped token must have come back from a tool.

    The one check that matters most, because an identifier is the part
    of an answer a reader will act on — paste into a query, cite in a
    finding, hand to another team — and the part they cannot verify by
    reading.
    """

    name = "identifiers"

    def unconfigured(self) -> List[str]:
        if not self._config.identifier_pattern:
            return [
                "no `identifier_pattern` in the grounding block, so nothing "
                "here knows what an identifier looks like on this platform. "
                "The grammar is content and the harness will not guess one"
            ]
        return []

    def extract(self, answer: str) -> Iterable[str]:
        pattern = re.compile(self._config.identifier_pattern)
        for match in pattern.finditer(answer):
            # A capturing group means the author narrowed what the token
            # actually is; honour it rather than the whole match.
            yield match.group(1) if match.groups() else match.group(0)


class NumericGroundingCheck(GroundingCheck):
    """Every figure must have come back from a tool — and not by echo.

    Off unless a manifest sets ``number_pattern``, and deliberately so:
    an answer legitimately contains numbers it computed — "3 assets",
    "two of the four" — and a check that flagged those would train
    whoever reads the report to ignore it.  A platform that wants
    figures checked writes a pattern narrow enough to mean it.

    **The echo hazard, and the rule that closes it.**  A model told a
    figure is unsupported has an obvious way out that is not the one the
    repair turn intends: run ``print('30,000')`` and submit the same
    answer again.  The stdout of that call is a tool result like any
    other, the figure is now "in the evidence", and the record says
    ``grounded: true``.  Nothing about the *shape* of the evidence
    distinguishes a computed figure from an echoed one — it is a tool's
    output either way — so a skill telling the model not to do it is
    skill content standing in for a harness property, which is to say it
    holds for exactly as long as the model cooperates.

    The rule is mechanical and narrow: **a code-plane call whose output
    holds no figure it was not already given grounds nothing.**  The
    model wrote the arguments; a call that printed back only numbers that
    were already in them round-tripped them, and round-tripping is not
    computing.  A call that produced even one figure its arguments did
    not hold did compute, and its whole output grounds as any tool's
    does.  Four things the rule deliberately does NOT do:

    * it does not touch a figure the script *derived*.  ``df[df.amount >
      30000]`` prints rows containing ``48750``, and the call grounds
      every figure it printed.  A computed result is unaffected, which is
      the overwhelming majority of real analysis;
    * **it does not dock a literal that merely collides with a computed
      result.**  The narrower "credit only figures absent from the
      arguments" was written first and the committed corpus refused it:
      the analyst pack's ``errors_by_hour`` mission increments a counter
      with ``+ 1`` and its program then computes that one hour has
      exactly ``1`` error — the same digit, one a step and one a result.
      Per-figure exclusion took that correct answer apart, spent the
      run's repair turn on it and ended ``answered_with_caveat``.  Small
      integers collide constantly: loop bounds, slice indices, rounding
      places.  A check that flags working code is a check its reader
      learns to skip, which un-catches the fabrications it exists for
      (see ``tests/test_grounding_code_is_not_a_claim.py``).  Asking
      whether the call computed keeps the hazard closed and the collision
      harmless;
    * it judges each RESULT against its own call's arguments, not the
      evidence pile against all of them.  The same figure echoed by one
      call and legitimately produced by another — or by any non-code tool
      — is supported by that other call.  Evidence is a union, and only
      the echoing result is dropped from it;
    * it applies to code-plane tools ONLY.  Every other tool's arguments
      legitimately reappear in its output: a ``run_id`` handed to a
      lookup comes back in the record it fetches, and docking that would
      make the check unusable on the submit-and-poll platforms it was
      written for.

    What it does not close, stated rather than left to be discovered: a
    model that prints its echo **beside** something it really computed
    gets the echo credited.  That is deliberate.  The alternative flags
    every script whose loop bound or slice index happens to equal a
    result, and the tier for an answer that computed something real and
    smuggled a figure in next to it is the reading check, not a grammar.

    Which tools are code-plane is read off the descriptors, through
    :func:`~core.runtime.skills.code_plane_tools` — the same one owner
    the sandbox gate uses — so a tool registered tomorrow asking for
    ``python.exec`` or ``shell.exec`` is covered without anybody
    remembering to add it here.  Matched with
    :func:`~core.tools.descriptors.same_tool`, unlike that gate: the
    sandbox question is *who runs the subprocess* and a bridged shell is
    the server's, but the echo question is *who wrote the code*, and that
    is the model whichever end executes it.  A server tool this install
    has no descriptor for is not covered — the harness cannot know that a
    name it has never seen takes a program as an argument, and inventing
    that would be the name-matching this repository keeps removing.

    **The clock is the second way a figure arrives without being
    measured**, and it needs no cooperation from the model at all: a
    timestamped tool result donates its minute and its second to the
    evidence set.  See :data:`CLOCK`, which masks timestamp-shaped spans
    on both sides.

    **What the model SENT is never a result.**  A failed call contributes
    its arguments to the evidence set — see
    :meth:`~core.runtime.results.MissionResultStore.evidence_texts`, and
    the reason is that "I tried that page and it answered 404" is a claim
    about the run — but those texts are marked
    :attr:`~core.runtime.results.SourcedEvidence.sent` and this check
    skips them, or an answer would support its own arithmetic by typing
    it into a call that fails.

    **The fourth way a figure arrives unmeasured is a tool-rich plane**, and
    it needs neither an echo, a clock nor a failed call: on the coding pack a ``patch
    apply`` result carries a ``match_count``, byte offsets and a hash, so
    a small integer is nearly always *somewhere* in the evidence.
    Measured 18 August 2026: ``feature_two_files.bad`` writes "3 passed"
    having never called ``verify``, and the run came back ``grounded:
    true``.  Nothing about that answer was checkable by asking whether the
    figure existed in the pile; what was wrong is that it had never been
    **measured by the thing that measures test counts**.

    :attr:`GroundingConfig.figures_from` is the manifest's answer — a list
    of tool names, and a figure grounds against those tools' results and
    nothing else.  Unset, every result grounds, which is what every
    manifest written before the key said.  Two properties of the scope,
    both deliberate:

    * **evidence with no provenance is out of scope**, not exempt from it.
      A plain ``str`` — a library caller's list, a hand-built evidence set
      — cannot say which call produced it, and "unknown" is not "verify".
      A deployment that scopes its figures is asking for exactly that
      strictness; one that hands in bare strings should not scope them;
    * **it applies to this check only.**  Identifiers keep the whole
      evidence set: a file path legitimately comes back from ``repo_map``,
      from ``fs`` or from a patch result, and a scope there would flag
      true tokens — which is the 10 August lesson recorded on
      :meth:`GroundingConfig.offering`.
    """

    name = "figures"

    def unconfigured(self) -> List[str]:
        if not self._config.number_pattern:
            return [
                "no `number_pattern` in the grounding block; figures are not "
                "checked unless a manifest asks for it"
            ]
        return []

    def extract(self, answer: str) -> Iterable[str]:
        """Every figure the manifest asks about, that is a figure here.

        Two patterns meet in this check and they used to disagree.  The
        manifest's ``number_pattern`` says which figures a platform cares
        about; :data:`FIGURE` below says what counts as one *at all*, and
        it is the careful one — it refuses a run of digits that follows a
        dot or continues a word, so that ``a.0000`` is an actor handle and
        not the number zero.  :meth:`prepare` reads the evidence with
        ``FIGURE``; this method read the answer with the manifest's pattern
        alone, and a manifest whose pattern is the ordinary
        word-boundary-to-word-boundary run of digits therefore pulled
        ``0000`` out of ``a.0000`` in the answer and looked for it in an
        evidence set that — correctly — had never put it there.

        Live, 16 August: a staged mission answered *"Run r-7 actor at top
        of actor list: a.0000"*, the identifier check passed it 2/2, the
        figure check reported ``0000`` unsupported, and the repair turn
        took the actor back out of a correct answer.  The disagreement was
        the whole of it, so the fix is one owner: the manifest chooses
        *which* figures are checked, ``FIGURE`` decides *whether* a run of
        characters is one, and a candidate that is not a figure where it
        sits is not a figure the model has to account for.

        Narrowing only.  Every token this still yields is one the previous
        version yielded, so no answer becomes grounded that was not.
        """
        pattern = re.compile(self._config.number_pattern)
        # The answer side of :data:`CLOCK`. A model that quotes the
        # timestamp it read is not claiming a quantity, and a mask applied
        # only to the evidence would make it one.
        answer = self._declocked(answer)
        for match in pattern.finditer(answer):
            # A capturing group means the author narrowed what the token
            # actually is; honour it rather than the whole match, exactly
            # as `IdentifierGroundingCheck.extract` does.
            index = 1 if match.groups() else 0
            start, end = match.span(index)
            if self._stands_alone(answer, start, end):
                yield match.group(index)

    @staticmethod
    def _stands_alone(text: str, start: int, end: int) -> bool:
        """:data:`FIGURE`'s two boundaries, asked of one span in *text*.

        The same rule stated once and applied on both sides: nothing wordy
        and no dot before it, nothing wordy after it.  Written as a
        boundary test rather than by re-running ``FIGURE`` over a slice,
        because a slice has boundaries of its own and would answer about
        those.
        """
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if before == "." or before == "_" or before.isalnum():
            return False
        return not (after == "_" or after.isalnum())

    #: Separators a figure may carry in prose and not in a payload, or
    #: the other way round.
    SEPARATORS = ",_ "

    #: One figure, wherever it sits in a payload or a sentence.  The
    #: boundaries do the work.  ``(?<![\w.])`` refuses a run of digits that
    #: continues a word or follows a dot, so ``5f21c9`` yields no ``21``
    #: and ``10.3871`` yields no ``3871``; ``(?![\w])`` refuses one that
    #: runs on into a word, so ``04349a489b2a1457`` is a corpus hash and
    #: not the number 4349.  Group separators are honoured only where they
    #: group — ``12,481`` is one figure and ``3, 127`` is two.
    FIGURE = re.compile(r"(?<![\w.])[+-]?\d(?:[\d,_]*\d)?(?:\.\d+)?(?![\w])")

    #: A clock is not a figure, on either side of the comparison.
    #:
    #: Measured 18 August 2026 on the research pack: a tool result stamped
    #: ``2026-08-18T01:52:07+00:00`` donates ``2026``, ``08``, ``18``,
    #: ``01``, ``52``, ``07`` and ``00`` to the evidence set, because
    #: :data:`FIGURE`'s boundaries are satisfied by a two-digit run after a
    #: colon.  An answer that invented "52 hours" was then reported
    #: grounded roughly one run in six — not by any tool having produced
    #: 52, but by the clock on an unrelated record.  The pack worked round
    #: it by writing ISO **basic** (``20260818T015207Z``), which is content
    #: standing in for a harness property: the next tool to stamp a result
    #: reopens it.
    #:
    #: Masked on BOTH sides — the answer's figures and the evidence's — for
    #: the reason :func:`typographic_plain` is applied to both: masking one
    #: side turns "the answer quoted a timestamp" into an unsupported
    #: claim, which is a false positive invented by the fix.  A time is not
    #: a quantity anywhere, so it is not extracted anywhere.
    #:
    #: **Epoch seconds are deliberately NOT masked.**  A ten-digit epoch is
    #: a SINGLE token under :data:`FIGURE`, so it can only launder an
    #: answer claiming that exact number, and masking it would hide a
    #: genuine claim to buy nothing.  What makes a timestamp dangerous is
    #: its separators: they cut it into small figures that collide with
    #: real ones.
    CLOCK = re.compile(
        r"(?<![\w])(?:"
        r"\d{4}-\d{2}-\d{2}"                     # a date, ISO extended
        r"(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
        r"(?:Z|[+-]\d{2}:?\d{2})?)?"               # with a time, and a zone
        r"|\d{8}T\d{6}(?:\.\d+)?Z?"               # ISO basic, no separators
        r"|\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"    # a bare clock
        r")(?![\w])"
    )

    @classmethod
    def _declocked(cls, text: Any) -> str:
        """*text* with every timestamp-shaped span blanked.

        Replaced by a space rather than removed, so that two figures which
        merely sat either side of a timestamp do not run together into a
        third that was never written.  See :data:`CLOCK`.
        """
        return cls.CLOCK.sub(" ", str(text or ""))

    def prepare(self, evidence: Sequence[str]) -> Sequence[Any]:
        """Every figure in the evidence, as an exact decimal, minus echoes.

        Extracted **structurally** and compared **numerically**, which is
        the whole substance of this check.  The obvious implementation —
        ``token in text`` — reports ``0.387`` as supported by an unrelated
        pagerank of ``10.3871``, because it is a substring of it.  That is
        not a corner case: scores share digits, a fabricated figure only
        has to be a substring of a real one somewhere in a governed view
        to be laundered into a grounded answer, and the bigger the payload
        the likelier it is.

        Per evidence text, and each one is asked two questions before its
        figures count.

        **Is it a result at all?**  What the model SENT is not.  A failed
        call contributes its arguments to the evidence set so that "I
        tried that page and it answered 404" can ground the page — see
        :meth:`~core.runtime.results.MissionResultStore.evidence_texts` —
        and those texts are marked ``sent``.  A figure typed into a call
        that fails grounds nothing, or an answer would support its own
        arithmetic by making a call it knew would break.

        **Did the call that produced it compute anything?**  A code-plane
        call whose output holds no figure its own arguments did not
        already hold printed back what it was told.  Text with no
        provenance — a library caller's list of strings, the staged path's
        union of five stores — has ``arguments`` of ``None``, which means
        *nothing known*, and nothing known is never read as nothing
        echoed.

        **Is it in scope?**  Where the manifest set
        :attr:`GroundingConfig.figures_from`, only the named tools' results
        are asked at all — see the class docstring, and the fabricated
        "3 passed" that a patch result grounded.  Unset, every result is in
        scope and this question is not asked.

        The surviving texts are unioned, so a figure one call echoed is
        still supported where another call produced it.
        """
        figures = set()
        for _text, found in self._grounding_texts(evidence):
            figures |= found
        return sorted(figures)

    def _grounding_texts(
        self, evidence: Sequence[Any],
    ) -> Iterable[Tuple[Any, set]]:
        """``(text, its figures)`` for every evidence text that may ground.

        The three questions of :meth:`prepare`, asked in one place because
        two checks ask them: this one, which wants the figures, and
        :class:`FieldAttributionCheck`, which wants the field NAMES out of
        the same texts and must not be able to read a name off a result
        that no figure of this skill could ground on.  A second copy of
        "is it sent, is it in scope, did the call compute" is a second
        answer to it the day one of them is amended.

        The figures come back with the text because both callers need them
        and finding them twice would double a walk over the largest thing
        in reach.
        """
        code_plane = tuple(code_plane_tools())
        for text in evidence:
            if getattr(text, "sent", False):
                continue
            if not self._in_scope(text):
                continue
            found = self._figures_in(text)
            arguments = getattr(text, "arguments", None)
            if (found and arguments is not None
                    and self._runs_composed_code(text, code_plane)
                    and not (found - self._figures_in(arguments))):
                continue
            yield text, found

    def remedy_words(self, failed: Sequence[str]) -> str:
        """Where the arithmetic belongs, which is the thing never said.

        Measured on the reference deployment, 19 August 2026.  Asked for
        the top-five share of a run's total "with the working shown", the
        model read a five-row ranking out of a lookup, summed the five
        scores **in prose**, took a real field off the same result that
        holds the run's elapsed seconds, divided one by the other and
        asserted a share of 121.2% — with a note explaining why a share may
        exceed 100%.  Every one of the three derived figures was correctly
        flagged, the repair turn was spent, and the model re-asserted them.

        The repair turn it got said *call a tool that returns them, or
        rewrite the answer without them*.  Neither branch is available to a
        model that believes it has done the arithmetic already: no tool
        returns a quotient nobody has computed, and rewriting without the
        figures deletes the answer.  The branch that was missing is the one
        the platform had already declared — a computation plane — so this
        names it, out of :attr:`GroundingConfig.figures_from` where the
        skill said which tools measure this quantity and generically where
        it did not.

        Said whichever sentence stated the finding, scoped or generic; see
        :attr:`CheckResult.remedy`.
        """
        if not failed:
            return ""
        scope = self._scope_words()
        if scope:
            return (
                f"Do not derive figures in prose. Call {scope} to compute "
                f"them from the tool results' own fields, and state only "
                f"what it prints."
            )
        return (
            "Do not derive figures in prose. If this catalogue offers a "
            "computation tool, compute it there and cite what it printed; "
            "otherwise state only figures the tools returned."
        )

    def repair_words(self, failed: Sequence[str]) -> str:
        """Own words under a scope, because the generic ones become false.

        "appears in your answer and in no tool output you received" is
        exactly right with no scope and wrong with one: the fabricated
        "3 passed" **is** in a patch result.  What is true is that no
        ``verify`` result printed it, and a repair turn that says so sends
        the model to run the tests rather than to hunt for a transcription
        slip that is not there.  See :attr:`CheckResult.repair`.
        """
        scope = self._scope_words()
        if not (failed and scope):
            return ""
        listed = ", ".join(repr(t) for t in failed)
        return (
            f"These figures are in no {scope} result from this mission: "
            f"{listed}. Under this skill a figure is supported by what "
            f"{scope} printed and by nothing else — a count that appears "
            f"somewhere else in the run was not measured. Call {scope} and "
            f"quote what it prints, or say the figure is not established."
        )

    def caveat_words(self, failed: Sequence[str]) -> str:
        """The same distinction, in the abstention.  See :meth:`repair_words`."""
        scope = self._scope_words()
        if not (failed and scope):
            return ""
        listed = ", ".join(failed)
        return (
            f"⚠️ Ungrounded: these figures were printed by no {scope} result "
            f"in this mission: {listed}. They may appear elsewhere in the "
            f"run — that is not a measurement of them — and must not be "
            f"relied on or cited onward."
        )

    def _scope_words(self) -> str:
        """The scoped tools as one phrase, or ``""`` where none was set."""
        return " or ".join(self._config.figures_from)

    def _in_scope(self, text: Any) -> bool:
        """Whether *text* is a result this skill lets a figure ground on.

        True for everything where no scope was declared, which is the
        default and every manifest written before the key.  Where one was,
        the text has to name a tool and that tool has to be one of them —
        :func:`~core.tools.descriptors.same_tool`, so ``mcp.verify`` is
        ``verify``.  Text with no provenance is out: see the class
        docstring for why "unknown" is not read as "in scope".
        """
        scope = self._config.figures_from
        if not scope:
            return True
        tool = str(getattr(text, "tool", "") or "")
        return bool(tool) and any(same_tool(tool, name) for name in scope)

    def _detail(self, stated: int, failed: int) -> str:
        """The base's line, plus the scope when there is one.

        Said in the record row rather than left to whoever remembers the
        manifest: ``2/3 supported`` and ``2/3 supported, figures scoped to
        verify`` are different findings, and the second one tells a reader
        that the third figure may well be *somewhere* in the run and was
        not measured by the tool that measures it.
        """
        detail = super()._detail(stated, failed)
        if self._config.figures_from:
            detail += f"; scope: [{', '.join(self._config.figures_from)}]"
        return detail

    @classmethod
    def _figures_in(cls, text: Any) -> set:
        """Every figure in *text*, as exact decimals.  :data:`FIGURE`'s
        grammar and :meth:`_plain`'s separators, stated once so the
        output side and the arguments side cannot drift apart — a rule
        that read ``30000`` out of a script but looked for ``30,000`` in
        the output would exclude nothing at all."""
        found = set()
        for match in cls.FIGURE.finditer(cls._declocked(text)):
            value = _as_decimal(cls._plain(match.group(0)))
            if value is not None:
                found.add(value)
        return found

    @staticmethod
    def _runs_composed_code(text: Any, code_plane: Sequence[str]) -> bool:
        """Whether *text* came back from a tool that runs a program the
        MODEL wrote.

        *code_plane* is :func:`~core.runtime.skills.code_plane_tools`,
        read once per check and passed in: it walks every registered
        descriptor, and doing that once per evidence text would be a
        per-token cost on the largest thing in reach.
        """
        tool = str(getattr(text, "tool", "") or "")
        return bool(tool) and any(
            same_tool(tool, entry) for entry in code_plane)

    def supported(self, token: str, evidence: Sequence[Any]) -> bool:
        """Whether some figure in the evidence *is* this figure.

        Equality of value, not of spelling: ``12,481`` in a draft and
        ``12481`` in the payload it was read from are the same figure, and
        so are ``338`` and ``338.0``.  Failing either pair would make this
        a formatting complaint that whoever reads the report learns to
        skip.

        A token that is not a number at all cannot be compared as one, and
        is reported unsupported rather than fallen back to substring
        matching.  The fallback is the leak; a ``number_pattern`` matching
        things that are not numbers is a manifest to fix.
        """
        value = _as_decimal(self._plain(token))
        return value is not None and value in evidence

    @classmethod
    def _plain(cls, text: str) -> str:
        for separator in cls.SEPARATORS:
            text = text.replace(separator, "")
        return text


#: A field name as a payload spells one and as prose quotes one:
#: ``snake_case`` inside backticks.  Narrow on purpose — an attribution
#: check that accepted any backticked word would read every quoted tool
#: name and every quoted filename as a claim about a field.
FIELD_NAME = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"

#: A key as JSON spells one, for **existence only**.  The fallback for a
#: result this module could not parse — a truncated payload, a log line
#: with an object embedded in it — where the key is plainly there and its
#: value is not reachable.  See :meth:`FieldAttributionCheck.prepare`.
KEY_IN_TEXT = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:')


def json_blocks(text: Any) -> Iterable[Any]:
    """Every JSON object or array in *text*, parsed.  Never raises.

    The whole text first, because a tool result usually is one payload.
    Failing that, each outermost ``{...}`` or ``[...]`` span is tried on
    its own: a result whose payload is wrapped in a sentence, a log with
    one record per line, a governed view with a preamble.  Depth is
    counted outside JSON strings only, so a brace inside a quoted value
    does not close the span it sits in.

    Text that holds no parseable JSON yields nothing, which is the honest
    answer: a check reading field NAMES off this has learned no names from
    it, and no names means nothing considered rather than everything
    invented.
    """
    raw = str(text or "")
    try:
        yield json.loads(raw)
        return
    except (json.JSONDecodeError, ValueError):
        pass

    depth = 0
    start = -1
    in_string = False
    escaped = False
    closing = {"{": "}", "[": "]"}
    opened = ""
    for index, char in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in closing:
            if depth == 0:
                start, opened = index, char
            depth += 1
        elif char in ("}", "]"):
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                if char == closing[opened]:
                    try:
                        yield json.loads(raw[start:index + 1])
                    except (json.JSONDecodeError, ValueError):
                        pass
                start = -1


def harvest_fields(node: Any, keys: set, values: dict) -> None:
    """Every mapping key in *node* into *keys*, its scalar figures into
    *values*.

    A key whose value is another object or a list is a key that exists and
    holds no figure of its own; it lands in *keys* and not in *values*, and
    :meth:`FieldAttributionCheck.supported` reads that difference as *the
    field is real and this check cannot say what it holds* rather than as a
    miss.
    """
    if isinstance(node, Mapping):
        for key, value in node.items():
            key = str(key)
            keys.add(key)
            if isinstance(value, (Mapping, list)):
                harvest_fields(value, keys, values)
                continue
            bucket = values.setdefault(key, set())
            number = _as_decimal(value)
            if number is not None:
                bucket.add(number)
    elif isinstance(node, list):
        for item in node:
            harvest_fields(item, keys, values)


class FieldAttributionCheck(NumericGroundingCheck):
    """A figure labelled with the field it came from must be in that field.

    The complement to its base class, and the failure it answers is one a
    membership check cannot see.  :class:`NumericGroundingCheck` asks *is
    this number anywhere in the evidence*; a large governed payload answers
    yes to a great many numbers, and the part of the sentence a reader
    actually acts on is not the number but the LABEL beside it.
    ``154.024 (field `total_s`)`` is a claim about provenance, and it is
    checkable by arithmetic, because the payload either holds that value
    under that key or it does not.

    Two findings, and they are different mistakes:

    * **the field does not exist.**  Nothing this mission received carries
      a key by that name.  The figure may well be real; what is invented is
      the account of where it came from, which is exactly the half a reader
      cannot verify and will cite onward;
    * **the field exists and does not hold that figure.**  A key read off
      one record and a value read off another, joined in one sentence.

    What it deliberately does NOT catch is the misreading the sibling
    ``remedy`` was written for: ``total_s`` really does hold ``154.024``,
    so ``154.024 (field `total_s`)`` is a **correct** attribution — of a
    wall clock that the answer then divided into as though it were a score.
    That is a semantic error, its instrument is
    :class:`ReadingGroundingCheck`, and this check passing it is the
    boundary between the two working rather than a gap between them.

    Inside the figures family, and by subclass rather than by resemblance:
    it runs only where a manifest asked for figures at all, it reads the
    same evidence texts through
    :meth:`NumericGroundingCheck._grounding_texts` — so an echoed result,
    a call's own arguments and a result outside
    :attr:`GroundingConfig.figures_from` teach it no field names either —
    and it spells a figure with the same grammar.
    """

    name = "attribution"

    #: Between the field and the figure in a token.  Both halves travel,
    #: because a repair turn naming only one of them would ask the model to
    #: guess which pairing was rejected.
    SEPARATOR = "="

    #: How many real field names a repair turn offers.  Enough to show the
    #: shape of the payload, few enough that the sentence stays readable —
    #: a governed view has hundreds of keys and pasting them all back is
    #: pasting the payload back.
    NAMED = 8

    #: The three spellings an answer pairs a figure with a field in, and
    #: the only three.  Separate patterns rather than one alternation, so
    #: each can say which side the figure sits on:
    #:
    #: * ``**154.024** (field `total_s`)`` — the figure, then the aside.
    #:   The recorded one;
    #: * ``field `total_s` is 154.024`` — the aside, then the figure;
    #: * ``` `total_s` = 154.024 ``` and ``` `total_s`: 154.024 `` — a bare
    #:   pairing, which needs its operator: a backticked word standing next
    #:   to a number is not otherwise a claim about a field.
    ATTRIBUTIONS: Tuple[Any, ...] = (
        re.compile(
            r"(?P<figure>" + NumericGroundingCheck.FIGURE.pattern + r")"
            r"\**\s*\(\s*(?:the\s+)?field\s+`(?P<field>" + FIELD_NAME
            + r")`\s*\)"),
        re.compile(
            r"(?:the\s+)?field\s+`(?P<field>" + FIELD_NAME + r")`\s*"
            r"(?:=|:|\bis\b|\bwas\b|\bholds\b|\breports\b)?\s*\**\s*"
            r"(?P<figure>" + NumericGroundingCheck.FIGURE.pattern + r")"),
        re.compile(
            r"`(?P<field>" + FIELD_NAME + r")`\s*(?:=|:)\s*\**\s*"
            r"(?P<figure>" + NumericGroundingCheck.FIGURE.pattern + r")"),
    )

    def __init__(self, config: GroundingConfig, *, ask: Optional[Ask] = None):
        super().__init__(config, ask=ask)
        #: The field names this mission's results actually carry, learned
        #: in :meth:`prepare` and read again in :meth:`repair_words` — the
        #: repair turn names real keys, and walking the evidence a second
        #: time to find them would be a second answer to what they are.
        self._known: set = set()

    def text(self, answer: str) -> str:
        """Prose with its **inline code kept**: the backticks are the grammar.

        A field name is quoted in an answer for the same reason it is
        quoted in a manifest, and :func:`prose_only` would delete every one
        of them before this check saw it.  Fenced code still goes — a
        program that assigns ``total_s = 154.024`` is proposing a
        computation and not attributing a figure — and so does the claim
        table, whose entries are :class:`ClaimGroundingCheck`'s to verify
        by walking.
        """
        return unfenced(CLAIM_BLOCK.sub(" ", answer or ""))

    def extract(self, answer: str) -> Iterable[str]:
        """Every ``field=figure`` pairing the prose states, once each."""
        answer = self._declocked(answer)
        found: List[str] = []
        for pattern in self.ATTRIBUTIONS:
            for match in pattern.finditer(answer):
                token = (match.group("field") + self.SEPARATOR
                         + match.group("figure"))
                if token not in found:
                    found.append(token)
        return found

    def prepare(self, evidence: Sequence[Any]) -> Sequence[Any]:
        """``(names, figures by name)`` from every result that may ground.

        Structured first: each text is parsed with :func:`json_blocks` and
        walked with :func:`harvest_fields`, which is what makes the value
        half of this check arithmetic rather than search.  Then
        :data:`KEY_IN_TEXT` over the raw text as well — always, not only
        where parsing failed — because a key spelled ``"total_s":`` in a
        result IS a key that result carries, and a name this check can see
        is a name it must not report as invented.  The fallback can only
        make the check kinder, never stricter.
        """
        names: set = set()
        figures: dict = {}
        for text, _found in self._grounding_texts(evidence):
            raw = str(text)
            for payload in json_blocks(raw):
                harvest_fields(payload, names, figures)
            for match in KEY_IN_TEXT.finditer(raw):
                names.add(match.group(1))
        self._known = names
        return (names, figures)

    def supported(self, token: str, evidence: Sequence[Any]) -> bool:
        """Whether the named field holds the figure beside it.

        Three answers, and the middle one is why the two halves of
        :meth:`prepare` are kept apart.  A field nothing carries is
        unsupported.  A field whose figures were read is supported when one
        of them is this figure, compared as a value and not as a spelling.
        A field seen only as a NAME — in a result nothing could parse, or
        as the key of a nested object — is **supported**: this check knows
        the account of provenance is not invented and cannot say more, and
        a check that reported its own blind spot as a finding would be
        putting its coverage into a governance report.
        """
        names, figures = evidence
        field, _, figure = token.partition(self.SEPARATOR)
        if field not in names:
            return False
        if field not in figures:
            return True
        value = _as_decimal(self._plain(figure))
        return value is not None and value in figures[field]

    def _detail(self, stated: int, failed: int) -> str:
        if not stated:
            detail = ("nothing to check — the answer pairs no figure with a "
                      "named field")
        else:
            detail = (f"{stated - failed}/{stated} figure(s) held by the "
                      f"field the answer names")
        if self._config.figures_from:
            detail += f"; scope: [{', '.join(self._config.figures_from)}]"
        return detail

    def repair_words(self, failed: Sequence[str]) -> str:
        """Which pairing failed, in which of the two ways, and the real keys.

        Wholly its own words: the generic sentence says the token appears
        in no tool output, and half of these figures appear in several.
        What is wrong is the label.
        """
        if not failed:
            return ""
        lines = ["That answer says which field each figure came from, and "
                 "these pairings are not what the results hold:"]
        invented = False
        for token in failed:
            field, _, figure = token.partition(self.SEPARATOR)
            if field in self._known:
                lines.append(
                    f"  `{field}` is a real field and holds no value "
                    f"{figure} anywhere in this mission's results")
            else:
                invented = True
                lines.append(
                    f"  `{field}` is not a field in any result of this "
                    f"mission; {figure} was attributed to a name nothing "
                    f"returned")
        if invented and self._known:
            named = ", ".join(sorted(self._known)[:self.NAMED])
            lines.append(
                f"Fields the results actually hold include: {named}.")
        lines.append(
            "Read the field back out of the result and quote it as it is "
            "spelled there, or drop the attribution and say only what the "
            "tool returned.")
        return "\n".join(lines)

    def caveat_words(self, failed: Sequence[str]) -> str:
        if not failed:
            return ""
        listed = ", ".join(
            token.replace(self.SEPARATOR, " = ") for token in failed)
        return (
            f"⚠️ Misattributed: this answer names the field each figure came "
            f"from and these are not what the results hold: {listed}. The "
            f"figures may be real; the account of where they came from is "
            f"not, and neither may be cited onward as sourced."
        )

    def remedy_words(self, failed: Sequence[str]) -> str:
        """None.  The base's direction is about where arithmetic belongs and
        this finding is about a label: a model told to move its arithmetic
        onto a computation plane because it misspelled a key would move the
        wrong thing."""
        return ""


class ClaimGroundingCheck(GroundingCheck):
    """Every figure beside the prose, as a path into what a tool returned.

    The complement to :class:`NumericGroundingCheck`, and the reason it is
    needed: a model told its figures are unsupported has an obvious way
    out, which is to write no figures.  Silence passes a fabrication check
    trivially, and the whole point of a synthesis is the numbers in it.

    So a drafting skill's ``output_format`` requires a **claim table**
    beside the prose — every figure emitted a second time as the path it
    came from::

        ```claims
        [{"value": 0.7446, "path": "gate.confidence"},
         {"value": 338.0, "path": "network.nodes[0].scores.out_weight"}]
        ```

    Verification is then arithmetic rather than search:
    :func:`~core.runtime.results.walk_path` — the same walker
    ``mission_result`` answers with — reads that path out of the payloads
    this mission actually received and compares the value.  A claim whose
    path does not resolve, or resolves to something else, is unsupported.
    Paired with a ``must_cite`` minimum ("a draft states at least three
    claims"), *delete all the numbers* stops being a winning move.

    Off unless a manifest sets ``claim_table``, like every other grammar
    here: requiring a table from a skill whose answers are prose would
    make the check a formatting complaint.
    """

    name = "claims"

    #: The fence the table is written in.  One spelling, because two
    #: spellings is a model guessing which one this deployment parses.
    BLOCK = CLAIM_BLOCK

    #: What a claim that could not be read is called in the report.  It is
    #: extracted rather than skipped: a table the harness cannot parse is a
    #: table nobody verified, and dropping it silently would make an
    #: unreadable claim table indistinguishable from a correct one.
    UNREADABLE = "unreadable claim table"

    def unconfigured(self) -> List[str]:
        if not self._config.claim_table:
            return [
                "no `claim_table` in the grounding block; a claim table is "
                "required only of skills whose answers carry figures"
            ]
        return []

    def text(self, answer: str) -> str:
        """The whole answer: this is the check that reads the table."""
        return answer

    def extract(self, answer: str) -> Iterable[str]:
        blocks = self.BLOCK.findall(answer or "")
        if not blocks:
            return
        for raw in blocks:
            try:
                claims = json.loads(raw)
            except json.JSONDecodeError as exc:
                yield f"{self.UNREADABLE}: {exc.msg} at line {exc.lineno}"
                continue
            if isinstance(claims, Mapping):
                claims = [claims]
            if not isinstance(claims, list):
                yield f"{self.UNREADABLE}: it holds a {type(claims).__name__}"
                continue
            for claim in claims:
                yield self._token(claim)

    @classmethod
    def _token(cls, claim: Any) -> str:
        """One claim as the string the report and the repair turn quote."""
        if not isinstance(claim, Mapping):
            return f"{cls.UNREADABLE}: a claim is an object, got {claim!r}"
        if "path" not in claim or "value" not in claim:
            return (
                f"{cls.UNREADABLE}: a claim is "
                f'{{"value": ..., "path": ...}}, got {sorted(claim)}'
            )
        return f"{claim['path']}={json.dumps(claim['value'], default=str)}"

    def prepare(self, evidence: Sequence[str]) -> Sequence[Any]:
        """Every tool payload that is JSON, parsed once.

        Once per check rather than once per claim: the evidence of a
        mission is the largest thing in reach and a draft can carry a
        dozen claims.
        """
        payloads: List[Any] = []
        for text in evidence:
            try:
                payloads.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                continue
        return payloads

    def supported(self, token: str, evidence: Sequence[Any]) -> bool:
        """Walk the claimed path and compare the claimed value.

        Any payload may answer it: a mission reads several tools and the
        claim carries the path, not the handle.  The value still has to
        match, so a path that happens to exist elsewhere supports nothing
        on its own.
        """
        path, _, raw = token.rpartition("=")
        if not path or token.startswith(self.UNREADABLE):
            return False
        try:
            claimed = json.loads(raw)
        except json.JSONDecodeError:
            return False

        for payload in evidence:
            found, problem = walk_path(payload, path)
            if problem:
                continue
            if _same_value(claimed, found):
                return True
        return False


def _same_value(claimed: Any, found: Any) -> bool:
    """Whether a claimed value is the value the payload holds.

    Numerically where both are numbers — ``338`` and ``338.0`` are the
    same out-weight, and a draft that rounded a display is not making a
    different claim — and exactly otherwise.
    """
    left, right = _as_decimal(claimed), _as_decimal(found)
    if left is not None and right is not None:
        return left == right
    if isinstance(claimed, str) and isinstance(found, str):
        return claimed.strip() == found.strip()
    return claimed == found


def _as_decimal(value: Any) -> Optional[Decimal]:
    """*value* as an exact decimal, or ``None`` if it is not a number.

    ``Decimal`` rather than ``float``: the figures in reach are scores and
    weights read out of JSON, and ``0.1 + 0.2`` arithmetic has no business
    deciding whether a governed number was fabricated.  ``bool`` is not a
    number here — ``True == 1`` is a Python fact, not a claim about a run.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    return None


class PlaneClaimCheck(GroundingCheck):
    """An answer may not claim a plane it never called.

    The other half of :attr:`GroundingConfig.tools_offered`, which until now
    was read only to derive what a check must *not* flag.  What it never
    asked was the opposite question: the answer says "I ran the code" — did
    anything on the code plane get dispatched this run?

    That failure is invisible to every other check here.  "I used the SDK to
    recompute the figure" contains no identifier, no figure and no claim
    table entry; it extracts nothing, so the mechanical tiers report
    ``nothing_considered`` and the answer comes back grounded while
    describing work that did not happen.  It is also the single most
    expensive sentence in a governance report to get wrong, because a reader
    who believes the SDK ran believes the number was computed rather than
    remembered.

    **What a plane is, is data.**  Which tools constitute "the SDK" and which
    phrases claim it arrive from the manifest as :class:`Plane` objects — a
    framework that hard-coded either would be naming another platform's tool
    families for it.  No ``planes:`` block, no check.

    The set of tools this run dispatched is **not** re-derived here.  It
    arrives through :meth:`GroundingCheck.observing` from the mission's own
    result store, which recorded each call as it was made; reading it back
    out of the conversation would be a second owner of the fact, and a
    second owner is what six-of-ten grounding fields looked like.
    """

    name = "planes"

    #: The separator between the plane's name and the phrase in a token.
    #: Both halves are in the token because a repair turn has to say *which*
    #: plane was claimed, and a reader has to see the words that claimed it.
    SEPARATOR = ": "

    def unconfigured(self) -> List[str]:
        if not self._config.planes:
            return [
                "no `planes` in the grounding block, so nothing here knows "
                "which tools are a plane on this platform or what an answer "
                "says when it claims one"
            ]
        return []

    def extract(self, answer: str) -> Iterable[str]:
        """Every plane-claiming phrase in the prose, as ``plane: phrase``.

        Case-insensitive substring, deliberately.  A model writes "I used
        the SDK", "we used the SDK to recompute" and "used the SDK for
        this" and all three are the claim; a phrase list that only matched
        whole sentences would be a list nobody could write correctly.
        """
        lowered = (answer or "").lower()
        found: List[str] = []
        for plane in self._config.planes:
            for phrase in plane.claims:
                if phrase.lower() in lowered:
                    found.append(f"{plane.name}{self.SEPARATOR}{phrase}")
        return found

    def supported(self, token: str, evidence: Sequence[str]) -> bool:
        """Whether **this run** dispatched a tool of the claimed plane.

        The evidence is not consulted at all, which is the one check here
        that reads nothing: what a tool *returned* is beside the point when
        the question is whether it was called.
        """
        name, _, _phrase = token.partition(self.SEPARATOR)
        plane = next((p for p in self._config.planes if p.name == name), None)
        if plane is None:                       # pragma: no cover - defensive
            return True
        return any(plane_matches(spec, called)
                   for spec in plane.tools for called in self._called)

    def _detail(self, stated: int, failed: int) -> str:
        if not stated:
            return ("nothing to check — the answer claims no plane this "
                    "skill named")
        called = ", ".join(self._called) or "nothing"
        return (f"{stated - failed}/{stated} plane claim(s) backed by a call "
                f"in this run; called: {called}")

    def repair_words(self, failed: Sequence[str]) -> str:
        if not failed:
            return ""
        lines = [
            "That answer says it used a tool plane that was never called in "
            "this mission. The claim is about what YOU did, so no tool "
            "output can support it and rewording it will not:",
        ]
        for token in failed:
            name, _, phrase = token.partition(self.SEPARATOR)
            plane = next(
                (p for p in self._config.planes if p.name == name), None)
            tools = ", ".join(plane.tools) if plane else ""
            lines.append(
                f"  {name}: the answer says {phrase!r} and nothing on this "
                f"plane ({tools}) was dispatched this run")
        lines.append(
            "Either call one of those tools and report what it returned, or "
            "delete the claim and say plainly how you actually arrived at "
            "the figures — from a tool result you already have, or not at "
            "all. This run dispatched: "
            + (", ".join(self._called) or "no tools."))
        return "\n".join(lines)

    def caveat_words(self, failed: Sequence[str]) -> str:
        if not failed:
            return ""
        listed = ", ".join(
            token.partition(self.SEPARATOR)[0] for token in failed)
        return (
            f"⚠️ Unperformed: this answer claims to have used {listed}, and "
            f"no tool of that plane was called in this mission. Whatever it "
            f"reports was not produced by the work it describes."
        )


#: Phrases an answer writes when its subject is the tool plane rather than
#: the objective.  Module data, closed, and short on purpose: every one of
#: them is a sentence ABOUT the run's instrumentation, and none of them is
#: a thing a person asked for.  Two of them together, or one of them beside
#: the name of a tool this run was offered, is the pattern
#: :class:`SubjectGroundingCheck` fires on.
#:
#: What is deliberately NOT in the list is any word for a failure of the
#: work itself — "could not", "no result", "not found".  A mission that
#: honestly reports the fetch returned 404 is answering the objective, and
#: a marker set that caught it would flag the most useful answer a run with
#: bad luck can produce.
META_MARKERS: Tuple[str, ...] = (
    "no tool",
    "not invoked",
    "was never called",
    "without a call to",
    "no evidence to cite",
    "registered tool",
    "not retrieved in this turn",
    "no call was made",
    "nothing was dispatched",
)

#: A prose sentence, for the proximity half of the rule.  A tool name and a
#: meta phrase in ONE sentence is the answer talking about the tool; the
#: same two words a paragraph apart are an answer that used a tool and
#: mentioned a limitation.
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


class SubjectGroundingCheck(GroundingCheck):
    """An answer whose subject is this run's tooling has not answered.

    The hole every other check here leaves open, and it was measured on the
    reference deployment on 19 August 2026.  Asked to build a small table
    and show it — a pure run-the-code objective — the model called nothing
    at all and wrote, in full: *"I could not determine whether a corpus
    exists … because no catalog or run-related tool was invoked in this
    turn. Without a call to a registered tool such as `…` I have no
    evidence to cite … the necessary information was not retrieved in this
    turn."*

    Every mechanical check passed it.  The identifier and figure grammars
    extracted nothing, so both reported ``nothing to check — the answer
    states no identifiers``, which under a skill with no ``must_cite`` is a
    legitimate verdict; there was no plane claim to be false, because the
    answer claims the opposite; and the run came back ``answered``.  The
    control was satisfied by an answer that discussed the harness instead
    of doing the work — which is the ``0/0`` lesson at the level of the
    SUBJECT rather than of the tokens.

    Three conditions, all of them, and each one closes a different way of
    getting this wrong:

    * **the run dispatched nothing.**  A mission that called a tool and
      then honestly reported what it could not establish is the answer this
      repository wants, and the commonest shape of it — "the fetch returned
      404, so the report cannot include the third source" — names a tool
      and a failure in one sentence.  With even one call this check is
      silent;
    * **nothing else in the answer had anything to check.**  Read off the
      rows the earlier checks already produced rather than by re-extracting
      the answer, so there is no second copy of the block's grammars here.
      An answer with real content — "the total is 48750, computed via the
      code tool" — gives the figures check something to consider and is
      never this finding, whatever else it mentions;
    * **the answer is about the tooling.**  Either a tool from THIS run's
      catalogue is named in the same sentence as a phrase from
      :data:`META_MARKERS`, or two different markers appear anywhere in it.
      The catalogue is the run's own, out of
      :attr:`GroundingConfig.tools_offered`, so a framework that has never
      heard of a deployment's tool names still recognises an answer
      reciting them.

    :data:`UNCONFIGURED` where nobody said how many calls the run made —
    see :meth:`GroundingCheck.observing`.  A library caller, a hand-built
    validator and the staged synthesizer all supply nothing, and silence is
    not zero: a check that read it as zero would report this finding about
    a run whose calls it cannot see.  That also means the check is
    unconfigured at :meth:`GroundingValidator.from_config` time, on
    purpose, so a grounding block that configures nothing else still builds
    no validator.
    """

    name = "subject"

    #: The one token this check ever considers.  A sentence rather than a
    #: fragment of the answer, because what failed is not a word in the
    #: text — it is what the text is about, and a report row quoting
    #: ``"without a call to"`` would send a reader looking for a phrase to
    #: delete.
    FINDING = "the answer's subject is this run's tooling, not the objective"

    def __init__(self, config: GroundingConfig, *, ask: Optional[Ask] = None):
        super().__init__(config, ask=ask)
        # Never a floor.  `must_cite: true` is a wildcard over every
        # configured check, and a minimum here would require every answer
        # under such a skill to BE a meta-answer — the requirement inverted
        # by a check whose `considered` is a defect and not a citation.  An
        # explicit `must_cite: subject` cannot reach this either: the check
        # is unconfigured at build time and `_audit_must_cite` refuses a
        # minimum on a check that reports no opinion.
        self._minimum = 0
        #: Why it fired, for the report row.  Set in :meth:`extract`.
        self._why: str = ""

    def unconfigured(self) -> List[str]:
        if self._calls is None:
            return [
                "nobody said how many tools this run called, and whether an "
                "answer is about the tool plane instead of the objective "
                "cannot be asked of a report that does not know whether any "
                "tool ran. A run supplies it; a library caller does not"
            ]
        return []

    def text(self, answer: str) -> str:
        """Prose with its **inline code kept**: a model names a tool in
        backticks, and :func:`prose_only` would delete the names this check
        is looking for.  Fenced code still goes."""
        return unfenced(CLAIM_BLOCK.sub(" ", answer or ""))

    def extract(self, answer: str) -> Iterable[str]:
        """:attr:`FINDING`, or nothing.  The three conditions, in cost order."""
        self._why = ""
        if self._calls:
            return ()
        if any(row.considered for row in self._so_far if row.configured):
            return ()
        why = self._about_the_tooling(answer)
        if not why:
            return ()
        self._why = why
        return (self.FINDING,)

    def _about_the_tooling(self, answer: str) -> str:
        """Why this answer is about the tool plane, or ``""``.

        The reason comes back rather than a bare boolean because it is what
        the report row says, and a row reading "the answer's subject is the
        tooling" with nothing behind it is a row a reader cannot check.
        """
        lowered = (answer or "").lower()
        spellings = self._tool_spellings()
        for sentence in _SENTENCE.split(lowered):
            markers = [m for m in META_MARKERS if m in sentence]
            named = [t for t in spellings if t in sentence]
            if markers and named:
                return (f"names {named[0]} beside {markers[0]!r} and no tool "
                        f"was called")
        found = [m for m in META_MARKERS if m in lowered]
        if len(found) >= 2:
            return (f"says {', '.join(repr(m) for m in found[:3])} and no "
                    f"tool was called")
        return ""

    def _tool_spellings(self) -> Tuple[str, ...]:
        """The catalogue's names as an ANSWER writes them, lower-cased.

        The offered name, and the same name with a leading namespace taken
        off: the MCP bridge prefixes a discovered server's tools so that one
        server cannot shadow another's, and a model writes the bare name it
        reads in the skill's prose.  Both are the tool.

        This is recognition and not comparison, which is why it is not
        :func:`~core.tools.descriptors.same_tool`: there is no second name
        here to compare with, only a sentence to look in.  Anything shorter
        than four characters is dropped rather than searched for — a
        two-letter tool name is a substring of ordinary prose, and a check
        that fired on it would be reading the word "go" as a catalogue
        entry.
        """
        found: List[str] = []
        for name in self._offered:
            for spelling in (str(name), str(name).split(".", 1)[-1]):
                spelling = spelling.lower().strip()
                if len(spelling) >= 4 and spelling not in found:
                    found.append(spelling)
        return tuple(found)

    def supported(self, token: str, evidence: Sequence[str]) -> bool:
        """Never.  Like :class:`PlaneClaimCheck` this reads no evidence: the
        finding is about what the run did and what the answer is about, and
        no tool output could bear on either."""
        return False

    def _detail(self, stated: int, failed: int) -> str:
        if not stated:
            return ("nothing to check — this run called a tool, or the "
                    "answer's subject is the objective")
        return f"the answer's subject is this run's tooling: {self._why}"

    def repair_words(self, failed: Sequence[str]) -> str:
        if not failed:
            return ""
        offered = ", ".join(self._offered) or "no tools"
        return (
            "That answer is about this mission's tooling rather than about "
            "the objective, and no tool was called in it. The objective is "
            "not about this run's tooling. Do the work: call the tool that "
            "does it, or answer the objective with what you have and name "
            "what is missing — without describing the tool plane. This "
            f"mission offers: {offered}."
        )

    def caveat_words(self, failed: Sequence[str]) -> str:
        if not failed:
            return ""
        return (
            "⚠️ Unattempted: this answer describes which tools were not "
            "called rather than answering the objective, and this mission "
            "dispatched none. Nothing in it was established by this run."
        )


class ReadingGroundingCheck(GroundingCheck):
    """Was the field read for what it is?  The tier that costs a model call.

    :class:`ClaimGroundingCheck` asks *is this value at this path?* and has
    a measured ceiling: on 10 August 2026 two agents on two harnesses each
    reported ``data.runs[0].total_s`` — a wall clock — as an influence
    score, and both figures are the honest contents of that path.  A
    membership check reports them supported and is right to.  The error is
    semantic, and :mod:`core.runtime.reading` is the instrument for it.

    This class is the *wiring* and nothing else.  Every prompt, the
    two-step design that keeps a reader from being anchored by the sentence
    it is judging, the cache, and the words a repair turn uses all live in
    :mod:`core.runtime.reading` and have one owner there.  What is decided
    here is where the tier sits in the order — **last**, after every
    mechanical check, because it is the only one that spends a model call
    and the cost argument is that it only pays for claims that already look
    fine.

    Off unless a manifest sets ``reading: true``, and it needs two more
    things before it can run: a ``claim_table``, which is where the path
    for each figure comes from, and an ``ask`` for
    :meth:`GroundingValidator.from_config`.  Missing either is reported as
    :data:`UNCONFIGURED` with the reason — never as a pass.
    """

    name = "reading"

    #: The fence the claim table is written in.  The same one
    #: :class:`ClaimGroundingCheck` reads, because it is the same table.
    BLOCK = CLAIM_BLOCK

    #: How many claims one answer may cost a reader.  Two calls each, minus
    #: whatever the per-field cache answers.  Beyond it the tier stops
    #: asking and says how many it looked at rather than quietly reviewing
    #: the first twelve of forty and reporting a clean pass.
    MAX_CLAIMS = 12

    #: A prose sentence.  Split on terminators followed by space or a line
    #: break, so a draft's bulleted findings are separate claims.
    SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

    def __init__(self, config: GroundingConfig, *, ask: Optional[Ask] = None):
        super().__init__(config, ask=ask)
        #: One reader per validator, so its per-field cache survives the
        #: repair turn: a mission that quotes five figures out of one view
        #: asks what that field holds once, and asks nothing at all on the
        #: second pass over the same fields.
        self._reader = (
            ReadingCheck(ask, max_claims=self.MAX_CLAIMS) if ask else None)
        self._sentences: dict = {}
        self._report = ReadingReport()

    @property
    def report(self) -> ReadingReport:
        """What the reader said about the last answer checked."""
        return self._report

    def unconfigured(self) -> List[str]:
        problems: List[str] = []
        if not self._config.reading:
            problems.append(
                "no `reading` in the grounding block; the field-misreading "
                "tier is the one that spends model calls and runs only where "
                "a skill asked for it")
            return problems
        if not self._config.claim_table:
            problems.append(
                "`reading: true` without `claim_table: true`; the tier reads "
                "the claim table for the path each figure came from")
        if self._reader is None:
            problems.append(
                "`reading: true` and no reader was supplied to the "
                "validator; the tier asks a model what each field holds and "
                "there is nothing here to ask")
        return problems

    def text(self, answer: str) -> str:
        """The whole answer: the table carries the paths and the prose the
        sentences, and this check needs both."""
        return answer

    def extract(self, answer: str) -> Iterable[str]:
        """Every claim-table entry that some sentence in the prose states.

        A claim nobody wrote a sentence about is not extracted.  The unit of
        this tier is *the claim*, and a figure that appears only in the
        machine-readable annex has not been asserted in words — there is no
        reading of it to be wrong about, and sending it to a reader would be
        paying for a question with no answer.
        """
        self._sentences = {}
        self._report = ReadingReport()
        prose = prose_only(self.BLOCK.sub(" ", answer or ""))
        sentences = [s.strip() for s in self.SENTENCE.split(prose) if s.strip()]
        found: List[str] = []
        for raw in self.BLOCK.findall(answer or ""):
            try:
                claims = json.loads(raw)
            except json.JSONDecodeError:
                # An unreadable table is `ClaimGroundingCheck`'s finding and
                # is reported there. Two checks reporting one broken fence
                # would be two rows for one defect.
                continue
            if isinstance(claims, Mapping):
                claims = [claims]
            if not isinstance(claims, list):
                continue
            for claim in claims:
                if not isinstance(claim, Mapping):
                    continue
                path = str(claim.get("path") or "")
                if not path or "value" not in claim:
                    continue
                sentence = self._sentence_for(claim["value"], sentences)
                if not sentence:
                    continue
                token = f"{path}={json.dumps(claim['value'], default=str)}"
                self._sentences[token] = sentence
                found.append(token)
        return found

    @classmethod
    def _sentence_for(cls, value: Any, sentences: Sequence[str]) -> str:
        """The first sentence that states *value*, or ``""``.

        Numerically for a number, because prose does not spell a payload's
        figures the way the payload does and a substring match would find
        none of the recorded cases:  ``1080`` is written ``1,080``, and see
        :meth:`_states` for the other two spellings the recording contains.

        This only decides **which sentence to ask the reader about**.  It is
        not a verification of anything and a wrong pairing costs one
        question about a sentence the answer really does contain, which is
        why it is allowed to be generous where the exact check beside it is
        not.
        """
        wanted = _as_decimal(value)
        for sentence in sentences:
            if wanted is None:
                if str(value) and str(value) in sentence:
                    return sentence
                continue
            for match in NumericGroundingCheck.FIGURE.finditer(sentence):
                found = _as_decimal(
                    NumericGroundingCheck._plain(match.group(0)))
                if found is not None and cls._states(wanted, found):
                    return sentence
        return ""

    @staticmethod
    def _states(wanted: "Decimal", found: "Decimal") -> bool:
        """Whether the figure *found* in prose is a rendering of *wanted*.

        Three ways, and each has a recorded case behind it:

        * **exactly** — ``80.847`` reported as ``80.847`` (Tai's draft);
        * **rounded for display** — ``80.889`` reported as ``80.89``
          (Goose's, and a pairing that insisted on all three decimals would
          miss the second of the two misreadings this tier exists for);
        * **as a percentage** — ``0.7446`` reported as ``74.46%`` and
          ``0.023169`` as ``2.3%``, which is how a proportion is written in
          a sentence and never how it is stored.

        Rounding is one-directional: the prose figure may have *fewer*
        decimals than the payload's, never more.  ``80.9`` in a payload is
        not stated by ``80.889`` in a sentence — that is a different number
        somebody would have had to compute.
        """
        if found == wanted:
            return True
        places = -found.as_tuple().exponent
        if places < 0:
            return False
        unit = Decimal(1).scaleb(-places)
        for candidate in (wanted, wanted * 100):
            try:
                if candidate.quantize(unit) == found:
                    return True
            except InvalidOperation:            # pragma: no cover - defensive
                continue
        return False

    def prepare(self, evidence: Sequence[str]) -> Sequence[Any]:
        """Every tool payload that is JSON, parsed once — the same shape
        :class:`ClaimGroundingCheck` walks, because it is the same walk."""
        payloads: List[Any] = []
        for text in evidence:
            try:
                payloads.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                continue
        return payloads

    def supported(self, token: str, evidence: Sequence[Any]) -> bool:
        """Ask the reader, and treat only an explicit *no* as a finding.

        An absent opinion — an unreachable reader, an unparseable reply, a
        reader that will not say what the field is — is **not** a
        misreading.  A tier whose own flakiness became findings would put
        its error rate into a governance report; the count of claims nobody
        answered for is in :meth:`_detail` instead.
        """
        path, _, _raw = token.rpartition("=")
        sentence = self._sentences.get(token, "")
        if self._reader is None or not sentence:  # pragma: no cover - guarded
            return True
        if len(self._report.verdicts) + len(self._report.skipped) \
                >= self.MAX_CLAIMS:
            return True
        report = self._reader.review([(path, sentence)], evidence)
        self._report = ReadingReport(
            verdicts=self._report.verdicts + report.verdicts,
            skipped=self._report.skipped + report.skipped,
        )
        return not any(v.misread for v in report.verdicts)

    def _detail(self, stated: int, failed: int) -> str:
        if not stated:
            return ("nothing to check — no figure in the claim table is "
                    "stated in the prose")
        unanswered = len(self._report.unanswered)
        detail = (f"{stated - failed}/{stated} figure(s) read for what the "
                  f"field holds")
        if unanswered:
            detail += (f"; {unanswered} the reader had no opinion on, which "
                       f"is not a pass")
        return detail

    def repair_words(self, failed: Sequence[str]) -> str:
        """:mod:`core.runtime.reading`'s own sentence.  One owner."""
        if not self._report.misread:
            return ""
        return ReadingCheck.repair_prompt(self._report)

    def caveat_words(self, failed: Sequence[str]) -> str:
        """Also reading's, for the same reason."""
        if not self._report.misread:
            return ""
        return ReadingCheck.caveat(self._report)


#: The order checks run in, and it is the **cost** order.  Identifiers
#: first: they are the finding a reader acts on, and a repair turn that
#: leads with them is the one most likely to be actionable.  Figures, the
#: attribution beside them, and claims next — still free, still arithmetic.
#: Planes after them: also free, but a statement about the run rather than
#: about the text.  Subject after ALL of those and not merely because it is
#: cheap: it asks whether anything else in the answer had something to
#: check, so every row it reads has to exist before it runs — see
#: :meth:`GroundingCheck.observing`'s ``so_far``.  Reading LAST, because it
#: is the only tier that spends a model call and the whole affordability
#: argument for it is that everything cheaper has already had its say.
DEFAULT_CHECKS: Tuple[type, ...] = (
    IdentifierGroundingCheck, NumericGroundingCheck, FieldAttributionCheck,
    ClaimGroundingCheck, PlaneClaimCheck, SubjectGroundingCheck,
    ReadingGroundingCheck,
)


# ---------------------------------------------------------------------------
# The composite
# ---------------------------------------------------------------------------

class GroundingValidator:
    """Run every check over one answer and say what to do next.

    The mission-tier analogue of :class:`~core.judge.judge.CompositeJudge`:
    a fixed sequence of checks, one report, and no fabricated opinion
    from a check that could not run.
    """

    def __init__(self, checks: Sequence[GroundingCheck], *, max_repairs: int = 1):
        self._checks = list(checks)
        self._max_repairs = max(0, int(max_repairs))

    @classmethod
    def from_config(
        cls, config: Optional[GroundingConfig],
        checks: Sequence[type] = DEFAULT_CHECKS,
        *, ask: Optional[Ask] = None,
    ) -> Optional["GroundingValidator"]:
        """A validator, or ``None`` when there is nothing to enforce.

        ``None`` rather than an empty validator: a mission with no
        grounding configuration runs exactly as it did before one
        existed, and nothing in its transcript claims it was checked.

        *ask* is ``prompt -> reply`` and is handed to **every** check
        rather than to the one that wants it, so this method never has to
        know which check is which.  Without one, a manifest that asked for
        ``reading: true`` gets a check that reports why it could not run —
        never one that reports a pass.
        """
        if config is None:
            return None
        built = [check(config, ask=ask) for check in checks]
        if not any(not c.unconfigured() for c in built):
            return None
        cls._audit_must_cite(config, built)
        return cls(built, max_repairs=config.max_repairs)

    @staticmethod
    def _audit_must_cite(
        config: GroundingConfig, built: Sequence["GroundingCheck"],
    ) -> None:
        """Refuse a ``must_cite`` that can never be satisfied or never bind.

        Both failures are silent otherwise, and both produce a mission that
        looks governed.  A minimum on a check this manifest did not
        configure never binds — the check reports no opinion and the
        requirement evaporates, which is the ``0/0`` hole wearing the
        clothes of the fix for it.  A minimum on a name no check answers to
        is a typo (``identifier`` for ``identifiers``) and does the same.
        """
        runnable = {c.name for c in built if not c.unconfigured()}
        known = {c.name for c in built}
        problems: List[str] = []
        for name, minimum in config.must_cite:
            if name == ANY_CHECK or not minimum:
                continue
            if name not in known:
                problems.append(
                    f"`must_cite` requires {minimum} from {name!r}, which is "
                    f"not a check this validator runs. Checks: "
                    f"{', '.join(sorted(known))}"
                )
            elif name not in runnable:
                problems.append(
                    f"`must_cite` requires {minimum} from {name!r} and this "
                    f"block does not configure that check, so it reports no "
                    f"opinion and the requirement never binds"
                )
        if problems:
            raise ValueError(
                "unusable grounding block:\n  - " + "\n  - ".join(problems)
            )

    @property
    def checks(self) -> List[GroundingCheck]:
        return list(self._checks)

    @property
    def max_repairs(self) -> int:
        return self._max_repairs

    def validate(self, answer: str, evidence: Sequence[str],
                 *, called: Sequence[str] = (),
                 calls: Optional[int] = None) -> GroundingReport:
        """Run every check over one answer.

        *called* is the tools this run actually dispatched, told to each
        check before it runs — see :meth:`GroundingCheck.observing`.  It
        defaults to empty so every caller that predates the plane-claim
        check keeps working; a caller that supplies nothing simply has no
        plane claims to support, which is the honest reading of "we do not
        know what was called".

        *calls* is how many dispatches there were, and its default is
        ``None`` and not ``0`` for the opposite reason: zero calls is a
        FINDING about a run, and reading a caller's silence as one would
        report it about every library caller and every staged synthesis.
        See :class:`SubjectGroundingCheck`, which is unconfigured without
        it.

        Each check is told the rows produced before it, so the ones whose
        question is partly about the rest of the report read them instead
        of re-deriving them.
        """
        evidence = list(evidence)
        results: List[CheckResult] = []
        for check in self._checks:
            check.observing(called, calls=calls, so_far=tuple(results))
            results.append(check.check(answer, evidence))
        return GroundingReport(results=tuple(results))

    # ── what the loop says next ─────────────────────────────────────────

    @staticmethod
    def repair_prompt(report: GroundingReport) -> str:
        """One turn, naming exactly what failed and in which direction.

        Two failures reach here and they need opposite instructions.  A
        model told "your figures are unsupported" and nothing else has an
        obvious way out — delete the figures — and that move is the one the
        second half of this prompt closes.
        """
        lines: List[str] = []

        # A check with words of its own is left OUT of the generic
        # paragraph rather than described twice. See `CheckResult.repair`:
        # the generic sentence is not vaguer for a misread field, it is
        # false, and a repair turn carrying both would contradict itself.
        generic = [r for r in report.results if r.unsupported and not r.repair]

        if generic:
            lines.append(
                "That answer contains claims no tool result in this mission "
                "supports. Every one of these appears in your answer and in "
                "no tool output you received:"
            )
            for result in generic:
                lines.append(
                    f"  {result.check}: "
                    + ", ".join(repr(t) for t in result.unsupported)
                )
            lines.append(
                "Either call a tool that returns them, or rewrite the answer "
                "without them and say plainly what could not be established "
                "about the objective — never by describing this run's "
                "tooling in the answer. Do not substitute a similar-looking "
                "value."
            )

        if report.uncited:
            lines.append(
                "That answer states less than this skill requires it to "
                "state. Removing what cannot be supported is not the same as "
                "supporting it:"
            )
            for result in report.results:
                if result.configured and not result.cited_enough:
                    lines.append(
                        f"  {result.check}: {len(result.considered)} stated, "
                        f"at least {result.minimum} required"
                    )
            lines.append(
                "Quote the values and identifiers the tool results actually "
                "returned, with the field each came from. If the tools "
                "genuinely returned nothing to cite, say that explicitly and "
                "name the calls you made — an empty answer is not a grounded "
                "one."
            )

        # A check's own finding, then its own direction out. Both are the
        # check's and they compose: `repair` REPLACES the generic sentence
        # for a check the generic sentence would state wrongly, and
        # `remedy` is owed whichever sentence stated the finding. See
        # `CheckResult.remedy` and the 121.2% the second one was written
        # after — a repair turn that names what is wrong and not what to do
        # instead gets the same answer back.
        for result in report.results:
            if not result.unsupported:
                continue
            if result.repair:
                lines.append(result.repair)
            if result.remedy:
                lines.append(result.remedy)

        lines.append("Reply with one JSON object as before.")
        return "\n".join(lines)

    @staticmethod
    def caveat(report: GroundingReport) -> str:
        """The abstention appended when a repair turn did not fix it."""
        parts: List[str] = []
        # The same partition the repair turn makes, and for the same reason:
        # "appears in no tool result" is the wrong sentence for a field that
        # is in the evidence and was read as the wrong quantity.
        generic: List[str] = []
        for result in report.results:
            if result.unsupported and not result.caveat:
                generic.extend(t for t in result.unsupported if t not in generic)
        if generic:
            listed = ", ".join(generic)
            parts.append(
                "⚠️ Ungrounded: the following appear in this answer and in no "
                f"tool result from this mission: {listed}. They were not "
                "established by this run and must not be relied on or cited "
                "onward."
            )
        for result in report.results:
            if result.unsupported and result.caveat:
                parts.append(result.caveat)
        if report.uncited:
            listed = ", ".join(report.uncited)
            parts.append(
                f"⚠️ Uncited: this answer states none of what the skill "
                f"requires it to cite ({listed}), so nothing in it was "
                "checked against a tool result. It carries no more support "
                "than an unsourced assertion and must not be relied on or "
                "cited onward."
            )
        if not parts:
            return ""
        return "\n\n---\n" + "\n\n".join(parts)
