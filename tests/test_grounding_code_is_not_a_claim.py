# tests/test_grounding_code_is_not_a_claim.py

"""Code is not a claim, and code that ran grounds its values.

The measured failure, August 2026, TAIPAN's hosted mission pane on
gpt-oss-20b: the analyst asked "plot sin, cos and tan using python", the
agent wrote correct matplotlib code, and the validator flagged the ANSWER
as fabricated.  ``np.linspace`` and ``plt.subplots`` match the dotted
identifier grammar exactly the way ``labels.7a19c4e2.taxonomy9f`` does,
``0.01`` matches the figure grammar the way an invented confidence does,
and no tool returns matplotlib's API — so a working script shipped under
a "not supported by its tools" banner.  A check that flags working code
is a check its reader learns to skip, which un-catches the fabrications
it exists for.

The principle this file pins has two halves:

* **prose asserts, code proposes.**  Prose states facts about the world
  and must ground in a tool result of this run.  Code is a proposed
  computation; its grounding is the RESULT of running it, not prior
  evidence.  So fenced and inline code are stripped before the prose
  checks extract, and prose outside the fences keeps full scrutiny —
  each half has a mutation test below.  Remove the stripping
  (``prose_only``) and :class:`TestCodeIsNotAClaim` goes red; weaken the
  prose check and :class:`TestProseKeepsFullScrutiny` goes red, alongside
  the recorded-fabrication suite.
* **code that ran grounds its values.**  When an execution tool's result
  is in the store, the numbers it printed are legitimate evidence for
  prose citing them.  No special-casing was needed to make that true —
  ``MissionResultStore.evidence_texts()`` already hands over every
  successful result's ``text``, whatever tool produced it — so
  :class:`TestCodeThatRanGroundsItsValues` pins the contract instead:
  an execution result is an ordinary stored result, stdout in ``text``,
  ``exit_code`` 0 for a run that succeeded.  That is the shape TAIPAN's
  ``run_code`` has to record in, and this file is where the two sides
  agree on it.
"""

import json

import pytest

from core.runtime.grounding import (
    NOTHING_CONSIDERED,
    GroundingConfig,
    GroundingValidator,
    prose_only,
)
from core.runtime.results import MissionResultStore

# The deployed grammars, imported rather than retyped: this file's claim is
# that the recorded failure reproduces under the configuration that produced
# it, and a copy would let the two drift until it no longer does.
from tests.test_grounding_catches_the_recorded_fabrication import (
    FIGURE_GRAMMAR,
    IDENTIFIER_GRAMMAR,
)

#: The answer class from the recording: correct prose around correct code,
#: full of tokens the grammars match.  ``np.linspace``/``plt.subplots`` for
#: the identifier check, ``0.01`` and the figsize floats for the figures
#: check.  Not a verbatim transcript — what was recorded is the banner over
#: an answer of exactly this shape.
PLOT_ANSWER = (
    "Here is a script that plots all three functions in one figure.\n"
    "\n"
    "```python\n"
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "\n"
    "x = np.linspace(-2 * np.pi, 2 * np.pi, 2000)\n"
    "fig, axes = plt.subplots(3, 1, figsize=(8.5, 10.0))\n"
    "axes[0].plot(x, np.sin(x))\n"
    "axes[1].plot(x, np.cos(x))\n"
    "tan = np.tan(x)\n"
    "tan[np.abs(tan) > 50] = np.nan  # blank the asymptotes\n"
    "axes[2].plot(x, tan)\n"
    "plt.tight_layout(pad=0.01)\n"
    "plt.show()\n"
    "```\n"
    "\n"
    "Run it and the three plots open stacked in one window."
)

#: Every token the August 2026 banner was built from.  None may be
#: extracted from the answer above once code is code.
FLAGGED_IN_AUGUST = ("np.linspace", "plt.subplots", "np.sin", "np.cos",
                     "np.tan", "plt.show", "0.01", "8.5", "10.0")

#: A dotted identifier that is an invention wherever it appears in PROSE.
#: The spelling `labels.<hex>.<word>` is the module docstring's own example
#: of an unverifiable-by-reading token.
INVENTED_ID = "labels.7a19c4e2.taxonomy9f"


@pytest.fixture
def validator():
    return GroundingValidator.from_config(GroundingConfig(
        identifier_pattern=IDENTIFIER_GRAMMAR,
        number_pattern=FIGURE_GRAMMAR,
        ignore=("e.g", "i.e")))


class TestCodeIsNotAClaim:
    """The mutation test for the stripping: remove `prose_only` from
    `GroundingCheck.text` and every test here goes red."""

    def test_the_recorded_failure_no_longer_reproduces(self, validator):
        """The plot answer, over a mission whose tools returned nothing
        relevant — which is the live case: no tool returns matplotlib."""
        report = validator.validate(PLOT_ANSWER, [])
        assert report.grounded, (
            f"a correct script is reported as fabrication again: "
            f"{report.unsupported}")
        assert report.unsupported == ()

    def test_nothing_inside_the_fence_is_even_considered(self, validator):
        """Considered, not just unsupported: a code token that happened to
        match some evidence would still be the check reading code, one
        payload away from flagging it."""
        report = validator.validate(PLOT_ANSWER, [])
        for result in report.results:
            if not result.configured:
                continue
            assert result.verdict == NOTHING_CONSIDERED, result
            for token in FLAGGED_IN_AUGUST:
                assert token not in result.considered

    def test_inline_code_is_code(self, validator):
        report = validator.validate(
            "Call `plt.subplots` once, then `np.linspace(0, 6.28, 500)` "
            "for the x axis.", [])
        assert report.grounded
        assert report.unsupported == ()

    def test_an_unterminated_fence_is_still_code(self, validator):
        """A model that opened a block and hit its token budget was writing
        code when it stopped; the truncated tail is not prose that resumed."""
        opened = PLOT_ANSWER[:PLOT_ANSWER.index("plt.show()")]
        assert opened.count("```") == 1  # the closing fence is gone
        report = validator.validate(opened, [])
        assert report.grounded, report.unsupported

    def test_a_stray_backtick_does_not_swallow_the_answer(self, validator):
        """The inline grammar is bounded to one line, so one typo'd backtick
        must not turn the rest of a paragraph into exempt "code"."""
        report = validator.validate(
            f"One ` slipped in here.\nThe labels are {INVENTED_ID}.", [])
        assert INVENTED_ID in report.unsupported


class TestProseKeepsFullScrutiny:
    """The other mutation: point 3 of the fix.  Exempting code must not
    have weakened prose checking by a token — an invented run-id beside a
    correct script is still an invented run-id."""

    def test_an_invented_id_in_prose_beside_correct_code_still_flags(
            self, validator):
        answer = PLOT_ANSWER + (
            f"\n\nThe curve labels come from the run's label set "
            f"{INVENTED_ID}.")
        report = validator.validate(answer, [])
        assert INVENTED_ID in report.unsupported
        assert not report.grounded
        # And the exemption did not leak the other way: the banner tokens
        # stay out of the report even while it fails.
        for token in FLAGGED_IN_AUGUST:
            assert token not in report.unsupported

    def test_an_invented_figure_in_prose_still_flags(self, validator):
        answer = PLOT_ANSWER + (
            "\n\nThe gate settled at a confidence of 0.7448.")
        report = validator.validate(answer, [])
        assert "0.7448" in report.unsupported

    def test_the_claim_table_is_still_read_through_the_stripping(self):
        """`ClaimGroundingCheck` overrides `text` to see the whole answer;
        the fence-stripping must not blind it to its own fenced table."""
        validator = GroundingValidator.from_config(GroundingConfig(
            identifier_pattern=IDENTIFIER_GRAMMAR,
            claim_table=True))
        answer = (
            "The gate held.\n\n```claims\n"
            + json.dumps([{"value": 0.7446, "path": "gate.confidence"}])
            + "\n```")
        report = validator.validate(answer, ['{"gate": {"confidence": 0.7446}}'])
        claims = next(r for r in report.results if r.check == "claims")
        assert claims.considered == ("gate.confidence=0.7446",)
        assert claims.unsupported == ()


class TestProseOnly:
    """The seam itself, small enough to pin exhaustively."""

    def test_prose_between_two_blocks_is_kept(self):
        text = prose_only("```a\ncode\n``` middle prose ```b\nmore\n```")
        assert "middle prose" in text
        assert "code" not in text and "more" not in text

    def test_empty_and_none_are_survivable(self):
        assert prose_only("") == ""
        assert prose_only(None) == ""


class TestCodeThatRanGroundsItsValues:
    """The contract with TAIPAN's `run_code`, stated where both sides can
    read it: an execution result is recorded like any other tool result —
    stdout in `text`, `exit_code` 0 on success — and `evidence_texts()`
    then makes its printed values evidence for prose that cites them.
    Nothing keys on the tool's name; the shape is the whole contract.
    """

    def test_stdout_of_a_successful_run_is_evidence(self, validator):
        store = MissionResultStore()
        store.record(
            "mcp.run_code",
            {"code": "print(f'peak gradient {max(g):.4f}')"},
            text="peak gradient 3.1416\n",
            exit_code=0)
        assert any("3.1416" in text for text in store.evidence_texts())

        report = validator.validate(
            "The computed peak gradient is 3.1416.", store.evidence_texts())
        assert report.grounded and report.verified, report.unsupported

    def test_a_failed_run_grounds_nothing(self, validator):
        """`evidence_texts()` skips non-zero exits, and an execution that
        crashed is one: a figure quoted out of a traceback is not a
        computed result, however plausible it looks."""
        store = MissionResultStore()
        store.record(
            "mcp.run_code", {"code": "..."},
            text="Traceback (most recent call last): gradient was 3.1416",
            exit_code=1)
        report = validator.validate(
            "The computed peak gradient is 3.1416.", store.evidence_texts())
        assert "3.1416" in report.unsupported

    def test_the_shape_not_the_name_is_the_contract(self, validator):
        """Whatever TAIPAN ends up calling the tool, its result grounds the
        same way, because the store treats every tool alike."""
        store = MissionResultStore()
        store.record("mcp.execute_python", {}, text="count=12481\n",
                     exit_code=0)
        report = validator.validate(
            "The scan counted 12,481 records.", store.evidence_texts())
        assert report.grounded, report.unsupported
