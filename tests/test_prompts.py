# tests/test_prompts.py — the conduct: what it says, and where it lands

"""The framework's own prompt text, held to its position and its bytes.

Three claims, and they fail for different reasons.

**Where it renders.**  ``persona → protocol → conduct → catalogue →
(memory)``, in :func:`~core.runtime.mission.stacked` order, byte for byte.
Not "the conduct appears somewhere in the turn": the position is the point,
because a served endpoint's prefix cache is keyed on bytes and a section
that moves between two module constants is a cache miss on every step of
every mission.  ``tests/test_run_corpus.py`` is the other half of that
claim — four recorded runs replayed with an empty drift record — and this
file is the readable half: a corpus diff says *something moved*, and these
say *what*.

**What it says.**  Seven load-bearing sentences, each one a lesson
``ROADMAP.md`` §5.9 or a shipped pack paid for, asserted by phrase.  A
lane that rewrites the prose is welcome to; a lane that drops one of the
seven has deleted a production lesson and is told so by name.  The word
cap and the no-shouting rule are asserted for the same reason: this text
is re-sent on every step, so it is the one string in the repository where
an extra paragraph has a running cost.

**What it retired.**  The three shipped packs and the eval fixture were
each writing this text out by hand, and the duplicates are asserted
*gone* — not "the framework says it too", which would leave two emitters
and let them drift.  Those assertions are the ones that make the
extraction real rather than additive.

Nothing here builds its own idea of a system turn: the runs come from
``tests.test_run_memory.a_run``, which is the harness the memory lane
already uses for exactly this question.
"""

import re

import pytest

from core.runtime.mission import (
    NATIVE_PROTOCOL, NATIVE_PROTOCOL_TEXT, PROTOCOL, stacked,
)
from core.runtime.prompts import GOVERNED_PLANE
from core.runtime.run import Personality
from core.runtime.skills import load_skill, resolve_skill
from core.skills.library import packs
from tests.test_run_memory import a_run, bus  # noqa: F401 — a fixture


#: The ceiling on the conduct, in whitespace-separated tokens.  344 today,
#: and the headroom is deliberate: a lane may reword a sentence, and a
#: lane that wants a whole new paragraph has to argue for the cap as well
#: as for the paragraph.  It is a cost and not a style — this string is in
#: the prefix of every request the harness makes.
#:
#: The argument for the 185 → 300 raise (18 Aug 2026): three sentences
#: the reference deployment's hard-tier regressions paid for on the 1.0
#: candidate — a derived figure is a computation tool's to print, and a
#: reference the plane can list is looked up before the human is asked,
#: and a lookup that finds two candidates for a state-changing act names
#: both and chooses out loud.
#: All three are failures of *conduct*, not of any pack, and the only place a
#: conduct sentence lands on every run is here.  A hundred and ten words for
#: three whole classes of wrong turn.
#:
#: The argument for 300 → 355 (21 Aug 2026): a production transcript on the
#: reference deployment showed "a failed call is an answer" landing as "a
#: failed call is a permanent fact" — a model apologising instead of
#: applying a fix the error named, and remembering "the platform cannot
#: render charts" across turns after two transport errors.  Two bounds on
#: the failed-call paragraph: an error that names the fix is an
#: instruction (apply it, call again once — changed, not repeated), and a
#: capability is absent only when the catalogue or a refusal says so.
WORD_CAP = 355

#: The one sentence that must NOT be here, because the protocol owns it.
#: "State your plan" alone is a contradiction: every reply is one JSON
#: object or one function call, so a model asked for a prose plan mid-run
#: burns a turn on a malformed reply.  The conduct says where the plan
#: goes instead, and this holds it to that.
NOT_A_PROSE_PLAN = "the plan goes in the answer"

#: The seven, as the phrase each is recognised by.  A rewrite that keeps
#: the lesson keeps the phrase or updates this list on purpose; a rewrite
#: that loses the lesson cannot do either quietly.
LOAD_BEARING = {
    "the closed governed plane":
        "the catalogue is all there is",
    "a refusal names its scope and is not retried":
        "never send the same call twice unchanged",
    "results are bounded and the whole is in the store":
        "Read on by handle, field or section",
    "a failed call is an answer":
        "A failed call is an answer",
    "the figure rule §2.8 asked for by name":
        "If a number is not in the view, it is not in the draft",
    "a plan before a multi-step change, and it goes where prose is legal":
        "Before a multi-step change, read every part you will change",
    "no claim of a check without the result":
        "without the tool result that shows it",
    "a derived figure is a computation tool's to print":
        "A figure you derive",
    "look a listable reference up before asking the human":
        "look it up before you ask",
    "two candidates for a state-changing act are chosen out loud":
        "never pick one silently",
    "an error naming the fix is an instruction, once":
        "apply the fix and call again, once",
    "a failure is not a missing capability":
        "absent only when the catalogue or a refusal says so",
}


# ── what it says ────────────────────────────────────────────────────────────


class TestTheTextItself:
    """The conduct as a string, before anything renders it."""

    @pytest.mark.parametrize("lesson,phrase", sorted(LOAD_BEARING.items()))
    def test_the_lesson_is_still_in_it(self, lesson, phrase):
        assert phrase in GOVERNED_PLANE, lesson

    def test_the_answer_with_what_you_have_rule_is_in_it_too(self):
        """The eighth, and it is one sentence rather than a clause:
        ``EVAL.md`` §8.2 is a whole regression case (an answer with a
        caveat beats a refusal) and the ``answered_with_caveat`` outcome
        exists because of it."""
        assert "answer with what you have and name what is missing" in \
            GOVERNED_PLANE
        assert "a caveat beats a refusal" in GOVERNED_PLANE

    def test_the_plan_sentence_does_not_contradict_the_protocol(self):
        """See :data:`NOT_A_PROSE_PLAN`.

        The mutation this catches is a rewrite back to a bare "state your
        plan before you start", which reads well and asks the model to
        break the one rule the parser enforces.
        """
        assert NOT_A_PROSE_PLAN in GOVERNED_PLANE

    def test_it_is_inside_the_word_cap(self):
        words = GOVERNED_PLANE.split()
        assert len(words) <= WORD_CAP, len(words)

    def test_nothing_in_it_is_shouted(self):
        """No ``CRITICAL``, no shouted ``MUST``, no all-caps anything.

        The migration rule for current models: capitals spent on emphasis
        are tokens spent on nothing, and a prompt that shouts teaches the
        reader that the quiet sentences are optional.  Asserted
        mechanically rather than by naming the two words, so the next
        ``ALWAYS`` is caught as well.
        """
        shouted = [word for word in re.findall(r"[A-Za-z]{2,}", GOVERNED_PLANE)
                   if word.isupper()]
        assert shouted == []

    def test_it_carries_no_clock_no_id_and_no_placeholder(self):
        """It is stacked into the cached prefix of every step, so anything
        in it that varies is a cache miss per step for nothing."""
        assert "{" not in GOVERNED_PLANE and "}" not in GOVERNED_PLANE
        assert not re.search(r"\d{4}-\d{2}-\d{2}", GOVERNED_PLANE)
        for word in ("run_id", "audit_ref", "bwrap"):
            assert word not in GOVERNED_PLANE

    def test_it_names_no_tool(self):
        """The catalogue names the tools, once.

        The store sentence says "this run's store" and not
        ``mission_result``: a run whose store tool is withheld
        (``store_tool=""``) would otherwise be told to call something it
        has not got, and the framework would be the second place a tool's
        name is written down.
        """
        for name in ("mission_result", "fs", "run_python_code",
                     "fetch_page_content", "verify", "patch"):
            assert name not in GOVERNED_PLANE


# ── where it renders ────────────────────────────────────────────────────────


class TestThePositionInTheSystemTurn:
    """Persona, protocol, catalogue, conduct — and the order is the claim.

    The conduct moved BELOW the catalogue on 18 Aug 2026, on data rather
    than argument: the reference deployment measured a 20b model at server
    sampling following the mid-prompt conduct roughly half the time
    (gate_respected 1/3, label_set_choice 1/2 across rc2/rc3).  Recency is
    the one prompt-shaped lever a framework has, so the conduct is the
    last constant section before history and objective.  Within one
    mission the catalogue is step-constant, so the pinned prefix still
    re-renders to identical bytes every step."""

    def test_the_turn_is_exactly_those_four_sections(self, bus):
        run = a_run(bus)
        assert run.system_turn() == {"role": "system", "content": stacked(
            "You are Tai.", PROTOCOL.strip(),
            "Tool catalogue:\n" + run.catalogue(), GOVERNED_PLANE.strip())}

    def test_and_the_five_with_a_bank(self, bus, tmp_path):
        """Core memory stays LAST: it is the one section an operator
        edits, and it is allowed to mention the tools, so it follows
        both the catalogue and the conduct."""
        from core.memory.bank import MemoryBank

        bank = MemoryBank(tmp_path / "bank", principal="alice")
        bank.write("a fact", label="ops")
        run = a_run(bus, memory=bank)
        assert run.system_turn() == {"role": "system", "content": stacked(
            "You are Tai.", PROTOCOL.strip(),
            "Tool catalogue:\n" + run.catalogue(), GOVERNED_PLANE.strip(),
            bank.core())}

    def test_the_conduct_sits_between_the_catalogue_and_the_history(
            self, bus):
        """Stated as three indices as well as as bytes, because an
        equality that fails prints two long strings and this prints the
        place where the order changed."""
        content = a_run(bus).system_turn()["content"]
        assert (content.index("You are Tai.")
                < content.index("Reply with exactly one JSON object")
                < content.index("Tool catalogue:")
                < content.index("If a number is not in the view"))

    def test_it_is_the_same_bytes_under_the_native_protocol(self, bus):
        """The protocol is the syntax and the conduct is the conduct: a
        native run is told to CALL rather than to write JSON, and is told
        the same thing about the plane."""
        run = a_run(bus)
        run.model.protocol = NATIVE_PROTOCOL
        content = run.system_turn()["content"]
        assert NATIVE_PROTOCOL_TEXT.strip() in content
        assert GOVERNED_PLANE.strip() in content
        assert PROTOCOL.strip() not in content

    def test_two_runs_of_one_mission_render_the_same_bytes(self, bus):
        assert a_run(bus).system_turn() == a_run(bus).system_turn()

    def test_it_is_inside_the_pinned_prefix(self, bus):
        """A compaction may never drop it: the system turn is message
        zero and ``pinned`` counts from there."""
        run = a_run(bus)
        seeded = run.seed("find things")
        assert "If a number is not in the view" in \
            seeded[0]["content"]
        assert run.pinned >= 1


class TestTheOverride:
    """``Personality.conduct`` — the framework's, nothing, or yours."""

    def test_the_default_is_none_and_not_the_string(self):
        """It has to be ``None``.

        A dataclass default of ``GOVERNED_PLANE`` would freeze whichever
        text was imported when the personality was built, so a framework
        that reworded its conduct would keep rendering the old bytes for
        any caller holding an older object.  ``None`` means *ask the
        framework*, and it is asked at the moment the turn is rendered.
        """
        assert Personality().conduct is None

    def test_none_renders_the_frameworks_own_text(self, bus):
        assert GOVERNED_PLANE.strip() in a_run(bus).system_turn()["content"]

    def test_empty_suppresses_the_section_entirely(self, bus):
        """The documented escape: *a platform that has its own conduct
        text sets this empty and writes it in the persona*.  What is left
        is the three sections a run had before this existed, which is the
        other half of the claim — an empty conduct must not leave a blank
        line behind, and ``stacked`` is what guarantees it."""
        run = a_run(bus, conduct="")
        assert run.system_turn() == {"role": "system", "content": stacked(
            "You are Tai.", PROTOCOL.strip(),
            "Tool catalogue:\n" + run.catalogue())}
        assert "If a number is not in the view" not in \
            run.system_turn()["content"]

    def test_a_string_replaces_it_in_the_same_position(self, bus):
        run = a_run(bus, conduct="Work the plane my way.")
        assert run.system_turn() == {"role": "system", "content": stacked(
            "You are Tai.", PROTOCOL.strip(),
            "Tool catalogue:\n" + run.catalogue(), "Work the plane my way.")}

    def test_an_overrides_stray_whitespace_does_not_make_a_new_prefix(
            self, bus):
        """``stacked`` strips every section, so ``"…way.\\n\\n"`` and
        ``"…way."`` are one prefix and not two."""
        assert a_run(bus, conduct="Work the plane my way.\n\n"
                     ).system_turn() == \
            a_run(bus, conduct="Work the plane my way.").system_turn()

    def test_a_child_run_keeps_whatever_the_turn_was_given(self, bus):
        """The swarm's executor is a ``Run`` child built with
        :func:`dataclasses.replace` over the turn's personality, so the
        conduct reaches every step of a staged mission without the swarm
        knowing this module exists."""
        from dataclasses import replace

        parent = a_run(bus, conduct="")
        child = parent.child(personality=replace(
            parent.personality, system_message="You are Tai.\n\nDo one step."))
        assert child.personality.conduct == ""
        assert "If a number is not in the view" not in \
            child.system_turn()["content"]


# ── what it retired ─────────────────────────────────────────────────────────


#: ``pack name -> the clauses it used to carry and the framework now says``.
#: Asserted ABSENT from the rendered prompt.  Two emitters of one rule is
#: the arrangement ``ROADMAP.md`` §3 calls a second owner, and it is what
#: this whole module exists to end — so the extraction is only real if the
#: originals are gone.
RETIRED = {
    "analyst": (
        "Never state a figure the code did not print",
        "do not describe a capability you do not have",
        "An answer with a caveat is worth more",
        "is a fabrication even when it happens to be right",
    ),
    "research": (
        "Never invent a source",
        "A 404 is an answer",
        "Do not fetch the same URL twice",
        "Never fill the gap from memory",
        "do not retry it",
        "Do not ask for a bigger cut",
    ),
    "coding": (
        "Plan before you patch",
        "a proposal, not a result",
        "do not re-send the same patch",
        "Never say the tests pass without",
    ),
}

#: What each pack KEEPS, because "the duplicates are gone" is only worth
#: something beside "and the particular survived".  A lane that deleted
#: the pack's own knowledge would pass every assertion above.
KEPT = {
    "analyst": ("printed BY THE COMPUTATION THAT PRODUCED IT",
                "Do not delete anything"),
    "research": ("Cite the URL for every claim",
                 "with the unit the page used",
                 "a claim about a moment"),
    "coding": ("Your plan is the files you read",
               "do not change the test to match the code"),
}


def rendered(name):
    """The pack's prompt as a mission would receive it.

    Through ``resolve_skill``, which is the door a command line goes
    through, so this reads the same manifest ``--skill analyst`` reads
    and not a file path spelled again here.
    """
    return resolve_skill(name).prompt


class TestThePacksStoppedSayingIt:
    """Every shipped pack, against the clauses this module took over."""

    def test_all_three_packs_are_covered(self):
        """A fourth pack shipping with its own copy of the conduct would
        otherwise be a pack this file never looks at."""
        assert set(packs()) == set(RETIRED) == set(KEPT)

    @pytest.mark.parametrize("name", sorted(RETIRED))
    def test_the_retired_clauses_are_gone(self, name):
        prompt = rendered(name)
        assert [clause for clause in RETIRED[name] if clause in prompt] == []

    @pytest.mark.parametrize("name", sorted(KEPT))
    def test_and_what_is_particular_to_the_pack_survived(self, name):
        prompt = rendered(name)
        assert [clause for clause in KEPT[name]
                if clause not in prompt] == []

    @pytest.mark.parametrize("name", sorted(RETIRED))
    def test_no_pack_restates_the_sentence_the_framework_owns(self, name):
        """The literal one, by name: ``ROADMAP.md`` §2.8 asked for "if a
        number is not in the view, it is not in the draft" to be the
        FRAMEWORK's, and a pack that says it too is the second emitter
        again in different words."""
        assert "not in the view" not in rendered(name)


class TestTheEvalFixtureStoppedSayingItToo:
    """``tests/fixtures/eval/stub_skill.md`` is the honest test of all
    this: the in-repo suite is scored against it, so a manifest that lost
    three policy lines and kept every verdict is the claim that the
    framework's text does the work the fixture's did."""

    def test_the_stub_manifest_has_no_policy_block(self, tmp_path):
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "eval" / "stub_skill.md"
        prompt = load_skill(path).prompt
        assert "Policy:" not in prompt

    def test_and_none_of_the_three_lines_survived(self):
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "eval" / "stub_skill.md"
        prompt = load_skill(path).prompt
        for clause in ("Never invent an asset id",
                       "If a number is not in a view",
                       "A refusal names the reason",
                       "an answer with a caveat is worth more than a"):
            assert clause not in prompt, clause

    def test_the_stub_kept_what_is_particular_to_the_stub_plane(self):
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "eval" / "stub_skill.md"
        prompt = load_skill(path).prompt
        assert "Every identifier and every figure exactly as the plane" in \
            prompt
        assert "mcp.run_shell_command" in prompt
