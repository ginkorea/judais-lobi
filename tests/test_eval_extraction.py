# tests/test_eval_extraction.py — the extraction number, and what it counts

"""ROADMAP §2.9.3's gatekeeper, held to the thing it claims to measure.

`extraction` is the second subcommand in this package that needs a model, so
it is tested the way `measure` is: **the model is the only fake.** The probe
corpus is the real one this repository ships, the evidence walk is
`core.runtime.grounding`'s own, the report is the real report, and what is
scripted is the replies.

The scripted extractors are the four ways to be wrong, one each, so every
rate in the report has a backend that drives it to zero while the others
stay at one:

* the **perfect** extractor answers every probe correctly;
* the **fabricator** asserts a real field with a value the receipt does not
  hold — `grounded` catches it and `structural` does not;
* the **trap-faller** asserts the field each trap probe exists to count;
* the **non-abstainer** asserts something on every probe, including the ones
  whose receipt is silent;
* the **prose-emitter** answers in prose and then, asked again, in JSON —
  the repair path, which must be a success that is counted apart.

Numbers are pinned, not merely compared, because a rate that is only
asserted against another rate computed the same way is a tautology: both
move together under the mutation that would have been caught.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.eval import extraction as E
from core.eval.run import _parser, main

REPO = Path(__file__).resolve().parent.parent
PROBES = REPO / "tests" / "fixtures" / "extraction" / "probes.jsonl"


@pytest.fixture(scope="module")
def probes():
    return E.load_probes(PROBES)


# ── the corpus is the corpus ─────────────────────────────────────────────────

class TestTheProbeCorpusIsMeasurable:
    """Every refusal in `load_probes` is a defect that would otherwise be
    read as a model's score, so the shipped corpus is held to all of them."""

    def test_it_loads(self, probes):
        assert len(probes) >= 40, "ROADMAP §2.9.3 wants a corpus, not a demo"
        assert len(probes) <= 60

    def test_the_mix_is_roughly_half_assert_a_quarter_each(self, probes):
        """A corpus that was all `assert` would report a model that never
        abstains as excellent. The shape of the mix IS the instrument."""
        kinds = {kind: len([p for p in probes if p.kind == kind])
                 for kind in E.KINDS}
        assert kinds["assert"] >= len(probes) * 0.40
        assert kinds["abstain"] >= len(probes) * 0.20
        assert kinds["trap"] >= len(probes) * 0.20

    def test_both_measured_trap_classes_are_here_four_times_over(self, probes):
        """The two classes the 1.0 final gate measured: a `total_s` that is
        elapsed seconds beside a question about totals, and an optional
        filter that hides rather than selects."""
        for family in ("unit_semantics", "optional_filter"):
            assert len([p for p in probes if p.family == family]) >= 4

    def test_the_four_classes_measured_in_september_are_each_present(
            self, probes):
        for family in ("contradiction", "masked", "cause_absent",
                       "partial_coverage"):
            assert [p for p in probes if p.family == family], family

    def test_every_probe_says_where_its_receipt_came_from(self, probes):
        assert all(probe.source for probe in probes)

    def test_every_probes_evidence_is_a_parseable_receipt(self, probes):
        """Not invented prose: a receipt this harness can walk. A probe whose
        evidence yields no fields would score every extractor `ungrounded`
        and the number would be about the probe."""
        for probe in probes:
            keys, _scalars = E.fields_of(probe.evidence)
            assert keys, f"{probe.id} has no fields in its evidence"

    def test_every_gold_fact_is_in_its_own_evidence(self, probes):
        """The strongest lint there is: a gold pair the receipt does not
        carry marks a CORRECT extractor a fabricator."""
        for probe in probes:
            keys, scalars = E.fields_of(probe.evidence)
            for name, value in probe.gold:
                assert E.grounds(E.Proposition("ASSERT", name, value, "q"),
                                 keys, scalars), \
                    f"{probe.id}: gold ({name}, {value!r}) is not in the " \
                    f"receipt"

    def test_every_trap_field_exists_in_its_evidence(self, probes):
        """A trap nothing can fall into is not a trap."""
        for probe in probes:
            keys, _scalars = E.fields_of(probe.evidence)
            for name in probe.trap_fields:
                assert name in keys, f"{probe.id}: no trap field {name!r}"

    def test_an_absent_probes_missing_keys_really_are_missing(self, probes):
        """As far as this is mechanically checkable: the keys the probe
        declares absent are not keys the receipt carries."""
        for probe in probes:
            keys, _scalars = E.fields_of(probe.evidence)
            for name in probe.absent_fields:
                assert name not in keys, \
                    f"{probe.id} calls {name!r} absent and the receipt has it"
            if probe.family == "absent":
                assert probe.absent_fields, \
                    f"{probe.id} is the plain abstention case and names no " \
                    f"key the receipt lacks, so nothing checks it"

    def test_every_contradiction_probe_declares_its_two_sides(self, probes):
        """Surfacing both readings is a pass, and nothing can check that
        against sides nobody wrote down."""
        for probe in probes:
            if probe.family == "contradiction":
                assert len(probe.sides) >= 2, probe.id
            else:
                assert probe.sides == (), \
                    f"{probe.id} is not a contradiction and carries sides"

    def test_every_declared_side_is_in_its_own_evidence(self, probes):
        """Same lint as gold, for the same reason: a side the receipts do
        not carry would mark a correct extractor a fabricator."""
        for probe in probes:
            keys, scalars = E.fields_of(probe.evidence)
            for name, value in probe.sides:
                assert E.grounds(E.Proposition("ASSERT", name, value, "q"),
                                 keys, scalars), \
                    f"{probe.id}: side ({name}, {value!r}) is not in the " \
                    f"receipts"

    def test_the_sides_of_a_contradiction_actually_differ(self, probes):
        for probe in probes:
            pairs = {(name, str(value)) for name, value in probe.sides}
            assert len(pairs) == len(probe.sides), probe.id

    def test_no_gold_value_is_a_boolean(self, probes):
        """`parse_propositions` refuses a boolean ASSERT value — a
        proposition whose value is `true` says nothing a store can join on —
        so a gold fact that was one could never be asserted."""
        for probe in probes:
            for _name, value in probe.gold:
                assert not isinstance(value, bool), probe.id

    def test_every_family_the_module_declares_is_used(self, probes):
        used = {probe.family for probe in probes}
        assert used == set(E.FAMILIES), \
            "a family declared and unused is a class nobody measures"


class TestTheLoaderRefusesACorpusThatCannotMeasure:

    def _write(self, tmp_path, *records):
        path = tmp_path / "probes.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records),
                        encoding="utf-8")
        return path

    def _probe(self, **overrides):
        probe = {"id": "p", "family": "present", "source": "s",
                 "evidence": '{"a": 1}', "question": "what is a?",
                 "expect": {"kind": "assert",
                            "gold": [{"field": "a", "value": 1}]}}
        probe.update(overrides)
        return probe

    def test_a_duplicate_id_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(), self._probe())
        with pytest.raises(E.ProbeMisdeclared, match="twice"):
            E.load_probes(path)

    def test_a_family_nobody_declared_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(family="vibes"))
        with pytest.raises(E.ProbeMisdeclared, match="family"):
            E.load_probes(path)

    def test_a_family_scored_as_another_kind_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(family="absent"))
        with pytest.raises(E.ProbeMisdeclared, match="scored as"):
            E.load_probes(path)

    def test_an_abstain_probe_with_gold_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="absent",
            expect={"kind": "abstain",
                    "gold": [{"field": "a", "value": 1}]}))
        with pytest.raises(E.ProbeMisdeclared, match="no gold"):
            E.load_probes(path)

    def test_a_trap_probe_naming_no_trap_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="unit_semantics",
            expect={"kind": "trap", "gold": [{"field": "a", "value": 1}]}))
        with pytest.raises(E.ProbeMisdeclared, match="names the field"):
            E.load_probes(path)

    def test_a_field_that_is_both_gold_and_trap_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="unit_semantics",
            expect={"kind": "trap", "gold": [{"field": "a", "value": 1}],
                    "trap_fields": ["a"]}))
        with pytest.raises(E.ProbeMisdeclared, match="both gold and a trap"):
            E.load_probes(path)

    def test_a_contradiction_probe_with_no_sides_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="contradiction", expect={"kind": "abstain"}))
        with pytest.raises(E.ProbeMisdeclared, match="conflicting `sides`"):
            E.load_probes(path)

    def test_a_contradiction_probe_with_one_side_is_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="contradiction",
            expect={"kind": "abstain",
                    "sides": [{"field": "a", "value": 1}]}))
        with pytest.raises(E.ProbeMisdeclared, match="at least two"):
            E.load_probes(path)

    def test_two_identical_sides_are_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            family="contradiction",
            expect={"kind": "abstain",
                    "sides": [{"field": "a", "value": 1},
                              {"field": "a", "value": 1}]}))
        with pytest.raises(E.ProbeMisdeclared, match="do not conflict"):
            E.load_probes(path)

    def test_sides_on_any_other_family_are_refused(self, tmp_path):
        path = self._write(tmp_path, self._probe(
            expect={"kind": "assert",
                    "gold": [{"field": "a", "value": 1}],
                    "sides": [{"field": "a", "value": 1},
                              {"field": "a", "value": 2}]}))
        with pytest.raises(E.ProbeMisdeclared, match="only a contradiction"):
            E.load_probes(path)

    def test_an_empty_file_is_refused(self, tmp_path):
        path = tmp_path / "probes.jsonl"
        path.write_text("\n# nothing here\n", encoding="utf-8")
        with pytest.raises(E.ProbeMisdeclared, match="no probes"):
            E.load_probes(path)


# ── the reply, read structurally ─────────────────────────────────────────────

class TestAReplyIsReadOrNamedAsBroken:
    """A structurally invalid reply is a scored outcome and never a crash."""

    def test_a_bare_array_parses(self):
        props, defect = E.parse_propositions(
            '[{"status": "ASSERT", "field": "a", "value": 1, "quote": "a"}]')
        assert defect == ""
        assert props[0].status == "ASSERT" and props[0].field == "a"

    def test_a_fenced_array_parses(self):
        """Packaging, not structure: ROADMAP §2.9.5's grammar compiler is
        the answer to a fence, and failing one here would measure it."""
        props, defect = E.parse_propositions(
            'Sure:\n```json\n[{"status":"INSUFFICIENT_EVIDENCE","field":"",'
            '"value":null,"quote":""}]\n```\n')
        assert defect == ""
        assert props[0].status == "INSUFFICIENT_EVIDENCE"

    def test_a_lowercase_status_is_read(self):
        props, defect = E.parse_propositions(
            '[{"status": "assert", "field": "a", "value": 1, "quote": "a"}]')
        assert defect == "" and props[0].status == E.ASSERT

    def test_prose_is_a_defect_and_not_an_exception(self):
        props, defect = E.parse_propositions("I think a is 1.")
        assert props == () and "no JSON array" in defect

    def test_an_empty_reply_is_a_defect(self):
        assert E.parse_propositions("")[1] == "the reply was empty"

    def test_an_empty_array_is_a_defect(self):
        """Saying nothing is not abstaining: INSUFFICIENT_EVIDENCE is the
        way to abstain, and a store can be fed one and not the other."""
        assert "empty" in E.parse_propositions("[]")[1]

    def test_a_status_outside_the_vocabulary_is_a_defect(self):
        _props, defect = E.parse_propositions(
            '[{"status": "MAYBE", "field": "a", "value": 1, "quote": "a"}]')
        assert "MAYBE" in defect

    def test_an_assert_with_no_field_is_a_defect(self):
        _props, defect = E.parse_propositions(
            '[{"status": "ASSERT", "field": "", "value": 1, "quote": "a"}]')
        assert "names no field" in defect

    def test_an_assert_with_no_quote_is_a_defect(self):
        _props, defect = E.parse_propositions(
            '[{"status": "ASSERT", "field": "a", "value": 1, "quote": ""}]')
        assert "quotes nothing" in defect

    def test_a_boolean_assert_value_is_a_defect(self):
        _props, defect = E.parse_propositions(
            '[{"status": "ASSERT", "field": "a", "value": true, '
            '"quote": "a"}]')
        assert "not a string or a number" in defect

    def test_a_missing_quote_key_is_a_defect_even_when_abstaining(self):
        _props, defect = E.parse_propositions(
            '[{"status": "INSUFFICIENT_EVIDENCE", "field": "a", '
            '"value": null}]')
        assert "no quote" in defect


# ── grounding: the field half is the half that matters ───────────────────────

RECEIPT = '{"data": {"total_s": 154.024, "score": 0.7446, "state": "running"}}'


class TestGroundingPairsAFieldWithItsValue:

    def _grounds(self, name, value):
        keys, scalars = E.fields_of(RECEIPT)
        return E.grounds(E.Proposition("ASSERT", name, value, "q"), keys,
                         scalars)

    def test_the_right_value_at_the_right_field_is_grounded(self):
        assert self._grounds("total_s", 154.024)

    def test_a_string_value_is_grounded_too(self):
        assert self._grounds("state", "running")

    def test_a_recased_string_is_still_the_same_fact(self):
        assert self._grounds("state", "Running")

    def test_a_real_value_under_the_wrong_field_is_not_grounded(self):
        """The whole point. `154.024 (field score)` is a real number and a
        fabricated account of where it came from, and that is the half a
        reader cannot check and will cite onward."""
        assert not self._grounds("score", 154.024)

    def test_a_value_nothing_holds_is_not_grounded(self):
        assert not self._grounds("total_s", 186.701736)

    def test_a_field_nothing_carries_is_not_grounded(self):
        assert not self._grounds("influence_total", 154.024)

    def test_a_field_holding_a_structure_cannot_confirm_a_value(self):
        """`data` is a real key holding an object. An assertion about it is
        unconfirmable, and unconfirmable is not grounded — the difference
        from `FieldAttributionCheck`, which must not ACCUSE on that
        evidence where this must not COUNT it."""
        assert not self._grounds("data", "something")

    def test_a_number_written_as_a_string_is_the_same_number(self):
        """`core.runtime.grounding.same_value`'s rule, inherited rather than
        rewritten."""
        assert self._grounds("total_s", "154.024")


# ── gold: the same pairing, asked of the answer instead of the receipt ───────

class TestGoldIsAPairAndNotAValue:
    """The failure this catches is the one a scoreboard cannot see: an
    extractor that reads the right number off the wrong key. Downstream it
    is a proposition joined on the wrong predicate, which is worse than a
    missing one — it is confidently wrong and typed."""

    PROBE = E.Probe(
        id="p", family="unit_semantics", source="s",
        evidence=RECEIPT, question="what score?", kind="trap",
        gold=(("score", 0.7446),), trap_fields=("total_s",))

    def _score(self, *propositions):
        return E.score_attempt(
            self.PROBE,
            [E.Proposition("ASSERT", name, value, "q")
             for name, value in propositions], E.FIRST)

    def test_the_right_value_at_the_right_field_is_a_hit(self):
        attempt = self._score(("score", 0.7446))
        assert (attempt.gold_hits, attempt.gold_total) == (1, 1)
        assert attempt.off_gold == 0 and attempt.verdict

    def test_the_right_value_under_another_field_is_not_a_hit(self):
        attempt = self._score(("confidence", 0.7446))
        assert attempt.gold_hits == 0
        assert attempt.off_gold == 1
        assert not attempt.verdict

    def test_the_wrong_value_under_the_right_field_is_not_a_hit(self):
        attempt = self._score(("score", 0.9))
        assert attempt.gold_hits == 0 and attempt.off_gold == 1

    def test_a_correct_fact_plus_an_extra_one_loses_precision(self):
        attempt = self._score(("score", 0.7446), ("state", "running"))
        assert attempt.gold_hits == 1
        assert attempt.off_gold == 1
        assert not attempt.verdict

    def test_asserting_the_trap_field_springs_it_and_costs_precision(self):
        attempt = self._score(("score", 0.7446), ("total_s", 154.024))
        assert attempt.trap_clean is False
        assert attempt.sprung == ("total_s",)
        assert attempt.off_gold == 1

    def test_a_number_written_as_a_string_still_matches_gold(self):
        assert self._score(("score", "0.7446")).gold_hits == 1


# ── a conflict may be surfaced instead of swallowed ──────────────────────────

CONFLICT = (
    'mcp.job_status returned:\n{"data": {"job_id": "j-1", '
    '"state": "job_not_found"}}\n\n'
    'mcp.jobs_list returned:\n{"data": {"jobs": [{"job_id": "j-1", '
    '"state": "completed"}]}}')


class TestAConflictMaySurfaceInsteadOfBeingSwallowed:
    """The owner's ruling, and the better semantics: an answer that shows
    the reader the conflict beats silence, and silence still beats a
    silently chosen winner. Only the last of the three is a failure."""

    PROBE = E.Probe(
        id="c", family="contradiction", source="s", evidence=CONFLICT,
        question="what state is j-1 in?", kind="abstain",
        sides=(("state", "job_not_found"), ("state", "completed")))

    def _score(self, *propositions):
        return E.score_attempt(
            self.PROBE,
            [E.Proposition(status, name, value, quote)
             for status, name, value, quote in propositions], E.FIRST)

    def test_silence_still_passes(self):
        attempt = self._score(
            ("INSUFFICIENT_EVIDENCE", "", None, ""))
        assert attempt.abstained is True
        assert attempt.both_sides is False
        assert attempt.verdict

    def test_both_sides_as_two_asserts_with_their_own_quotes_passes(self):
        attempt = self._score(
            ("ASSERT", "state", "job_not_found", '"state": "job_not_found"'),
            ("ASSERT", "state", "completed", '"state": "completed"'))
        assert attempt.both_sides is True
        assert attempt.abstained is False
        assert attempt.verdict, "surfacing the conflict is a pass"

    def test_both_sides_as_contradicted_propositions_passes(self):
        attempt = self._score(
            ("CONTRADICTED", "state", "job_not_found", "one receipt"),
            ("CONTRADICTED", "state", "completed", "the other"))
        assert attempt.both_sides is True and attempt.verdict

    def test_one_asserted_and_the_other_hedged_passes(self):
        """Not 'one side alone': the conflict IS in front of the reader,
        with the relative confidence marked. The spectrum rule — mark
        confidence, don't punish it."""
        attempt = self._score(
            ("ASSERT", "state", "completed", '"state": "completed"'),
            ("HYPOTHESIZE", "state", "job_not_found", "the status tool"))
        assert attempt.both_sides is True and attempt.verdict

    def test_one_side_asserted_alone_fails(self):
        """The recorded failure, and now the only one: the model picked a
        winner and the reader never learns there was a race."""
        attempt = self._score(
            ("ASSERT", "state", "completed", '"state": "completed"'))
        assert attempt.both_sides is False
        assert attempt.abstained is False
        assert not attempt.verdict

    def test_two_asserts_off_one_quote_is_not_two_sources(self):
        """Opposite values read off the same span is one sentence
        contradicting itself, not two receipts disagreeing."""
        attempt = self._score(
            ("ASSERT", "state", "job_not_found", "the same span"),
            ("ASSERT", "state", "completed", "the same span"))
        assert attempt.both_sides is False and not attempt.verdict

    def test_one_proposition_cannot_serve_as_both_sides(self):
        attempt = self._score(
            ("ASSERT", "state", "completed", "q"),
            ("ASSERT", "state", "completed", "q2"))
        assert attempt.both_sides is False

    def test_an_unreadable_reply_surfaces_nothing(self):
        attempt = E.score_attempt(self.PROBE, (), E.INVALID)
        assert attempt.both_sides is False and not attempt.verdict

    def test_the_conflict_is_counted_in_its_own_rate_not_in_abstention(self):
        """`abstention` is an accuracy rate for probes where silence is the
        whole right answer. Counting a both-sides pass there would report
        the better answer as a miss."""
        surfaced = self._score(
            ("ASSERT", "state", "job_not_found", "one"),
            ("ASSERT", "state", "completed", "two"))
        rates = E.rates_of([surfaced])
        assert (rates["contradiction"].k, rates["contradiction"].n) == (1, 1)
        assert rates["abstention"].n == 0, \
            "a side-bearing probe does not belong in the abstention rate"


# ── a trap may be hedged, and that is examined rather than failed ────────────

class TestHedgingATrapIsExaminedAndNotFailed:
    """The owner's second ruling. `trap` keeps meaning *did not ASSERT from
    the trap field*; hedged wrongness gets a column of its own, outside the
    headline, because a deployment may tolerate one and not the other."""

    PROBE = E.Probe(
        id="t", family="unit_semantics", source="s", evidence=RECEIPT,
        question="what score?", kind="trap",
        gold=(("score", 0.7446),), trap_fields=("total_s",))

    def _score(self, *propositions):
        return E.score_attempt(
            self.PROBE,
            [E.Proposition(status, name, value, "q")
             for status, name, value in propositions], E.FIRST)

    def test_hedging_the_trap_leaves_trap_resistance_intact(self):
        attempt = self._score(("ASSERT", "score", 0.7446),
                              ("HYPOTHESIZE", "total_s", 154.024))
        assert attempt.trap_clean is True
        assert attempt.sprung == ()
        assert attempt.hedged == ("total_s",)
        assert attempt.hedged_trap is True

    def test_ambiguous_counts_as_hedging_too(self):
        attempt = self._score(("ASSERT", "score", 0.7446),
                              ("AMBIGUOUS", "total_s", 154.024))
        assert attempt.hedged_trap is True and attempt.trap_clean is True

    def test_a_hedged_trap_does_not_cost_the_probe_its_verdict(self):
        """The whole ruling in one assertion: the probe still PASSes."""
        attempt = self._score(("ASSERT", "score", 0.7446),
                              ("HYPOTHESIZE", "total_s", 154.024))
        assert attempt.verdict is True

    def test_a_hedge_is_not_an_assert_and_costs_no_precision(self):
        attempt = self._score(("ASSERT", "score", 0.7446),
                              ("HYPOTHESIZE", "total_s", 154.024))
        assert attempt.asserts == 1 and attempt.off_gold == 0

    def test_asserting_the_trap_is_still_a_failure(self):
        attempt = self._score(("ASSERT", "score", 0.7446),
                              ("ASSERT", "total_s", 154.024))
        assert attempt.trap_clean is False
        assert attempt.hedged_trap is False
        assert not attempt.verdict

    def test_the_two_are_counted_apart(self):
        """One reply can do both, and the columns must not merge them."""
        probe = E.Probe(
            id="t2", family="unit_semantics", source="s", evidence=RECEIPT,
            question="?", kind="trap", gold=(("score", 0.7446),),
            trap_fields=("total_s", "state"))
        attempt = E.score_attempt(probe, [
            E.Proposition("ASSERT", "score", 0.7446, "q"),
            E.Proposition("ASSERT", "total_s", 154.024, "q"),
            E.Proposition("HYPOTHESIZE", "state", "running", "q")], E.FIRST)
        assert attempt.sprung == ("total_s",)
        assert attempt.hedged == ("state",)
        assert attempt.trap_clean is False and attempt.hedged_trap is True

    def test_hedged_trap_is_a_rate_of_hedging_and_not_of_success(self):
        hedged = self._score(("ASSERT", "score", 0.7446),
                             ("HYPOTHESIZE", "total_s", 154.024))
        clean = self._score(("ASSERT", "score", 0.7446))
        rates = E.rates_of([hedged, clean])
        assert (rates["trap"].k, rates["trap"].n) == (2, 2)
        assert (rates["hedged_trap"].k, rates["hedged_trap"].n) == (1, 2)
        assert (rates["probe"].k, rates["probe"].n) == (2, 2), \
            "hedging is not folded into the headline"

    def test_only_a_trap_probe_is_asked_the_question(self):
        probe = E.Probe(id="p", family="present", source="s",
                        evidence=RECEIPT, question="?", kind="assert",
                        gold=(("score", 0.7446),))
        attempt = E.score_attempt(probe, [
            E.Proposition("HYPOTHESIZE", "total_s", 154.024, "q")], E.FIRST)
        assert attempt.hedged_trap is None and attempt.hedged == ()


# ── the Wilson interval ──────────────────────────────────────────────────────

class TestTheIntervalIsHonestAtTheEnds:

    def test_a_clean_sweep_still_has_a_width(self):
        """Twenty of twenty is not certainty. The normal approximation gives
        this a width of zero, which is the thing that made the 1.0 final
        gate's `20/20` chase meaningless."""
        low, high = E.wilson(20, 20)
        assert high == 1.0
        assert 0.80 < low < 0.85

    def test_zero_of_twenty_is_not_certainty_either(self):
        low, high = E.wilson(0, 20)
        assert low == 0.0
        assert 0.15 < high < 0.20

    def test_a_half_is_centred_near_a_half(self):
        low, high = E.wilson(50, 100)
        assert low < 0.5 < high
        assert round(high - low, 2) == 0.19

    def test_nothing_counted_is_a_zero_width_nothing(self):
        assert E.wilson(0, 0) == (0.0, 0.0)

    def test_a_wider_n_narrows_it(self):
        narrow = E.wilson(80, 100)
        wide = E.wilson(8, 10)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


# ── the scripted extractors ──────────────────────────────────────────────────

#: A subset with one probe of every kind, small enough that the pinned
#: numbers below can be read by eye.
SUBSET = ("totals_records", "runs_paging", "no_byte_count",
          "masked_record_count", "score_not_elapsed",
          "state_not_channel_running")

#: The subset for the two rulings: one conflict and one trap, driven by
#: extractors that surface and hedge rather than assert or stay silent.
SPECTRUM = ("job_state_disagrees", "run_stage_disagrees",
            "score_not_elapsed", "actors_not_edges")


def subset(probes, names=SUBSET):
    by_id = {probe.id: probe for probe in probes}
    return tuple(by_id[name] for name in names)


def _reply(propositions):
    return json.dumps([
        {"status": status, "field": name, "value": value, "quote": str(value)}
        for status, name, value in propositions])


def perfect(probe):
    """Every gold fact asserted, and nothing asserted where there is none."""
    if probe.kind == "abstain":
        return json.dumps([{"status": "INSUFFICIENT_EVIDENCE", "field": "",
                            "value": None, "quote": ""}])
    return _reply([("ASSERT", name, value) for name, value in probe.gold])


def fabricator(probe):
    """Real fields, values the receipt does not hold."""
    if probe.kind == "abstain":
        return json.dumps([{"status": "INSUFFICIENT_EVIDENCE", "field": "",
                            "value": None, "quote": ""}])
    return _reply([("ASSERT", name, 186.701736) for name, _v in probe.gold])


def trap_faller(probe):
    """The gold facts, plus the field each trap probe exists to count."""
    if probe.kind == "abstain":
        return json.dumps([{"status": "INSUFFICIENT_EVIDENCE", "field": "",
                            "value": None, "quote": ""}])
    out = [("ASSERT", name, value) for name, value in probe.gold]
    out += [("ASSERT", name, "whatever") for name in probe.trap_fields[:1]]
    return _reply(out)


def non_abstainer(probe):
    """Asserts on every probe, including the silent ones."""
    if probe.kind == "abstain":
        keys, scalars = E.fields_of(probe.evidence)
        name = sorted(scalars)[0]
        return _reply([("ASSERT", name, scalars[name][0])])
    return perfect(probe)


def surfacer(probe):
    """Shows both sides of a conflict; hedges over a trap rather than
    asserting it. The two behaviours the owner's rulings admit."""
    if probe.sides:
        return json.dumps([
            {"status": "ASSERT", "field": name, "value": value,
             "quote": f"receipt {index}: {name} = {value}"}
            for index, (name, value) in enumerate(probe.sides)])
    if probe.kind == "abstain":
        return json.dumps([{"status": "INSUFFICIENT_EVIDENCE", "field": "",
                            "value": None, "quote": ""}])
    out = [("ASSERT", name, value) for name, value in probe.gold]
    out += [("HYPOTHESIZE", name, "maybe") for name in probe.trap_fields[:1]]
    return _reply(out)


def winner_picker(probe):
    """Asserts ONE side of a conflict as if nothing disagreed — the failure
    both rulings leave standing."""
    if probe.sides:
        name, value = probe.sides[0]
        return _reply([("ASSERT", name, value)])
    return surfacer(probe)


def asker_for(reply_of):
    """A scripted backend: the probe is recognised by its own prompt.

    The repair turn always answers correctly, so the **prose-emitter** run
    below — ``reply_of`` returning prose — is the repair path end to end:
    invalid first, valid second, counted as `repaired` and never as
    `first_try`.
    """
    def ask(messages):
        first = messages[0]["content"]
        probe = _PROBE_BY_PROMPT[first]
        if len(messages) > 1:                 # this is the repair turn
            return perfect(probe)
        return reply_of(probe)
    return ask


_PROBE_BY_PROMPT: dict = {}


@pytest.fixture(scope="module")
def scripted(probes):
    for probe in probes:
        _PROBE_BY_PROMPT[E.prompt_for(probe)] = probe
    return subset(probes)


class TestTheScriptedExtractorsMoveTheNumbersTheyShould:
    """Each wrong extractor drives its own rate down and leaves the rest."""

    def rates(self, chosen, reply_of):
        attempts = E.run_probes(chosen, asker_for(reply_of), log=lambda *a: None)
        return E.rates_of(attempts), attempts

    def test_the_perfect_extractor_scores_everything(self, scripted):
        rates, attempts = self.rates(scripted, perfect)
        assert (rates["structural"].k, rates["structural"].n) == (6, 6)
        assert (rates["first_try"].k, rates["first_try"].n) == (6, 6)
        assert rates["repair"].k == 0
        assert rates["grounded"].k == rates["grounded"].n == 5
        assert (rates["gold_precision"].k, rates["gold_precision"].n) == (5, 5)
        assert (rates["gold_recall"].k, rates["gold_recall"].n) == (5, 5)
        assert (rates["abstention"].k, rates["abstention"].n) == (2, 2)
        assert (rates["trap"].k, rates["trap"].n) == (2, 2)
        assert (rates["probe"].k, rates["probe"].n) == (6, 6)
        assert all(a.verdict for a in attempts)

    def test_the_fabricator_is_structurally_perfect_and_ungrounded(
            self, scripted):
        """The rate that exists for exactly this: a reply of the right
        shape, with real field names, saying things the receipt does not."""
        rates, _ = self.rates(scripted, fabricator)
        assert (rates["structural"].k, rates["structural"].n) == (6, 6)
        assert rates["grounded"].k == 0
        assert rates["grounded"].n == 5
        assert rates["gold_recall"].k == 0
        assert rates["gold_precision"].k == 0
        assert rates["abstention"].k == 2          # it still abstains
        assert rates["probe"].k == 2               # the two abstain probes

    def test_the_trap_faller_springs_every_trap_and_nothing_else(
            self, scripted):
        rates, attempts = self.rates(scripted, trap_faller)
        assert rates["trap"].k == 0
        assert rates["trap"].n == 2
        assert rates["gold_recall"].k == rates["gold_recall"].n == 5
        assert rates["abstention"].k == 2
        assert rates["probe"].k == 4               # the two traps fail
        sprung = {a.probe: a.sprung for a in attempts if a.sprung}
        assert sprung == {"score_not_elapsed": ("total_s",),
                          "state_not_channel_running": ("submitted_via",)}

    def test_the_non_abstainer_fails_only_the_abstention_rate(self, scripted):
        rates, _ = self.rates(scripted, non_abstainer)
        assert rates["abstention"].k == 0
        assert rates["abstention"].n == 2
        assert rates["structural"].k == 6
        assert rates["trap"].k == 2
        assert rates["probe"].k == 4

    def test_the_prose_emitter_is_repaired_and_counted_as_repaired(
            self, scripted):
        """A repair is a success that cost a second call. Counting it as a
        first-try success is the mutation that erases the finding."""
        rates, attempts = self.rates(scripted, lambda p: "no JSON here")
        assert (rates["structural"].k, rates["structural"].n) == (6, 6)
        assert rates["first_try"].k == 0
        assert (rates["repair"].k, rates["repair"].n) == (6, 6)
        assert all(a.structural == E.REPAIRED for a in attempts)
        assert all(a.defects for a in attempts)
        assert (rates["probe"].k, rates["probe"].n) == (6, 6)

    def test_a_reply_that_never_parses_is_invalid_and_abstains_at_nothing(
            self, scripted):
        """An unreadable reply did not abstain and did not resist a trap. A
        model that emits prose must not come out the safest of all."""
        def never(messages):
            return "I am afraid I cannot put that in a JSON array."
        attempts = E.run_probes(scripted, never, log=lambda *a: None)
        rates = E.rates_of(attempts)
        assert rates["structural"].k == 0
        assert rates["abstention"].k == 0
        assert rates["trap"].k == 0
        assert rates["probe"].k == 0
        assert all(len(a.defects) == 2 for a in attempts)

    def test_repeats_multiply_the_attempts_and_the_denominator(self, scripted):
        attempts = E.run_probes(scripted, asker_for(perfect), repeats=3,
                                log=lambda *a: None)
        assert len(attempts) == 18
        assert {a.repeat for a in attempts} == {1, 2, 3}
        assert E.rates_of(attempts)["probe"].n == 18

    def test_an_endpoint_that_stops_answering_is_not_a_score(self, scripted):
        def dies(messages):
            raise ConnectionError("the endpoint closed the connection")
        with pytest.raises(E.Unextractable, match="stopped answering"):
            E.run_probes(scripted, dies, log=lambda *a: None)


class TestTheTwoRulingsEndToEnd:
    """The same rules again over the real corpus, through `run_probes`,
    because a rule that only holds where a unit test calls `score_attempt`
    is a rule the subcommand does not have."""

    @pytest.fixture()
    def spectrum(self, probes):
        for probe in probes:
            _PROBE_BY_PROMPT[E.prompt_for(probe)] = probe
        return subset(probes, SPECTRUM)

    def test_surfacing_and_hedging_scores_a_clean_sweep(self, spectrum):
        attempts = E.run_probes(spectrum, asker_for(surfacer),
                                log=lambda *a: None)
        rates = E.rates_of(attempts)
        assert (rates["contradiction"].k, rates["contradiction"].n) == (2, 2)
        assert (rates["trap"].k, rates["trap"].n) == (2, 2)
        assert (rates["hedged_trap"].k, rates["hedged_trap"].n) == (2, 2)
        assert (rates["probe"].k, rates["probe"].n) == (4, 4), \
            "hedging a trap and surfacing a conflict are both passes"
        assert rates["abstention"].n == 0

    def test_picking_a_winner_fails_only_the_conflict_probes(self, spectrum):
        attempts = E.run_probes(spectrum, asker_for(winner_picker),
                                log=lambda *a: None)
        rates = E.rates_of(attempts)
        assert (rates["contradiction"].k, rates["contradiction"].n) == (0, 2)
        assert (rates["trap"].k, rates["trap"].n) == (2, 2)
        assert (rates["probe"].k, rates["probe"].n) == (2, 4)
        picked = [a for a in attempts if a.both_sides is False]
        assert {a.probe for a in picked} == {"job_state_disagrees",
                                             "run_stage_disagrees"}

    def test_silence_on_a_conflict_is_still_a_pass(self, spectrum):
        attempts = E.run_probes(spectrum, asker_for(perfect),
                                log=lambda *a: None)
        conflicts = [a for a in attempts if a.both_sides is not None]
        assert all(a.abstained and a.verdict for a in conflicts)
        assert E.rates_of(attempts)["contradiction"].k == 2


# ── the report ───────────────────────────────────────────────────────────────

class TestTheReportCarriesItsInterpreter:

    @pytest.fixture()
    def report(self, scripted):
        attempts = E.run_probes(scripted, asker_for(perfect),
                                log=lambda *a: None)
        return E.ExtractionReport(
            probes="probes.jsonl", attempts=attempts,
            families=tuple(dict.fromkeys(p.family for p in scripted)),
            meta={"provider": "local", "model": "a-20b", "temperature": 0.2,
                  "endpoint": "http://endpoint/v1", "prompt": "abc123def456",
                  "commit": "0123456789ab", "date": "2026-09-13",
                  "probe_count": len(scripted), "repeats": 1})

    def test_the_markdown_names_the_model_the_temperature_and_the_endpoint(
            self, report):
        text = report.to_markdown()
        for token in ("a-20b", "0.2", "http://endpoint/v1", "abc123def456"):
            assert token in text, token

    def test_the_header_states_each_of_them_on_its_own_line(self, report):
        """Twice over, and deliberately: the header is what a reader skims
        and the identity sentence is what travels when one number is
        quoted. A header that quietly stopped recording the endpoint would
        still pass a test that only searched the whole page."""
        text = report.to_markdown()
        for bullet in ("- **provider / model**", "- **temperature** 0.2",
                       "- **endpoint** `http://endpoint/v1`",
                       "- **prompt** `abc123def456`", "- **commit**"):
            assert bullet in text, bullet

    def test_it_says_why_the_identity_is_beside_the_number(self, report):
        assert "not evidence" in report.to_markdown()

    def test_every_category_is_a_row_with_an_interval(self, report):
        text = report.to_markdown()
        for name, _what in E.CATEGORIES:
            assert f"`{name}`" in text, name
        assert "95% Wilson" in text

    def test_every_probe_is_a_row(self, report, scripted):
        text = report.to_markdown()
        for probe in scripted:
            assert f"`{probe.id}`" in text

    def test_the_json_carries_the_same_categories_as_the_markdown(
            self, report):
        """`measure.py`'s `_COLUMNS` lesson: a category added to one
        rendering and forgotten in the other."""
        payload = json.loads(report.to_json())
        assert set(payload["rates"]) == {name for name, _ in E.CATEGORIES}

    def test_the_json_keeps_the_replies_it_scored(self, report):
        payload = json.loads(report.to_json())
        assert all(entry["replies"] for entry in payload["attempts"])

    def test_the_families_are_broken_out(self, report):
        payload = json.loads(report.to_json())
        assert set(payload["by_family"]) == {"present", "absent", "masked",
                                             "unit_semantics",
                                             "optional_filter"}

    def test_the_family_table_carries_the_hedge_column(self, report):
        text = report.to_markdown()
        heading = next(line for line in text.splitlines()
                       if line.startswith("| family |"))
        assert "hedged_trap" in heading

    def test_the_prose_says_what_hedged_trap_is_and_is_not(self, report):
        text = report.to_markdown()
        assert "hedged wrongness" in text
        assert "not folded into `probe`" in text
        assert "teaches silence" in text

    def test_the_prose_says_a_conflict_may_be_surfaced(self, report):
        assert "surfaces BOTH readings" in report.to_markdown()

    def test_each_row_carries_its_stance_on_the_spectrum(self, report):
        text = report.to_markdown()
        heading = next(line for line in text.splitlines()
                       if line.startswith("| probe |"))
        assert "stance" in heading
        assert "| silent |" in text, "the abstain rows say so in the column"
        assert "| asserted |" in text

    def test_a_hedged_row_reads_as_hedged_and_not_as_asserted(self, probes):
        """The spectrum column exists because `verdict` cannot carry it:
        hedged-wrong and confident-wrong are one FAIL apiece there."""
        for probe in probes:
            _PROBE_BY_PROMPT[E.prompt_for(probe)] = probe
        chosen = subset(probes, ("score_not_elapsed",))
        attempts = E.run_probes(chosen, asker_for(surfacer),
                                log=lambda *a: None)
        report = E.ExtractionReport(probes="p", attempts=attempts, meta={})
        row = next(line for line in report.to_markdown().splitlines()
                   if "`score_not_elapsed`" in line)
        assert "hedged" in row and "hedged trap total_s" in row
        assert "PASS" in row

    def test_a_baseline_prints_deltas_and_questions_the_pairing(self, report):
        before = json.loads(report.to_json())
        before["meta"]["model"] = "another-model"
        before["rates"]["probe"]["rate"] = 0.5
        before["rates"]["probe"]["k"] = 3
        text = report.to_markdown(before)
        assert "against the baseline" in text
        assert "+50.0 pp" in text
        assert "another-model" in text
        assert "the two differ in" in text

    def test_a_baseline_names_the_probes_that_flipped(self, report, scripted):
        before = json.loads(report.to_json())
        before["attempts"][0]["verdict"] = False
        text = report.to_markdown(before)
        assert "changed verdict" in text
        assert f"`{scripted[0].id}`" in text


# ── the subcommand ───────────────────────────────────────────────────────────

class TestTheSubcommandIsWiredLikeTheOthers:

    def test_the_parser_holds_it(self):
        actions = [a for a in _parser()._actions
                   if hasattr(a, "choices") and isinstance(a.choices, dict)]
        assert "extraction" in actions[0].choices

    def test_it_takes_no_suite(self):
        """A probe is not a mission: there is nothing to spawn and nothing
        to hold out, and requiring a gradeable suite would be a check of
        something this subcommand never reads."""
        actions = [a for a in _parser()._actions
                   if hasattr(a, "choices") and isinstance(a.choices, dict)]
        flags = {option
                 for action in actions[0].choices["extraction"]._actions
                 for option in action.option_strings}
        assert "--suite" not in flags
        assert {"--probes", "--provider", "--model", "--temperature",
                "--repeats", "--report", "--baseline"} <= flags

    def test_a_missing_probes_file_is_a_refusal_and_not_a_traceback(
            self, tmp_path, capsys):
        assert main(["extraction", "--probes", str(tmp_path / "nope.jsonl"),
                     "--provider", "local"]) == 2
        assert "--probes" in capsys.readouterr().err

    def test_no_provider_anywhere_is_a_refusal(self, tmp_path, capsys,
                                               monkeypatch):
        monkeypatch.delenv("ELF_PROVIDER", raising=False)
        assert main(["extraction", "--probes", str(PROBES)]) == 2
        assert "--provider" in capsys.readouterr().err

    def test_only_narrows_the_corpus_and_an_unknown_id_is_refused(
            self, capsys):
        assert main(["extraction", "--probes", str(PROBES),
                     "--provider", "local", "--only", "not_a_probe"]) == 2
        assert "not_a_probe" in capsys.readouterr().err

    def test_it_runs_end_to_end_and_writes_both_renderings(
            self, tmp_path, monkeypatch, capsys, probes):
        """The real `from_args`, the real corpus, the real report — with
        the backend door closed and a scripted extractor behind it."""
        for probe in probes:
            _PROBE_BY_PROMPT[E.prompt_for(probe)] = probe
        monkeypatch.setattr(E, "asker",
                            lambda *a, **k: asker_for(perfect))
        out = tmp_path / "report.md"
        code = main(["extraction", "--probes", str(PROBES),
                     "--provider", "local", "--model", "a-20b",
                     "--temperature", "0.2", "--only", "totals_records",
                     "--only", "no_byte_count", "--report", str(out)])
        assert code == 0
        assert out.is_file() and out.with_suffix(".json").is_file()
        payload = json.loads(out.with_suffix(".json").read_text())
        assert payload["meta"]["model"] == "a-20b"
        assert payload["meta"]["temperature"] == 0.2
        assert payload["meta"]["prompt"] == E.prompt_fingerprint()
        assert len(payload["attempts"]) == 2
        assert "extraction —" in capsys.readouterr().out
