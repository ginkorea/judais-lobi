# tests/test_grounding_catches_the_recorded_fabrication.py

"""The 10 August 2026 fabrication, replayed through the real validator.

A permanent regression fixture. On 10 August two agents on the same 20B base
model — one carrying a governance persona, one carrying none — independently
reported "total influence strength 80.847" over a run whose
`total_causal_influence` is 0.0. The figure appears in no tool result.

`NumericGroundingCheck` is the check built for exactly that input, and it did
not run, because it only activates when a skill manifest supplies a
`grounding:` block and the mission was launched with no `--skill` at all. So
this file asserts the two things that were never asserted together:

* configured as the manifests now configure it, the validator **fails** that
  draft and names the figure;
* configured without a `number_pattern`, it reports `configured: false` and
  **not** grounded — because the difference between a control and a decoration
  is entirely whether a check that could not run says so.

The evidence below is what the mission's tools returned, in the shape
`MissionResultStore.evidence_texts()` hands to the validator: whole tool
payloads, untruncated. Every figure in it is one the 10 August graders
confirmed against the run.
"""

import pytest

from core.runtime.grounding import (
    GroundingConfig,
    GroundingValidator,
    NumericGroundingCheck,
)

# ── the recorded answer, trimmed to its figure-bearing sentences ─────────────
DRAFT = (
    "In the most recent finished influence run the causal-influence model "
    "analyzed 127 distinct actors inter-acting through 1,080 directed edges, "
    "revealing a tightly-connected network clustered into three communities "
    "with a community-detection confidence of 0.7446. The overall influence "
    "score, a summed measure of out-flow and in-flow centrality across the "
    "network, reached 80.847, indicating a relatively high magnitude of "
    "propagated influence across the Weibo-based corpus. The actor who most "
    "strongly propagated the narratives was account 6436464948, which earned "
    "an out-weight of 338.0 and an in-weight of 1,081.0."
)

#: What `runs_list` and `runs_get` actually returned, as the store keeps them.
EVIDENCE = [
    '{"runs": [{"run_id": "a971d4c4149c", "stage": "gate", '
    '"node_count": 127, "edge_count": 1080, "blocks": 3}]}',
    '{"provenance": {"run_id": "a971d4c4149c", '
    '"corpus_hash": "04349a489b2a1457", "seed": 7}, '
    '"network": {"node_count": 127, "edge_count": 1080, '
    '"nodes": [{"actor_id": "6436464948", '
    '"scores": {"out_weight": 338.0, "in_weight": 1081.0, '
    '"pagerank": 0.036}}]}, '
    '"blocks": [{"community": 0, "total_causal_influence": 0.0}, '
    '{"community": 1, "total_causal_influence": 0.0}, '
    '{"community": 2, "total_causal_influence": 0.0}], '
    '"gate": {"decision": 3, "confidence": 0.7446}}',
]

#: As `run_inspection/SKILL.md` now declares it.
AS_DECLARED = GroundingConfig(
    identifier_pattern=r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b",
    number_pattern=r"\b\d+\.\d{2,}\b",
    ignore=("e.g", "i.e", "report_view.json", "manifest.json", "packet.json"),
    max_repairs=1,
)

FABRICATION = "80.847"


@pytest.fixture()
def validator():
    built = GroundingValidator.from_config(AS_DECLARED)
    assert built is not None, "the declared config produced no validator"
    return built


class TestTheFabricationIsCaught:
    def test_the_report_is_not_grounded(self, validator):
        report = validator.validate(DRAFT, EVIDENCE)
        assert report.ran
        assert not report.grounded

    def test_the_invented_figure_is_named(self, validator):
        report = validator.validate(DRAFT, EVIDENCE)
        assert FABRICATION in report.unsupported, (
            f"the validator did not name {FABRICATION!r}. It is the whole "
            f"reason this fixture exists: unsupported={report.unsupported}")

    def test_the_real_figures_are_not_named(self, validator):
        """The confidence and the weights DID come back from `runs_get`.

        A check that flagged them would be a check whoever reads the report
        learns to skip, and a skipped report is no report with extra steps.
        """
        report = validator.validate(DRAFT, EVIDENCE)
        for real in ("0.7446", "338.0", "1081.0"):
            assert real not in report.unsupported, (
                f"{real} came back from a tool and was flagged anyway: "
                f"{report.unsupported}")

    def test_the_repair_turn_quotes_the_figure(self, validator):
        """A repair turn that does not name the token is unactionable."""
        report = validator.validate(DRAFT, EVIDENCE)
        prompt = validator.repair_prompt(report)
        assert FABRICATION in prompt
        assert "similar-looking" in prompt, (
            "the repair turn does not close the substitution move, which is "
            "the fluent thing a weak model reaches for under challenge")

    def test_an_unrepaired_answer_keeps_its_text_and_gains_a_caveat(
            self, validator):
        report = validator.validate(DRAFT, EVIDENCE)
        caveat = validator.caveat(report)
        assert FABRICATION in caveat
        assert "must not be relied on" in caveat


class TestTheMutations:
    """Change one thing at a time and the verdict has to move."""

    def test_a_draft_without_the_fabrication_is_grounded(self, validator):
        clean = DRAFT.replace(
            "reached 80.847, indicating a relatively high magnitude of "
            "propagated influence across the Weibo-based corpus",
            "is recorded as 0.0 for all three blocks, so this run measures "
            "propagation volume and not effect")
        report = validator.validate(clean, EVIDENCE)
        assert report.grounded, (
            f"a draft quoting only figures the run returned is reported as "
            f"ungrounded: {report.unsupported}")

    def test_one_digit_off_is_still_caught(self, validator):
        """`0.7446` is real; `0.7448` is not, and they differ by one digit.

        The failure this guards is a check that passes anything shaped roughly
        right — which is what substring matching over a flattened payload
        does.
        """
        report = validator.validate(DRAFT.replace("0.7446", "0.7448"),
                                    EVIDENCE)
        assert "0.7448" in report.unsupported, report.unsupported

    def test_with_no_number_pattern_the_check_abstains(self):
        """The whole difference between a control and a decoration.

        Without a grammar the figures check must report `configured: false`.
        It must NOT report an answer with a fabricated number in it as
        grounded, and it must not report the *validator* as having an opinion
        it does not have.
        """
        config = GroundingConfig(
            identifier_pattern=AS_DECLARED.identifier_pattern)
        validator = GroundingValidator.from_config(config)
        report = validator.validate(DRAFT, EVIDENCE)

        figures = [r for r in report.results
                   if r.check == NumericGroundingCheck.name]
        assert figures and figures[0].configured is False, (
            "the figures check reports itself as configured with no pattern")
        assert FABRICATION not in report.unsupported, (
            "a check that could not run produced a finding anyway")

    def test_with_no_config_at_all_there_is_no_validator(self):
        """This is the 10 August configuration, stated as a test.

        `from_config(None)` returns `None`, the mission runs exactly as it did
        before grounding existed, and nothing in the transcript claims it was
        checked. That is correct behaviour and it is why the missing
        `grounding:` block was invisible.
        """
        assert GroundingValidator.from_config(None) is None


class TestTheKnownLeakInSubstringSupport:
    """`supported()` is substring matching, and substrings coincide.

    Not a hypothetical: `"0.387" in "10.3871"` is true, so a fabricated score
    is "supported" by an unrelated pagerank that happens to contain its digits.
    This test documents the hole rather than asserting the desired behaviour,
    because fixing it is a change to `NumericGroundingCheck` and belongs in a
    change of its own — but a hole nobody has written down is a hole that gets
    rediscovered by an incident.
    """

    def test_a_coincidental_substring_currently_passes(self):
        validator = GroundingValidator.from_config(AS_DECLARED)
        report = validator.validate(
            "the actor scored 0.387 on the estimate.",
            ['{"nodes": [{"pagerank": 10.3871}]}'])
        assert "0.387" not in report.unsupported, (
            "the leak has been fixed — good. Delete this test and assert the "
            "opposite in the check's own suite.")
