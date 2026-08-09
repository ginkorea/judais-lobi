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
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple


class GroundingMisdeclared(TypeError):
    """A check subclass is unusable, with every reason in one message."""


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
    #: Literals that match a pattern but are not claims — placeholders,
    #: field names, the platform's own word for "none".
    ignore: Tuple[str, ...] = ()
    #: Repair turns before the caveat. Zero goes straight to the caveat.
    max_repairs: int = 1

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

        known = {"identifier_pattern", "number_pattern", "ignore", "max_repairs"}
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
            ignore=tuple(str(item) for item in ignore),
            max_repairs=repairs,
        )


@dataclass(frozen=True)
class CheckResult:
    """One check's opinion, or its explicit lack of one."""

    check: str
    #: False means *this check could not run*. It is not a pass.
    configured: bool = True
    considered: Tuple[str, ...] = ()
    unsupported: Tuple[str, ...] = ()
    detail: str = ""

    @property
    def grounded(self) -> bool:
        """True only when the check ran and found nothing unsupported."""
        return self.configured and not self.unsupported


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
    def grounded(self) -> bool:
        """Every configured check passed.

        A report where nothing was configured is **not** grounded: it is
        a report with no opinion, and callers ask :attr:`ran` first.
        """
        return self.ran and all(
            r.grounded for r in self.results if r.configured
        )


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

class GroundingCheck(ABC):
    """One way of asking whether an answer's claims came from a tool.

    A subclass supplies :meth:`extract` — which tokens in the answer are
    claims of its kind — and may narrow :meth:`supported` and
    :meth:`unconfigured`.  :meth:`check` is the template and is
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

    def __init__(self, config: GroundingConfig):
        self._config = config
        self._ignore = frozenset(config.ignore)

    @property
    def config(self) -> GroundingConfig:
        return self._config

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

        considered: List[str] = []
        for token in self.extract(answer or ""):
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
            detail=(
                f"{len(considered) - len(unsupported)}/{len(considered)} "
                f"supported by a tool result in this run"
            ),
        )

    # ── what a subclass supplies ────────────────────────────────────────

    @abstractmethod
    def extract(self, answer: str) -> Iterable[str]:
        """The tokens in *answer* this check is responsible for."""
        raise NotImplementedError

    def unconfigured(self) -> List[str]:
        """Why this check cannot run, or an empty list."""
        return []

    def ignored(self, token: str) -> bool:
        return token in self._ignore

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

    def prepare(self, evidence: Sequence[str]) -> Sequence[str]:
        """Evidence as written, and again with separators stripped."""
        return [*evidence, *(self._plain(text) for text in evidence)]

    def supported(self, token: str, evidence: Sequence[str]) -> bool:
        """A figure is supported as written or with its separators gone.

        ``12,481`` in a draft and ``12481`` in the payload it was read
        from are the same figure, in either direction, and failing that
        pair would make the check a formatting complaint that whoever
        reads the report soon learns to skip.
        """
        return (
            super().supported(token, evidence)
            or super().supported(self._plain(token), evidence)
        )

    @classmethod
    def _plain(cls, text: str) -> str:
        for separator in cls.SEPARATORS:
            text = text.replace(separator, "")
        return text


#: The order checks run in. Identifiers first: they are the finding a
#: reader acts on, and a repair turn that leads with them is the one
#: most likely to be actionable.
DEFAULT_CHECKS: Tuple[type, ...] = (IdentifierGroundingCheck, NumericGroundingCheck)


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
        cls, config: Optional[GroundingConfig], checks: Sequence[type] = DEFAULT_CHECKS,
    ) -> Optional["GroundingValidator"]:
        """A validator, or ``None`` when there is nothing to enforce.

        ``None`` rather than an empty validator: a mission with no
        grounding configuration runs exactly as it did before one
        existed, and nothing in its transcript claims it was checked.
        """
        if config is None:
            return None
        built = [check(config) for check in checks]
        if not any(not c.unconfigured() for c in built):
            return None
        return cls(built, max_repairs=config.max_repairs)

    @property
    def checks(self) -> List[GroundingCheck]:
        return list(self._checks)

    @property
    def max_repairs(self) -> int:
        return self._max_repairs

    def validate(self, answer: str, evidence: Sequence[str]) -> GroundingReport:
        evidence = list(evidence)
        return GroundingReport(
            results=tuple(check.check(answer, evidence) for check in self._checks),
        )

    # ── what the loop says next ─────────────────────────────────────────

    @staticmethod
    def repair_prompt(report: GroundingReport) -> str:
        """One turn, naming exactly what could not be supported."""
        lines = [
            "That answer contains claims no tool result in this mission "
            "supports. Every one of these appears in your answer and in no "
            "tool output you received:",
        ]
        for result in report.results:
            if result.unsupported:
                lines.append(
                    f"  {result.check}: "
                    + ", ".join(repr(t) for t in result.unsupported)
                )
        lines.append(
            "Either call a tool that returns them, or rewrite the answer "
            "without them and say plainly what the tools could not establish. "
            "Do not substitute a similar-looking value. Reply with one JSON "
            "object as before."
        )
        return "\n".join(lines)

    @staticmethod
    def caveat(report: GroundingReport) -> str:
        """The abstention appended when a repair turn did not fix it."""
        listed = ", ".join(report.unsupported)
        return (
            "\n\n---\n"
            "⚠️ Ungrounded: the following appear in this answer and in no "
            f"tool result from this mission: {listed}. They were not "
            "established by this run and must not be relied on or cited "
            "onward."
        )
