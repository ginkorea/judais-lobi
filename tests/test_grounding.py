# tests/test_grounding.py — does the answer cite anything that exists?

"""The mission-tier analogue of the CompositeJudge tests.

Two properties carry the module. An invented identifier must fail, and a
check that could not run must not report a pass — the second is the one
that would otherwise turn "we had no grammar" into a governance claim.
"""

import json
from dataclasses import replace

import pytest

from core.runtime.grounding import (
    DEFAULT_CHECKS,
    NOTHING_CONSIDERED,
    SUPPORTED,
    UNCONFIGURED,
    UNSUPPORTED,
    VERDICTS,
    CheckResult,
    ClaimGroundingCheck,
    GroundingCheck,
    GroundingConfig,
    GroundingMisdeclared,
    GroundingReport,
    GroundingValidator,
    IdentifierGroundingCheck,
    NumericGroundingCheck,
    PlaneClaimCheck,
    ReadingGroundingCheck,
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


class TestTypographyIsNotContent:
    """The 17 non-breaking hyphens of ``what_can_this_pool_run``.

    The answer named a model whose id it had read correctly out of the
    catalogue and typed back with U+2011 instead of U+002D. A substring
    test between those two strings fails, which would report a correctly
    cited identifier as invented — the false positive that teaches a
    reader the check is noise, on the mission where the answer was right.
    """

    HF = r"\b[A-Za-z][\w.-]*/[A-Za-z0-9][\w.-]*[A-Za-z0-9]\b"
    MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

    def test_a_model_id_typed_with_non_breaking_hyphens_is_grounded(self):
        pretty = self.MODEL.replace("-", "‑", 99)
        report = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=self.HF)
        ).validate(f"The pool serves {pretty}.", [f'{{"id": "{self.MODEL}"}}'])
        assert report.grounded, report.unsupported
        # THE WHOLE id, not a prefix of it. Unnormalised, U+2011 is not a word
        # character, so the pattern stops at the first one and considers
        # `sentence-transformers/paraphrase` — which is a substring of the
        # real id and therefore "supported". A pass for the wrong reason, and
        # a check that would then miss an invention past the first pretty
        # hyphen.
        considered = next(r for r in report.results
                          if r.check == "identifiers").considered
        assert considered == (self.MODEL,), considered

    def test_the_evidence_side_is_normalised_too(self):
        """One-sided normalisation flatters the check; both sides or neither."""
        pretty = self.MODEL.replace("-", "‑", 99)
        report = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=self.HF)
        ).validate(f"The pool serves {self.MODEL}.", [f'{{"id": "{pretty}"}}'])
        assert report.grounded, report.unsupported

    def test_an_invention_is_not_laundered_by_normalising(self):
        report = GroundingValidator.from_config(
            GroundingConfig(identifier_pattern=self.HF)
        ).validate("The pool serves meta‑llama/Llama‑4.",
                   [f'{{"id": "{self.MODEL}"}}'])
        assert report.unsupported == ("meta-llama/Llama-4",)

    def test_a_figure_written_with_a_unicode_minus_still_compares(self):
        report = GroundingValidator.from_config(
            GroundingConfig(number_pattern=r"-?\b\d[\d,]*\.\d+\b")
        ).validate("The margin was −0.25 nats.", ['{"dl_margin": -0.25}'])
        assert report.grounded, report.unsupported


class TestTheNameOfAnOfferedToolIsNotAnInvention:
    """The recorded ``absence_is_an_answer`` fault, and the derivation fix.

    10 August 2026, turn 3: the answer said truthfully which tool it had
    used. The identifier check flagged ``mcp.catalog_search_assets`` — the
    tool's own wire name — as an ungrounded asset id, because the
    manifest's ``ignore`` list carried only the *dotted* spelling somebody
    had typed. The repair turn deleted the sentence, and the mission
    answered with nothing citable at all: ``0/0``, ``grounded: True``.

    The grammar here deliberately matches a wire name, because that is the
    grammar the recording ran under.
    """

    #: Wide enough to match a tool name, exactly as the deployed one was.
    WIRE = r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b"

    @pytest.mark.parametrize("spelling", [
        "mcp.catalog_search_assets",   # what the bus dispatches
        "catalog.search_assets",       # what the catalogue prose says
        "catalog_search_assets",       # what the skill prose says
        "MCP.Catalog_Search_Assets",   # a fourth nobody has invented yet
    ])
    def test_no_spelling_of_an_offered_tool_is_flagged(self, spelling):
        config = GroundingConfig(identifier_pattern=self.WIRE).offering(
            ["mcp.catalog_search_assets", "mcp.runs_get"])
        report = GroundingValidator.from_config(config).validate(
            f"I searched the catalogue with {spelling} and found nothing.",
            EVIDENCE)
        assert report.grounded, (
            f"{spelling!r} is a spelling of a tool this mission offered — the "
            f"harness wrote that name into the prompt itself — and the check "
            f"called it an invented identifier")
        assert not report.unsupported

    def test_without_the_derivation_the_recorded_fault_reproduces(self):
        """The mutation. Drop ``offering`` and turn 3 happens again."""
        config = GroundingConfig(
            identifier_pattern=self.WIRE,
            # exactly what the deployed manifest carried: the dotted one
            ignore=("catalog.search_assets",))
        report = GroundingValidator.from_config(config).validate(
            "I searched the catalogue with mcp.catalog_search_assets.",
            EVIDENCE)
        assert not report.grounded
        assert report.unsupported == ("mcp.catalog_search_assets",)

    def test_a_tool_that_was_not_offered_is_still_a_claim(self):
        """Derivation, not amnesty. An unoffered name is still checked."""
        config = GroundingConfig(identifier_pattern=self.WIRE).offering(
            ["mcp.catalog_search_assets"])
        report = GroundingValidator.from_config(config).validate(
            "I used mcp.compute_submit_job to run it.", EVIDENCE)
        assert report.unsupported == ("mcp.compute_submit_job",)

    def test_a_manifest_cannot_declare_the_offered_set(self):
        """It is derived at run time; a manifest that types it is refused."""
        with pytest.raises(ValueError, match="tools_offered"):
            GroundingConfig.from_mapping(
                {"identifier_pattern": PATTERN, "tools_offered": ["x"]})


class TestFigureGrounding:
    def test_it_is_off_unless_a_manifest_asks(self, config):
        result = NumericGroundingCheck(config).check("There were 4 blocks.", EVIDENCE)
        assert result.configured is False
        assert result.grounded is False

    def test_every_result_grounds_a_figure_unless_a_manifest_narrows_it(self):
        """The default, stated here because it is what every manifest
        written before `figures_from:` means and what the committed
        corpora were recorded under. The narrowed behaviour, and the
        fabrication it catches, are `tests/test_evidence_scope.py`."""
        config = GroundingConfig.from_mapping(
            {"number_pattern": r"\b\d[\d,]{3,}\b"})
        assert config.figures_from == ()
        assert GroundingValidator.from_config(config).validate(
            "12,481 records.", EVIDENCE).grounded

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


class TestFiguresAreComparedAsNumbers:
    """Structural extraction and numeric comparison, not `token in text`.

    The substring implementation reported `0.387` as supported by an unrelated
    pagerank of `10.3871`, because it is a substring of it. A fabricated figure
    only had to appear inside a real one somewhere in a governed view to be
    laundered into a grounded answer, and a governed view is tens of thousands
    of numbers wide.
    """

    CONFIG = GroundingConfig(number_pattern=r"\b\d+\.\d{2,}\b")
    VIEW = ['{"nodes": [{"pagerank": 10.3871, "out_weight": 338.0}], '
            '"gate": {"confidence": 0.7446}}']

    def report(self, answer, evidence=None):
        return GroundingValidator.from_config(self.CONFIG).validate(
            answer, self.VIEW if evidence is None else evidence)

    def test_a_figure_that_is_merely_a_substring_is_unsupported(self):
        """THE test. `"0.387" in "10.3871"` is true and means nothing."""
        report = self.report("the actor scored 0.387 on the estimate.")
        assert report.unsupported == ("0.387",)

    def test_the_figure_it_hid_behind_is_still_supported(self):
        """The real 10.3871 must still pass, or this is just a stricter bug."""
        assert self.report("its pagerank is 10.3871.").grounded

    def test_a_leading_digit_run_does_not_support_a_longer_claim(self):
        report = self.report("the score is 10.38710001.")
        assert report.unsupported == ("10.38710001",)

    def test_a_figure_inside_a_hex_identifier_is_not_a_figure(self):
        """`04349a489b2a1457` is a corpus hash. It supports nothing."""
        report = self.report(
            "the estimate is 43.49.",
            ['{"provenance": {"corpus_hash": "04349a489b2a1457"}}'])
        assert report.unsupported == ("43.49",)

    def test_separators_still_do_not_make_it_a_different_figure(self):
        config = GroundingConfig(number_pattern=r"\b\d[\d,]{3,}\b")
        validator = GroundingValidator.from_config(config)
        evidence = ['{"records": 12481}']
        assert validator.validate("12,481 records.", evidence).grounded
        assert validator.validate("12481 records.", evidence).grounded
        assert validator.validate(
            "12,481 records.", ["Taiwan corpus, 12,481 records"]).grounded

    def test_a_trailing_zero_is_the_same_figure(self):
        """338 and 338.0 are one out-weight, written two ways."""
        config = GroundingConfig(number_pattern=r"\b\d+(?:\.\d+)?\b")
        report = GroundingValidator.from_config(config).validate(
            "an out-weight of 338.", self.VIEW)
        assert report.grounded

    def test_a_figure_the_evidence_does_not_hold_is_still_caught(self):
        assert not self.report("a confidence of 0.7448.").grounded


class TestAFigureIsTheSameThingOnBothSides:
    """One owner for *what a figure is*, in the answer and in the evidence.

    `NumericGroundingCheck.prepare` reads the evidence with the check's own
    `FIGURE`, which refuses a run of digits that follows a dot — so an actor
    handle of `a.0000` puts no figure `0000` into the evidence set. The
    answer used to be read with the manifest's `number_pattern` alone, and
    an ordinary one pulls `0000` straight out of `a.0000`.

    Live, 16 August: a staged mission answered "Run r-7 actor at top of
    actor list: a.0000", the identifier check passed it 2/2, the figure
    check called `0000` unsupported, and the repair turn took the actor
    back out of an answer that was right.
    """

    #: The naive pattern almost every manifest writes.
    CONFIG = GroundingConfig(
        identifier_pattern=r"\b(?:asset|a|rec)\.[0-9a-z]{4,}\b",
        number_pattern=r"\b\d[\d,]*(?:\.\d+)?\b")
    VIEW = ['{"run_id": "r-7", "actors": [{"handle": "a.0000", '
            '"score": 1.0}], "totals": {"records": 12481}}']

    def report(self, answer):
        return GroundingValidator.from_config(self.CONFIG).validate(
            answer, self.VIEW)

    def test_the_digits_inside_an_identifier_are_not_a_figure(self):
        """THE test. The whole answer is true and every part of it was read
        from the payload."""
        report = self.report("top actor a.0000, 12481 records.")
        assert report.grounded
        assert report.unsupported == ()

    def test_the_identifier_is_still_checked_as_an_identifier(self):
        """Narrowing the figure check must not stop the identifier check
        catching an invented handle."""
        report = self.report("top actor a.9999, 12481 records.")
        assert report.unsupported == ("a.9999",)

    def test_a_figure_that_stands_alone_is_still_checked(self):
        assert self.report("top actor a.0000, 99999 records.").unsupported \
            == ("99999",)

    def test_a_run_of_digits_inside_a_word_is_not_a_figure_either(self):
        """`(?![\\w])` is the other half of the same boundary, and a
        manifest pattern that ignores it must not be able to invent work."""
        report = GroundingValidator.from_config(
            GroundingConfig(number_pattern=r"\b\d[\d,]*\b")).validate(
                "the shard is 12481a.", ['{"records": 12481}'])
        assert report.unsupported == ()


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


class TestTheClaimTable:
    """Every figure emitted a second time as the path it came from.

    The complement to the figures check, and the control that prices the
    escape it opens: a model told its numbers are unsupported can delete its
    numbers. It cannot delete them and still state three claims.

    Verification here is arithmetic, not search — `walk_path` reads the claimed
    path out of the payload the model was given and the values are compared.
    """

    VIEW = [
        '{"gate": {"confidence": 0.7446, "decision": 3}, '
        '"network": {"node_count": 127, '
        '"nodes": [{"actor_id": "6436464948", '
        '"scores": {"out_weight": 338.0, "pagerank": 10.3871}}]}}',
    ]
    CONFIG = GroundingConfig(claim_table=True)

    def report(self, answer, evidence=None, **kw):
        config = replace(self.CONFIG, **kw) if kw else self.CONFIG
        return GroundingValidator.from_config(config).validate(
            answer, self.VIEW if evidence is None else evidence)

    @staticmethod
    def table(*claims):
        return "The run is described above.\n\n```claims\n" + json.dumps(
            list(claims)) + "\n```"

    def test_a_claim_that_walks_to_its_value_is_supported(self):
        report = self.report(self.table(
            {"value": 0.7446, "path": "gate.confidence"},
            {"value": 338.0, "path": "network.nodes[0].scores.out_weight"}))
        assert report.grounded and report.verified

    def test_a_fabricated_value_at_a_real_path_is_not(self):
        """The 80.847 move, in the table rather than in the prose."""
        report = self.report(self.table(
            {"value": 80.847, "path": "gate.confidence"}))
        assert not report.grounded
        assert report.unsupported == ("gate.confidence=80.847",)

    def test_a_path_that_does_not_resolve_is_not_supported(self):
        report = self.report(self.table(
            {"value": 80.847, "path": "network.total_influence"}))
        assert not report.grounded

    def test_a_value_at_the_wrong_path_is_not_supported(self):
        """0.7446 IS in the view, and not there. The path is the claim."""
        report = self.report(self.table(
            {"value": 0.7446, "path": "network.nodes[0].scores.pagerank"}))
        assert not report.grounded

    def test_an_integer_and_a_float_are_the_same_figure(self):
        report = self.report(self.table(
            {"value": 338, "path": "network.nodes[0].scores.out_weight"}))
        assert report.grounded

    def test_a_missing_table_considers_nothing_rather_than_passing(self):
        report = self.report("A fluent paragraph with no table in it.")
        claims = [r for r in report.results if r.check == "claims"][0]
        assert claims.verdict == NOTHING_CONSIDERED
        assert report.verified is False

    def test_a_missing_table_fails_a_skill_that_requires_claims(self):
        """The schema minimum: 'delete all the numbers' stops working."""
        report = self.report("A fluent paragraph with no table in it.",
                             must_cite=(("claims", 3),))
        assert not report.grounded
        assert report.uncited == ("claims",)

    def test_too_few_claims_fails_the_minimum(self):
        report = self.report(
            self.table({"value": 0.7446, "path": "gate.confidence"}),
            must_cite=(("claims", 3),))
        assert not report.grounded
        assert "at least 3" in [
            r for r in report.results if r.check == "claims"][0].detail

    def test_enough_true_claims_passes_it(self):
        report = self.report(
            self.table(
                {"value": 0.7446, "path": "gate.confidence"},
                {"value": 3, "path": "gate.decision"},
                {"value": 127, "path": "network.node_count"}),
            must_cite=(("claims", 3),))
        assert report.grounded and report.verified

    def test_an_unreadable_table_is_a_finding_and_not_a_skip(self):
        """A table nobody could parse is a table nobody verified."""
        report = self.report(
            "```claims\n[{'value': 0.7446, 'path': 'gate.confidence'}]\n```")
        assert not report.grounded
        assert "unreadable claim table" in report.unsupported[0]

    def test_a_claim_missing_its_path_is_a_finding(self):
        report = self.report(self.table({"value": 0.7446}))
        assert not report.grounded
        assert "unreadable claim table" in report.unsupported[0]

    def test_the_check_is_off_unless_the_manifest_asks(self):
        result = ClaimGroundingCheck(GroundingConfig()).check(
            self.table({"value": 1, "path": "gate.decision"}), self.VIEW)
        assert result.configured is False
        assert result.grounded is False

    def test_text_evidence_that_is_not_json_is_skipped_not_crashed(self):
        report = self.report(
            self.table({"value": 0.7446, "path": "gate.confidence"}),
            evidence=["Stored results in this mission: r1, r2", *self.VIEW])
        assert report.grounded

    def test_the_prose_checks_do_not_read_the_table(self):
        """A field path is not an invented asset id.

        `{"path": "gate.confidence"}` is a dotted lower-case token and an
        identifier grammar matches it. Left in the prose the checks read, a
        draft that did exactly what its skill required would be reported as
        inventing identifiers — and a report that cries wolf is one nobody
        reads.
        """
        config = replace(self.CONFIG,
                         identifier_pattern=r"\b[a-z][a-z0-9_]*\.[a-z0-9_.]+\b")
        report = GroundingValidator.from_config(config).validate(
            "The gate is confident.\n\n" + self.table(
                {"value": 0.7446, "path": "gate.confidence"},
                {"value": 127, "path": "network.node_count"}),
            self.VIEW)
        assert report.grounded, report.unsupported

    def test_the_repair_turn_quotes_the_claim(self):
        report = self.report(self.table(
            {"value": 80.847, "path": "gate.confidence"}))
        assert "gate.confidence=80.847" in GroundingValidator.repair_prompt(
            report)


class TestSilenceIsNotAPass:
    """The 10 August hole: a check that extracted nothing reported a pass.

    Six of the first ten measured missions reported `grounded: identifiers —
    0/0 supported by a tool result in this run`, two of them on questions whose
    answers are lists of asset ids. The verdict has to separate *nothing was
    considered* from *things were considered and all supported*, or the cheapest
    way to pass a citation check is to write nothing checkable.
    """

    def test_an_answer_citing_nothing_and_one_citing_correctly_differ(
            self, validator):
        """The mutation. Both are `grounded`; only one was checked."""
        nothing = validator.validate("The catalogue returned nothing.", EVIDENCE)
        cited = validator.validate(
            "asset.5f21c9 derives labels.9a3b1c.", EVIDENCE)

        assert nothing.grounded and cited.grounded
        assert nothing.verified is False
        assert cited.verified is True
        assert nothing.silent == ("identifiers",)
        assert cited.silent == ()
        assert nothing.results[0].verdict == NOTHING_CONSIDERED
        assert cited.results[0].verdict == SUPPORTED

    def test_the_detail_line_no_longer_says_zero_of_zero_supported(
            self, validator):
        """The exact string the six missions printed."""
        report = validator.validate("The catalogue returned nothing.", EVIDENCE)
        detail = report.results[0].detail
        assert "0/0 supported" not in detail
        assert "nothing to check" in detail

    def test_an_unsupported_claim_is_its_own_verdict(self, validator):
        report = validator.validate("It is labels.7a19c4e2.", EVIDENCE)
        assert report.results[0].verdict == UNSUPPORTED

    def test_an_unconfigured_check_keeps_its_own_verdict(self):
        result = IdentifierGroundingCheck(GroundingConfig()).check("x", [])
        assert result.verdict == UNCONFIGURED

    def test_the_verdicts_are_a_closed_set(self, validator):
        for answer in ("", "nothing here", "asset.5f21c9", "labels.7a19c4e2"):
            for row in validator.validate(answer, EVIDENCE).results:
                assert row.verdict in VERDICTS


class TestASkillDeclaresWhetherSilenceIsAcceptable:
    """`must_cite` — content, like the grammar, and in the manifest.

    Making `0/0` ungrounded in the harness would be wrong:
    `absence_is_an_answer` is a legitimate mission whose correct answer cites
    nothing, and a validator that failed it would be switched off inside a week.
    So the skill says.
    """

    REQUIRED = GroundingConfig(
        identifier_pattern=PATTERN, must_cite=(("identifiers", 1),))

    def test_a_skill_that_requires_a_citation_fails_the_empty_answer(self):
        """The second mutation, and the point of the whole change."""
        report = GroundingValidator.from_config(self.REQUIRED).validate(
            "The catalogue returned nothing.", EVIDENCE)
        assert not report.grounded
        assert report.uncited == ("identifiers",)
        assert report.results[0].verdict == NOTHING_CONSIDERED

    def test_the_same_skill_passes_an_answer_that_cites(self):
        report = GroundingValidator.from_config(self.REQUIRED).validate(
            "The corpus is asset.5f21c9.", EVIDENCE)
        assert report.grounded and report.verified
        assert report.uncited == ()

    def test_a_skill_that_declares_nothing_still_allows_silence(self, validator):
        """`absence_is_an_answer` must keep working, or this gets turned off."""
        report = validator.validate("The catalogue returned nothing.", EVIDENCE)
        assert report.grounded

    def test_a_minimum_above_one_is_a_schema_minimum(self):
        config = GroundingConfig(
            identifier_pattern=PATTERN, must_cite=(("identifiers", 3),))
        built = GroundingValidator.from_config(config)
        evidence = [*EVIDENCE, '{"run_id": "run.44ff01"}']
        assert not built.validate("asset.5f21c9 and labels.9a3b1c.",
                                  evidence).grounded
        assert built.validate(
            "asset.5f21c9, labels.9a3b1c and run.44ff01.", evidence).grounded

    def test_the_repair_turn_says_what_is_missing_rather_than_listing_nothing(
            self):
        report = GroundingValidator.from_config(self.REQUIRED).validate(
            "The catalogue returned nothing.", EVIDENCE)
        prompt = GroundingValidator.repair_prompt(report)
        assert "at least 1 required" in prompt
        assert "an empty answer is not a grounded one" in prompt

    def test_the_caveat_says_nothing_was_checked(self):
        report = GroundingValidator.from_config(self.REQUIRED).validate(
            "The catalogue returned nothing.", EVIDENCE)
        caveat = GroundingValidator.caveat(report)
        assert "Uncited" in caveat and "identifiers" in caveat
        assert "must not be relied on" in caveat

    def test_a_true_flag_requires_one_of_every_configured_check(self):
        config = GroundingConfig.from_mapping({
            "identifier_pattern": PATTERN, "must_cite": True})
        report = GroundingValidator.from_config(config).validate("silence.", [])
        assert not report.grounded

    def test_a_named_check_beats_the_wildcard(self):
        config = GroundingConfig(
            identifier_pattern=PATTERN, must_cite=(("*", 1), ("identifiers", 0)))
        assert config.minimum_for("identifiers") == 0
        assert config.minimum_for("figures") == 1


class TestMustCiteIsReadFromTheManifest:
    def test_a_list_of_names_means_one_each(self):
        config = GroundingConfig.from_mapping({
            "identifier_pattern": PATTERN, "must_cite": ["identifiers"]})
        assert config.must_cite == (("identifiers", 1),)

    def test_a_mapping_carries_the_count(self):
        config = GroundingConfig.from_mapping({
            "identifier_pattern": PATTERN, "must_cite": {"identifiers": 3}})
        assert config.must_cite == (("identifiers", 3),)

    def test_true_is_the_wildcard(self):
        config = GroundingConfig.from_mapping({
            "identifier_pattern": PATTERN, "must_cite": True})
        assert config.must_cite == (("*", 1),)

    def test_absent_requires_nothing(self):
        config = GroundingConfig.from_mapping({"identifier_pattern": PATTERN})
        assert config.must_cite == ()
        assert config.minimum_for("identifiers") == 0

    def test_a_count_that_is_not_a_count_is_refused(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({
                "identifier_pattern": PATTERN,
                "must_cite": {"identifiers": "yes"}})
        assert "must_cite" in str(exc.value)

    def test_a_misspelled_check_name_is_refused_at_load(self):
        """`identifier` for `identifiers` would otherwise never bind."""
        config = GroundingConfig(
            identifier_pattern=PATTERN, must_cite=(("identifier", 1),))
        with pytest.raises(ValueError) as exc:
            GroundingValidator.from_config(config)
        assert "identifier" in str(exc.value)
        assert "identifiers" in str(exc.value)

    def test_requiring_a_check_this_block_does_not_configure_is_refused(self):
        """A requirement on an unconfigured check evaporates silently.

        Which is the original hole, wearing the name of the fix for it.
        """
        config = GroundingConfig(
            identifier_pattern=PATTERN, must_cite=(("figures", 2),))
        with pytest.raises(ValueError) as exc:
            GroundingValidator.from_config(config)
        assert "never binds" in str(exc.value)


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

    def test_the_default_checks_are_the_five_named_in_cost_order(self):
        """The order is the cost order and the tuple states it.

        Reading is last because it is the only tier that spends a model
        call, and the whole affordability argument for it is that every
        free check has already had its say. A change that moved it earlier
        would be a change to what a mission costs.
        """
        assert DEFAULT_CHECKS == (
            IdentifierGroundingCheck, NumericGroundingCheck,
            ClaimGroundingCheck, PlaneClaimCheck, ReadingGroundingCheck,
        )


class TestThePlaneClaimCheck:
    """"I ran the code" is a claim about the run, not about the text.

    It contains no identifier, no figure and no claim-table entry, so every
    other check here extracts nothing from it and reports
    `nothing_considered` — and the answer comes back grounded while
    describing work that did not happen. That is the hole this closes, and
    it is the most expensive one in a governance report: a reader who
    believes the SDK ran believes the number was computed rather than
    remembered.
    """

    SDK = {"sdk": {"tools": ["run_code", "run_python"],
                   "claims": ["I used the SDK", "ran the code"]},
           "catalogue": {"tools": ["catalog_*"],
                         "claims": ["searched the catalogue"]}}

    def config(self):
        return GroundingConfig.from_mapping({"planes": self.SDK})

    def report(self, answer, called):
        return GroundingValidator.from_config(self.config()).validate(
            answer, [], called=called)

    def row(self, answer, called):
        return next(r for r in self.report(answer, called).results
                    if r.check == "planes")

    # ── off by default ──────────────────────────────────────────────────

    def test_no_planes_block_no_check(self):
        result = PlaneClaimCheck(GroundingConfig()).check(
            "I used the SDK to recompute it.", [])
        assert result.configured is False
        assert result.grounded is False
        assert "`planes`" in result.detail

    def test_a_manifest_without_planes_parses_to_none(self):
        assert GroundingConfig.from_mapping({}).planes == ()

    # ── the claim, and the call behind it ───────────────────────────────

    def test_a_claim_with_no_call_to_that_plane_fails(self):
        row = self.row("I used the SDK to recompute the figure.",
                       called=["catalog_search_assets"])
        assert row.verdict == "unsupported"
        assert row.unsupported == ("sdk: I used the SDK",)

    def test_the_same_claim_with_the_call_behind_it_passes(self):
        row = self.row("I used the SDK to recompute the figure.",
                       called=["run_code"])
        assert row.verdict == "supported"

    def test_an_answer_claiming_no_plane_says_so(self):
        row = self.row("The gate settled on three communities.", called=[])
        assert row.verdict == "nothing_considered"
        assert row.grounded is True, (
            "an answer that claims nothing has claimed nothing falsely")

    def test_the_claim_is_matched_however_the_sentence_runs_on(self):
        """A phrase list nobody could write correctly is a phrase list
        nobody writes: "I used the SDK" has to match the sentence it is
        embedded in."""
        assert self.row("So I used the SDK for this part.",
                        called=[]).verdict == "unsupported"

    def test_case_does_not_decide_whether_a_claim_was_made(self):
        assert self.row("i used the sdk.", called=[]).verdict == "unsupported"

    # ── which spellings of a tool count ─────────────────────────────────

    def test_a_namespaced_spelling_of_the_tool_counts(self):
        """The bridge prefixes a server's tools; a manifest writes the bare
        name. `same_tool` is the one owner of that and this uses it."""
        assert self.row("I used the SDK.",
                        called=["mcp.run_code"]).verdict == "supported"

    def test_a_trailing_star_is_a_family(self):
        assert self.row("I searched the catalogue for it.",
                        called=["mcp.catalog_search_assets"]).verdict \
            == "supported"

    def test_a_family_does_not_swallow_a_different_tool(self):
        assert self.row("I searched the catalogue for it.",
                        called=["xcatalog_search"]).verdict == "unsupported"

    # ── what a caller that says nothing gets ────────────────────────────

    def test_a_caller_that_names_no_calls_supports_no_claim(self):
        """`validate` defaults `called` to empty so every caller written
        before this check keeps working — and the honest reading of "we do
        not know what ran" is that nothing backs a claim that it did."""
        report = GroundingValidator.from_config(self.config()).validate(
            "I used the SDK.", [])
        assert report.grounded is False

    # ── the words ───────────────────────────────────────────────────────

    def test_the_repair_turn_does_not_ask_for_a_tool_output(self):
        validator = GroundingValidator.from_config(self.config())
        report = validator.validate("I used the SDK.", [], called=["fetch"])
        prompt = validator.repair_prompt(report)
        assert "never called in this mission" in prompt
        assert "run_code" in prompt, "a repair turn has to name the plane"
        assert "in no tool output you received" not in prompt, (
            "no tool output could ever support a claim about what the model "
            "itself did, so the generic sentence sends it looking for one")

    def test_the_caveat_says_the_work_was_not_done(self):
        validator = GroundingValidator.from_config(self.config())
        report = validator.validate("I used the SDK.", [], called=[])
        caveat = validator.caveat(report)
        assert "Unperformed" in caveat and "sdk" in caveat

    def test_the_detail_names_what_the_run_actually_called(self):
        row = self.row("I used the SDK.", called=["catalog_search_assets"])
        assert "catalog_search_assets" in row.detail

    # ── a declaration that can never bind is a typo ─────────────────────

    def test_a_plane_with_no_claims_is_refused(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping(
                {"planes": {"sdk": {"tools": ["run_code"]}}})
        assert "never binds" in str(exc.value)

    def test_a_plane_with_no_tools_is_refused(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping(
                {"planes": {"sdk": {"claims": ["I used the SDK"]}}})
        assert "fails whatever this run called" in str(exc.value)

    def test_a_bare_list_of_tools_is_refused_with_the_reason(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({"planes": {"sdk": ["run_code"]}})
        assert "no phrases to recognise a claim by" in str(exc.value)

    def test_an_unknown_key_inside_a_plane_is_refused(self):
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping(
                {"planes": {"sdk": {"tool": ["run_code"],
                                    "claims": ["x"]}}})
        assert "unknown key(s): tool" in str(exc.value)


class TestWhichToolsWereCalledHasOneOwner:
    """The store recorded every dispatch as it happened. Nothing re-derives
    it by reading the conversation back, which is the second owner that goes
    wrong the day a call is made somewhere the messages do not show it.
    """

    def store(self):
        from core.runtime.results import MissionResultStore

        store = MissionResultStore()
        store.record("run_code", {}, text="ok")
        store.record("run_code", {}, text="again")
        store.record("catalog_search", {}, text="", exit_code=1)
        return store

    def test_each_tool_once_in_the_order_called(self):
        assert self.store().called_tools() == ["run_code", "catalog_search"]

    def test_a_failed_call_still_used_the_plane(self):
        """The question is whether the plane was used, not whether it
        worked. What a non-zero call produced is the other checks' business
        — `evidence_texts` already drops it."""
        store = self.store()
        assert "catalog_search" in store.called_tools()
        assert len(store.evidence_texts()) == 2


class TestTheCriticSwitchIsTheManifests:
    """`critic:` is the only key here that configures no check.

    It is read by whoever builds the mission — the caller that already reads
    the manifest — and answered by `core.critic.mission`, whose verdict
    lands beside `grounded` and never in it. It lives in this block anyway
    because it is a statement about how hard this skill's answers are
    checked, and a skill that says `claim_table` and `reading` here should
    not have to say the third thing somewhere else.
    """

    def test_it_is_off_unless_a_skill_asks(self):
        assert GroundingConfig.from_mapping({}).critic is False
        assert GroundingConfig().critic is False

    def test_a_skill_can_ask_for_it(self):
        assert GroundingConfig.from_mapping({"critic": True}).critic is True

    def test_it_is_true_or_false_and_not_a_provider_name(self):
        """Which critic is a deployment's handling decision, settled in its
        own config; a manifest naming one would be a skill deciding where a
        governed draft is posted."""
        with pytest.raises(ValueError) as exc:
            GroundingConfig.from_mapping({"critic": "anthropic"})
        assert "it is true or false" in str(exc.value)

    def test_it_configures_no_check(self):
        """Nothing in the validator answers to `critic`, so a `must_cite`
        naming it is refused by the audit that already exists."""
        assert "critic" not in {c.name for c in DEFAULT_CHECKS}
