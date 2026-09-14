# tests/test_cognition_compiled_context.py — the view, in the model's input

"""``--compiled-context`` on, and the block is where it says it is.

``tests/test_cognition_compile.py`` owns the compiler — pure, no mission.
This file owns the **wiring**, and it is the shadow file's argument one
flag further on: ``tests/test_cognition_shadow.py`` proves that cognition
changes nothing, and Phase 18 is the one thing that deliberately changes
something.  So every claim here is about *what* changed and *how far*:

* **the flag** — off unless somebody asks, and asking for the view asks
  for the state (it implies ``--cognition`` rather than refusing);
* **one live view** — a step's block replaces the step before it, and the
  conversation never becomes a log of views.  This is the assertion the
  whole design rests on: an accumulating block is a transcript with extra
  steps, which is the thing being replaced;
* **where it rides** — last, next to the current turn, with the cached
  prefix untouched.  rc4 measured that a 20B binds what it reads last;
* **what it carries** — a receipt read three steps ago, still quotable at
  the step that needs it.  That is the mechanism, and it is proved against
  the benchmark pack's multi-hop mission rather than against a fixture
  written to pass;
* **what it costs when it breaks** — nothing.  A compiler that raises
  stops compiling, writes one note, and the mission ends exactly as it
  would have.

The corpus half is deliberately the *negative*: with the flag off — which
includes a run with ``--cognition`` on — no block reaches any model input
at all, on the same committed fixtures the shadow lane replays.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition.compile import TITLE
from core.durable import RunStore
from core.runtime.cognition import (NOTE_KEY, REASONING_LOG, UNCOMPILED_NOTE,
                                    ShadowCognition, open_shadow,
                                    replay_reasoning)
from tests.test_cli_mission_skill import STUB as MISSION_STUB
from tests.test_cli_mission_skill import elf                       # noqa: F401
from tests.test_cli_mission_skill import run_cli as mission_run_cli
from tests.test_cognition_shadow import (_replay, _skill_for, corpus,  # noqa: F401,E501
                                         lines)
from tests.test_record_replay import CORPUS_RUNS

#: One call to the stub's governed view, and the answer that ends the run.
VIEW = json.dumps({"tool": "mcp.governed_view",
                   "arguments": {"run_id": "asset.5f21", "section": "totals"}})
ANSWER = json.dumps({"answer": "The view holds 12481 records, asset.5f21."})


def blocks_in(messages) -> list:
    """Every compiled-context block in one model input, in order."""
    return [message for message in messages
            if TITLE in str(message.get("content") or "")]


def script(agent, *replies):
    """Serve *replies* in order, then answer.  Records every model input."""
    queue = list(replies)

    def _chat(**kw):
        agent.seeds.append([dict(m) for m in kw["messages"]])
        return queue.pop(0) if queue else ANSWER

    agent.client.chat.side_effect = _chat


def run(MockClass, tmp_path, *extra):
    mission_run_cli(MockClass, "--skill", str(_skill_for(tmp_path)), *extra)


def model_calls(tmp_path):
    """The recorded model requests of the one run in this test's store."""
    store = RunStore(tmp_path / "runs")
    listed = store.list()
    assert len(listed) == 1, [run.run_id for run in listed]
    path = store.directory(listed[0].run_id) / "model.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        messages = (record.get("request") or {}).get("messages")
        if record.get("kind") == "mission" and messages:
            out.append(messages)
    return out


# ── the flag ─────────────────────────────────────────────────────────────────


def _parsed(*argv):
    from tests.test_contract import _mission_parser

    return _mission_parser().parse_args(["go", *argv])


class TestTheFlagIsOffUntilSomebodyAsks:
    """The one switch in this package that changes a prompt is the last one
    that may be on by default.

    The environment is the flag's argparse *default*, which is the
    ``--mcp-timeout`` idiom and what makes "the flag wins" true without a
    second resolution step anywhere.
    """

    def test_the_default_is_off(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_COMPILED_CONTEXT", raising=False)
        assert _parsed().compiled_context is False

    def test_the_flag_turns_it_on(self, monkeypatch):
        monkeypatch.delenv("JUDAIS_LOBI_COMPILED_CONTEXT", raising=False)
        assert _parsed("--compiled-context").compiled_context is True

    def test_the_variable_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_COMPILED_CONTEXT", "1")
        assert _parsed().compiled_context is True

    def test_a_blank_variable_is_not_a_request(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_COMPILED_CONTEXT", "   ")
        assert _parsed().compiled_context is False

    def test_the_flag_wins_where_the_variable_is_silent(self, monkeypatch):
        monkeypatch.setenv("JUDAIS_LOBI_COMPILED_CONTEXT", "")
        assert _parsed("--compiled-context").compiled_context is True

    def test_the_help_says_it_implies_cognition(self):
        """One sentence, where an operator meets it. Read off the action
        rather than out of the formatted page, because argparse wraps and a
        substring search over the wrapped text finds the usage line."""
        from tests.test_contract import _mission_parser

        action = [option for option in _mission_parser()._actions
                  if "--compiled-context" in option.option_strings][0]
        assert "--cognition" in action.help
        assert "IMPLIES" in action.help

    def test_the_flag_is_published(self):
        from core.runtime import contract

        assert "--compiled-context" in contract.CLI_FLAGS
        assert "JUDAIS_LOBI_COMPILED_CONTEXT" in contract.ENV_VARS


class TestAskingForTheViewAsksForTheState:
    """``--compiled-context`` implies ``--cognition`` and does not refuse.

    The view is compiled from the shadow's own state, so the two are one
    request; a harness that made an operator type both would be charging
    them for an implementation detail, and one that refused would be
    charging them twice.
    """

    def test_the_view_alone_still_opens_the_shadow(self, elf, tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        store = RunStore(tmp_path / "runs")
        run_id = store.list()[0].run_id
        assert (store.directory(run_id) / REASONING_LOG).exists()

    def test_and_the_block_is_in_the_input(self, elf, tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        assert any(blocks_in(seed) for seed in agent.seeds)


# ── one live view, never a log of them ───────────────────────────────────────


class TestOneLiveViewAndNotALog:
    """The design, stated as three assertions.

    A block that accumulated would make the conversation a log of every
    view the run has ever had — which is the transcript accumulation this
    feature exists to replace, with a heading on it.
    """

    @pytest.fixture
    def seeds(self, elf, tmp_path):
        """The MISSION calls, off the recording.

        Not ``agent.seeds``: one backend serves the mission loop and the
        critic, and a grounding call's message list is not a step's. The
        recorder is the thing that already knows which is which — one
        owner for "what kind of call was that" — and its log is also the
        artefact a platform would read, which is where §2.9.5 says this
        block is observable at all.
        """
        MockClass, agent = elf
        script(agent, VIEW, VIEW, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        return model_calls(tmp_path)

    def test_the_first_step_has_no_block(self, seeds):
        """Nothing has been dispatched yet, so the state is empty and there
        is nothing to say. A heading over nothing is a claim."""
        assert blocks_in(seeds[0]) == []

    def test_every_later_step_carries_exactly_one(self, seeds):
        carried = [len(blocks_in(seed)) for seed in seeds[1:]]
        assert carried and set(carried) == {1}, carried

    def test_the_one_it_carries_is_the_newest(self, seeds):
        """Two steps, two states, two different blocks — and the second
        step's input holds the second one. A replacement that kept the old
        text would pass every count above."""
        first = blocks_in(seeds[1])[0]["content"]
        last = blocks_in(seeds[-1])[0]["content"]
        assert first != last
        assert "r2" in last and "r2" not in first

    def test_the_blocks_never_pile_up(self, seeds):
        assert sum(len(blocks_in(seed)) for seed in seeds) == len(seeds) - 1


class TestWhereTheBlockRides:
    """Last, next to the current turn — and not in the cached prefix.

    Both halves are measurements this repository already paid for: rc4
    moved the conduct below the catalogue because a 20B followed it from
    the end and not from the middle, and the seed's order is
    most-constant-first because a served endpoint caches a prefix.
    """

    @pytest.fixture
    def seeds(self, elf, tmp_path):
        MockClass, agent = elf
        script(agent, VIEW, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        return model_calls(tmp_path)

    def test_the_block_is_the_last_message(self, seeds):
        for seed in seeds[1:]:
            assert TITLE in seed[-1]["content"], seed[-1]

    def test_it_rides_after_the_whole_transcript(self, seeds):
        """After the objective, after the assistant turn, after the tool
        result — which is what "the transcript is above it" means, and what
        makes the sentence in the block about reaching past it true."""
        seed = seeds[1]
        where = [index for index, message in enumerate(seed)
                 if TITLE in str(message.get("content") or "")][0]
        assert where == len(seed) - 1
        assert any(message.get("role") in ("assistant", "tool")
                   for message in seed[:where])

    def test_the_system_turn_is_untouched(self, seeds):
        """The pinned prefix — persona, protocol, catalogue, conduct — is
        the longest byte-stable thing a served endpoint can cache, and a
        view rendered into it would move the cache every single step."""
        assert seeds[0][0]["content"] == seeds[-1][0]["content"]
        assert TITLE not in seeds[-1][0]["content"]

    def test_the_objective_is_still_the_objective(self, seeds):
        assert seeds[0][1] == seeds[-1][1]


class TestTheWindowStillOwnsWhatFits:
    """The block is inside the bound, and the bound is not this lane's.

    :meth:`core.runtime.run.Run._compile_context` appends **before**
    :meth:`~core.runtime.run.Run._fit`, which is one line and two claims —
    and the review asked for both to be pinned rather than argued in a
    docstring.  A block appended *after* the fit would make a request
    larger than the window said it was, which is the failure
    :class:`~core.runtime.context_window.MissionWindow` exists to prevent;
    and a block the window then evicts must leave the next step's removal a
    no-op rather than a crash or a wrong deletion.
    """

    @pytest.fixture
    def paged(self):
        from tests.test_mission import paged_bus

        return paged_bus.__wrapped__()

    def _shadow(self, tmp_path, text="x" * 600):
        """A shadow that always has a big view, without a kernel in it.

        Duck-typed exactly as ``Store.cognition`` is — the loop holds the
        fact that there is one and not its type — so the window claim can
        be made against a block of a stated size rather than against
        whatever a fixture's receipts happened to compile to.
        """
        class _Always:
            def __init__(self):
                self.blocks = 0

            def receipt(self, *_args, **_kwargs):
                pass

            def close_step(self):
                pass

            def compiled_block(self):
                self.blocks += 1
                return f"{TITLE} — {text}"

        return _Always()

    def test_the_fit_is_handed_the_block(self, paged, tmp_path,
                                         monkeypatch):
        """The precise claim, at the seam it is about.

        Every list that reaches :meth:`~core.runtime.run.Run._fit` on a
        step that has a view ends with that view — so the window measures
        the request the model is actually sent. A block appended after the
        fit would be invisible to the one object that owns what fits, and
        the first thing anybody would know about it is a 400 from a served
        endpoint.
        """
        from core.runtime.mission import MissionRunner
        from core.runtime.run import Run
        from tests.test_mission import _paging_model, _small_window

        seen = []
        real = Run._fit

        def spy(self, messages):
            seen.append([dict(message) for message in messages])
            return real(self, messages)

        monkeypatch.setattr(Run, "_fit", spy)
        MissionRunner(_paging_model(6), paged, ["catalog.page"], max_steps=8,
                      window=_small_window(),
                      cognition=self._shadow(tmp_path)).run("go")
        withblock = [messages for messages in seen if blocks_in(messages)]
        assert len(withblock) >= 2, "no step handed the fit a view"
        for messages in withblock:
            assert TITLE in messages[-1]["content"]

    def test_the_window_bounds_the_request_the_block_is_in(self, paged,
                                                           tmp_path):
        """And the bound still holds with it there.

        Given room for the view, the conversation is compacted around it
        and every request stays inside the limit — which is what "the
        window is still the one owner of what fits" has to mean in
        behaviour and not only in call order. (A window too small for its
        own pinned prefix plus a view is short by construction and says so
        in ``tokens_after``; that is the window's documented floor, not
        this lane's rule.)
        """
        from core.runtime.context_window import ContextConfig, MissionWindow
        from core.runtime.mission import MissionRunner

        from tests.test_mission import _paging_model

        window = MissionWindow(config=ContextConfig(
            max_context_tokens=2200, max_output_tokens=200))
        model = _paging_model(6)
        MissionRunner(model, paged, ["catalog.page"], max_steps=8,
                      window=window,
                      cognition=self._shadow(tmp_path)).run("go")
        assert any(TITLE in str(message.get("content") or "")
                   for sent in model.seen for message in sent), \
            "the block never reached a request at all"
        assert max(window.estimate(sent) for sent in model.seen) \
            <= window.limit_tokens

    def test_a_block_the_window_evicts_leaves_the_removal_a_no_op(
            self, paged, tmp_path):
        """The other half, and the one that could corrupt a conversation.

        Removal is by object identity through a `fit` that rebuilds the
        list and a `_heal_native` that rebuilds it again; an evicted block
        is simply not there, and the step that looks for it must delete
        nothing else and must not raise. Driven at a window small enough
        that compaction really runs, with the mission asserted to have
        finished and every request still one block or none.
        """
        from core.runtime.mission import MissionRunner
        from tests.test_mission import _paging_model, _small_window

        window, model = _small_window(), _paging_model(6)
        shadow = self._shadow(tmp_path)
        transcript = MissionRunner(model, paged, ["catalog.page"],
                                   max_steps=8, window=window,
                                   cognition=shadow).run("go")
        assert transcript.outcome == "answered"
        assert shadow.blocks >= 2, "no step compiled a second block"
        for sent in model.seen:
            assert len(blocks_in(sent)) <= 1, sent

    def test_an_operator_s_lookalike_injection_is_not_the_block(self,
                                                                tmp_path):
        """Removal is by identity and never by matching the text.

        An operator who injects a paragraph that *begins* like the view —
        quoting it back, arguing with it — would have their instruction
        silently deleted by a step that recognised blocks by their first
        words. The one they sent stays; the one the runtime put there is
        the one that goes.
        """
        from core.runtime.run import Run

        run = _bare_run(self._shadow(tmp_path))
        messages = [{"role": "system", "content": "you are"},
                    {"role": "user", "content": "go"}]
        run._compile_context(messages)
        mine = messages[-1]
        theirs = {"role": "user",
                  "content": f"{TITLE} — no it does not, look again"}
        messages.append(theirs)

        run._compile_context(messages)
        # BY IDENTITY, both ways: the two blocks are byte-identical here
        # (the fake shadow answers with one string), which is exactly the
        # case a value comparison cannot tell apart and the case an
        # operator quoting the view back produces.
        assert any(message is theirs for message in messages)
        assert all(message is not mine for message in messages)
        assert len(blocks_in(messages)) == 2
        assert messages[-1] is run._compiled


def _bare_run(shadow):
    """One :class:`~core.runtime.run.Run`, built the way the adapter does."""
    from core.contracts.schemas import PolicyPack
    from core.runtime.mission import MissionRunner
    from core.tools.bus import ToolBus
    from core.tools.capability import CapabilityEngine
    from core.tools.sandbox import NoneSandbox

    engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))
    bus = ToolBus(capability_engine=engine, sandbox=NoneSandbox())
    return MissionRunner(lambda messages, **kw: "{}", bus, [],
                         cognition=shadow)._run


class TestTheBlockCarriesEvidenceForward:
    """The mechanism, against the benchmark pack rather than a fixture.

    ``three_receipts_one_total`` is the multi-hop mission: list, read,
    read, read, add.  Its diagnostic half is exactly this — a model holding
    two of those receipts in its window will answer from the two and sound
    identical — so the question *is* whether the runtime carried the first
    receipt's figure to the step that needed it.

    The scripted model is the pack's own ``good`` agent, unchanged, so this
    measures the wiring and not a script written to pass.
    """

    @pytest.fixture
    def inputs(self, tmp_path, monkeypatch):
        pytest.importorskip("yaml", reason="a skill manifest is frontmatter")
        from tests.test_eval_benchmark_suite import (BENCH, SCRIPTS, SKILL,
                                                     _agent)
        from core.eval.benchmark_suite import SUITE

        monkeypatch.setenv("JUDAIS_LOBI_APPROVALS", str(tmp_path / "approve"))
        mission = [m for m in SUITE.missions
                   if m.key == "three_receipts_one_total"][0]
        argv = ["judais", mission.prompt, "--mission",
                "--mcp-stdio", f"{sys.executable} {BENCH}",
                "--skill", str(SKILL),
                "--events", str(tmp_path / "events.jsonl"),
                "--cognition", "--compiled-context", *mission.flags]
        with patch("sys.argv", argv):
            from core.cli import _main
            _main(_agent(SCRIPTS[mission.key]["good"]))
        return model_calls(tmp_path)

    def test_the_figure_read_at_step_two_is_still_there_at_step_five(
            self, inputs):
        """``led.a41``'s 120 units arrives at the second step and is needed
        at the fifth, three receipts later. It is in the block, with the
        handle that fetched it, and the model did not have to re-read the
        transcript to find it."""
        adding = inputs[4][-1]["content"]
        assert TITLE in adding
        assert "units = 120" in adding
        assert "mcp.ledger_entry#r2" in adding

    def test_all_three_figures_the_addition_needs_are_in_one_block(
            self, inputs):
        adding = inputs[4][-1]["content"]
        for figure in ("units = 120", "units = 86", "units = 112"):
            assert figure in adding, adding

    def test_every_figure_carries_the_receipt_it_came_from(self, inputs):
        for line in inputs[4][-1]["content"].splitlines():
            if " = " in line and line.startswith("mcp."):
                assert "#r" in line.split(" · ")[0], line

    def test_the_mission_still_passes_its_own_rubric(self, tmp_path, inputs):
        """The floor rule, measured where it matters: cognition-on never
        blocks an answer, and a block in the input must not cost the run
        the verdict it would have had."""
        from core.eval.score import score_run
        from core.eval.benchmark_suite import SUITE

        mission = [m for m in SUITE.missions
                   if m.key == "three_receipts_one_total"][0]
        verdict = score_run(tmp_path / "events.jsonl", mission)
        assert verdict.passed, verdict.reasons


# ── with the flag off, nothing at all ────────────────────────────────────────


class TestTheFlagOffChangesNothing:
    """The negative, on the committed corpus the shadow lane replays.

    ``--cognition`` alone must be the run it was last night: the compiler
    exists, the state is there, and not one byte of it reaches a model.
    """

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_a_replay_with_cognition_alone_asks_the_recorded_questions(
            self, corpus, tmp_path, run_id):
        """``drift.first: None`` is the positive statement that this run's
        model input was byte for byte the recording's — which is exactly
        what a block would break."""
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        drift = RunStore(corpus).meta(fresh).meta["drift"]
        assert drift["first"] is None, drift
        assert drift["calls"] == 0

    @pytest.mark.parametrize("run_id", CORPUS_RUNS)
    def test_and_no_block_is_anywhere_in_what_it_asked(self, corpus,
                                                       tmp_path, run_id):
        fresh = _replay(corpus, tmp_path, run_id, "--cognition")
        path = RunStore(corpus).directory(fresh) / "model.jsonl"
        assert TITLE not in path.read_text(encoding="utf-8")

    def test_a_run_with_neither_flag_has_no_shadow_to_compile_from(
            self, elf, tmp_path):
        MockClass, agent = elf
        script(agent, VIEW)
        run(MockClass, tmp_path)
        assert all(not blocks_in(seed) for seed in agent.seeds)

    def test_a_run_with_cognition_alone_compiles_nothing(self, elf,
                                                         tmp_path):
        MockClass, agent = elf
        script(agent, VIEW, VIEW)
        run(MockClass, tmp_path, "--cognition")
        assert all(not blocks_in(seed) for seed in agent.seeds)


# ── when it breaks ───────────────────────────────────────────────────────────


class _Boom(Exception):
    pass


def _boom(*_args, **_kwargs):
    raise _Boom("Boom")


class TestAFailingCompilerDoesNotMarkTheRun:
    """The floor rule with the one flag that could break it.

    A compiler that raises stops *compiling* — the harvest goes on, the log
    goes on — and the mission ends exactly as it would have. Two switches,
    one direction each.
    """

    @pytest.fixture
    def poisoned(self, monkeypatch):
        monkeypatch.setattr("core.runtime.cognition.compile_view", _boom)

    def test_the_mission_answers_anyway(self, elf, tmp_path, poisoned):
        MockClass, agent = elf
        script(agent, VIEW, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        assert agent.seeds
        assert all(not blocks_in(seed) for seed in agent.seeds)

    def test_the_harvest_keeps_running(self, elf, tmp_path, poisoned):
        """The narrow switch, checked: a compiler that cannot render is not
        a store that cannot hold."""
        MockClass, agent = elf
        script(agent, VIEW, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        store = RunStore(tmp_path / "runs")
        path = store.directory(store.list()[0].run_id) / REASONING_LOG
        assert replay_reasoning(path).propositions()

    def test_the_log_says_which_half_stopped(self, elf, tmp_path, poisoned):
        MockClass, agent = elf
        script(agent, VIEW, VIEW)
        run(MockClass, tmp_path, "--compiled-context")
        store = RunStore(tmp_path / "runs")
        path = store.directory(store.list()[0].run_id) / REASONING_LOG
        notes = [line for line in lines(path) if NOTE_KEY in line]
        assert [note[NOTE_KEY] for note in notes] == [UNCOMPILED_NOTE]
        assert "Boom" in notes[0]["error"]

    def test_it_stops_for_the_rest_of_the_run(self, tmp_path, monkeypatch):
        """Counted once and off: a compiler retried every step would write
        a note a step and spend the failure again and again."""
        shadow = ShadowCognition(tmp_path / REASONING_LOG, "run-1",
                                 compiling=True)
        shadow.receipt("t", "r1", '{"records": 12481}')
        shadow.close_step()
        monkeypatch.setattr("core.runtime.cognition.compile_view", _boom)
        assert shadow.compiled_block() == ""
        monkeypatch.undo()
        assert shadow.compiled_block() == ""
        assert shadow.compile_failures == 1
        assert shadow.compiling is False
        assert shadow.on is True

    def test_a_stopped_shadow_shows_no_view(self, tmp_path, monkeypatch):
        """Cognition stopping stops the view with it: a frozen half-state
        presented as *the runtime's view* would be the one shape this block
        must never have."""
        shadow = ShadowCognition(tmp_path / REASONING_LOG, "run-1",
                                 compiling=True)
        shadow.receipt("t", "r1", '{"records": 12481}')
        shadow.close_step()
        assert shadow.compiled_block()
        monkeypatch.setattr("core.runtime.cognition.observations_of", _boom)
        shadow.receipt("t", "r2", '{"records": 1}')
        assert shadow.on is False
        assert shadow.compiled_block() == ""

    def test_an_empty_state_is_no_block_and_no_failure(self, tmp_path):
        shadow = ShadowCognition(tmp_path / REASONING_LOG, "run-1",
                                 compiling=True)
        assert shadow.compiled_block() == ""
        assert shadow.compile_failures == 0
        assert shadow.compiling is True


# ── picking it back up ───────────────────────────────────────────────────────


class TestResumeRecompilesFromTheLog:
    """Nothing extra is persisted for the view, and nothing needs to be.

    A view is a rendering of the store, and a rendering written down is a
    second copy of a fact that already has an owner. ``--resume`` replays
    the log into a state and the next block is compiled from that — so a
    resumed run's model reads what the first process believed.
    """

    def test_a_reopened_shadow_compiles_the_replayed_state(self, tmp_path):
        store = RunStore(tmp_path / "store")
        first = open_shadow(store, store.create().run_id, compiling=True)
        first.receipt("mcp.governed_view", "r1", '{"records": 12481}')
        first.close_step()
        before = first.compiled_block()

        again = open_shadow(store, Path(first.path).parent.name,
                            compiling=True)
        assert again.compiled_block() == before
        assert "records = 12481" in before

    def test_nothing_extra_is_written_for_it(self, tmp_path):
        store = RunStore(tmp_path / "store")
        shadow = open_shadow(store, store.create().run_id, compiling=True)
        shadow.receipt("mcp.governed_view", "r1", '{"records": 12481}')
        shadow.close_step()
        before = Path(shadow.path).read_text(encoding="utf-8")
        beside = _files_beside(shadow.path)
        shadow.compiled_block()
        shadow.compiled_block()
        assert Path(shadow.path).read_text(encoding="utf-8") == before
        assert _files_beside(shadow.path) == beside

    def test_a_resumed_process_shows_what_the_first_one_believed(
            self, elf, tmp_path):
        """The whole of it on the command line: killed at a step boundary,
        picked back up, and the first thing the resumed model reads is a
        block holding the receipt the dead process took.

        It is also the guard on an orphan. The resumed tail is rebuilt from
        the run's own *event stream* — replies and results — and not from
        the recorded model input, so the block the first process injected
        is not in it. A tail rebuilt the other way would leave a block no
        run object holds the handle to, and the conversation would carry
        two: one live and one nobody can replace.
        """
        MockClass, agent = elf
        queue = [VIEW]

        def dying(**kw):
            agent.seeds.append([dict(m) for m in kw["messages"]])
            if queue:
                return queue.pop(0)
            raise RuntimeError("the model server went away")

        agent.client.chat.side_effect = dying
        with pytest.raises(SystemExit):
            run(MockClass, tmp_path, "--compiled-context")
        run_id = RunStore(tmp_path / "runs").list()[0].run_id

        script(agent, VIEW)
        argv = ["test", "--mission", "--resume", run_id,
                "--mcp-stdio", f"{sys.executable} {MISSION_STUB}",
                "--skill", str(_skill_for(tmp_path)), "--compiled-context"]
        with patch("sys.argv", argv):
            from core.cli import _main
            _main(MockClass)

        calls = model_calls(tmp_path)
        assert all(len(blocks_in(messages)) <= 1 for messages in calls)
        resumed = [messages for messages in calls
                   if blocks_in(messages)][-1]
        block = blocks_in(resumed)[0]["content"]
        assert "mcp.governed_view#r1" in block
        assert "records = 12481" in block

    def test_a_reopened_shadow_that_was_not_asked_compiles_nothing(self,
                                                                   tmp_path):
        """The switch is the caller's on both paths through ``open_shadow``:
        a resumed run that quietly stopped showing the model its own view
        is the defect that argument exists to prevent."""
        store = RunStore(tmp_path / "store")
        run_id = store.create().run_id
        first = open_shadow(store, run_id, compiling=True)
        first.receipt("t", "r1", '{"records": 12481}')
        first.close_step()
        assert open_shadow(store, run_id).compiled_block() == ""
        assert open_shadow(store, run_id, compiling=True).compiled_block()


def _files_beside(path) -> list:
    return sorted(item.name for item in Path(path).parent.iterdir())


# ── the state a mission builds is the state a view is compiled from ──────────


def test_the_shadow_compiles_what_it_harvested(tmp_path):
    """The seam between the two halves of this lane, in one assertion: what
    ``observations_of`` made is what the block says, without a mission."""
    shadow = ShadowCognition(tmp_path / REASONING_LOG, "run-1",
                             compiling=True)
    shadow.receipt("mcp.governed_view", "r3",
                   '{"records": 12481, "total_s": 154.024}')
    shadow.close_step()
    block = shadow.compiled_block()
    assert "mcp.governed_view#r3 · records = 12481  [verified]" in block
    assert "mcp.governed_view#r3 · total_s = 154.024  [verified]" in block


def test_a_library_caller_gets_the_same_switch():
    """``ShadowCognition`` is what a library caller builds and hands to
    ``Run``; a parameter the constructor could not take would be a feature
    only the CLI has."""
    import inspect

    parameters = inspect.signature(ShadowCognition.__init__).parameters
    assert "compiling" in parameters
    assert parameters["compiling"].default is False
    assert "compiling" in inspect.signature(open_shadow).parameters


def test_the_view_a_run_shows_is_the_state_the_log_replays(tmp_path):
    """One owner: the block is compiled from the same object the log is
    written from, so a reader of ``reasoning.jsonl`` can reconstruct what
    the model was shown."""
    store = RunStore(tmp_path / "store")
    shadow = open_shadow(store, store.create().run_id, compiling=True)
    shadow.receipt("mcp.governed_view", "r1", '{"records": 12481}')
    shadow.close_step()
    from core.cognition import compile_view

    assert shadow.compiled_block() == compile_view(
        replay_reasoning(shadow.path)).text
