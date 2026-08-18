# tests/test_evidence_scope.py — a figure grounds where it was measured

"""``grounding: figures_from: [verify]``, and the fabrication it catches.

Measured on the coding pack, 18 August 2026. `feature_two_files.bad`
patches two files, never calls `verify`, and writes "3 passed" — and the
run came back `grounded: True`. Nothing was broken: a `patch apply`
result carries a `match_count`, byte offsets and a hash, so the digit 3
really was in this run's evidence. `NumericGroundingCheck` supported the
figure because it supported *any* figure that appeared anywhere, and on a
plane whose tools emit diagnostics that is nearly every small integer.

The missing rule is not about where a figure appears but about **what
measured it**. A test count is printed by the test runner or it is not a
test count, and the manifest is where a platform says which tool measures
the quantity its `number_pattern` describes.

Two properties carry this module: the scope must catch the recorded
fabrication, and an unset scope must change nothing — the analyst and
research packs declare none, and their committed corpora are the
regression test for that half.
"""

import pytest

from core.runtime.grounding import (
    GroundingConfig,
    GroundingValidator,
    NumericGroundingCheck,
)
from core.runtime.results import SourcedEvidence

#: The coding pack's own grammar: only the figures a test runner prints.
COUNTS = (r'(?<![\w.])(\d+)\s+(?:tests?\s+)?'
          r'(?:passed|passing|pass|failed|failing|fail|errors?|skipped)\b')

#: What a patch result carries, and why the digit 3 was already "evidence".
PATCHED = SourcedEvidence(
    '{"success": true, "match_count": 3, "offset": 118, "files": ["core.py"]}',
    tool="patch", arguments='{"action": "apply", "patch_set_json": "..."}')

#: What actually measures a test count.
VERIFIED = SourcedEvidence(
    "===== 3 passed in 0.04s =====",
    tool="verify", arguments='{"action": "test"}')

#: The fabrication, verbatim in shape: the work is real, the count is not.
FABRICATION = "I changed core.py and api.py. The suite is green: 3 passed."


def scoped(**overrides):
    config = GroundingConfig(number_pattern=COUNTS, **overrides)
    return GroundingValidator.from_config(config)


class TestTheScopeIsAManifestDecision:
    """It is content, like every other grammar in the block."""

    def test_it_round_trips_from_a_manifest(self):
        config = GroundingConfig.from_mapping(
            {"number_pattern": COUNTS, "figures_from": ["verify"]})
        assert config.figures_from == ("verify",)

    def test_a_bare_string_is_refused_like_a_bare_ignore(self):
        """`figures_from: verify` is one tool spelled as a scalar, and it
        is refused rather than read as a one-item list — the same answer
        `ignore` gives, because a block where one list-shaped key accepts
        a scalar and the next does not is a block nobody can write from
        memory."""
        with pytest.raises(ValueError, match="list of tool names"):
            GroundingConfig.from_mapping(
                {"number_pattern": COUNTS, "figures_from": "verify"})

    def test_absent_is_every_tool_and_not_an_empty_scope(self):
        config = GroundingConfig.from_mapping({"number_pattern": COUNTS})
        assert config.figures_from == ()

    def test_a_scope_over_a_check_that_is_off_is_refused(self):
        """The rule `planes:` already states one field down: a declaration
        that can never bind is a typo, not leniency. Scoping figures
        without a `number_pattern` reads, in a report, as a skill that
        narrowed its figures — and narrows nothing, because the check
        never runs at all."""
        with pytest.raises(ValueError, match="figures_from"):
            GroundingConfig.from_mapping({"figures_from": ["verify"]})

    def test_a_number_is_not_a_list_of_tools(self):
        with pytest.raises(ValueError, match="list of tool names"):
            GroundingConfig.from_mapping(
                {"number_pattern": COUNTS, "figures_from": 7})


class TestTheRecordedFabrication:
    """`feature_two_files.bad`, in miniature and without a repository."""

    def test_unscoped_the_patch_result_grounds_the_invented_count(self):
        """The defect, kept as a test so the fix cannot be mistaken for a
        no-op. This is what every manifest without the key still does."""
        report = scoped().validate(FABRICATION, [PATCHED])
        assert report.grounded
        assert report.unsupported == ()

    def test_scoped_to_verify_the_same_answer_is_ungrounded(self):
        report = scoped(figures_from=("verify",)).validate(
            FABRICATION, [PATCHED])
        assert not report.grounded
        assert report.unsupported == ("3",)

    def test_a_real_verify_result_supports_it(self):
        report = scoped(figures_from=("verify",)).validate(
            FABRICATION, [PATCHED, VERIFIED])
        assert report.grounded, report.unsupported

    def test_the_scope_is_in_the_row_a_reader_sees(self):
        """`2/3 supported` and `2/3 supported, figures scoped to verify`
        are different findings: the second says the third figure may well
        be somewhere in the run and was not measured."""
        result = NumericGroundingCheck(
            GroundingConfig(number_pattern=COUNTS, figures_from=("verify",))
        ).check(FABRICATION, [PATCHED])
        assert "scope: [verify]" in result.detail

    def test_an_unscoped_row_says_nothing_about_a_scope(self):
        result = NumericGroundingCheck(
            GroundingConfig(number_pattern=COUNTS)
        ).check(FABRICATION, [PATCHED])
        assert "scope" not in result.detail


class TestWhatTheScopeAdmits:
    """Which evidence is in it, stated case by case."""

    def test_a_bridged_spelling_of_the_named_tool_is_the_named_tool(self):
        """`same_tool`, like every other tool-name comparison here: a
        platform that reaches its verifier over MCP has not stopped
        verifying."""
        bridged = SourcedEvidence("3 passed", tool="mcp.verify",
                                  arguments='{"action": "test"}')
        assert scoped(figures_from=("verify",)).validate(
            FABRICATION, [bridged]).grounded

    def test_a_second_tool_in_the_list_is_also_in_scope(self):
        shelled = SourcedEvidence("3 passed", tool="run_shell_command",
                                  arguments='{"command": "pytest -q"}')
        assert scoped(
            figures_from=("verify", "run_shell_command")
        ).validate(FABRICATION, [shelled]).grounded

    def test_evidence_with_no_provenance_is_out_of_scope(self):
        """"Unknown" is not "verify". A deployment that scopes its figures
        is asking for exactly this; one that hands a validator bare
        strings should not scope them."""
        assert not scoped(figures_from=("verify",)).validate(
            FABRICATION, ["===== 3 passed in 0.04s ====="]).grounded

    def test_what_the_model_sent_is_still_never_a_result(self):
        """The scope narrows the evidence; it does not re-admit what an
        earlier rule threw out. A figure typed into a `verify` call that
        never reached a tool grounds nothing."""
        sent = SourcedEvidence('{"action": "test", "expect": "3 passed"}',
                               tool="verify", sent=True,
                               arguments='{"action": "test"}')
        assert not scoped(figures_from=("verify",)).validate(
            FABRICATION, [sent]).grounded

    def test_identifiers_keep_the_whole_evidence_set(self):
        """The scope is this check's and no other's. A file path comes
        back from `repo_map`, from `fs` or from a patch result, and
        scoping those would flag true tokens — the 10 August lesson."""
        config = GroundingConfig(
            identifier_pattern=r'(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.py)',
            number_pattern=COUNTS,
            figures_from=("verify",))
        report = GroundingValidator.from_config(config).validate(
            "I changed core.py. The suite is green: 3 passed.",
            [PATCHED])
        assert report.unsupported == ("3",), report.unsupported


class TestWhatTheModelIsToldNext:
    """The repair turn and the caveat, which the generic wording gets
    wrong under a scope: the fabricated "3 passed" **is** in a patch
    result, and a model sent looking for a transcription slip will not
    find one."""

    @pytest.fixture
    def report(self):
        return scoped(figures_from=("verify",)).validate(
            FABRICATION, [PATCHED])

    def test_the_repair_turn_names_the_tool_that_measures(self, report):
        prompt = GroundingValidator.repair_prompt(report)
        assert "in no verify result" in prompt
        assert "and in no tool output you received" not in prompt

    def test_the_caveat_says_appearing_is_not_measuring(self, report):
        caveat = GroundingValidator.caveat(report)
        assert "printed by no verify result" in caveat
        assert "in no tool result from this mission" not in caveat

    def test_without_a_scope_the_generic_wording_is_the_one_owner(self):
        report = scoped().validate("The suite is green: 9 passed.", [PATCHED])
        prompt = GroundingValidator.repair_prompt(report)
        assert "in no tool output you received" in prompt
        assert "verify" not in prompt
