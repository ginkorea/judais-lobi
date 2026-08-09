# tests/test_grounding.py — does the answer cite anything that exists?

"""The mission-tier analogue of the CompositeJudge tests.

Two properties carry the module. An invented identifier must fail, and a
check that could not run must not report a pass — the second is the one
that would otherwise turn "we had no grammar" into a governance claim.
"""

import pytest

from core.runtime.grounding import (
    DEFAULT_CHECKS,
    CheckResult,
    GroundingCheck,
    GroundingConfig,
    GroundingMisdeclared,
    GroundingReport,
    GroundingValidator,
    IdentifierGroundingCheck,
    NumericGroundingCheck,
)

#: Ids look guessable on purpose — that is the whole problem.
PATTERN = r"\b(?:asset|labels|run|rec)\.[0-9a-f]{4,}\b"

EVIDENCE = [
    "asset.5f21c9 — Taiwan narrative corpus, 12,481 records",
    '{"label_set": "labels.9a3b1c", "derives_from": "asset.5f21c9"}',
]


@pytest.fixture
def config():
    return GroundingConfig(identifier_pattern=PATTERN)


@pytest.fixture
def validator(config):
    return GroundingValidator.from_config(config)


class TestConfigFromAManifest:
    def test_absent_means_no_validator_at_all(self):
        assert GroundingConfig.from_mapping(None) is None
        assert GroundingValidator.from_config(None) is None

    def test_a_pattern_and_ignores_round_trip(self):
        config = GroundingConfig.from_mapping({
            "identifier_pattern": PATTERN, "ignore": ["asset.0000"], "max_repairs": 2,
        })
        assert config.identifier_pattern == PATTERN
        assert config.ignore == ("asset.0000",)
        assert config.max_repairs == 2

    def test_an_unusable_regex_is_refused_at_load_and_not_at_hour_three(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({"identifier_pattern": "[unclosed"})
        assert "not a usable regex" in str(exc.value)

    def test_a_misspelled_key_is_refused_rather_than_ignored(self):
        """Ignoring it would produce a validator with no opinion and a
        report that looks exactly like a clean one."""
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({"identifier_patern": PATTERN})
        assert "identifier_patern" in str(exc.value)

    def test_every_problem_arrives_at_once(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({
                "identifier_pattern": "[bad", "ignore": "not-a-list", "max_repairs": -1,
            })
        message = str(exc.value)
        assert "regex" in message and "ignore" in message and "max_repairs" in message

    def test_a_block_with_no_pattern_builds_no_validator(self):
        """A grounding block that configures nothing enforces nothing —
        and must not look like it enforced something."""
        config = GroundingConfig.from_mapping({"max_repairs": 3})
        assert GroundingValidator.from_config(config) is None


class TestIdentifierGrounding:
    def test_an_identifier_from_a_tool_result_passes(self, validator):
        report = validator.validate("The corpus is asset.5f21c9.", EVIDENCE)
        assert report.grounded

    def test_an_invented_identifier_fails(self, validator):
        """THE test. It is well-formed, plausible, and in no tool output."""
        report = validator.validate("The label set is labels.7a19c4e2.", EVIDENCE)
        assert not report.grounded
        assert "labels.7a19c4e2" in report.unsupported

    def test_an_identifier_only_in_a_structured_payload_is_grounded(self, validator):
        report = validator.validate("Labels: labels.9a3b1c.", EVIDENCE)
        assert report.grounded

    def test_prose_without_identifiers_is_grounded(self, validator):
        assert validator.validate("The catalogue returned nothing.", EVIDENCE).grounded

    def test_a_real_and_an_invented_id_together_report_only_the_invention(self, validator):
        report = validator.validate(
            "asset.5f21c9 derives labels.deadbeef.", EVIDENCE,
        )
        assert report.unsupported == ("labels.deadbeef",)

    def test_the_same_invention_twice_is_reported_once(self, validator):
        report = validator.validate("run.abcdef and run.abcdef.", EVIDENCE)
        assert report.unsupported == ("run.abcdef",)

    def test_an_ignored_literal_is_not_a_claim(self):
        config = GroundingConfig(identifier_pattern=PATTERN, ignore=("asset.0000",))
        report = GroundingValidator.from_config(config).validate(
            "Placeholder asset.0000 was used.", EVIDENCE,
        )
        assert report.grounded

    def test_a_capturing_group_narrows_what_the_token_is(self):
        config = GroundingConfig(identifier_pattern=r"\[id:([a-z0-9.]+)\]")
        report = GroundingValidator.from_config(config).validate(
            "See [id:asset.5f21c9].", EVIDENCE,
        )
        assert report.grounded

    def test_evidence_from_another_run_does_not_count(self, validator):
        report = validator.validate("asset.5f21c9 is the corpus.", [])
        assert not report.grounded


class TestFigureGrounding:
    def test_it_is_off_unless_a_manifest_asks(self, config):
        result = NumericGroundingCheck(config).check("There were 4 blocks.", EVIDENCE)
        assert result.configured is False
        assert result.grounded is False

    def test_a_quoted_figure_passes(self):
        config = GroundingConfig(number_pattern=r"\b\d[\d,]{3,}\b")
        report = GroundingValidator.from_config(config).validate(
            "12,481 records.", EVIDENCE,
        )
        assert report.grounded

    def test_separators_do_not_make_it_a_different_figure(self):
        config = GroundingConfig(number_pattern=r"\b\d[\d,]{3,}\b")
        report = GroundingValidator.from_config(config).validate(
            "12481 records.", EVIDENCE,
        )
        assert report.grounded

    def test_an_invented_figure_fails(self):
        config = GroundingConfig(number_pattern=r"\b\d[\d,]{3,}\b")
        report = GroundingValidator.from_config(config).validate(
            "13,902 records.", EVIDENCE,
        )
        assert report.unsupported == ("13,902",)


class TestNoOpinionIsNotAPass:
    def test_an_unconfigured_check_is_not_grounded(self, ):
        result = IdentifierGroundingCheck(GroundingConfig()).check("anything", [])
        assert result.configured is False
        assert result.grounded is False

    def test_it_says_why_it_could_not_run(self):
        result = IdentifierGroundingCheck(GroundingConfig()).check("x", [])
        assert "identifier_pattern" in result.detail

    def test_a_report_where_nothing_ran_is_not_grounded(self):
        report = GroundingReport(results=(
            CheckResult(check="identifiers", configured=False),
        ))
        assert report.ran is False
        assert report.grounded is False

    def test_a_report_with_one_running_check_has_an_opinion(self):
        report = GroundingReport(results=(
            CheckResult(check="identifiers", configured=True),
            CheckResult(check="figures", configured=False),
        ))
        assert report.ran is True
        assert report.grounded is True


class TestTheReport:
    def test_it_counts_what_it_considered(self, validator):
        report = validator.validate("asset.5f21c9 and run.999999.", EVIDENCE)
        identifiers = report.results[0]
        assert identifiers.considered == ("asset.5f21c9", "run.999999")
        assert "1/2 supported" in identifiers.detail

    def test_the_repair_turn_names_the_exact_tokens(self, validator):
        report = validator.validate("labels.7a19c4e2 is it.", EVIDENCE)
        prompt = validator.repair_prompt(report)
        assert "labels.7a19c4e2" in prompt
        assert "similar-looking" in prompt

    def test_the_caveat_names_them_too(self, validator):
        report = validator.validate("labels.7a19c4e2 is it.", EVIDENCE)
        assert "labels.7a19c4e2" in validator.caveat(report)

    def test_unsupported_is_deduplicated_across_checks(self):
        config = GroundingConfig(
            identifier_pattern=r"\bZZ\d+\b", number_pattern=r"\bZZ\d+\b",
        )
        report = GroundingValidator.from_config(config).validate("ZZ42", [])
        assert report.unsupported == ("ZZ42",)


class TestDeclaration:
    """Checked at class creation, with every problem in one message."""

    def test_a_check_without_a_name_is_refused(self):
        with pytest.raises(GroundingMisdeclared) as exc:
            class Nameless(GroundingCheck):
                def extract(self, answer):
                    return []
        assert "`name` is empty" in str(exc.value)

    def test_a_check_that_does_not_extract_is_refused(self):
        with pytest.raises(GroundingMisdeclared) as exc:
            class Inert(GroundingCheck):
                name = "inert"
        assert "does not implement `extract`" in str(exc.value)

    def test_overriding_the_template_is_refused(self):
        with pytest.raises(GroundingMisdeclared) as exc:
            class Reimplemented(GroundingCheck):
                name = "reimplemented"

                def extract(self, answer):
                    return []

                def check(self, answer, evidence):
                    return CheckResult(check="reimplemented")
        assert "final" in str(exc.value)

    def test_every_problem_arrives_in_one_message(self):
        with pytest.raises(GroundingMisdeclared) as exc:
            class Hopeless(GroundingCheck):
                def check(self, answer, evidence):
                    return CheckResult(check="hopeless")
        message = str(exc.value)
        assert "`name` is empty" in message
        assert "does not implement `extract`" in message
        assert "final" in message

    def test_an_intermediate_base_may_be_abstract(self):
        class Intermediate(GroundingCheck):
            abstract = True

        assert Intermediate.name == ""

    def test_a_well_formed_check_is_accepted(self):
        class Custom(GroundingCheck):
            name = "custom"

            def extract(self, answer):
                return answer.split()

        assert Custom(GroundingConfig()).check("a b", ["a b"]).grounded

    def test_the_default_checks_are_the_two_named(self):
        assert DEFAULT_CHECKS == (IdentifierGroundingCheck, NumericGroundingCheck)
