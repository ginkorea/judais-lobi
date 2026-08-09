# core/judge/tiers.py — Scoring tiers for the Composite Judge
#
# TestTier (hard pass/fail), LintTier (soft-block), LLMReviewTier (real review).
#
# Each tier is pure logic: receives verification results as kwargs, returns
# TierResult. No subprocess calls, no ToolBus dependency — the caller runs the
# tools and passes the results. LLMReviewTier holds an injected `chat_fn` and
# not a client, so it keeps that property.

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from core.judge.models import TierResult, TierVerdict

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class BaseTier(ABC):
    """Base class for scoring tiers."""
    name: str = ""
    weight: float = 0.0

    @abstractmethod
    def evaluate(self, **kwargs) -> TierResult:
        """Evaluate this tier. kwargs contain verification results."""
        ...


class TestTier(BaseTier):
    """Hard pass/fail based on test suite exit code.

    Weight: 0.6. Short-circuits on failure (remaining tiers skipped).
    """
    name = "test"
    weight = 0.6

    def evaluate(self, *, test_exit_code: int = 1,
                 test_stdout: str = "", test_stderr: str = "",
                 **kw) -> TierResult:
        if test_exit_code == 0:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.PASS,
                score=1.0,
                weight=self.weight,
                details=test_stdout[:200] if test_stdout else "all tests passed",
            )
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.FAIL,
            score=0.0,
            weight=self.weight,
            details=(test_stderr or test_stdout)[:200],
            short_circuit=True,
        )


class LintTier(BaseTier):
    """Soft-block based on linter exit code.

    Weight: 0.25. Does not short-circuit.
    Supports lint waive: score 0.5 instead of 0.0 when waived.
    """
    name = "lint"
    weight = 0.25

    def evaluate(self, *, lint_exit_code: int = 1,
                 lint_stdout: str = "", lint_waive: bool = False,
                 **kw) -> TierResult:
        if lint_exit_code == 0:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.PASS,
                score=1.0,
                weight=self.weight,
                details="lint clean",
            )
        if lint_waive:
            return TierResult(
                tier_name=self.name,
                verdict=TierVerdict.WAIVED,
                score=0.5,
                weight=self.weight,
                details=lint_stdout[:200] if lint_stdout else "lint issues waived",
            )
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.FAIL,
            score=0.0,
            weight=self.weight,
            details=lint_stdout[:200] if lint_stdout else "lint failed",
        )


class LLMReviewTier(BaseTier):
    """Tiebreaker via LLM review of the diff.

    Weight: 0.15. Never short-circuits — an opinion about style does not
    get to stop a run whose tests passed.

    **An unavailable reviewer returns UNKNOWN, not 0.5.** This tier used
    to hand back a flat ``0.5`` labelled ``"stub: no LLM review
    performed"``, and downstream that number was indistinguishable from
    a reviewer that had genuinely read the diff and felt lukewarm. A
    fabricated midpoint is worse than an absent one: it moves the
    composite, it moves the verdict at the boundary, and nothing outside
    the details string says it was invented. ``CompositeJudge`` takes an
    UNKNOWN tier's weight out of the denominator, so a missing reviewer
    now costs nothing instead of silently costing 0.15.

    The tier stays pure — it holds a ``chat_fn``, never a client, a
    ToolBus or a subprocess, exactly as the other two hold none. Build
    one from an agent with :meth:`from_agent`.
    """
    name = "llm_review"
    weight = 0.15

    #: What the reviewer is asked for: one JSON object with a 0..1 score,
    #: a verdict, and at most three concrete concerns. Prose is not
    #: requested, because prose is what gets skimmed and then quoted as
    #: though it were a finding.
    PROMPT = (
        "You are reviewing a proposed code change. The test suite and the "
        "linter have already run and are scored separately — do not repeat "
        "them. Judge only what they cannot see: correctness the tests miss, "
        "unsafe handling, misleading names, dead or duplicated logic.\n\n"
        "Reply with exactly one JSON object and nothing else:\n"
        '{"score": <0.0-1.0>, "verdict": "pass"|"fail", '
        '"concerns": ["...", "..."]}\n\n'
        "score 1.0 = nothing to raise. 0.0 = a defect you would block on. "
        "List at most three concerns, each naming the specific thing. An "
        "empty concerns list with a low score is not useful; if you cannot "
        "name the problem, the score is high."
    )

    def __init__(self, chat_fn: Optional[Callable[[List[Dict]], Any]] = None,
                 max_diff_chars: int = 6000):
        self._chat = chat_fn
        self._max_diff_chars = max_diff_chars

    @classmethod
    def from_agent(cls, agent, **kw) -> "LLMReviewTier":
        """A tier that reviews through an agent's configured backend."""
        def chat_fn(messages):
            return agent.client.chat(model=agent.model, messages=messages,
                                     stream=False)
        return cls(chat_fn, **kw)

    @property
    def available(self) -> bool:
        return self._chat is not None

    def evaluate(self, *, diff: str = "", **kw) -> TierResult:
        if self._chat is None:
            return self._unknown(
                "no reviewer configured: this tier was built without a "
                "chat_fn, so nothing read the diff"
            )
        if not (diff or "").strip():
            return self._unknown("nothing to review: no diff reached the judge")

        body = diff[:self._max_diff_chars]
        truncated = len(diff) > self._max_diff_chars
        messages = [
            {"role": "system", "content": self.PROMPT},
            {"role": "user", "content": (
                (f"[diff truncated to the first {self._max_diff_chars} "
                 f"characters]\n" if truncated else "") + body
            )},
        ]

        try:
            reply = self._chat(messages)
        except Exception as exc:  # noqa: BLE001 — any failure is "no opinion"
            return self._unknown(
                f"reviewer unreachable: {type(exc).__name__}: {exc}"
            )

        parsed, problem = self._parse(str(reply or ""))
        if problem:
            return self._unknown(problem)

        concerns = parsed["concerns"]
        return TierResult(
            tier_name=self.name,
            verdict=(TierVerdict.PASS if parsed["verdict"] == "pass"
                     else TierVerdict.FAIL),
            score=parsed["score"],
            weight=self.weight,
            details=("; ".join(concerns)[:200] if concerns
                     else "no concerns raised"),
        )

    def _unknown(self, why: str) -> TierResult:
        """No opinion. The reason is the useful part of the report."""
        return TierResult(
            tier_name=self.name,
            verdict=TierVerdict.UNKNOWN,
            score=0.0,
            weight=self.weight,
            details=why[:200],
        )

    @staticmethod
    def _parse(reply: str):
        """Return ``(parsed, problem)``; exactly one is truthy.

        A reply this cannot read is UNKNOWN and never a guess. Scoring a
        malformed answer at its apparent sentiment is how a reviewer that
        returned an apology becomes a 0.4.
        """
        text = _FENCE.sub("", reply.strip()).strip()
        if not text:
            return None, "reviewer returned nothing"
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, f"reviewer reply was not JSON ({exc.msg})"
        if not isinstance(data, dict):
            return None, (f"reviewer returned a {type(data).__name__}, "
                          f"not an object")

        raw = data.get("score")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None, f"reviewer gave a non-numeric score: {raw!r}"
        score = float(raw)
        if not 0.0 <= score <= 1.0:
            return None, f"reviewer gave a score outside 0..1: {score}"

        verdict = str(data.get("verdict") or "").strip().lower()
        if verdict not in ("pass", "fail"):
            return None, f"reviewer gave an unrecognised verdict: {verdict!r}"

        raw_concerns = data.get("concerns") or []
        if not isinstance(raw_concerns, list):
            return None, "reviewer's concerns were not a list"
        concerns = [str(c).strip() for c in raw_concerns if str(c).strip()]

        return {"score": score, "verdict": verdict, "concerns": concerns}, None
