# tests/test_reading.py — the field-misreading tier, and where its edge is

"""What a reader-check can reach, and what the mechanical tier already had.

Two failure classes put a wrong fact in front of a partner on 10 August 2026
and **both passed every check that ran**. They are opposites, they need
opposite instruments, and the useful result of building this tier was finding
out which needs which:

* **right value, wrong field.** ``total_s: 80.847`` reported as "the overall
  influence score". The value is in the payload, at a real path, unaltered —
  so a membership check says supported and is correct to. Three models made
  this error on the same field: Tai (80.847, "overall influence score"),
  Goose (80.889, "the influence score metric, named Total_S"), and Qwen3-30B
  (80.847, "a bridge count"). Only a reader catches it.
  :class:`TestTheReaderCatchesWhatMembershipCannot`.

* **wrong value, right field.** Qwen3-30B put ``@wangwuba`` in front of a
  notional partner for an actor whose real display name is ``王裕庆_台湾省``,
  and gpt-oss reported the same actor as ``王锦厦_台湾省`` — one invented, one
  a mis-decode of the ASCII-escaped name it was shown. **Neither needs a
  model.** Both are caught by walking the path and comparing, which the claim
  table already does for free. What let them through was that the claim table
  is asked for figures only, and the prose identifier grammar
  (``\\b[a-z][a-z0-9_]*(?:\\.[a-z0-9_]+)+\\b``) matches neither an ``@handle``
  nor a CJK name — it extracted **nothing**, reported
  ``nothing_considered``, and the answer came back ``grounded``.
  :class:`TestIdentityIsAMechanicalCheckAfterAll`.

So the reader tier is narrower than it first looked, and that is the point of
having measured it: the expensive instrument is reserved for the one class the
free one provably cannot reach.

The reader here is recorded, not live. Every reply in :data:`RECORDED` is a
verbatim answer measured on 11 August 2026 against the prompts this module
generates, one isolated call per case. That keeps the suite offline and makes
the anchoring result — the reason the check is two steps — a regression test
rather than a paragraph.
"""

import json
from pathlib import Path

import pytest

from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.reading import (
    FieldContext,
    FieldReading,
    ReadingCheck,
    field_context,
    field_question,
    match_question,
    parse_field_reading,
    parse_reader_reply,
)

FIXTURE = Path(__file__).parent / "fixtures" / "field_misreadings.json"


@pytest.fixture(scope="module")
def cases():
    return json.loads(FIXTURE.read_text())["cases"]


def context_of(case) -> FieldContext:
    raw = case["context"]
    return FieldContext(
        path=raw["path"], value=raw["value"],
        siblings=tuple(tuple(s) for s in raw["siblings"]),
        siblings_truncated=raw["siblings_truncated"],
    )


# ── the recorded reader ─────────────────────────────────────────────────────

#: Step one, verbatim. Nine distinct fields, every one `confident: true`,
#: every one correct — including the two the anchored prompt got wrong.
RECORDED_STEP_ONE = {
    "data.runs[0].total_s":
        '{"quantity": "total elapsed time for the analysis run", '
        '"unit": "seconds", "confident": true}',
    "data.view.network.edge_count":
        '{"quantity": "number of edges in network", "unit": "count", '
        '"confident": true}',
    "data.coverage.records":
        '{"quantity": "total records in dataset", "unit": "count", '
        '"confident": true}',
    "data.view.gate.confidence":
        '{"quantity": "confidence in decision", "unit": "probability", '
        '"confident": true}',
    "data.view.blocks[0].size":
        '{"quantity": "number of members", "unit": "count", '
        '"confident": true}',
    "data.view.network.node_count":
        '{"quantity": "Number of nodes in a network", "unit": "count", '
        '"confident": true}',
    "data.view.network.nodes[0].scores.out_weight":
        '{"quantity": "Sum of outgoing edge weights", "unit": "weight", '
        '"confident": true}',
    "data.coverage.share":
        '{"quantity": "proportion of labeled records", "unit": "proportion", '
        '"confident": true}',
}


class RecordedReader:
    """Replays measured answers, and refuses to invent one it does not have.

    A stub that returned a plausible default for an unseen prompt would make
    this file assert the stub instead of the measurement.
    """

    def __init__(self, step_two=None):
        self.step_two = step_two or {}
        self.asked = []

    def __call__(self, prompt: str) -> str:
        self.asked.append(prompt)
        if prompt.startswith("A field was read out of a tool result. You are"):
            for path, reply in RECORDED_STEP_ONE.items():
                if f"path:  {path}\n" in prompt:
                    return reply
            raise AssertionError(f"no recorded step-one answer:\n{prompt[:200]}")
        for key, reply in self.step_two.items():
            if key in prompt:
                return reply
        raise AssertionError(f"no recorded step-two answer:\n{prompt[:300]}")


# ── the context extractor ───────────────────────────────────────────────────

class TestFieldContext:
    PAYLOAD = {"data": {"runs": [{"run_id": "a1", "total_s": 80.847,
                                  "nodes": 127, "tags": [1, 2, 3],
                                  "meta": {"a": 1}}]}}

    def test_it_finds_the_value_and_the_neighbours(self):
        ctx = field_context([self.PAYLOAD], "data.runs[0].total_s")
        assert ctx.resolved and ctx.value == 80.847
        assert dict(ctx.siblings)["run_id"] == '"a1"'
        assert "total_s" not in dict(ctx.siblings), (
            "the claimed field is quoted above the neighbours; repeating it "
            "spends the sibling budget on what the reader already has")

    def test_containers_become_their_shape(self):
        """127 node objects must not be pasted into a 200-token prompt."""
        ctx = field_context([self.PAYLOAD], "data.runs[0].total_s")
        siblings = dict(ctx.siblings)
        assert siblings["tags"] == "[3 items]"
        assert siblings["meta"] == "{1 fields}"

    def test_a_path_that_resolves_nowhere_carries_the_walkers_problem(self):
        ctx = field_context([self.PAYLOAD], "data.runs[0].nope")
        assert not ctx.resolved
        assert "nope" in ctx.problem and "total_s" in ctx.problem, (
            "a miss that does not name what WAS there sends the model back "
            "with the same wrong guess")

    def test_it_searches_every_payload(self):
        """A mission reads several tools; a claim carries the path, not the
        handle."""
        ctx = field_context([{"other": 1}, self.PAYLOAD],
                            "data.runs[0].total_s")
        assert ctx.resolved and ctx.value == 80.847

    def test_the_prompt_stays_small(self, cases):
        """The whole affordability argument for a check per claim."""
        for case in cases:
            question = field_question(context_of(case))
            assert len(question) < 2000, (
                f"{case['id']}: step one is {len(question)} chars; the point "
                f"of sending the neighbourhood instead of the payload is that "
                f"it stays small")


# ── the measured result the two-step design comes from ──────────────────────

class TestTheReaderIsAnchoredByTheClaim:
    """Why step one withholds the sentence. This is the whole design.

    Measured 11 August 2026, one isolated call per case. Asked "is this
    sentence right about this field?", a reader shown
    `"The overall influence score ... reached 80.847"` **agrees**. Asked what
    `total_s` holds with no sentence in the prompt, the same reader answers
    "total elapsed time, seconds" and is sure of it.

    It knew. Being shown the claim is what stopped it knowing.
    """

    def test_asked_cold_the_reader_knows_total_s_is_a_duration(self):
        reading = parse_field_reading(
            RECORDED_STEP_ONE["data.runs[0].total_s"],
            path="data.runs[0].total_s")
        assert reading.usable
        assert "elapsed" in reading.quantity.lower()
        assert reading.unit == "seconds"

    def test_every_recorded_field_came_back_confident_and_usable(self):
        for path, reply in RECORDED_STEP_ONE.items():
            reading = parse_field_reading(reply, path=path)
            assert reading.usable, f"{path}: {reading}"

    def test_step_one_never_shows_the_sentence(self, cases):
        """The mutation that matters: put the claim back and the tier is the
        one-step version that lost both `total_s` cases."""
        sentences = {c["sentence"] for c in cases}
        for case in cases:
            question = field_question(context_of(case))
            assert "You are not being shown any claim" in question
            for sentence in sentences:
                assert sentence not in question, (
                    f"{case['id']}: step one leaked a claim into the prompt")

    def test_step_two_leads_with_the_readers_own_answer(self, cases):
        """The sentence is the thing on trial, not the premise."""
        case = next(c for c in cases
                    if c["id"] == "total_s_as_influence_score_tai")
        ctx = context_of(case)
        reading = parse_field_reading(
            RECORDED_STEP_ONE[ctx.path], path=ctx.path)
        question = match_question(ctx, reading, case["sentence"])
        assert question.index("this field is:") < question.index(
            "Someone then wrote this sentence"), (
            "step two must state what the field is BEFORE quoting the claim")
        assert "total elapsed time" in question


class TestTheReaderCatchesWhatMembershipCannot:
    """The one class no arithmetic reaches: right value, wrong field."""

    #: Step two, verbatim, for the recorded Tai draft.
    MISREAD_REPLY = (
        '{"read_correctly": false, "why": "total_s is the run\'s total '
        'elapsed time in seconds, not a centrality-derived influence score.", '
        '"correction": "This field is the run duration in seconds. The run\'s '
        'influence figure is blocks[*].total_causal_influence, which is 0.0."}')

    def test_the_verdict_names_the_field_and_the_right_one(self):
        verdict = parse_reader_reply(
            self.MISREAD_REPLY,
            path="data.runs[0].total_s",
            sentence="The overall influence score ... reached 80.847",
            reading=parse_field_reading(
                RECORDED_STEP_ONE["data.runs[0].total_s"],
                path="data.runs[0].total_s"))
        assert verdict.misread
        line = verdict.as_repair_line()
        assert "total elapsed time" in line, (
            "a repair turn that does not say what the field IS leaves the "
            "model to guess again")
        assert "total_causal_influence" in line, (
            "naming the right field is the actionable half")

    def test_an_absent_opinion_is_not_a_misreading(self):
        """UNKNOWN, not 0.5. A parse failure must not become a finding."""
        verdict = parse_reader_reply("not json at all", path="p", sentence="s")
        assert verdict.read_correctly is None
        assert not verdict.misread
        assert "not JSON" in verdict.problem

    def test_an_unconfident_reader_does_not_get_to_judge(self):
        """A reader that cannot say what the field is has no standing."""
        reading = parse_field_reading(
            '{"quantity": "unclear", "unit": "", "confident": false}',
            path="data.runs[0].total_s")
        assert not reading.usable

    def test_step_one_is_asked_once_per_field_not_once_per_claim(self):
        """The cost argument. Five figures from one view, one step-one call."""
        payload = {"data": {"runs": [{"run_id": "a1", "total_s": 80.847}]}}
        reader = RecordedReader({
            "sentence": '{"read_correctly": true, "why": "ok", '
                        '"correction": ""}'})
        check = ReadingCheck(reader)
        check.review([("data.runs[0].total_s", "a sentence"),
                      ("data.runs[0].total_s", "another sentence"),
                      ("data.runs[0].total_s", "a third sentence")], [payload])
        step_ones = [p for p in reader.asked
                     if p.startswith("A field was read out of a tool result. "
                                     "You are")]
        assert len(step_ones) == 1, (
            f"step one ran {len(step_ones)} times for one field; it is keyed "
            f"on the path and cached")

    def test_a_claim_the_mechanical_tier_rejected_is_not_sent(self):
        """The tier only pays for claims that already look fine."""
        reader = RecordedReader()
        check = ReadingCheck(reader)
        report = check.review([("data.nope.gone", "a sentence")],
                              [{"data": {"runs": []}}])
        assert report.skipped == ("data.nope.gone",)
        assert reader.asked == [], "a resolved-nowhere path cost a model call"


# ── the other half, and it needs no model ───────────────────────────────────

class TestIdentityIsAMechanicalCheckAfterAll:
    """Both wrong-identity failures are caught by walking the path.

    Measured against the real node from run `a971d4c4149c`. The finding is
    not that a reader is needed here — it is that the free check already
    reaches this, and the reason it did not on 10 August is that the claim
    table is asked for figures only while identities were left to a prose
    regex that matches neither an `@handle` nor a CJK name.
    """

    EVIDENCE = ['{"network": {"nodes": [{"actor_id": "6436464948", '
                '"display_name": "王裕庆_台湾省", '
                '"scores": {"out_weight": 338.0}}]}}']
    PATH = "network.nodes[0].display_name"
    TRUE_NAME = "王裕庆_台湾省"
    QWEN_INVENTED = "@wangwuba"
    GPTOSS_CORRUPTED = "王锦厦_台湾省"

    PROSE_GRAMMAR = r"\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b"

    def table(self, name):
        return ("The strongest propagator was " + name + ".\n\n```claims\n"
                + json.dumps([{"value": name, "path": self.PATH}],
                             ensure_ascii=False) + "\n```")

    def validator(self, claim_table):
        return GroundingValidator.from_config(GroundingConfig(
            identifier_pattern=self.PROSE_GRAMMAR,
            number_pattern=r"\b\d+\.\d{2,}\b",
            claim_table=claim_table,
            must_cite=(("claims", 1),) if claim_table else ()))

    def verdict_for(self, name):
        report = self.validator(True).validate(self.table(name), self.EVIDENCE)
        return [r for r in report.results if r.check == "claims"][0].verdict

    def test_the_true_name_is_supported(self):
        assert self.verdict_for(self.TRUE_NAME) == "supported"

    def test_the_invented_handle_is_caught(self):
        assert self.verdict_for(self.QWEN_INVENTED) == "unsupported"

    def test_the_corrupted_cjk_name_is_caught(self):
        """The harder one: it is not invented, it is the real name mis-decoded
        from the ASCII escapes the wire showed the model."""
        assert self.verdict_for(self.GPTOSS_CORRUPTED) == "unsupported"

    @pytest.mark.parametrize("name", [QWEN_INVENTED, GPTOSS_CORRUPTED])
    def test_the_prose_grammar_sees_neither_of_them(self, name):
        """The 10 August configuration, and why both answers passed.

        `considered` is empty, so there is nothing to be unsupported, so the
        report is `grounded`. This is the `0/0` hole with a wrong identity
        inside it.
        """
        report = self.validator(False).validate(
            f"The strongest propagator was {name}.", self.EVIDENCE)
        identifiers = [r for r in report.results
                       if r.check == "identifiers"][0]
        assert identifiers.considered == ()
        assert identifiers.verdict == "nothing_considered"
        assert report.grounded is True
        assert report.verified is False, (
            "`verified` is the bit that separates this from a checked answer")
