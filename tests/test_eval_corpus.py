# tests/test_eval_corpus.py — the training corpus, held to "copied, never invented"

"""ROADMAP §2.9.8's first step, tested against the one property it sells.

`core.eval corpus` writes training data, and a training corpus is the one
artefact in this tree whose defects are invisible at the moment they are
made: a wrong rate is argued about the same afternoon, and a completion
somebody tidied on the way out is discovered months later as a checkpoint
that learned to answer a question nobody asks. So the assertions here are
about **bytes**: the completion written is the string the model emitted,
character for character, and the turns around it are the turns
`core.eval.extraction` sent — rebuilt through its own `prompt_for`, so that
a prompt change cannot quietly become a corpus change.

Nothing here is mocked except the report, and the report is mocked the way
the extraction tests mock a model: the *replies* are scripted and everything
else is real — the shipped probe corpus, the real recorded run directories
under `tests/fixtures/runs`, the real redactor, the real file writer.

The three counts that must be able to fail, and do:

* a completion that is normalised, re-serialised or "cleaned" — the
  verbatim assertions go red;
* the abstention floor — `test_a_corpus_below_the_floor_warns` goes red if
  the check is dropped, because §2.9.8 wants this corpus abstention-heavy
  and a silent thin one is the failure Phase 21 exists to avoid;
* the refuse-after-scrub path — a credential shape that survives the
  redactor must never reach the file, and the assertion is on the bytes of
  the file and not on a counter.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.eval import corpus as C
from core.eval.extraction import (load_probes, prompt_fingerprint, prompt_for,
                                  repair_for)
from core.eval.run import _parser, main

REPO = Path(__file__).resolve().parent.parent
PROBES = REPO / "tests" / "fixtures" / "extraction" / "probes.jsonl"
RUNS = REPO / "tests" / "fixtures" / "runs"

#: One real reply per kind, in the shape the instrument recorded them — the
#: odd spacing included, because that is what "verbatim" has to survive.
ASSERTED = ('[{"status":"ASSERT","field":"records","value":12481,'
            '"quote":"\\"records\\": 12481"}]')
ABSTAINED = ('[{"status": "INSUFFICIENT_EVIDENCE", "field": "bytes", '
             '"value": "", "quote": ""}]')
TRAP_CLEAN = ('[{"status":"ASSERT","field":"score","value":1.0,'
              '"quote":"\\"score\\": 1.0"}]')


@pytest.fixture(scope="module")
def probes():
    return {probe.id: probe for probe in load_probes(PROBES)}


# ── building a report the way the instrument writes one ──────────────────────

def attempt(probe: str, kind: str, *, verdict: bool = True,
            replies=(ASSERTED,), structural: str = "first", defects=(),
            propositions=None, repeat: int = 1) -> dict:
    """One `Attempt.as_dict()`, in the report's own shape."""
    if propositions is None:
        propositions = [{"status": "ASSERT", "field": "records",
                         "value": 12481, "quote": '"records": 12481'}]
    return {"probe": probe, "family": "present", "kind": kind,
            "repeat": repeat, "structural": structural,
            "defects": list(defects), "propositions": list(propositions),
            "replies": list(replies), "verdict": verdict}


def report(attempts, **meta) -> dict:
    base = {"provider": "local", "model": "openai/gpt-oss-20b",
            "temperature": 0.2, "constrained": False,
            "prompt": prompt_fingerprint(False), "scorer": 2,
            "commit": "0" * 40, "date": "2026-09-13"}
    base.update(meta)
    return {"probes": "probes.jsonl", "meta": base, "attempts": list(attempts)}


def build(tmp_path: Path, payload: dict, *argv) -> tuple[int, dict, list]:
    """Run the subcommand over *payload* and read back what it wrote."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "report.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "corpus.jsonl"
    code = main(["corpus", "--out", str(out), "--from-extraction",
                 str(source), "--probes", str(PROBES), *argv])
    if not out.exists():
        return code, {}, []
    lines = [json.loads(line) for line in
             out.read_text(encoding="utf-8").splitlines() if line.strip()]
    return code, lines[0], lines[1:]


# ── a passing attempt becomes the turns that were sent ───────────────────────

def test_a_passing_attempt_is_the_prompt_and_the_reply_verbatim(tmp_path,
                                                                probes):
    """One example, two facts: the turn was rebuilt and the reply was copied.

    `prompt_for` is called here as well, deliberately — the corpus must
    agree with the instrument by *construction* and not by a string that
    happens to match today. If the prompt is ever reworded, this test and
    the corpus move together and the fingerprint guard (below) refuses the
    old reports.
    """
    code, header, rows = build(
        tmp_path, report([attempt("totals_records", "assert")]))
    assert code == 0
    assert len(rows) == 1
    example = rows[0]
    assert example["messages"] == [
        {"role": "user", "content": prompt_for(probes["totals_records"])}]
    # The mutation this pins: any normalising of the completion — a
    # json.loads/json.dumps round trip, a strip(), a re-indent — changes
    # these bytes and nothing else in the file would notice.
    assert example["completion"] == ASSERTED
    assert example["meta"]["probe"] == "totals_records"
    assert example["meta"]["kind"] == "assert"
    assert example["meta"]["stance"] == "asserted"
    assert example["meta"]["source"] == "extraction"
    assert example["meta"]["interpreter"]["model"] == "openai/gpt-oss-20b"
    assert header["examples"] == 1


def test_a_repaired_attempt_carries_the_failed_reply_and_the_repair(tmp_path,
                                                                    probes):
    """Three turns, because that is the conversation the pass answered.

    A repaired attempt is a real success — the instrument counts it apart as
    a cost, not a failure — and the completion it produced was the answer to
    a prompt that already held the model's own bad reply and the sentence
    naming the defect. Training the passing completion against the *first*
    turn alone would teach the model to emit the repair without ever having
    been told what was wrong.
    """
    code, _header, rows = build(tmp_path, report([
        attempt("totals_records", "assert", structural="repaired",
                replies=["here is the answer: 12481", ASSERTED],
                defects=["the reply is not a JSON array"])]))
    assert code == 0
    assert [m["role"] for m in rows[0]["messages"]] == [
        "user", "assistant", "user"]
    assert rows[0]["messages"][0]["content"] == prompt_for(
        probes["totals_records"])
    assert rows[0]["messages"][1]["content"] == "here is the answer: 12481"
    assert rows[0]["messages"][2]["content"] == repair_for(
        "the reply is not a JSON array")
    assert rows[0]["completion"] == ASSERTED
    assert rows[0]["meta"]["structural"] == "repaired"


def test_a_failed_attempt_is_excluded_and_counted(tmp_path):
    """The corpus is validated behaviour; the count says how much was not."""
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert"),
        attempt("score_not_elapsed", "trap", verdict=False,
                replies=['[{"status":"ASSERT","field":"total_s",'
                         '"value":154.024,"quote":"x"}]']),
        attempt("no_byte_count", "abstain", verdict=False, replies=["nope"]),
    ]))
    assert code == 0
    assert [row["meta"]["probe"] for row in rows] == ["totals_records"]
    assert header["excluded"]["failed_probe"] == 2


def test_an_attempt_with_no_recorded_reply_is_never_invented(tmp_path):
    """A pass with nothing to copy is dropped, not reconstructed."""
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert", replies=[])]))
    assert code == 0
    assert rows == []
    assert header["excluded"]["no_reply"] == 1


def test_a_repair_that_cannot_be_rebuilt_leaves(tmp_path):
    """Half a conversation is not a training example.

    A `repaired` attempt whose first reply or whose defect sentence was not
    recorded would have to have one of them invented, and the completion is
    only true as the answer to the turns that were actually sent.
    """
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert", structural="repaired",
                replies=[ASSERTED], defects=["not a JSON array"]),
        attempt("totals_blocks", "assert", structural="repaired",
                replies=["prose", ASSERTED], defects=[]),
    ]))
    assert code == 0
    assert rows == []
    assert header["excluded"]["unrebuildable_repair"] == 2


# ── the two refusals that protect the weights ────────────────────────────────

def test_a_probe_the_corpus_does_not_hold_is_refused(tmp_path):
    """A report rebuilt against the wrong probes would train on the wrong
    questions, so the build stops rather than guessing at one."""
    code, _header, rows = build(tmp_path, report([
        attempt("a_probe_from_another_file", "assert")]))
    assert code == 1
    assert rows == []


def test_a_report_from_another_prompt_is_refused(tmp_path):
    """The fingerprint is what says the turns can be rebuilt at all.

    Yesterday's replies under today's wording is a file of answers to an
    instruction the model will never see again — and it is silent: every
    line of it looks perfectly well formed.
    """
    code, _header, rows = build(tmp_path, report(
        [attempt("totals_records", "assert")], prompt="deadbeef0000"))
    assert code == 1
    assert rows == []


def test_a_report_that_is_not_one_is_refused(tmp_path):
    code, _header, _rows = build(tmp_path, {"meta": {}, "rates": {}})
    assert code == 1


# ── the abstention floor ─────────────────────────────────────────────────────

def test_a_corpus_below_the_floor_warns_and_is_still_written(tmp_path, capsys):
    """§2.9.8 wants abstention-heavy, and a thin corpus says so out loud.

    Warn, not refuse: the share is a property of a sample nobody controls —
    a model that fails every trap leaves few passing trap examples behind,
    which is exactly when the operator most needs to be told and least needs
    a tool that declines to write the file.

    The mutation: delete the floor comparison in `from_args` and this goes
    red, because nothing else in the output mentions the share against the
    floor.
    """
    code, header, rows = build(tmp_path, report(
        [attempt(name, "assert") for name in
         ("totals_records", "totals_blocks", "totals_run_id", "actors_top")]
        + [attempt("no_byte_count", "abstain", replies=[ABSTAINED],
                   propositions=[{"status": "INSUFFICIENT_EVIDENCE",
                                  "field": "bytes", "value": "",
                                  "quote": ""}])]))
    assert code == 0
    assert len(rows) == 5
    assert header["abstention_share"] == pytest.approx(0.2)
    printed = capsys.readouterr().out
    assert "below the floor" in printed
    assert "20%" in printed


def test_a_corpus_above_the_floor_says_nothing(tmp_path, capsys):
    code, header, _rows = build(tmp_path, report([
        attempt("totals_records", "assert"),
        attempt("no_byte_count", "abstain", replies=[ABSTAINED],
                propositions=[{"status": "INSUFFICIENT_EVIDENCE",
                               "field": "bytes", "value": "", "quote": ""}]),
    ]))
    assert code == 0
    assert header["abstention_share"] == pytest.approx(0.5)
    assert "below the floor" not in capsys.readouterr().out


def test_balance_downsamples_the_assert_half_to_reach_the_floor(tmp_path,
                                                                capsys):
    """Four asserts and one abstention is 20%; --balance leaves 40%.

    And a corpus balanced to the floor does not then warn about the floor:
    the drop counts down under the same comparison the warning makes, which
    is why the closed-form float that lands on 2.9999999999999996 is not
    used.
    """
    payload = report([attempt(name, "assert") for name in
                      ("totals_records", "totals_blocks", "totals_run_id",
                       "actors_top")]
                     + [attempt("no_byte_count", "abstain",
                                replies=[ABSTAINED],
                                propositions=[{"status":
                                               "INSUFFICIENT_EVIDENCE",
                                               "field": "bytes", "value": "",
                                               "quote": ""}])])
    code, header, rows = build(tmp_path, payload, "--balance")
    assert code == 0
    assert header["abstention_share"] >= C.ABSTENTION_FLOOR
    assert header["excluded"]["balanced_out"] == 3
    assert len(rows) == 2
    # Input order survives a drop: --balance is a subset, not a shuffle.
    assert [row["meta"]["kind"] for row in rows] == ["assert", "abstain"]
    assert [row["meta"]["probe"] for row in rows] == ["totals_run_id",
                                                      "no_byte_count"]
    assert "below the floor" not in capsys.readouterr().out


def test_balance_is_deterministic_in_its_seed(tmp_path):
    """Two builds of the same inputs are the same file; a different seed is
    a different sample of the same corpus.

    The kept set is **pinned** and not merely compared with itself: the
    drop order is a sha256 over the seed and the example's provenance, and
    a mutation that dropped the path-dependence — or the seed — would leave
    a test that still agreed with itself. The same pinning is why the key
    carries no file path: these two ids are what any machine keeps.
    """
    payload = report([attempt(name, "assert") for name in
                      ("totals_records", "totals_blocks", "totals_run_id",
                       "actors_top", "actors_second_score",
                       "actors_listing_run")]
                     + [attempt(name, "abstain", replies=[ABSTAINED])
                        for name in ("no_byte_count", "no_run_cost")])
    first = build(tmp_path / "a", payload, "--balance", "--seed", "0")
    second = build(tmp_path / "b", payload, "--balance", "--seed", "0")
    third = build(tmp_path / "c", payload, "--balance", "--seed", "3")
    kept = [r["meta"]["probe"] for r in first[2] if r["meta"]["kind"] ==
            "assert"]
    assert kept == ["totals_run_id", "actors_second_score",
                    "actors_listing_run"]
    assert [r["meta"]["probe"] for r in second[2]] == \
           [r["meta"]["probe"] for r in first[2]]
    assert [r["meta"]["probe"] for r in third[2] if r["meta"]["kind"] ==
            "assert"] == ["totals_records", "totals_blocks", "actors_top"]


def test_balance_leaves_a_corpus_it_cannot_fix(tmp_path):
    """No abstentions at all: dropping the rest would fix a ratio by
    destroying the sample, so nothing is dropped and the warning stands."""
    payload = report([attempt(name, "assert") for name in
                      ("totals_records", "totals_blocks")])
    code, header, rows = build(tmp_path, payload, "--balance")
    assert code == 0
    assert len(rows) == 2
    assert "balanced_out" not in header["excluded"]


# ── the scrub, and the second opinion ────────────────────────────────────────

def test_the_scrub_redacts_a_credential_the_redactor_owns(tmp_path):
    """A bearer header in a recorded reply is written, redacted, and the
    count of rewritten examples is on the header."""
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert",
                replies=['[{"status":"ASSERT","field":"records",'
                         '"value":12481,"quote":"Authorization: Bearer '
                         'abc123def456ghi789"}]'])]))
    assert code == 0
    assert len(rows) == 1
    assert "abc123def456ghi789" not in rows[0]["completion"]
    assert "<redacted:" in rows[0]["completion"]
    assert header["scrub_changed"] == 1


def test_a_credential_shape_that_survives_the_scrub_is_never_written(tmp_path):
    """The second opinion, and the reason there is one.

    A bearer token that arrives without the word `Bearer` in front of it —
    a bare JWT under a key nobody called `_TOKEN` — is a shape
    `core.redact` has no rule for, so re-running the redactor and asking it
    again would answer a question nobody had. `residue_in` looks with its
    own patterns, and what it finds is refused: counted, and absent from
    the file.

    The mutation: write the example anyway and this goes red on the bytes
    of the file, not on the counter.
    """
    token = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
             "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P")
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert"),
        attempt("totals_blocks", "assert",
                replies=['[{"status":"ASSERT","field":"blocks","value":7,'
                         '"quote":"session ' + token + '"}]'])]))
    assert code == 0
    assert header["excluded"]["credential_residue"] == 1
    assert [row["meta"]["probe"] for row in rows] == ["totals_records"]
    written = (tmp_path / "corpus.jsonl").read_text(encoding="utf-8")
    assert token not in written
    assert "eyJhbGci" not in written


def test_residue_walks_to_any_depth():
    """A secret inside a nested mapping is still a secret."""
    assert C.residue_in({"meta": {"flags": ["ghp_" + "a" * 20]}}) == \
        "github-token"
    assert C.residue_in(["-----BEGIN RSA PRIVATE KEY-----"]) == "private-key"
    # The English words, which a check that only counted characters would
    # have refused a corpus over.
    assert C.residue_in("bearer authentication is not a bearer token") is None


# ── recorded runs ────────────────────────────────────────────────────────────

#: The four recorded runs these tests are about, named rather than swept
#: for. `tests/fixtures/runs/` is also where the durable-store tests leave a
#: run behind when the suite runs, and a test that pointed `--from-runs` at
#: the directory itself would count whatever else the day's suite had
#: dropped there — green on a clean checkout and red on the second run, for
#: a reason nothing in the assertion names.
CORPUS_RUNS = ("run_corpusjson-0001", "run_corpusnative-0001",
               "run_corpusswarm-0001", "run_corpusswarmcaveat-0001")


def staged(tmp_path: Path) -> Path:
    """The four fixture runs, copied where only this test can reach them."""
    root = tmp_path / "runs"
    root.mkdir(parents=True, exist_ok=True)
    for name in CORPUS_RUNS:
        shutil.copytree(RUNS / name, root / name, dirs_exist_ok=True)
    return root


def runs_build(tmp_path: Path, *argv) -> tuple[int, dict, list]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "corpus.jsonl"
    code = main(["corpus", "--out", str(out), "--from-runs",
                 str(staged(tmp_path)), *argv])
    lines = [json.loads(line) for line in
             out.read_text(encoding="utf-8").splitlines() if line.strip()]
    return code, lines[0], lines[1:]


def test_a_recorded_run_that_answered_yields_one_example_per_call(tmp_path):
    """The request as recorded, the reply as recorded, tagged by position."""
    code, header, rows = runs_build(tmp_path)
    assert code == 0
    ours = [row for row in rows if row["meta"]["run"] == "run_corpusjson-0001"]
    assert len(ours) == 2
    assert [row["meta"]["position"] for row in ours] == ["tool_call", "answer"]
    assert [row["meta"]["seq"] for row in ours] == [1, 2]
    recorded = [json.loads(line) for line in
                (RUNS / "run_corpusjson-0001" / "model.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()]
    assert ours[0]["messages"] == recorded[0]["request"]["messages"]
    assert ours[0]["completion"] == recorded[0]["reply"]["content"]
    assert ours[1]["completion"] == recorded[1]["reply"]["content"]
    assert header["by_source"]["runs"] == len(rows)


def test_a_run_the_grounding_would_not_verify_leaves_whole(tmp_path):
    """`answered_with_caveat` is the validator saying it could not check the
    answer. A corpus of validated traces does not train on it."""
    _code, header, rows = runs_build(tmp_path)
    assert header["excluded"]["not_answered"] == 1
    assert not [row for row in rows
                if row["meta"]["run"] == "run_corpusswarmcaveat-0001"]


def test_a_native_reply_has_no_text_to_copy_and_says_so(tmp_path):
    """v1 writes text completions. A `--protocol native` turn puts its
    payload in `tool_calls`, and rendering that structure into a string
    would be inventing a target format the model never emitted."""
    _code, header, rows = runs_build(tmp_path)
    assert header["excluded"]["no_text_reply"] == 2
    assert not [row for row in rows
                if row["meta"]["run"] == "run_corpusnative-0001"]


def test_the_flag_filter_selects_runs(tmp_path):
    """Every filter must match, and a run that does not is counted."""
    _code, _header, all_runs = runs_build(tmp_path, "--flag-filter",
                                          "skill=SKILL.md")
    assert {row["meta"]["run"] for row in all_runs} == {
        "run_corpusjson-0001", "run_corpusswarm-0001"}

    _code, header, swarmed = runs_build(tmp_path / "swarm", "--flag-filter",
                                        "skill=SKILL.md", "--flag-filter",
                                        "swarm=True")
    assert {row["meta"]["run"] for row in swarmed} == {"run_corpusswarm-0001"}
    assert header["excluded"]["flags"] == 2

    _code, header, none = runs_build(tmp_path / "nothing", "--flag-filter",
                                     "skill=other.md")
    assert none == []
    assert header["excluded"]["flags"] == 4


def test_a_run_with_no_model_log_is_counted_not_crashed(tmp_path):
    empty = tmp_path / "runs" / "run_nothing"
    empty.mkdir(parents=True)
    out = tmp_path / "corpus.jsonl"
    code = main(["corpus", "--out", str(out), "--from-runs",
                 str(tmp_path / "runs")])
    assert code == 0
    header = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert header["excluded"]["no_model_log"] == 1
    assert header["abstention_share"] is None


def test_the_run_bar_is_one_function():
    """Every reason a run may not be trained on, asked of one place."""
    answered = [{"event": "mission_finished", "outcome": "answered"}]
    assert C._bar(answered) is None
    assert C._bar([]) == "no_stream"
    assert C._bar([{"event": "mission_finished",
                    "outcome": "answered_with_caveat"}]) == "not_answered"
    assert C._bar(answered + [{"event": "reply_rejected",
                               "problem": "x"}]) == "reply_rejected"
    assert C._bar(answered + [{"event": "grounding", "ran": True,
                               "grounded": False,
                               "verified": False}]) == "grounding_rejected"
    # A deployment that declined the checks (`--no-grounding`) recorded a
    # grounding that did not run, and that is not a rejection.
    assert C._bar(answered + [{"event": "grounding", "ran": False,
                               "grounded": False, "verified": False}]) is None


# ── the header, the digest, the command line ─────────────────────────────────

def test_every_reason_the_code_counts_is_a_reason_the_table_explains():
    """`EXCLUSIONS` is the vocabulary, not a comment beside it.

    A reason counted in the code and missing from the table is a number a
    reader of a corpus meets with no sentence attached — which is the whole
    complaint the table exists to answer. Read out of the source rather
    than out of a run, so a branch no fixture happens to hit is still held
    to it.
    """
    import re

    source = (REPO / "core" / "eval" / "corpus.py").read_text(encoding="utf-8")
    counted = set(re.findall(r'excluded\["([a-z_]+)"\]', source))
    assert counted, "the sweep found nothing; the spelling moved"
    assert counted - set(C.EXCLUSIONS) == set()
    assert all(len(why) > 20 for why in C.EXCLUSIONS.values())


def test_the_header_counts_what_the_file_holds(tmp_path):
    code, header, rows = build(tmp_path, report([
        attempt("totals_records", "assert"),
        attempt("no_byte_count", "abstain", replies=[ABSTAINED],
                propositions=[{"status": "INSUFFICIENT_EVIDENCE",
                               "field": "bytes", "value": "", "quote": ""}]),
        attempt("score_not_elapsed", "trap", replies=[TRAP_CLEAN],
                propositions=[{"status": "ASSERT", "field": "score",
                               "value": 1.0, "quote": '"score": 1.0'}]),
        attempt("totals_blocks", "assert", verdict=False, replies=["no"]),
    ]), "--note", "fixtures only")
    assert code == 0
    assert header[C.SCHEMA_KEY] == C.CORPUS_SCHEMA_VERSION
    assert header["examples"] == len(rows) == 3
    assert header["by_kind"] == {"assert": 1, "abstain": 1, "trap": 1}
    assert header["by_source"] == {"extraction": 3}
    assert header["excluded"] == {"failed_probe": 1}
    assert header["license_note"] == "fixtures only"
    assert all(row["meta"]["license_note"] == "fixtures only" for row in rows)
    assert C.SCRUB_STATEMENT in header["scrub"]


def test_the_digest_is_of_the_file_and_is_stable(tmp_path, capsys):
    """The corpus is an experiment input, so it carries an identity.

    Two builds of the same inputs print the same digest, and it is the
    digest of the bytes on disk — a reader can check it with `sha256sum`.
    """
    payload = report([attempt("totals_records", "assert")])
    build(tmp_path, payload)
    first = capsys.readouterr().out
    build(tmp_path, payload)
    second = capsys.readouterr().out
    digest = [line for line in first.splitlines() if "digest:" in line][0]
    assert digest in second
    written = (tmp_path / "corpus.jsonl").read_text(encoding="utf-8")
    assert C.digest_of(written) in digest


def test_the_corpus_subcommand_is_registered_and_needs_a_source(tmp_path,
                                                                capsys):
    parsed = _parser().parse_args(["corpus", "--out", str(tmp_path / "c")])
    assert parsed.command == "corpus"
    assert main(["corpus", "--out", str(tmp_path / "c.jsonl")]) == 2
    assert "at least one source" in capsys.readouterr().err


def test_a_floor_outside_a_share_is_refused(tmp_path, capsys):
    assert main(["corpus", "--out", str(tmp_path / "c.jsonl"), "--from-runs",
                 str(RUNS), "--floor", "1.5"]) == 2
    assert "--floor" in capsys.readouterr().err


def test_json_prints_the_summary_as_a_document(tmp_path, capsys):
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report([attempt("totals_records",
                                                 "assert")])),
                      encoding="utf-8")
    code = main(["corpus", "--out", str(tmp_path / "c.jsonl"),
                 "--from-extraction", str(source), "--probes", str(PROBES),
                 "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["header"]["examples"] == 1
    assert payload["digest"].startswith("sha256:")


# ── the two labellers ────────────────────────────────────────────────────────

@pytest.mark.parametrize("statuses,expected", [
    ([], "silent"),
    (["ASSERT"], "asserted"),
    (["ASSERT", "ASSERT"], "asserted"),
    (["INSUFFICIENT_EVIDENCE"], "abstained"),
    (["HYPOTHESIZE"], "hedged"),
    (["AMBIGUOUS"], "hedged"),
    (["CONTRADICTED", "CONTRADICTED"], "contradicted"),
    (["ASSERT", "CONTRADICTED"], "contradicted"),
    (["ASSERT", "HYPOTHESIZE"], "mixed"),
])
def test_stance_reads_the_statuses(statuses, expected):
    assert C.stance_of([{"status": s} for s in statuses]) == expected


@pytest.mark.parametrize("reply,expected", [
    ({"content": '{"tool": "x", "arguments": {}}'}, "tool_call"),
    ({"content": '{"answer": "done"}'}, "answer"),
    ({"content": "let me think about this"}, "planning"),
    ({"content": "", "tool_calls": [{"name": "x"}]}, "tool_call"),
    ({"content": "[1, 2, 3]"}, "planning"),
])
def test_position_reads_the_reply(reply, expected):
    assert C.position_of(reply) == expected
