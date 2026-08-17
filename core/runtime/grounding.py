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
from core.runtime.results import walk_path
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
    text = FENCED_CODE.sub(" ", answer or "")
    head, fence, _unclosed = text.partition("```")
    if fence:
        text = head
    return INLINE_CODE.sub(" ", text)


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
                 "critic", "planes"}
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
        #: The tools this mission offered. Compared with
        #: :func:`~core.tools.descriptors.same_tool`, so every spelling of
        #: one is covered. See :meth:`GroundingConfig.offering` for why
        #: this is derived and the manifest's ``ignore`` list is not.
        self._offered = tuple(config.tools_offered)
        self._minimum = config.minimum_for(self.name)

    @property
    def config(self) -> GroundingConfig:
        return self._config

    def observing(self, called: Sequence[str]) -> None:
        """Told which tools this run dispatched, before :meth:`check` runs.

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
        """
        self._called = tuple(
            str(name) for name in called if str(name or "").strip())

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
        evidence = [typographic_plain(str(text or "")) for text in evidence]

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
    """Every figure must have come back from a tool.

    Off unless a manifest sets ``number_pattern``, and deliberately so:
    an answer legitimately contains numbers it computed — "3 assets",
    "two of the four" — and a check that flagged those would train
    whoever reads the report to ignore it.  A platform that wants
    figures checked writes a pattern narrow enough to mean it.
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
        pattern = re.compile(self._config.number_pattern)
        for match in pattern.finditer(answer):
            yield match.group(1) if match.groups() else match.group(0)

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

    def prepare(self, evidence: Sequence[str]) -> Sequence[Any]:
        """Every figure in the evidence, as an exact decimal.

        Extracted **structurally** and compared **numerically**, which is
        the whole substance of this check.  The obvious implementation —
        ``token in text`` — reports ``0.387`` as supported by an unrelated
        pagerank of ``10.3871``, because it is a substring of it.  That is
        not a corner case: scores share digits, a fabricated figure only
        has to be a substring of a real one somewhere in a governed view
        to be laundered into a grounded answer, and the bigger the payload
        the likelier it is.
        """
        figures = set()
        for text in evidence:
            for match in self.FIGURE.finditer(str(text or "")):
                value = _as_decimal(self._plain(match.group(0)))
                if value is not None:
                    figures.add(value)
        return sorted(figures)

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
#: leads with them is the one most likely to be actionable.  Figures and
#: claims next — still free, still arithmetic.  Planes after them: also
#: free, but a statement about the run rather than about the text.
#: Reading LAST, because it is the only tier that spends a model call and
#: the whole affordability argument for it is that everything cheaper has
#: already had its say.
DEFAULT_CHECKS: Tuple[type, ...] = (
    IdentifierGroundingCheck, NumericGroundingCheck, ClaimGroundingCheck,
    PlaneClaimCheck, ReadingGroundingCheck,
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
                 *, called: Sequence[str] = ()) -> GroundingReport:
        """Run every check over one answer.

        *called* is the tools this run actually dispatched, told to each
        check before it runs — see :meth:`GroundingCheck.observing`.  It
        defaults to empty so every caller that predates the plane-claim
        check keeps working; a caller that supplies nothing simply has no
        plane claims to support, which is the honest reading of "we do not
        know what was called".
        """
        evidence = list(evidence)
        results = []
        for check in self._checks:
            check.observing(called)
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
                "without them and say plainly what the tools could not "
                "establish. Do not substitute a similar-looking value."
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

        for result in report.results:
            if result.unsupported and result.repair:
                lines.append(result.repair)

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
