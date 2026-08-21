# tests/test_grounding_catches_the_recorded_fabrication.py

"""The 10 August 2026 misreading, replayed through the real validator.

A permanent regression fixture. On 10 August two agents on the same 20B base
model — one carrying a governance persona, one carrying none — independently
reported "total influence strength 80.847" over a run whose
`total_causal_influence` is 0.0.

**Corrected 11 August 2026.** This docstring used to continue "The figure
appears in no tool result", and that was false. 80.847 is
`data.runs[0].total_s` — the run's wall-clock seconds — returned by
`runs_list` and quoted without a digit changed. The error is semantic: a
duration reported as an influence score. Goose read 80.889 out of the same
field the same way on a different run, and Qwen3-30B called it "a bridge
count of 80.847", so three models on two harnesses made one error.

The evidence list below was the cause of the mistake: it had been transcribed
from the draft rather than from the recording, and it omitted `total_s`. Under
the real payload the membership check calls the figure supported — correctly —
and `TestTheFigureWasNeverFabricated` pins that, because it is the measured
ceiling of "is this value in the evidence?" and the reason
:mod:`core.runtime.reading` exists.

`NumericGroundingCheck` is still the check built for a genuinely invented
figure, and it did not run on 10 August, because it only activates when a
skill manifest supplies a `grounding:` block and the mission was launched with
no `--skill` at all. So this file asserts the two things that were never
asserted together:

* configured as the manifests now configure it, the validator **fails** a
  draft carrying a figure the run did not return, and names it;
* configured without a `number_pattern`, it reports `configured: false` and
  **not** grounded — because the difference between a control and a decoration
  is entirely whether a check that could not run says so.

And, from the first measured run with those blocks switched on, the escape that
opens: six of the first ten missions reported `grounded: identifiers — 0/0
supported by a tool result in this run`. A fabrication check that is passed by
deleting the fabrication has one move in it. `TestTheEscapeTheFirstFixtureOpens`
is the second move — an answer that cites nothing must not report like an
answer that cited correctly, and under a skill that requires a citation it must
fail.

The evidence below is what the mission's tools returned, in the shape
`MissionResultStore.evidence_texts()` hands to the validator: whole tool
payloads, untruncated. Every figure in it is one the 10 August graders
confirmed against the run.
"""

import json
import os
import re
from dataclasses import replace

import pytest

from core.runtime.grounding import (
    NOTHING_CONSIDERED,
    SUPPORTED,
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
#:
#: **Corrected 11 August 2026 against the recording, and the correction is the
#: finding.** The first version of this list was written from the draft rather
#: than from the transcript, and it left `total_s` out of the `runs_list` row.
#: That single omission is the only reason 80.847 looked invented. It is not
#: invented: it is the run's wall-clock duration, and the row below is quoted
#: from `02-read_a_finished_run/events.jsonl` as `mcp.runs_list` returned it.
#: See :class:`TestTheFigureWasNeverFabricated`.
#:
#: A hand-copied payload, in the file that anchors every fabrication claim in
#: this package. The defect the module docstrings warn about, in the worst
#: available place.
EVIDENCE = [
    '{"data": {"runs": [{"run_id": "a971d4c4149c", "stage": "gate", '
    '"created_at": "2026-08-10T16:29:32.027779+00:00", "mode": "agentic", '
    '"nodes": 127, "edges": 1080, "communities": 3, '
    '"communities_decided_by": "agent", "communities_confidence": 0.7446, '
    '"communities_outcome": "pass", "total_s": 80.847, '
    '"has_interpretation": false, "corpus_hash": "04349a489b2a1457"}]}}',
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

#: The two grammars `run_inspection/SKILL.md` declares. The draft above is an
#: EXCERPT — its figure-bearing sentences — so the tests that replay it are the
#: ones about the grammar, and the whole-answer minimums live in
#: :data:`WITH_ITS_MINIMUMS` below and are exercised against whole answers.
AS_DECLARED = GroundingConfig(
    identifier_pattern=r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b",
    number_pattern=r"\b\d+\.\d{2,}\b",
    ignore=("e.g", "i.e", "report_view.json", "manifest.json", "packet.json"),
    max_repairs=1,
)

#: The rest of what that manifest declares: a drafting skill's answer has to
#: state something. Added 10 Aug 2026 with the three-state verdict, because
#: without it "delete every number" passes every other test in this file.
#:
#: Only the figures minimum is pinned here. The manifest also requires an
#: identifier, and the recorded evidence above holds no dotted asset id at all
#: — that mission never called `catalog_get_asset` — so no answer over THIS
#: evidence could satisfy it. A mutation with no green side asserts nothing;
#: the identifier minimum is pinned in `tests/test_grounding.py`, against
#: evidence built for it.
WITH_ITS_MINIMUMS = replace(AS_DECLARED, must_cite=(("figures", 1),))

#: The figure this whole file was built around. Called `FABRICATION` until
#: 11 August 2026, which was wrong: it is `data.runs[0].total_s`, the run's
#: wall-clock seconds, and the draft above is not inventing it but renaming it.
FABRICATION = "80.847"

#: A figure that genuinely appears in nothing this mission received, kept for
#: the tests that need one. `0.181` is the value from the original report line
#: that motivated `unsupported` naming the tokens rather than counting them.
ABSENT_FIGURE = "0.181"

#: An answer of the shape the six `0/0` reports were written over: fluent,
#: on-topic, and carrying nothing a tool result can be compared against. Not a
#: recorded transcript — what was recorded on 10 August is the report line
#: `grounded: identifiers — 0/0 supported by a tool result in this run`, and
#: this is the input class that produces it.
SILENT_DRAFT = (
    "The run finished and its network is tightly connected, clustered into a "
    "handful of communities. The gate settled on a block count with reasonable "
    "confidence. One account stands out as the strongest propagator of the "
    "narratives, with substantially more outward than inward weight."
)


@pytest.fixture()
def validator():
    built = GroundingValidator.from_config(AS_DECLARED)
    assert built is not None, "the declared config produced no validator"
    return built


class TestTheFigureWasNeverFabricated:
    """The correction, pinned so it cannot be un-learned.

    This class replaces `TestTheFabricationIsCaught`, whose four assertions
    were all true only because :data:`EVIDENCE` had been transcribed from the
    draft instead of from the recording and had dropped one field.

    With the real `runs_list` row in place, `NumericGroundingCheck` reports
    80.847 as **supported** — and it is right to. The value is in the payload,
    at `data.runs[0].total_s`, unaltered. What the draft got wrong is not the
    number but the *name*: it calls a duration "the overall influence score".

    That is the measured ceiling of asking "is this value in the evidence?",
    and the reason :mod:`core.runtime.reading` exists. Two other models made
    the identical error on the identical field — Goose read 80.889 the same
    way, and Qwen3-30B called it "a bridge count of 80.847" — so this is a
    class of failure and not one bad draft.
    """

    def test_the_figure_is_in_the_payload(self):
        """Ground truth, stated as an assertion rather than as prose."""
        row = json.loads(EVIDENCE[0])["data"]["runs"][0]
        assert row["total_s"] == 80.847
        assert row["run_id"] == "a971d4c4149c"

    def test_the_membership_check_calls_it_supported(self, validator):
        """The hole, in one assertion.

        Not a bug in `NumericGroundingCheck`. It answers the question it was
        asked, correctly. The question is the wrong one for this failure.
        """
        report = validator.validate(DRAFT, EVIDENCE)
        assert report.ran
        assert FABRICATION not in report.unsupported, (
            "80.847 is data.runs[0].total_s and IS in the evidence; a check "
            "reporting otherwise is matching against a payload that is not "
            "the one the mission received")

    def test_and_therefore_the_whole_draft_passes(self, validator):
        """The consequence: a governed report says this draft is grounded.

        Every figure in it came back from a tool. The sentence calling a
        duration an influence score is not visible to any check in
        :mod:`core.runtime.grounding`, and the answer is reported clean.
        """
        report = validator.validate(DRAFT, EVIDENCE)
        assert report.grounded and report.verified, (
            f"unsupported={report.unsupported}")

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
        """A repair turn that does not name the token is unactionable.

        Exercised against a figure that really is absent, since the one this
        file is named after is not.
        """
        draft = DRAFT.replace(FABRICATION, ABSENT_FIGURE)
        report = validator.validate(draft, EVIDENCE)
        prompt = validator.repair_prompt(report)
        assert ABSENT_FIGURE in prompt
        assert "similar-looking" in prompt, (
            "the repair turn does not close the substitution move, which is "
            "the fluent thing a weak model reaches for under challenge")

    def test_an_unrepaired_answer_keeps_its_text_and_gains_a_caveat(
            self, validator):
        draft = DRAFT.replace(FABRICATION, ABSENT_FIGURE)
        report = validator.validate(draft, EVIDENCE)
        caveat = validator.caveat(report)
        assert ABSENT_FIGURE in caveat
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


class TestTheEscapeTheFirstFixtureOpens:
    """Having learned it cannot invent 80.847, a model can write no numbers.

    The same day the checks above were switched on, six of the first ten
    missions reported `grounded: identifiers — 0/0 supported by a tool result
    in this run` — the control satisfied by silence. A fabrication check that
    can be passed by deleting the fabrication is a check with one move in it,
    and this is the second move.
    """

    def test_the_silent_draft_is_not_reported_as_verified(self):
        """Under ANY skill: nothing was checked, and the report says so."""
        validator = GroundingValidator.from_config(AS_DECLARED)
        report = validator.validate(SILENT_DRAFT, EVIDENCE)
        assert report.verified is False
        assert set(report.silent) == {"identifiers", "figures",
                                      "attribution"}
        for row in report.results:
            if row.configured:
                assert row.verdict == NOTHING_CONSIDERED

    def test_the_zero_of_zero_wording_is_gone(self):
        """The exact string those six reports printed."""
        validator = GroundingValidator.from_config(AS_DECLARED)
        report = validator.validate(SILENT_DRAFT, EVIDENCE)
        for row in report.results:
            assert "0/0 supported" not in row.detail

    def test_a_drafting_skill_fails_it_outright(self):
        """`run_inspection` declares that its answers cite something."""
        validator = GroundingValidator.from_config(WITH_ITS_MINIMUMS)
        report = validator.validate(SILENT_DRAFT, EVIDENCE)
        assert report.ran
        assert not report.grounded
        assert report.uncited == ("figures",)

    def test_deleting_the_fabrication_alone_does_not_save_it(self):
        """The move this test exists to price.

        Take the recorded draft, strike every figure out of it, and the answer
        that remains passes the figures check on the old rule and fails on
        this one.
        """
        validator = GroundingValidator.from_config(WITH_ITS_MINIMUMS)
        struck = re.sub(r"\d[\d,.]*", "some", DRAFT)
        report = validator.validate(struck, EVIDENCE)
        assert FABRICATION not in report.unsupported     # it is gone
        assert not report.grounded                       # and so is the answer
        assert "figures" in report.uncited

    def test_a_skill_that_declares_no_minimum_still_allows_silence(self):
        """`absence_is_an_answer` is a real mission and must keep passing.

        `catalogue_recon` deliberately declares no minimum: "the catalogue
        holds none of that" is a correct answer with nothing in it to check.
        What it may NOT do is look like an answer that cited three things.
        """
        recon = GroundingConfig(
            identifier_pattern=AS_DECLARED.identifier_pattern,
            ignore=AS_DECLARED.ignore)
        report = GroundingValidator.from_config(recon).validate(
            "The catalogue returns nothing for that mission.", EVIDENCE)
        assert report.grounded is True
        assert report.verified is False
        assert report.uncited == ()

    def test_it_is_distinguishable_from_an_answer_that_cited_correctly(self):
        """The mutation: silence and a clean citation must not report alike."""
        validator = GroundingValidator.from_config(WITH_ITS_MINIMUMS)
        silent = validator.validate(SILENT_DRAFT, EVIDENCE)
        cited = validator.validate(
            "The gate settled at a confidence of 0.7446 and the strongest "
            "account carries an out-weight of 338.0 against an in-weight of "
            "1081.0.",
            EVIDENCE)

        assert (silent.grounded, silent.verified) == (False, False)
        assert (cited.grounded, cited.verified) == (True, True)
        figures = [r for r in cited.results if r.check == "figures"]
        assert [r.verdict for r in figures] == [SUPPORTED]
        assert "figures" not in cited.silent
        assert "figures" in silent.silent


class TestTheSameFabricationInAClaimTable:
    """The recorded draft rewritten the way `run_inspection` now asks for it.

    `output_format` requires every figure beside the prose as
    `{"value": ..., "path": ...}` into the run view, so verification stops
    being a search over flattened text and becomes a walk: read that path out
    of the payload the mission received and compare. The 80.847 has to survive
    that too, and it does not — there is no path in the view holding it.
    """

    CONFIG = replace(AS_DECLARED, claim_table=True,
                     must_cite=(("claims", 3),))

    @staticmethod
    def table(*claims):
        return "\n\n```claims\n" + json.dumps(list(claims)) + "\n```"

    def validate(self, answer):
        return GroundingValidator.from_config(self.CONFIG).validate(
            answer, EVIDENCE)

    def test_the_true_claims_walk_to_their_values(self):
        report = self.validate(self.table(
            {"value": 0.7446, "path": "gate.confidence"},
            {"value": 127, "path": "network.node_count"},
            {"value": 338.0, "path": "network.nodes[0].scores.out_weight"}))
        claims = [r for r in report.results if r.check == "claims"][0]
        assert claims.verdict == SUPPORTED, claims

    def test_the_fabrication_has_no_path_to_stand_on(self):
        """80.847 is not anywhere in that view, under any field name."""
        report = self.validate(self.table(
            {"value": 0.7446, "path": "gate.confidence"},
            {"value": 127, "path": "network.node_count"},
            {"value": 80.847, "path": "network.total_influence_strength"}))
        assert not report.grounded
        assert any(FABRICATION in token for token in report.unsupported), \
            report.unsupported

    def test_pointing_it_at_a_real_field_does_not_save_it(self):
        """The substitution move, structurally: right path, wrong number.

        `total_causal_influence` IS in the view and it is 0.0. A claim that
        the same field holds 80.847 is checked against the payload, not
        against whether the field exists.
        """
        report = self.validate(self.table(
            {"value": 0.7446, "path": "gate.confidence"},
            {"value": 127, "path": "network.node_count"},
            {"value": 80.847, "path": "blocks[0].total_causal_influence"}))
        assert not report.grounded
        assert "blocks[0].total_causal_influence=80.847" in report.unsupported

    def test_the_true_value_of_that_field_is_accepted(self):
        """0.0 is what the run says, and the draft may say it."""
        report = self.validate(self.table(
            {"value": 0.7446, "path": "gate.confidence"},
            {"value": 127, "path": "network.node_count"},
            {"value": 0.0, "path": "blocks[0].total_causal_influence"}))
        assert report.grounded and report.verified

    def test_a_draft_with_no_table_at_all_fails_the_minimum(self):
        """The escape closed: writing no numbers is not a way through.

        This is the recorded draft with every figure struck out — the answer a
        model produces once it learns that figures get it caught.
        """
        report = self.validate(re.sub(r"\d[\d,.]*", "some", DRAFT))
        assert not report.grounded
        assert "claims" in report.uncited


class TestTheFabricationCannotBorrowARealFiguresDigits:
    """`0.387` is not supported by a pagerank of `10.3871`.

    This replaces the test that documented the opposite. `supported()` was
    substring matching, so a fabricated score was "supported" by any unrelated
    figure in the payload that happened to contain its digits — and the larger
    the governed view, the likelier that is. The check now extracts figures
    structurally and compares them as decimals; the pinned behaviours live in
    `tests/test_grounding.py::TestFiguresAreComparedAsNumbers`, and what is
    kept here is the version of the recorded fabrication that used to slip
    through.
    """

    def test_a_coincidental_substring_is_no_longer_support(self):
        validator = GroundingValidator.from_config(AS_DECLARED)
        report = validator.validate(
            "the actor scored 0.387 on the estimate.",
            ['{"nodes": [{"pagerank": 10.3871}]}'])
        assert "0.387" in report.unsupported, report.unsupported

    def test_an_absent_figure_cannot_hide_inside_a_longer_one(self):
        """`0.181` laundered by a view that happens to contain `10.1815`.

        Written against 80.847 until 11 August 2026, which made it a test
        that could not fail for the reason it claimed: 80.847 is in the
        evidence on its own account. The leak it guards is real, so it is
        exercised here against a figure that is genuinely absent.
        """
        validator = GroundingValidator.from_config(AS_DECLARED)
        draft = DRAFT.replace(FABRICATION, ABSENT_FIGURE)
        report = validator.validate(
            draft, [*EVIDENCE, '{"weights": {"total_out": 10.1815}}'])
        assert ABSENT_FIGURE in report.unsupported, (
            f"{ABSENT_FIGURE} was supported by a figure that merely contains "
            f"its digits: {report.unsupported}")


# ── the ten fabricated identities, and the grammar that could not see them ───

#: The deployed `identifier_pattern` as of 11 August 2026, verbatim from every
#: `SKILL.md`. Five shapes, because this platform has five.
IDENTIFIER_GRAMMAR = (
    r"(?:\b(?=[0-9a-f]*[0-9])[0-9a-f]{8,}\b"
    r"|\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b"
    r"|\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b"
    r"|\b[A-Za-z][\w.-]*/(?=[\w.-]*[\d.-])[A-Za-z0-9][\w.-]*[A-Za-z0-9]\b"
    r"|[㐀-鿿]+(?:[_·][㐀-鿿]+)*)"
)

#: The one it replaced. Kept so the mutation is a fact in the file rather than
#: a claim in a commit message.
IDENTIFIER_GRAMMAR_BEFORE = r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b"

FIGURE_GRAMMAR = r"\b\d[\d,]*\.\d+\b"
FIGURE_GRAMMAR_BEFORE = r"\b\d+\.\d{2,}\b"

#: `tai.read_a_finished_run`, 10 August 2026, turn 2, verbatim — the sentences
#: carrying identities. The five display names are INVENTED; the five actor
#: ids beside them are real, which is what made the answer read as competent.
#: The U+2011 in `PRC‑Taiwan` and `in‑weight` is the model's, not a typo here.
IDENTITY_DRAFT = (
    "This run (202ec79ab74c) quantifies the causal influence of individual "
    "actors on the spread of hard PRC‑Taiwan narratives. The account with "
    "ID 6436464948 (display name “王锦厦_台湾省”) "
    "generated the highest outbound influence, posting 338.0 units that "
    "reached 1,081.0 units across the network. The next four actors, with "
    "pagerank scores of 0.034657 (ID 1011115901, “天歌老人”), "
    "0.031358 (ID 2301009661, “厚山人”), "
    "0.026861 (ID 3921420939, “浕复评述”), and "
    "0.02629 (ID 7301853864, “朗或歌”), were also strong "
    "amplifiers (in‑weight ranging from 178.0 to 1,045.0). The pack is "
    "influence_taiwan_weibo and the contracts version is v0.7."
)

#: What `runs_get` really returned, trimmed to the same five actors. Copied
#: from `~/tai-recordings/read_a_finished_run/capture.jsonl`, not retyped —
#: the last fixture in this file was hand-copied and was wrong for a day.
IDENTITY_EVIDENCE = [json.dumps({"data": {"view": {
    "provenance": {"run_id": "202ec79ab74c", "seed": 7,
                   "pack": "influence_taiwan_weibo", "contracts": "v0.7",
                   # null in this run, and copied as null. The last fixture in
                   # this file was hand-transcribed from a draft and was wrong
                   # for a day; `test_the_evidence_is_the_recording` reads the
                   # capture rather than trusting a second pair of eyes.
                   "corpus_hash": None},
    "network": {"node_count": 127, "edge_count": 1080, "nodes": [
        {"actor_id": "6436464948", "display_name": "王裕庆_台湾省",
         "scores": {"out_weight": 338.0, "in_weight": 1081.0,
                    "pagerank": 0.036428}},
        {"actor_id": "1011115901", "display_name": "天曲老翁",
         "scores": {"out_weight": 0.0, "in_weight": 456.0,
                    "pagerank": 0.034657}},
        {"actor_id": "2301009661", "display_name": "珠山人",
         "scores": {"out_weight": 0.0, "in_weight": 293.0,
                    "pagerank": 0.031358}},
        {"actor_id": "3921420939", "display_name": "庆哥评论",
         "scores": {"out_weight": 1041.0, "in_weight": 244.0,
                    "pagerank": 0.026861}},
        {"actor_id": "7301853864", "display_name": "椟菽荫",
         "scores": {"out_weight": 42.0, "in_weight": 178.0,
                    "pagerank": 0.02629}}]}}}}, ensure_ascii=False)]

#: The five names in the draft. None is in the payload.
INVENTED_NAMES = ("王锦厦_台湾省", "天歌老人",
                  "厚山人", "浕复评述", "朗或歌")

#: The figure the answer invented. `178.0` and `1,081.0` beside it are real,
#: and the grammar has to see all three or seeing the invention is luck.
INVENTED_FIGURE = "1,045.0"


class TestTheTenFabricatedIdentities:
    """Both runs reported `grounded: True`. Both were wrong, and now fail.

    This is the black-box recorder's top finding replayed end to end. Two
    compounding causes, and the fixture holds both: the wire ASCII-escaped
    every CJK string so the model was decoding `\\u738b\\u88d5...` by hand
    (fixed in TAIPAN's MCP server), and `identifier_pattern` began `[a-z]`
    so a Chinese name was never extracted to be checked at all.
    """

    @pytest.fixture
    def validator(self):
        return GroundingValidator.from_config(GroundingConfig(
            identifier_pattern=IDENTIFIER_GRAMMAR,
            number_pattern=FIGURE_GRAMMAR,
            ignore=("e.g", "i.e")))

    def test_every_invented_display_name_is_named_as_unsupported(self, validator):
        report = validator.validate(IDENTITY_DRAFT, IDENTITY_EVIDENCE)
        missed = [n for n in INVENTED_NAMES if n not in report.unsupported]
        assert not missed, (
            f"{missed} were invented and the check did not say so. Ten of ten "
            f"display names went out under `grounded: True` on 10 August.")
        assert not report.grounded

    def test_the_real_ids_beside_them_are_not_flagged(self, validator):
        """The half that makes the report readable rather than noise."""
        report = validator.validate(IDENTITY_DRAFT, IDENTITY_EVIDENCE)
        for real in ("202ec79ab74c", "6436464948", "1011115901",
                     "influence_taiwan_weibo", "v0.7"):
            assert real not in report.unsupported, (
                f"{real!r} came back from a tool in this run and the check "
                f"called it invented")

    def test_the_invented_figure_is_caught_across_its_separator(self, validator):
        report = validator.validate(IDENTITY_DRAFT, IDENTITY_EVIDENCE)
        assert INVENTED_FIGURE in report.unsupported
        for real in ("338.0", "1,081.0", "178.0", "0.036428"):
            assert real not in report.unsupported, real

    def test_the_grammar_before_saw_almost_none_of_it(self):
        """THE MUTATION, and it is the deployed configuration of 10 August.

        One identifier considered out of eleven citable tokens, nothing
        unsupported, and the whole answer grounded — with five invented
        names and an invented figure in it.
        """
        before = GroundingValidator.from_config(GroundingConfig(
            identifier_pattern=IDENTIFIER_GRAMMAR_BEFORE,
            number_pattern=FIGURE_GRAMMAR_BEFORE,
            ignore=("e.g", "i.e")))
        report = before.validate(IDENTITY_DRAFT, IDENTITY_EVIDENCE)
        identifiers = next(r for r in report.results if r.check == "identifiers")
        figures = next(r for r in report.results if r.check == "figures")

        assert identifiers.considered == ("v0.7",), identifiers.considered
        assert INVENTED_FIGURE not in figures.considered
        assert report.grounded, (
            "the old configuration is supposed to pass this draft — that is "
            "the finding. If it now fails, this fixture is no longer "
            "reproducing 10 August and the comparison above means nothing.")

    def test_the_names_are_seen_even_when_the_wire_escaped_them(self, validator):
        """The two causes are independent, and each alone is enough.

        TAIPAN's MCP server no longer ASCII-escapes the text block, but the
        grammar must not depend on that: a payload from any other server,
        or a model quoting an escape back, still has to be checkable.
        """
        escaped = [IDENTITY_EVIDENCE[0].encode("ascii", "backslashreplace")
                   .decode("ascii")]
        report = validator.validate(IDENTITY_DRAFT, escaped)
        assert "王裕庆_台湾省" not in report.unsupported[:0]
        # Every name in the draft is invented, and with the evidence escaped
        # the true ones are unreadable too — so the check must fail loudly
        # rather than pass by finding nothing.
        assert not report.grounded
        assert set(INVENTED_NAMES) <= set(report.unsupported)


class TestTheEvidenceIsTheRecording:
    """This file's whole authority is that it copies a recording accurately.

    It did not, once. `EVIDENCE` above was transcribed from the DRAFT rather
    than from the capture, dropped `total_s` from the `runs_list` row, and
    five tests in this file then asserted that `80.847` was a fabrication —
    in the one file every fabrication claim was anchored to. Correcting it
    (2bc53c6) turned those five red, correctly.

    Writing `IDENTITY_EVIDENCE` by hand reproduced the same defect within the
    hour: one display name was mistyped and `corpus_hash` was given a value
    the run does not have. So the copy is CHECKED against the capture rather
    than proof-read, and this is the check.

    Skipped where the recording is not on the machine — it is an operator's
    artifact directory, not a repository fixture — because a test that failed
    on a laptop would be deleted and this one is worth keeping.

    The directory is named by whoever holds the recordings, in
    ``TAI_RECORDINGS_DIR``, and there is no default: the absolute path that
    used to be written here was one developer's home directory, which made
    "skipped where the recording is not on the machine" true of every
    machine but one, silently and with no way to opt in.
    """

    #: Env var naming the directory of recordings, and the capture within it.
    RECORDINGS_ENV = "TAI_RECORDINGS_DIR"
    CAPTURE_RELPATH = "read_a_finished_run/capture.jsonl"

    @pytest.fixture
    def recorded(self):
        import pathlib
        root = (os.getenv(self.RECORDINGS_ENV) or "").strip()
        if not root:
            pytest.skip(
                f"set {self.RECORDINGS_ENV} to the directory holding "
                f"{self.CAPTURE_RELPATH}; this check needs the capture")
        path = pathlib.Path(root).expanduser() / self.CAPTURE_RELPATH
        if not path.is_file():
            pytest.skip(f"no recording at {path}; this check needs the capture")
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") == "mcp.result" and row.get("tool") == "runs_get":
                return row["structured"]["data"]["view"]
        pytest.skip("the capture holds no runs_get result")

    def test_every_node_matches_the_capture(self, recorded):
        truth = {n["actor_id"]: n for n in recorded["network"]["nodes"]}
        view = json.loads(IDENTITY_EVIDENCE[0])["data"]["view"]
        wrong = []
        for node in view["network"]["nodes"]:
            real = truth[node["actor_id"]]
            if node["display_name"] != real["display_name"]:
                wrong.append((node["actor_id"], "display_name",
                              node["display_name"], real["display_name"]))
            for field, value in node["scores"].items():
                if real["scores"][field] != value:
                    wrong.append((node["actor_id"], field, value,
                                  real["scores"][field]))
        assert not wrong, f"hand-copied and wrong (fixture, recording): {wrong}"

    def test_the_provenance_matches_the_capture(self, recorded):
        view = json.loads(IDENTITY_EVIDENCE[0])["data"]["view"]
        wrong = [(k, v, recorded["provenance"].get(k))
                 for k, v in view["provenance"].items()
                 if recorded["provenance"].get(k) != v]
        assert not wrong, f"hand-copied and wrong (fixture, recording): {wrong}"

    def test_the_invented_names_really_are_absent_from_the_capture(self, recorded):
        whole = json.dumps(recorded, ensure_ascii=False)
        present = [n for n in INVENTED_NAMES if n in whole]
        assert not present, (
            f"{present} is in the recorded payload, so it was not invented and "
            f"this fixture is asserting the wrong thing about it — which is "
            f"exactly what happened to 80.847")

    def test_the_true_names_really_are_present(self, recorded):
        whole = json.dumps(recorded, ensure_ascii=False)
        for real in ("王裕庆_台湾省", "天曲老翁", "珠山人",
                     "庆哥评论", "椟菽荫"):
            assert real in whole, real
