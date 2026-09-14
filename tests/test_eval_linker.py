# tests/test_eval_linker.py — the false-link instrument, and its teeth

"""`python -m core.eval linker` over the shipped corpus, and the proof it
can fail.

Two halves, and the second is the one that earns the file.  The first runs
the corpus this repository ships through the production attachment and
pins the number the design promises: **zero false links** — with a floor
under the claim, because a linker that linked *nothing* would also report
zero.  The second half feeds the runner outcomes the ground truth
forbids — an extra link, a missing one, a projected cross-kind claim, a
counter that moved — and asserts every one comes back RED: an instrument
that cannot fail is not an instrument, and the probe file's own loader is
held to the same rule (an unknown key is refused, never ignored, because
a misspelled assertion that is silently dropped is one that can never
fail).

The corpus's power against the disease it exists for is proven by
mutation, not by a test that ships: break the cross-kind guard in
`core.runtime.cognition._identify` (`one_kind = True`) and the three
cross-kind probes go red with the manufactured claims named — that run is
in the lane's mutation table, where every flip lives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cognition import CognitiveState
from core.eval import linker as mod
from core.eval.linker import (LinkProbe, ProbeMisdeclared, load_probes,
                              run_probe, run_probes)
from core.eval.run import main as eval_main

CORPUS = Path(__file__).resolve().parent / "fixtures" / "cognition" \
    / "link_probes.jsonl"


def probe(**overrides) -> LinkProbe:
    """A one-line healthy probe, overridden into whatever a test needs."""
    base = dict(
        id="p1", why="a test probe", tool="mcp.job_status",
        identifiers={"data.job_id": "job"},
        text=json.dumps({"data": {"job_id": "jl-1", "records": 3}}),
        expect_links=("job:jl-1",))
    base.update(overrides)
    return LinkProbe(**base)


class TestTheShippedCorpusIsGreen:
    def test_every_probe_passes_and_no_link_is_false(self):
        report = run_probes(load_probes(CORPUS))
        assert report.passed == len(report.verdicts)
        assert report.false_links == 0
        assert report.missed_links == 0

    def test_zero_false_links_is_not_zero_links(self):
        """The floor under the headline: a linker that linked NOTHING
        would also report zero false links, so the corpus must make the
        instrument link — the positive controls are load-bearing."""
        report = run_probes(load_probes(CORPUS))
        assert report.links_made >= 5, report.links_made

    def test_the_corpus_holds_both_adversarial_classes_by_name(self):
        """The design's two named near-misses (same value under a
        non-identifier key; colliding values across kinds) must stay in
        the corpus — a slimmed fixture that dropped one would leave the
        cross-kind guard measured by nothing."""
        ids = {p.id for p in load_probes(CORPUS)}
        assert "same_value_under_a_non_identifier_key" in ids
        assert "colliding_values_across_kinds" in ids

    def test_the_report_is_deterministic(self):
        """Same corpus, same bytes — the property the identity block
        claims, asserted rather than narrated."""
        probes = load_probes(CORPUS)
        assert run_probes(probes).to_json() == run_probes(probes).to_json()

    def test_the_identity_is_the_code_not_a_model(self):
        meta = run_probes(load_probes(CORPUS)[:1]).meta
        assert meta["commit"]
        assert meta["kernel"] and meta["event_schema"]
        assert meta["deterministic"] is True
        assert "model" not in meta and "provider" not in meta


class TestTheInstrumentCanFail:
    def test_a_link_the_truth_does_not_hold_is_a_false_link(self):
        verdict = run_probe(probe(expect_links=()))
        assert not verdict.passed
        assert verdict.false_links == ("job:jl-1",)

    def test_a_link_owed_and_not_made_is_missed(self):
        verdict = run_probe(probe(
            text=json.dumps({"data": {"records": 3}})))
        assert not verdict.passed
        assert verdict.missed_links == ("job:jl-1",)

    def test_a_forbidden_subject_field_that_is_held_goes_red(self):
        """`records` legitimately projects onto the subject, so forbidding
        it must fire — the pin that proves `forbid_subject_fields` reads
        the store rather than the probe's hopes."""
        verdict = run_probe(probe(
            forbid_subject_fields={"job:jl-1": ("records",)}))
        assert not verdict.passed
        assert any("forbidden field 'records'" in problem
                   for problem in verdict.problems)

    def test_an_expected_subject_field_that_is_absent_goes_red(self):
        verdict = run_probe(probe(
            expect_subject_fields={"job:jl-1": ("owner",)}))
        assert not verdict.passed
        assert any("does not hold expected field 'owner'" in problem
                   for problem in verdict.problems)

    def test_a_counter_that_moved_goes_red(self):
        verdict = run_probe(probe(expect_refused=1))
        assert not verdict.passed
        assert any("refused is 0, probe expects 1" in problem
                   for problem in verdict.problems)

    def test_a_crashed_cognition_is_red_not_a_quiet_empty_pass(self,
                                                               monkeypatch):
        """A shadow that stopped holds an empty store, and an empty store
        satisfies `expect_links: []` — so the stop itself must be a
        problem, or a hostile receipt could pass a probe by crashing."""

        class Dead:
            on = False
            failures = 1
            refused = ambiguous = unlinked = 0
            state = CognitiveState()

            def __init__(self, *args, **kwargs):
                pass

            def receipt(self, *args, **kwargs):
                pass

            def close_step(self):
                pass

        monkeypatch.setattr(mod, "ShadowCognition", Dead)
        verdict = run_probe(probe(expect_links=(),
                                  expect_refused=None))
        assert not verdict.passed
        assert any("cognition STOPPED" in problem
                   for problem in verdict.problems)


class TestTheLoaderRefusesWhatItCannotMean:
    def write(self, tmp_path, *lines) -> Path:
        path = tmp_path / "probes.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def line(self, **overrides) -> str:
        base = {"id": "p1", "why": "w", "tool": "t",
                "identifiers": {"data.job_id": "job"},
                "receipt": {"data": {"job_id": "jl-1"}},
                "expect_links": ["job:jl-1"]}
        base.update(overrides)
        return json.dumps(base)

    def test_an_unknown_key_is_refused_never_ignored(self, tmp_path):
        """The rule the whole file exists for: a misspelled `expect_linsk`
        silently dropped is an assertion that can never fail, wearing the
        name of one that can."""
        with pytest.raises(ProbeMisdeclared, match="expect_linsk"):
            load_probes(self.write(
                tmp_path, self.line(expect_linsk=["job:jl-1"])))

    def test_expect_links_is_required(self, tmp_path):
        raw = json.loads(self.line())
        del raw["expect_links"]
        with pytest.raises(ProbeMisdeclared, match="expect_links"):
            load_probes(self.write(tmp_path, json.dumps(raw)))

    def test_receipt_and_receipt_text_are_exclusive(self, tmp_path):
        with pytest.raises(ProbeMisdeclared, match="exactly one"):
            load_probes(self.write(
                tmp_path, self.line(receipt_text="{}")))

    def test_a_duplicate_id_is_refused(self, tmp_path):
        with pytest.raises(ProbeMisdeclared, match="duplicate"):
            load_probes(self.write(tmp_path, self.line(), self.line()))

    def test_a_line_that_is_not_json_is_refused(self, tmp_path):
        with pytest.raises(ProbeMisdeclared, match="not JSON"):
            load_probes(self.write(tmp_path, "{nope"))

    def test_an_empty_corpus_is_refused(self, tmp_path):
        path = tmp_path / "probes.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ProbeMisdeclared, match="no probes"):
            load_probes(path)

    def test_a_boolean_is_not_a_count(self, tmp_path):
        with pytest.raises(ProbeMisdeclared, match="expect_refused"):
            load_probes(self.write(
                tmp_path, self.line(expect_refused=True)))


class TestTheCommandLine:
    def test_the_shipped_corpus_exits_zero(self, capsys):
        assert eval_main(["linker", "--probes", str(CORPUS)]) == 0
        assert "false-link rate" in capsys.readouterr().out

    def test_a_red_probe_exits_one_and_allow_failures_lifts_it(
            self, tmp_path, capsys):
        path = tmp_path / "red.jsonl"
        path.write_text(json.dumps({
            "id": "red", "why": "expects a link nothing makes",
            "tool": "t", "identifiers": {"data.job_id": "job"},
            "receipt": {"data": {"records": 1}},
            "expect_links": ["job:never"]}) + "\n", encoding="utf-8")
        assert eval_main(["linker", "--probes", str(path)]) == 1
        capsys.readouterr()
        assert eval_main(["linker", "--probes", str(path),
                          "--allow-failures"]) == 0

    def test_only_an_unknown_id_exits_two_with_the_sentence(self, capsys):
        assert eval_main(["linker", "--probes", str(CORPUS),
                          "--only", "no_such_probe"]) == 2
        assert "no_such_probe" in capsys.readouterr().err

    def test_json_and_report_both_land(self, tmp_path, capsys):
        report = tmp_path / "out.md"
        assert eval_main(["linker", "--probes", str(CORPUS), "--json",
                          "--report", str(report)]) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["false_links"] == 0
        assert report.read_text(encoding="utf-8").startswith("# linker")
        beside = json.loads((tmp_path / "out.json")
                            .read_text(encoding="utf-8"))
        assert beside["probes"] == printed["probes"]

    def test_the_module_exports_what_it_documents(self):
        for name in mod.__all__:
            assert hasattr(mod, name), name
