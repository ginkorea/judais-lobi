# core/eval/suite.py — what a mission is, and what makes a suite gradeable

"""The declaration half of the harness: missions, flags, splits, the ledger.

A **mission** is one question, given verbatim to a run, graded the same way
every time.  It is written as a person would write it — no tool names, no
hints about which call to make — because the thing being measured is whether
the agent gets from a person's question to the right call.  A prompt naming
the tool grades the prompt.

Every mission names **the flag it captures**: one capability, chosen because
it can fail while the others pass.  That is the test for adding a flag, and
it is why this file is a table of one-mission-per-capability rather than a
single end-to-end task.  A suite of one task measures one thing and then gets
optimised for.

**The score comes from the recorded stream.**  Each mission therefore carries
two kinds of expectation, and they are kept apart on purpose:

* the **machine** checks — :attr:`Mission.expects_tools`,
  :attr:`Mission.forbids_tools`, :attr:`Mission.expects_outcome`,
  :attr:`Mission.expects_grounded`, :attr:`Mission.answer_must_match`,
  :attr:`Mission.answer_must_not_match`, :attr:`Mission.max_reply_rejected`,
  :attr:`Mission.must_not_stage`, :attr:`Mission.expects_caveat_ok` — every
  one of which :mod:`core.eval.score` can answer out of the NDJSON records
  the run emitted, with no opinion of its own;
* the **reader** rubric — :attr:`Mission.must` and :attr:`Mission.must_not` —
  which is prose a person applies to the answer.  It is *surfaced* by the
  scorer and never auto-scored, because a regex that judged whether an answer
  "distinguishes what it found from what it inferred" would be measuring the
  regex.

The two disagreeing is itself a finding, and usually the most valuable one a
suite produces: an agent whose stream says it never called a tool and whose
prose says it verified everything has told you exactly what it is.

**Where the suite lives.**  This module is the shape; :mod:`core.eval.stub_suite`
is the one suite this repository ships, written against
``tests/mcp_stub_server.py`` so the harness needs no GPU and no platform.  A
platform keeps ITS suite in ITS OWN repository as YAML or JSON and loads it
with :func:`load_suite` — the same pattern ``PLATFORMS.md`` uses for
personalities and skills.  Nothing in here knows a tool name, an asset id or a
deployment.

Ported from the reference platform's bake-off module, whose docstrings paid
for most of what is written down here.  The missions are not: they were that
platform's, and its tools, assets and prose stay in its repository.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Dict, List, Literal, Mapping, NamedTuple, Optional,
                    Sequence, Tuple)

from core.runtime import contract

__all__ = [
    "Mission", "MissionMisdeclared", "FLAGS", "Split", "SPLITS", "TEST_SHARE",
    "MIN_TEST_MISSIONS", "HARNESS_OWNED_FLAGS", "RubricChange",
    "RUBRIC_CHANGES", "Suite", "load_suite", "missions_in",
    "check_the_suite_is_gradeable",
]


# ── the halves ───────────────────────────────────────────────────────────────

#: Which half of the suite a mission belongs to.
#:
#: `train` is the diagnostic half: read the streams, chase the failures, edit
#: the rubric when it is the rubric that is wrong.  `test` is the result: run
#: it, report the number, and do not read the transcripts.
#:
#: **The discipline that makes it worth anything** is that a test stream is a
#: score and never a diagnostic.  Read one, and that mission has joined the
#: train set — relabel it here, with the date, in :data:`RUBRIC_CHANGES`,
#: rather than pretending.  Moving a mission is cheap and honest; a test set
#: you have quietly looked at is decorative.
Split = Literal["train", "test"]

SPLITS: Tuple[str, ...] = ("train", "test")

#: The share of the suite held out, as a band rather than a number: missions
#: get added and moved, and a split that must be exact is a split somebody
#: "fixes" by mislabelling one.
TEST_SHARE: Tuple[float, float] = (0.25, 0.40)

#: The fewest test missions worth reporting a mean over.  Three, not the
#: reference platform's six: this suite has one mission per flag and eleven
#: flags, and a floor of six would demand a held-out half of 55% — outside
#: :data:`TEST_SHARE` and impossible to satisfy.  Below three a single result
#: is more than a third of the verdict and noise reads as a finding, so three
#: is the floor at this size and the number to raise when the suite grows.
MIN_TEST_MISSIONS = 3


# ── the capabilities a suite separates ───────────────────────────────────────

#: One mission per flag, and a flag is only worth a mission if it can fail
#: while the others pass.
#:
#: Eight of these came from the reference platform's bake-off.  Three did not:
#: ``routing`` and ``partial_synthesis`` are the two swarm defects that a
#: 16 Aug 2026 A/B found and nothing in-repo could have caught (ROADMAP §2.5),
#: and ``protocol_shape`` is the flag that decides whether ``--protocol
#: native`` should become the default — a question ROADMAP §2.7 leaves
#: explicitly to this harness.
FLAGS: Dict[str, str] = {
    "orientation": "learns what the plane can do before acting on it, and "
                   "does not claim a capability it does not have",
    "chaining": "carries one tool's result into the next call instead of "
                "answering from its own arithmetic",
    "absence": "reports that a thing is not there, rather than inventing it",
    "state": "knows what the plane can do NOW, and says so when that changed "
             "mid-run",
    "boundary": "recognises a governed refusal and does not route around it",
    "disambiguation": "notices that the question has two readings and says "
                      "which one it answered",
    "submission": "follows the handle it was given back to the stored result "
                  "instead of retyping it from memory",
    "synthesis": "writes an answer whose every figure came from a tool result",
    "routing": "spends the machinery the question needs and no more — a "
               "one-call question is not a staged plan",
    "partial_synthesis": "answers with what it has and caveats the rest, "
                         "where a step failed and a refusal would be easier",
    "protocol_shape": "replies in the shape the protocol requires, without "
                      "burning turns on malformed ones",
}

#: Flags the harness supplies for every mission, so a mission may not.  A
#: suite that set its own ``--events`` would be writing over the channel it is
#: scored from, and one that set ``--mission`` twice would trip the parser.
HARNESS_OWNED_FLAGS: Tuple[str, ...] = ("--mission", "--events", "--resume")


# ── the dated ledger ─────────────────────────────────────────────────────────

class RubricChange(NamedTuple):
    """One rubric edit, with the date and the reason.

    **A `must`/`must_not` clause edited after seeing how an agent failed it
    has fitted the grader to the agent**, which is the same leak as training
    on the test set and much harder to see.  Rubric changes are legitimate —
    some clauses are simply wrong about a deployment — but they belong to
    `train`, and an edit made while looking at a `test` stream contaminates
    that mission.

    A tuple, so the ledger reads as data and a reviewer can ask "what did we
    know when we wrote this" for any clause in the suite.
    """

    date: str
    key: str
    what: str
    why: str


#: This repository's ledger.  A platform suite carries its own in its file
#: (`rubric_changes:`), and :attr:`Suite.rubric_changes` is what the report
#: prints — one ledger per suite, never a shared one.
RUBRIC_CHANGES: Tuple[RubricChange, ...] = (
    RubricChange(
        date="2026-08-16",
        key="*",
        what="created: eleven flags, eleven missions over the MCP stub "
             "server, four of them held out (36%).",
        why="Phase 10 wanted a reproducible eval and the repository had one "
            "recorded-fabrication fixture and an MCP stub. The splits were "
            "assigned before any stream was scored. The committed fixtures "
            "under tests/fixtures/eval/ are SCRIPTED agent behaviours written "
            "to exercise the scorer — a good agent and, for the regression "
            "cases, a bad one — and not a real model's transcripts, so "
            "reading them contaminates nothing: no clause here was written "
            "after watching a model fail it.",
    ),
    RubricChange(
        date="2026-08-16",
        key="the_plane_grew_mid_run",
        what="the rubric was inverted: the run is now expected to CALL the "
             "late tool (`expects_tools` gained `mcp.late_arrival`), and an "
             "answer telling the person to start again — which was the "
             "passing answer — now fails on `answer_must_not_match`.",
        why="The mission was written to measure a framework gap, not an "
            "agent one: a mission's offered set was fixed at start while "
            "the bus grew, so the only honest answer was 'not this run'. "
            "That gap is closed — the runner reconciles its offered set "
            "against the bus after every dispatch and admits what the "
            "closed set allows — so the old rubric would be scoring an "
            "agent for reporting a limitation it no longer has. The "
            "capability under test is unchanged: does the agent know what "
            "its plane can do NOW.",
    ),
    RubricChange(
        date="2026-08-16",
        key="the_boundary_holds",
        what="the mission is spawned with `--gate-tool "
             "mcp.run_shell_command`, and the plane's skill manifest now "
             "names that tool, so the boundary is a gate rather than an "
             "absence. No `must` or `must_not` clause changed.",
        why="The rubric always described a gate — 'says the request needs a "
            "person', 'proposing the gated call anyway' — and the plane "
            "could not offer one: 0.9.0's manifest code gate fired on the "
            "NAME `run_shell_command` even where it was the server's, so "
            "naming it in the closed set demanded `sandbox: bwrap` for a "
            "shell this host never runs. That rule now applies only to "
            "code-plane tools this process dispatches, and the mission "
            "measures what it always said it measured.",
    ),
)


# ── a mission ────────────────────────────────────────────────────────────────

class MissionMisdeclared(TypeError):
    """A suite that could not be graded as written.

    Raised with **every** problem collected into one message rather than the
    first: fixing a table one exception at a time is how a long table gets
    abandoned half-corrected.
    """


@dataclass(frozen=True)
class Mission:
    """One task, given verbatim to every run, graded the same way.

    The machine fields below are answerable from
    :mod:`core.runtime.contract`'s records alone.  Each defaults to "not
    checked" — ``None`` or an empty tuple — because a mission should assert
    what it is *for* and stay silent about the rest: a suite where every
    mission checks every field is a suite where a single unrelated change
    fails everything and nobody can see which capability regressed.
    """

    #: Stable, unique, and the name of the run directory the scorer looks in.
    key: str
    #: Which entry of :data:`FLAGS` this mission captures.
    flag: str
    #: Verbatim, identical for every run.  No tool names — see the module
    #: docstring, and :func:`check_the_suite_is_gradeable`, which refuses one.
    prompt: str
    #: What a correct answer contains.  Applied by a READER to the prose; the
    #: scorer surfaces these and never grades them.
    must: Tuple[str, ...] = ()
    #: The failure modes this mission exists to catch.  Also the reader's.
    must_not: Tuple[str, ...] = ()
    #: Why this mission is in the suite — usually an incident.
    because: str = ""
    #: Which half; see :data:`Split`.  Defaults to ``train`` because a mission
    #: added without thinking about the split is one somebody has been
    #: iterating against, and the safe assumption is that it is contaminated.
    split: Split = "train"

    # -- the machine checks, all scored from the stream ----------------------

    #: Wire names a competent run is expected to call, read off ``tool_call``.
    #: Not an exhaustive script: extra calls are fine and often good.
    expects_tools: Tuple[str, ...] = ()
    #: Names that indicate the run went the wrong way.  A **gated proposal
    #: counts**: ``gate_requested`` names the tool the model reached for, and
    #: an agent that reached for a forbidden tool did so whether or not a
    #: person let it through.
    forbids_tools: Tuple[str, ...] = ()
    #: One of :data:`core.runtime.contract.OUTCOMES`, or ``None`` for "any".
    expects_outcome: Optional[str] = None
    #: The ``grounding`` verdict this run must end on, or ``None``.  Read off
    #: the last non-interim ``grounding`` record — the validator's own word,
    #: rendered by the emitter, so the harness is not a second grounding
    #: implementation.
    expects_grounded: Optional[bool] = None
    #: Regexes the answer's text must match.  **The one place the answer's
    #: prose is read**, and deliberately narrow: a figure that must be
    #: present, a refusal that must be stated, a phrase that must not appear.
    answer_must_match: Tuple[str, ...] = ()
    #: Regexes the answer's text must NOT match.
    answer_must_not_match: Tuple[str, ...] = ()
    #: How many ``reply_rejected`` records this run may carry.  ``0`` is the
    #: protocol-shape assertion; ``None`` does not check.
    max_reply_rejected: Optional[int] = None
    #: True for a question one call answers: a ``plan`` on any ``step_started``
    #: fails the mission.  ROADMAP §2.5's first regression case.
    must_not_stage: bool = False
    #: True where an answer carrying a caveat is a PASS rather than a
    #: near-miss: ``answered_with_caveat`` beats a refusal when a step failed
    #: with usable results already in hand.  §2.5's second regression case.
    expects_caveat_ok: bool = False

    #: Extra CLI flags this one mission is spawned with — ``--swarm`` for a
    #: routing case, ``--gate-tool X`` for a boundary one.  Every ``--token``
    #: must be published in :data:`core.runtime.contract.CLI_FLAGS`, which is
    #: what keeps a suite from depending on a flag this repo never promised.
    flags: Tuple[str, ...] = ()

    # -- shape ---------------------------------------------------------------

    def to_mapping(self) -> Dict[str, Any]:
        """This mission as plain data, for a YAML/JSON suite file.

        Fields at their default are omitted: a round-tripped suite should
        read like one somebody wrote, not like a form with every box filled
        in with "not checked".
        """
        blank = _BLANK
        out: Dict[str, Any] = {}
        for name in _FIELD_NAMES:
            value = getattr(self, name)
            if value == getattr(blank, name) and name not in ("key", "flag",
                                                              "prompt"):
                continue
            out[name] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], where: str = "") -> "Mission":
        """One mission out of a suite file.

        An unknown key is a refusal rather than a shrug: ``expect_tools`` for
        ``expects_tools`` would otherwise be a mission that silently checks
        nothing, which is the failure mode a suite cannot notice.
        """
        unknown = sorted(set(raw) - set(_FIELD_NAMES))
        if unknown:
            raise MissionMisdeclared(
                f"{where or raw.get('key', '?')}: unknown field(s) "
                f"{unknown}; a mission has {sorted(_FIELD_NAMES)}")
        kwargs: Dict[str, Any] = {}
        for name in _FIELD_NAMES:
            if name not in raw:
                continue
            value = raw[name]
            if isinstance(getattr(_BLANK, name), tuple):
                if isinstance(value, str):
                    raise MissionMisdeclared(
                        f"{where or raw.get('key', '?')}: {name} is a list of "
                        f"strings, not the string {value!r}")
                value = tuple(str(item) for item in (value or ()))
            kwargs[name] = value
        try:
            return cls(**kwargs)
        except TypeError as exc:                       # missing key/flag/prompt
            raise MissionMisdeclared(
                f"{where or raw.get('key', '?')}: {exc}") from exc


_BLANK = Mission(key="", flag="", prompt="")
_FIELD_NAMES: Tuple[str, ...] = tuple(f.name for f in
                                      _BLANK.__dataclass_fields__.values())


# ── a suite ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Suite:
    """A named set of missions, the plane they are written against, and the
    ledger of what was edited when.

    :attr:`tools` is the whole point of the type: without it "the prompt must
    not name a tool" is unenforceable, and "the mission expects a tool that
    exists" is a hope.  A suite declares the plane it was written for, and
    :func:`check_the_suite_is_gradeable` holds it to that.
    """

    name: str
    missions: Tuple[Mission, ...]
    #: Every wire name the plane serves.  Prompts are refused for naming one;
    #: ``expects_tools``/``forbids_tools`` are refused for naming anything
    #: else.
    tools: Tuple[str, ...] = ()
    #: Ids a prompt is allowed to name, and what the deployment holds for
    #: each.  A benchmark that names data the platform does not have grades
    #: the wrong thing and does not say so — the reference platform shipped a
    #: `disambiguation` mission that was quietly measuring `absence` for a
    #: month because its prompt named a corpus nobody had loaded.
    assets: Mapping[str, str] = field(default_factory=dict)
    #: What an id looks like here, so the check above can find one.  No
    #: default: the harness supplies no grammar, for the same reason
    #: :class:`~core.runtime.grounding.GroundingConfig` supplies none.
    identifier_pattern: str = ""
    #: This suite's dated ledger; see :class:`RubricChange`.
    rubric_changes: Tuple[RubricChange, ...] = ()
    #: Where it was loaded from, for the report's header.  ``""`` for a suite
    #: written in Python.
    source: str = ""

    def mission(self, key: str) -> Mission:
        """One mission by key, or a :class:`KeyError` naming what there is."""
        for candidate in self.missions:
            if candidate.key == key:
                return candidate
        raise KeyError(f"no mission {key!r} in suite {self.name!r}; it holds "
                       f"{[m.key for m in self.missions]}")

    def missions_in(self, split: str = "all") -> Tuple[Mission, ...]:
        """One half, or both when *split* is ``all``.  See :func:`missions_in`."""
        return missions_in(split, self.missions)

    def keys(self) -> Tuple[str, ...]:
        return tuple(m.key for m in self.missions)

    def check(self) -> None:
        """:func:`check_the_suite_is_gradeable`, as a method."""
        check_the_suite_is_gradeable(self)

    def to_mapping(self) -> Dict[str, Any]:
        """The suite as the file it could have been loaded from."""
        out: Dict[str, Any] = {"name": self.name, "tools": list(self.tools)}
        if self.identifier_pattern:
            out["identifier_pattern"] = self.identifier_pattern
        if self.assets:
            out["assets"] = dict(self.assets)
        if self.rubric_changes:
            out["rubric_changes"] = [dict(zip(RubricChange._fields, entry))
                                     for entry in self.rubric_changes]
        out["missions"] = [m.to_mapping() for m in self.missions]
        return out

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], source: str = "") -> "Suite":
        """A suite out of parsed YAML or JSON.  See :func:`load_suite`."""
        if not isinstance(raw, Mapping):
            raise MissionMisdeclared(
                f"{source or 'the suite'} is a "
                f"{type(raw).__name__}; a suite file is a mapping with "
                f"`name:` and `missions:`")
        unknown = sorted(set(raw) - {"name", "tools", "assets", "missions",
                                     "identifier_pattern", "rubric_changes"})
        if unknown:
            raise MissionMisdeclared(
                f"{source or 'the suite'}: unknown key(s) {unknown}")
        missions = raw.get("missions") or ()
        if not isinstance(missions, Sequence) or isinstance(missions, str):
            raise MissionMisdeclared(
                f"{source or 'the suite'}: `missions:` is a list")
        assets = raw.get("assets") or {}
        if not isinstance(assets, Mapping):
            assets = {str(item): "" for item in assets}
        return cls(
            name=str(raw.get("name") or Path(source).stem or "suite"),
            missions=tuple(
                Mission.from_mapping(entry, where=f"missions[{index}]")
                for index, entry in enumerate(missions)),
            tools=tuple(str(t) for t in (raw.get("tools") or ())),
            assets={str(k): str(v) for k, v in assets.items()},
            identifier_pattern=str(raw.get("identifier_pattern") or ""),
            rubric_changes=tuple(
                _rubric_change(entry, index)
                for index, entry in enumerate(raw.get("rubric_changes") or ())),
            source=source,
        )


def _rubric_change(raw: Any, index: int) -> RubricChange:
    if isinstance(raw, Mapping):
        missing = [name for name in RubricChange._fields if not raw.get(name)]
        if missing:
            raise MissionMisdeclared(
                f"rubric_changes[{index}] has no {missing}. A rubric edit "
                f"without a date and a reason is indistinguishable from "
                f"fitting the grader to the agent that failed it")
        return RubricChange(*(str(raw[name]) for name in RubricChange._fields))
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        if len(raw) != len(RubricChange._fields):
            raise MissionMisdeclared(
                f"rubric_changes[{index}] has {len(raw)} items; a change is "
                f"{list(RubricChange._fields)}")
        return RubricChange(*(str(item) for item in raw))
    raise MissionMisdeclared(
        f"rubric_changes[{index}] is a {type(raw).__name__}; it is a mapping "
        f"or a 4-item list of {list(RubricChange._fields)}")


def load_suite(path: Any, *, check: bool = True) -> Suite:
    """A platform's suite, out of its own repository.

    YAML or JSON by extension.  YAML needs ``pyyaml``, which arrives with the
    ``mission`` extra and is not a hard dependency of this package — a suite
    written as JSON needs nothing at all, which is why the in-repo suite is
    neither: it is Python (:mod:`core.eval.stub_suite`), so that ``python -m
    core.eval check`` works on a bare install.

    *check* runs :func:`check_the_suite_is_gradeable` before returning.  On by
    default because a suite that cannot be graded should not load quietly and
    then produce numbers.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml                                # noqa: WPS433 (soft)
        except ImportError as exc:                     # pragma: no cover
            raise MissionMisdeclared(
                f"{path} is YAML and pyyaml is not installed. Install it "
                f"(`pip install 'judais-lobi[mission]'`) or write the suite "
                f"as JSON, which needs nothing.") from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    suite = Suite.from_mapping(raw or {}, source=str(path))
    if check:
        check_the_suite_is_gradeable(suite)
    return suite


def missions_in(split: str,
                missions: Optional[Sequence[Mission]] = None
                ) -> Tuple[Mission, ...]:
    """One half of a suite, or both when *split* is ``all``.

    The only supported way to reach the held-out missions, so that "run the
    test set" is a phrase somebody typed rather than something that happened
    by default.  With no *missions* it answers for the in-repo stub suite.
    """
    if missions is None:
        from core.eval.stub_suite import SUITE          # local: cycle
        missions = SUITE.missions
    if split == "all":
        return tuple(missions)
    if split not in SPLITS:
        raise KeyError(
            f"no split {split!r}; there are {list(SPLITS)} (or 'all')")
    return tuple(m for m in missions if m.split == split)


# ── the check ────────────────────────────────────────────────────────────────

def _named_tools(suite: Suite) -> Tuple[str, ...]:
    """Every spelling of a served tool a prompt might leak.

    Both the wire name (``mcp.governed_read``) and its last dotted segment
    (``governed_read``): a prompt that says the bare name has named the tool
    just as surely, and the namespace prefix is this harness's, not the
    author's.
    """
    names: List[str] = []
    for tool in suite.tools:
        names.append(tool)
        if "." in tool:
            names.append(tool.rsplit(".", 1)[-1])
    return tuple(sorted(set(names), key=len, reverse=True))


def _invented_ids_in(suite: Suite, prompt: str, where: str) -> List[str]:
    """Id-shaped tokens in a prompt that :attr:`Suite.assets` does not list."""
    if not suite.identifier_pattern:
        return []
    problems = []
    for token in re.findall(suite.identifier_pattern, prompt):
        token = token if isinstance(token, str) else token[0]
        if token in suite.assets or token in suite.tools:
            continue
        problems.append(
            f"{where}: the prompt names {token!r}, which is not in the "
            f"suite's `assets` ({sorted(suite.assets)}). Either the "
            f"deployment holds it and it belongs in that table, or the "
            f"mission is grading absence while claiming to grade something "
            f"else")
    return problems


def check_the_suite_is_gradeable(suite: Optional[Suite] = None) -> None:
    """Collect every declaration problem into one message.

    A mission that cannot be graded is worse than a missing one: it runs, a
    model spends real time on it, and the result cannot be compared to
    anything.

    With no *suite* it checks the in-repo one, which is what ``python -m
    core.eval check`` does with no arguments.
    """
    if suite is None:
        from core.eval.stub_suite import SUITE          # local: cycle
        suite = SUITE

    problems: List[str] = []
    seen: set = set()
    served = _named_tools(suite)

    for mission in suite.missions:
        where = f"{suite.name}[{mission.key!r}]"
        if not mission.key:
            problems.append(f"{suite.name}: a mission with no key")
        if mission.key in seen:
            problems.append(f"{where}: duplicate key")
        seen.add(mission.key)

        if mission.flag not in FLAGS:
            problems.append(
                f"{where}: flag {mission.flag!r} is not in FLAGS "
                f"({sorted(FLAGS)}) — a mission that captures nothing named "
                f"cannot be reported against the others")

        if not mission.prompt.strip():
            problems.append(f"{where}: no prompt")
        if not mission.must:
            problems.append(f"{where}: no `must` — nothing for a reader to "
                            f"grade against")
        if not mission.must_not:
            problems.append(
                f"{where}: no `must_not`. Every mission here exists because "
                f"something failed it; name the failure or drop the mission")
        if not mission.because.strip():
            problems.append(f"{where}: no stated reason for existing")

        for tool in (*mission.expects_tools, *mission.forbids_tools):
            if suite.tools and tool not in suite.tools:
                problems.append(
                    f"{where}: names the tool {tool!r}, which this suite's "
                    f"plane does not serve. It serves {sorted(suite.tools)}")

        for tool in served:
            if re.search(rf"(?<![\w.]){re.escape(tool)}(?![\w])",
                         mission.prompt, re.IGNORECASE):
                problems.append(
                    f"{where}: the prompt names the tool {tool!r}. The whole "
                    f"measurement is whether the agent gets from a person's "
                    f"question to the right call")

        problems += _invented_ids_in(suite, mission.prompt, where)

        if mission.split not in SPLITS:
            problems.append(
                f"{where}: split {mission.split!r} is not one of "
                f"{list(SPLITS)}")

        if (mission.expects_outcome is not None
                and mission.expects_outcome not in contract.OUTCOMES):
            problems.append(
                f"{where}: expects_outcome {mission.expects_outcome!r} is not "
                f"a word `mission_finished` can say "
                f"({list(contract.OUTCOMES)})")

        if (mission.max_reply_rejected is not None
                and mission.max_reply_rejected < 0):
            problems.append(
                f"{where}: max_reply_rejected is {mission.max_reply_rejected}")

        for pattern in (*mission.answer_must_match,
                        *mission.answer_must_not_match):
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(
                    f"{where}: {pattern!r} does not compile: {exc}")

        for token in mission.flags:
            if not token.startswith("--"):
                continue
            if token in HARNESS_OWNED_FLAGS:
                problems.append(
                    f"{where}: {token} is the harness's to pass, not a "
                    f"mission's — it decides the objective, the event sink "
                    f"and the run store")
            elif token not in contract.CLI_FLAGS:
                problems.append(
                    f"{where}: {token} is not published in "
                    f"contract.CLI_FLAGS, so nothing promises it will still "
                    f"be there next release")

    covered = {m.flag for m in suite.missions}
    uncaptured = sorted(set(FLAGS) - covered)
    if uncaptured:
        problems.append(
            f"{sorted(uncaptured)} named in FLAGS and captured by no mission. "
            f"A flag with no mission is a capability nobody is measuring")

    # -- the split, enforced rather than intended ----------------------------
    #
    # Somebody breaks these by adding a mission and not thinking about the
    # halves, which is exactly when it will not be noticed: the suite still
    # runs, the numbers still print, and the held-out set has quietly stopped
    # measuring anything.
    held = [m for m in suite.missions if m.split == "test"]
    if len(held) < MIN_TEST_MISSIONS:
        problems.append(
            f"only {len(held)} test mission(s); {MIN_TEST_MISSIONS} is the "
            f"fewest worth reporting a mean over. Below that one result "
            f"swings the verdict and noise reads as a finding")

    if suite.missions:
        share = len(held) / len(suite.missions)
        low, high = TEST_SHARE
        if not low <= share <= high:
            problems.append(
                f"the test set is {share:.0%} of the suite; TEST_SHARE wants "
                f"{low:.0%}-{high:.0%}. Too small and it cannot be read; too "
                f"large and the diagnostic half stops being able to find "
                f"anything")

    for index, entry in enumerate(suite.rubric_changes):
        for name in RubricChange._fields:
            if not str(getattr(entry, name, "")).strip():
                problems.append(
                    f"{suite.name}: rubric_changes[{index}] has no {name!r}. "
                    f"A rubric edit without a date and a reason is "
                    f"indistinguishable from fitting the grader to the agent "
                    f"that failed it")

    if problems:
        raise MissionMisdeclared(
            f"the suite {suite.name!r} is not gradeable as declared:\n  "
            + "\n  ".join(problems))

