# tests/test_cognition_rule_packs.py — the rules a run reasons under, and
# where they come from

"""A skill manifest carries a ``cognition:`` block, and the shadow loads it.

``ROADMAP.md`` §2.9.4, the bullet this file closes: *rules arrive through
skills — a skill manifest may carry a rule pack, which makes rule authorship
a named cost of the architecture rather than an unexamined assumption.*

Until now the shadow was a store that could only ever hold what a receipt
said.  Nothing derived, because nothing had been told how; nothing was owed,
because no goal had been named; ``frontier()`` was empty by construction and
an empty frontier is indistinguishable from a finished one.  A pack is the
other half, and this file is the instrument for four claims about it:

* **it is loaded through the kernel's ordinary doors** — ``declare_field``,
  ``add_rule``, ``promote_rule``, ``add_goal`` — so every clause is an event
  in ``reasoning.jsonl`` and the promotion of a rule is something a reader
  can find.  A loader that passed ``SKILL`` straight to ``add_rule`` would
  produce the same store and walk round the wall;
* **it lands before the first receipt**, in one order (cardinality, rules,
  goals), so two runs of one manifest write the same sequence and a goal is
  never added after the steps it was for;
* **a resume replays it and never loads it twice**.  The log holds the pack,
  the replay applies it, and a second load would give the store two rule ids
  deriving one conclusion and a frontier counting each obligation twice;
* **it costs a mission nothing.**  A pack that will not load turns cognition
  off for the run with a note of its own; a manifest that carries one and is
  run *without* ``--cognition`` is byte for byte the run it always was.

The last claim is the floor rule (§2.9.3: cognition-on never blocks an
answer) and it is checked against the committed corpus, the same way the
shadow lane checks the flag itself.
"""

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition import CognitiveState, PropositionStatus, RuleAuthority
from core.cognition.compile import TITLE
from core.durable import RunStore
from core.runtime.cognition import (NOTE_KEY, REASONING_LOG, UNLOADED_NOTE,
                                    RulePack, open_shadow, read_reasoning,
                                    replay_reasoning)
from core.runtime.skills import SkillManifestError, load_skill
from tests.test_cli_mission_skill import STUB as MISSION_STUB
from tests.test_cli_mission_skill import elf  # noqa: F401
from tests.test_cognition_shadow import _timeless, corpus  # noqa: F401
from tests.test_record_replay import (JSON_RUN, SKILL, comparable, lines,
                                      records, replay_argv, run_cli,
                                      scripted_elf, write_skill)

#: The tiny pack, over the one receipt the corpus mission and the mission
#: stub both produce: ``governed_view(section="totals")`` answers
#: ``{"run_id": …, "totals": {"records": 12481, "blocks": 7}}``, which the
#: v1 harvest reads as two figures on ONE entity — ``run_id`` is a string
#: and is dropped.
#:
#: **Written to the v1 entity model on purpose.**  An entity is
#: ``"{tool}#{seq}"``, one per receipt, so the only join a v1 rule can make
#: for free is between two fields of the same receipt.  ``sizeable`` is that
#: join; ``cleared`` is the one that cannot be satisfied, because nothing on
#: this plane ever says ``reviewed`` — which is exactly what makes the
#: frontier non-empty and is the whole point of a goal.
PACK = {
    "cardinality": {"blocks": "one"},
    "rules": [
        {"name": "sizeable",
         "head": ["?v", "sizeable", "?n"],
         "body": [["?v", "records", "?n"], ["?v", "blocks", 7]]},
        {"name": "cleared",
         "head": ["?v", "cleared", True],
         "body": [["?v", "sizeable", "?n"], ["?v", "reviewed", True]]},
    ],
    "goals": [
        {"name": "view_cleared", "pattern": ["?v", "cleared", True]},
    ],
}

#: What that receipt looks like when the bus hands it over.
RECEIPT = json.dumps({"run_id": "asset.5f21",
                      "totals": {"records": 12481, "blocks": 7}})

#: The manifest, with the pack in it and the block indented into the
#: frontmatter rather than assembled by hand: a pack author writes YAML.
SKILL_WITH_PACK = """\
---
name: packed
skill:
  skill_id: packed
  when_to_use: Reading a governed view and reasoning about it.
  allowed_tools:
    - governed_view
  policy:
    - Never invent an asset id.
  output_format: One sentence.
  grounding:
    identifier_pattern: '\\basset\\.[0-9a-z]{4,}\\b'
  cognition:
    cardinality:
      blocks: one
    rules:
      - name: sizeable
        head: ["?v", "sizeable", "?n"]
        body:
          - ["?v", "records", "?n"]
          - ["?v", "blocks", 7]
      - name: cleared
        head: ["?v", "cleared", true]
        body:
          - ["?v", "sizeable", "?n"]
          - ["?v", "reviewed", true]
    goals:
      - name: view_cleared
        pattern: ["?v", "cleared", true]
---

# Packed

Read the view, then answer in one sentence.
"""


#: :data:`tests.test_record_replay.SKILL` **and nothing else but a pack**.
#:
#: Built by insertion rather than rewritten, which is the whole argument of
#: the ablation below: the corpus manifest's prompt, closed set and
#: grounding grammar have to be byte for byte the ones the recording was
#: made under, or the two arms would differ for a reason that is not the
#: pack.  The same trick ``STRICTER`` plays beside it.
PACKED_CORPUS_SKILL = SKILL.replace("---\n\n# Corpus", textwrap.indent(
    textwrap.dedent("""\
        cognition:
          cardinality:
            blocks: one
          rules:
            - name: sizeable
              head: ["?v", "sizeable", "?n"]
              body:
                - ["?v", "records", "?n"]
                - ["?v", "blocks", 7]
        """), "  ") + "---\n\n# Corpus")


def write_packed_skill(directory, text=SKILL_WITH_PACK):
    path = Path(directory) / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def ops(path):
    """The kernel ops in a reasoning log, in order."""
    return [event["op"] for event in read_reasoning(path)[1]]


def notes(path):
    return [note.get(NOTE_KEY) for note in read_reasoning(path)[2]]


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "store")


# ── the load ─────────────────────────────────────────────────────────────────


class TestThePackGoesInThroughTheKernelsOwnDoors:
    """Four kinds of event, in one order, before anything else is believed.

    Every one of them is a *public* kernel call, which is what makes the
    log a complete account of the store: a replay rebuilds the pack by
    applying the same ops, and nothing anywhere has to read the manifest
    twice.
    """

    def test_the_whole_pack_is_in_the_log(self, store):
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        assert ops(shadow.path) == ["declare_field", "add_rule",
                                    "promote_rule", "add_rule",
                                    "promote_rule", "add_goal"]

    def test_the_order_is_cardinality_then_rules_then_goals(self, store):
        """Declared, not incidental. A cardinality that arrived after the
        observations it governs leaves a store whose ledger cannot be
        explained by its own rules, and a goal that arrives last is a
        frontier that was empty while the mission was deciding."""
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        order = ops(shadow.path)
        assert order.index("declare_field") < order.index("add_rule")
        assert order.index("add_rule") < order.index("add_goal")

    def test_it_lands_before_the_first_receipt(self, store):
        """THE ORDER THAT MATTERS. A pack loaded after the harvest is a
        run that spent its early steps with no rules and no goals, and
        nothing in the log would say which steps those were."""
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        shadow.receipt("mcp.governed_view", "r1", RECEIPT)
        shadow.close_step()
        order = ops(shadow.path)
        assert order.index("add_goal") < order.index("assert_observation")

    def test_a_rule_is_promoted_and_not_merely_added(self, store):
        """The wall's intended door. `add_rule` defaults to PROPOSED and a
        PROPOSED rule derives nothing; a loader that passed SKILL straight
        to `add_rule` would build the same store with one event where
        there should be two, and 'who promoted this clause' would have no
        answer in the file."""
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        assert [rule.authority for rule in shadow.state.rules()] == \
            [RuleAuthority.SKILL, RuleAuthority.SKILL]
        assert ops(shadow.path).count("promote_rule") == 2

    def test_a_goal_keeps_the_name_the_pack_gave_it(self, store):
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        assert [goal.note for goal in shadow.state.goals()] == ["view_cleared"]

    def test_the_counts_are_reported(self, store):
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        assert shadow.loaded == (1, 2, 1)
        assert shadow.pack.rules[0].name == "sizeable"

    def test_no_block_is_the_shadow_the_flag_alone_has_always_been(self,
                                                                   store):
        run = store.create()
        shadow = open_shadow(store, run.run_id)
        assert shadow.pack is None
        assert ops(shadow.path) == []

    def test_a_declared_empty_pack_writes_nothing_and_is_still_a_pack(
            self, store):
        """`cognition: {}` is a skill saying it has a block and the block
        says nothing. Loading it writes nothing, which is the correct
        amount, and the object still says a pack was asked for."""
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block={})
        assert shadow.pack is not None and not shadow.pack
        assert ops(shadow.path) == []


class TestWithAPackTheReceiptsDerive:
    """The point of the whole thing, with its control arm beside it.

    Without a pack a receipt is two figures and a full stop. With one it
    is two figures, a conclusion drawn from them, and a named thing that
    is still missing — which is the inversion the arc is for: the runtime
    stops asking the model what to do next and starts saying what is owed.
    """

    @pytest.fixture
    def loaded(self, store):
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        shadow.receipt("mcp.governed_view", "r1", RECEIPT)
        shadow.close_step()
        return shadow

    def test_the_conclusion_is_in_the_store(self, loaded):
        derived = [(p.entity, p.field, p.value)
                   for p in loaded.state.propositions(
                       status=PropositionStatus.DERIVED)]
        assert derived == [("mcp.governed_view#r1", "sizeable", 12481)]

    def test_it_traces_back_to_the_receipt(self, loaded):
        """A derived fact is worth its evidence or it is worth nothing,
        and the kernel's proof walk is what says so."""
        pid = loaded.state.claim(("mcp.governed_view#r1", "sizeable", 12481))
        leaves = loaded.state.support(pid).evidence_leaves
        assert [ref.locator.endswith("/r1/mcp.governed_view")
                for ref in leaves] == [True]

    def test_the_frontier_names_what_is_still_missing(self, loaded):
        frontier = loaded.state.frontier()
        assert [item.pattern for item in frontier] == \
            [("mcp.governed_view#r1", "reviewed", True)]

    def test_the_next_obligation_is_that_one(self, loaded):
        assert loaded.state.next_obligation().pattern == \
            ("mcp.governed_view#r1", "reviewed", True)

    def test_without_the_pack_nothing_derives_and_nothing_is_owed(self,
                                                                  store):
        """The control arm, and the reason the pack is the feature: the
        same receipt through the same harvest, with no clauses, is a store
        that concludes nothing and reports an empty frontier."""
        run = store.create()
        bare = open_shadow(store, run.run_id)
        bare.receipt("mcp.governed_view", "r1", RECEIPT)
        bare.close_step()
        assert not bare.state.propositions(status=PropositionStatus.DERIVED)
        assert not bare.state.frontier()

    def test_a_declared_cardinality_makes_a_conflict_reachable(self, store):
        """`blocks: one` is the pack turning collision detection on for one
        field. Two receipts disagreeing about it is then a contradiction
        the store records, where an undeclared field would hold both
        quietly — which is the compiler lane's finding, closed."""
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block={
            "cardinality": {"blocks": "one"}})
        shadow.receipt("v", "r1", json.dumps({"blocks": 7}))
        shadow.receipt("v", "r1", json.dumps({"blocks": 9}))
        shadow.close_step()
        assert [c.kind for c in shadow.state.contradictions()] == ["value"]


# ── resume ───────────────────────────────────────────────────────────────────


class TestAResumeReplaysThePackAndNeverLoadsItTwice:
    """The log holds the pack, so the manifest is not read again.

    A second load is not a harmless repetition: it mints a second rule id
    for the same clause, so one conclusion gets two derivations and the
    frontier counts every obligation twice. The kernel would be right about
    all of it, which is what makes it hard to see.
    """

    def test_a_second_open_adds_no_second_copy(self, store):
        run = store.create()
        first = open_shadow(store, run.run_id, cognition_block=PACK)
        first.receipt("mcp.governed_view", "r1", RECEIPT)
        first.close_step()
        again = open_shadow(store, run.run_id, cognition_block=PACK)
        assert ops(again.path).count("add_rule") == 2
        assert len(again.state.rules()) == 2
        assert len(again.state.goals()) == 1

    def test_the_resumed_store_is_the_store_that_was_killed(self, store):
        run = store.create()
        first = open_shadow(store, run.run_id, cognition_block=PACK)
        first.receipt("mcp.governed_view", "r1", RECEIPT)
        first.close_step()
        again = open_shadow(store, run.run_id, cognition_block=PACK)
        assert again.state.digest() == first.state.digest()

    def test_the_resumed_store_still_derives_and_still_owes(self, store):
        """Replayed clauses are clauses: the rules came back promoted, so
        a receipt taken after the resume derives exactly as one taken
        before it would have."""
        run = store.create()
        open_shadow(store, run.run_id, cognition_block=PACK)
        again = open_shadow(store, run.run_id, cognition_block=PACK)
        again.receipt("mcp.governed_view", "r1", RECEIPT)
        again.close_step()
        assert [(p.entity, p.field, p.value) for p in
                again.state.propositions(status=PropositionStatus.DERIVED)] \
            == [("mcp.governed_view#r1", "sizeable", 12481)]
        assert len(again.state.frontier()) == 1

    def test_the_numbering_stays_its_own_positions(self, store):
        """The kernel refuses a log whose `n` is not its position, so a
        double load would not merely duplicate — it would leave a file the
        next reader cannot trust."""
        run = store.create()
        first = open_shadow(store, run.run_id, cognition_block=PACK)
        first.receipt("mcp.governed_view", "r1", RECEIPT)
        first.close_step()
        open_shadow(store, run.run_id, cognition_block=PACK)
        _header, events, _notes = read_reasoning(first.path)
        assert [event["n"] for event in events] == list(
            range(1, len(events) + 1))


# ── failure isolation ────────────────────────────────────────────────────────


class TestAPackThatWillNotLoadCostsTheRunItsCognitionAndNothingElse:
    """The floor rule, at the one new door.

    Cognition off is the price; a mission is not. The note has a sentence
    of its own because a reader that could not tell a dead pack from a
    dead harvest would go looking in the wrong file.
    """

    @pytest.fixture
    def refused(self, store):
        run = store.create()
        # A block a library caller could hand over: the manifest loader
        # would have refused it at the door, and a `Store` built in
        # process has no door. This is what that costs.
        return open_shadow(store, run.run_id,
                           cognition_block={"rules": "not a list"})

    def test_the_door_does_not_raise(self, refused):
        assert refused is not None

    def test_cognition_is_off_for_the_run(self, refused):
        assert refused.on is False
        assert refused.pack is None
        assert refused.failures == 1

    def test_the_note_says_which_half_failed(self, refused):
        assert notes(refused.path) == [UNLOADED_NOTE]

    def test_the_harvest_after_it_writes_nothing(self, refused):
        before = Path(refused.path).read_text(encoding="utf-8")
        refused.receipt("mcp.governed_view", "r1", RECEIPT)
        refused.close_step()
        assert Path(refused.path).read_text(encoding="utf-8") == before

    def test_a_kernel_refusal_at_load_time_is_the_same_note(self, store,
                                                            monkeypatch):
        """The narrow case the manifest door cannot see: the pack is
        well-formed and this store refuses it anyway."""
        def boom(self, state):
            raise RuntimeError("no")

        monkeypatch.setattr(RulePack, "load_into", boom)
        run = store.create()
        shadow = open_shadow(store, run.run_id, cognition_block=PACK)
        assert shadow.on is False
        assert notes(shadow.path) == [UNLOADED_NOTE]

    def test_the_next_run_is_not_poisoned(self, store, refused):
        """Failure is per-run and carries nothing forward: the block is
        read fresh every time, so a store that refused one run's pack has
        no memory of it when the next run opens."""
        other = store.create()
        assert open_shadow(store, other.run_id,
                           cognition_block=PACK).on is True


# ── the manifest door, and the flag that is not needed to reach it ───────────


class TestTheBlockIsParsedWhetherOrNotAnybodyAsksForCognition:
    """The ``--no-grounding`` precedent: parsed always, acted on when asked.

    A manifest carrying a pack the kernel would refuse is a manifest that
    does not load — no flag, no run store, no mission. That is not
    strictness for its own sake: the alternative is a deployment that
    ships a broken pack for a month because nothing it runs turns
    cognition on, and then finds out on the day somebody does.
    """

    def test_a_usable_pack_loads_with_no_flag_in_sight(self, tmp_path):
        manifest = load_skill(write_packed_skill(tmp_path))
        assert manifest.cognition["cardinality"] == {"blocks": "one"}

    def test_an_unusable_pack_refuses_with_no_flag_in_sight(self, tmp_path):
        broken = SKILL_WITH_PACK.replace('["?v", "blocks", 7]',
                                         '["?v", "blocks"]')
        assert broken != SKILL_WITH_PACK
        with pytest.raises(SkillManifestError) as exc:
            load_skill(write_packed_skill(tmp_path, broken))
        assert "three terms, got 2" in str(exc.value)

    def test_the_pack_is_not_prose_in_the_prompt(self, tmp_path):
        """It reaches the model as conclusions, if at all. Horn clauses in
        a system message would be the runtime asking a 20B to do the
        inference the runtime just did."""
        prompt = load_skill(write_packed_skill(tmp_path)).prompt
        assert "sizeable" not in prompt
        assert "cognition" not in prompt

    def test_the_manifests_block_is_what_the_kernel_takes(self, tmp_path):
        """One owner: what `skills.py` carries is what `RulePack` reads,
        and a test that built its own dict would not say so."""
        manifest = load_skill(write_packed_skill(tmp_path))
        state = CognitiveState()
        assert RulePack.from_mapping(manifest.cognition).load_into(state) \
            == (1, 2, 1)


# ── the ablation: a pack changes nothing until the flag is on ────────────────


def _replay_under(corpus_root, skill_path, run_id, *extra):
    """Replay *run_id* under a named manifest and return the new run's id."""
    before = {run.run_id for run in RunStore(corpus_root).list()}
    MockClass, _ = scripted_elf(refuse=True)
    run_cli(MockClass, *replay_argv(run_id, skill_path, *extra))
    after = {run.run_id for run in RunStore(corpus_root).list()}
    fresh = after - before
    assert len(fresh) == 1, sorted(fresh)
    return fresh.pop()


class TestAPackWithoutTheFlagIsTheRunItAlwaysWas:
    """The corpus guard, one flag further in than the shadow lane's.

    ``tests/test_cognition_shadow.py`` proves that *the flag* costs
    nothing; this proves that *a pack in the manifest* costs nothing
    either. The two are different claims: a block is read at the manifest
    door on every run, whether or not anybody asked for cognition, and a
    loader that rendered it into the prompt — or refused a manifest over
    it — would move a mission that never turned the feature on.
    """

    @pytest.fixture
    def arms(self, corpus, tmp_path):  # noqa: F811
        (tmp_path / "plain").mkdir(parents=True, exist_ok=True)
        plain = _replay_under(corpus, write_skill(tmp_path / "plain"),
                              JSON_RUN)
        packed = _replay_under(
            corpus, write_packed_skill(tmp_path / "packed",
                                       PACKED_CORPUS_SKILL), JSON_RUN)
        return corpus, plain, packed

    def test_the_two_manifests_differ_only_in_the_pack(self, tmp_path):
        """The arms are only worth what they hold constant, and the
        constant is the prompt: `cognition:` is structural, so a loader
        that rendered it would show up here before it showed up as drift."""
        (tmp_path / "plain").mkdir(parents=True, exist_ok=True)
        plain = load_skill(write_skill(tmp_path / "plain"))
        packed = load_skill(write_packed_skill(tmp_path / "packed",
                                               PACKED_CORPUS_SKILL))
        assert packed.prompt == plain.prompt
        assert packed.cognition is not None and plain.cognition is None

    def test_the_event_stream_is_the_same_stream(self, arms):
        root, plain, packed = arms
        assert comparable(records(root, packed)) == \
            comparable(records(root, plain))

    def test_the_model_was_asked_the_same_questions(self, arms):
        root, plain, packed = arms
        store = RunStore(root)
        assert _timeless(lines(store.directory(packed) / "model.jsonl")) == \
            _timeless(lines(store.directory(plain) / "model.jsonl"))

    def test_the_same_tools_were_dispatched(self, arms):
        root, plain, packed = arms
        store = RunStore(root)
        assert _timeless(lines(store.directory(packed) / "tools.jsonl")) == \
            _timeless(lines(store.directory(plain) / "tools.jsonl"))

    def test_neither_arm_wrote_a_reasoning_log(self, arms):
        root, plain, packed = arms
        store = RunStore(root)
        for run_id in (plain, packed):
            assert not (store.directory(run_id) / REASONING_LOG).exists()


# ── end to end: one mission, both flags, the whole mechanism ─────────────────


class TestOneMissionUnderOnePack:
    """The wiring, against the stub server rather than a hand-built store.

    Everything above is a claim about a component. This is the claim about
    the product: an operator writes a pack into a manifest, types
    ``--cognition --compiled-context``, and the mission derives a fact its
    receipts never stated, knows what is still owed, and shows the model
    the first of those — without the answer being held, checked or refused
    against any of it.
    """

    @pytest.fixture
    def mission(self, elf, tmp_path):  # noqa: F811
        MockClass, agent = elf
        agent.replies = [
            json.dumps({"tool": "mcp.governed_view",
                        "arguments": {"run_id": "asset.5f21",
                                      "section": "totals"}}),
            json.dumps({"answer": "The view holds 12481 records, "
                                  "asset.5f21."}),
        ]
        argv = ["test", "what exists?", "--mission",
                "--mcp-stdio", f"{sys.executable} {MISSION_STUB}",
                "--skill", write_packed_skill(tmp_path / "skill"),
                "--cognition", "--compiled-context"]
        with patch("sys.argv", argv):
            from core.cli import _main
            _main(MockClass)
        store = RunStore(tmp_path / "runs")
        listed = store.list()
        assert len(listed) == 1, [run.run_id for run in listed]
        return (agent, store.directory(listed[0].run_id) / REASONING_LOG,
                store.records(listed[0].run_id))

    def test_the_pack_is_in_the_reasoning_log(self, mission):
        _agent, path, _stream = mission
        assert ops(path)[:6] == ["declare_field", "add_rule", "promote_rule",
                                 "add_rule", "promote_rule", "add_goal"]

    def test_the_pack_lands_before_the_first_receipt(self, mission):
        _agent, path, _stream = mission
        order = ops(path)
        assert order.index("add_goal") < order.index("assert_observation")

    def test_the_receipt_derived_a_fact_the_plane_never_stated(self, mission):
        _agent, path, _stream = mission
        state = replay_reasoning(path)
        assert [(p.entity, p.field, p.value) for p in
                state.propositions(status=PropositionStatus.DERIVED)] == \
            [("mcp.governed_view#r1", "sizeable", 12481)]

    def test_the_frontier_is_not_empty_at_the_step_that_matters(self, mission):
        _agent, path, _stream = mission
        frontier = replay_reasoning(path).frontier()
        assert [item.pattern for item in frontier] == \
            [("mcp.governed_view#r1", "reviewed", True)]

    def test_the_derived_fact_is_in_the_view_the_model_reads(self, mission):
        agent, _path, _stream = mission
        blocks = [message for seed in agent.seeds for message in seed
                  if TITLE in str(message.get("content") or "")]
        assert blocks, "no compiled block reached the model"
        assert any("sizeable = 12481" in str(block["content"])
                   for block in blocks)

    def test_the_mission_still_answered(self, mission):
        """The floor: cognition on never blocks an answer, and a pack is
        cognition on with more of it. Read off the stream rather than off
        the script, because a loop that ended any other way would still
        have consumed every reply."""
        _agent, _path, stream = mission
        assert stream[-1]["outcome"] == "answered"

    def test_nothing_about_the_pack_is_on_the_wire(self, mission):
        """No record type, no field, no outcome — the same empty contract
        fit `--cognition` has. A pack is manifest content and a file in
        the run directory, and a platform pins nothing for it."""
        _agent, _path, stream = mission
        assert not [record for record in stream
                    if "rule" in json.dumps(record)
                    or "sizeable" in json.dumps(record)]
