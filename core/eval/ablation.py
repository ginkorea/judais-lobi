# core/eval/ablation.py — the same missions, one thing removed at a time

"""``python -m core.eval ablation`` — does each piece earn its place?

``measure`` asks *which configuration is better* over a matrix that was
written to answer three specific questions about defaults.  This module
asks the owner's question of 13 September 2026 — *testing through ablation
to make sure each piece contributes to the whole* — which is a different
shape: one mission set, several **arms**, and a paired reading of what
moved between them.

**An arm is a name plus a set of CLI flag deltas, and it is data.**
:data:`ARMS` is a tuple of :class:`Arm` entries; everything else about the
run — provider, model, tool plane, skill, suite, split, seeds — is the
caller's and is held still.  The only difference between two arms is the
tokens appended to the spawn line, and the report prints that delta beside
every arm so the comparison describes itself.  A toggle that lands next
month is one entry here and no branch anywhere.

**Availability is mechanical and never a list somebody maintains.**  Every
arm here was declared before its flag existed: ``--cognition`` landed with
the shadow lane, ``--compiled-context`` with Phase 18, and
``--graph-context`` with Phase 20a.  Each of them graduated with **no edit
to this module's machinery** — an arm's ``why`` is retold when it lands,
and nothing else moves.  An arm whose
flags the installed CLI does not accept is
**SKIPPED with the reason**, and whether it accepts them is settled by
asking the spawn line's own ``--help`` — see :func:`accepted_flags`.  So
this module never has to be edited when a flag arrives; the same table
starts reporting a column that was skipped the day before.  That is the
opposite of :func:`core.eval.measure._check_flags_are_published`, and
deliberately: a *measurement* may only use flags this repository has
promised, because somebody outside this checkout has to be able to repeat
it, while an *ablation* is about a piece that may not be built yet and has
to be able to say so.

**Repeats are all-must-pass.**  A mission passes an arm only if it passed
in every repeat.  That is the reliability idiom the rc iteration paid for:
a 20-scenario tier at a 20B is twenty dice landing 14–16, and an arm
credited with a mission it won once in three is an arm credited with
noise.  The rate a Wilson interval is computed over is the **run**-level
one — every mission of every repeat — because that is the n the interval
is honest about, and both numbers are printed side by side.  There is ONE
Wilson in this package and it is :func:`core.eval.extraction.wilson`; what
lives here is :func:`band`, the rule that an arm with no runs gets no
interval at all.

**A repeat the endpoint ate is not evidence about a flag delta.**  A run
that never reached a model — :func:`core.eval.score.infra_reason` — is out
of ``k``, out of ``n`` and out of the interval, and a mission whose every
repeat was one of those drops out of the tally rather than counting as a
loss.  Crediting the network's bad afternoon to the arm under test is the
one way an ablation can be wrong about exactly the thing it exists to
measure.  Each is listed under its arm with its run id: out of the rate is
not out of the report.

**The model is named beside every number.**  A rate without the model that
produced it is a figure somebody quotes next month against a different
endpoint; every table here carries the provider, the model and the commit
under it, out of :func:`core.eval.measure.header`, which is the one owner
of that header.

**Every arm's price prints beside its rate.**  The owner's commissioning
criterion for the whole cognitive arc is that *all of this we add, does not
make the context bloated and the agent less capable* — two halves, and this
module only ever measured the second.  So each arm's row carries the mean
request size and the compiled view's share of it, computed by
:func:`core.eval.context.summarise_runs` over the arm's **own recorded
runs**, and the paired table carries the delta of that beside the delta in
missions passed.  "This arm gained four and cost 2.1 KB a step" is then one
line rather than two beliefs.  Where an arm cost context and passed no more
than the baseline, :func:`bloat` says so in as many words — a flag and not a
verdict, because the run that says it is one run.

**Nothing here spawns anything.**  :func:`core.eval.run.run_suite` is the
one spawner in this package, as it is for ``measure``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Dict, FrozenSet, List, Mapping, Optional, Sequence,
                    Tuple)

from core.durable import atomic_write_text
from core.eval.context import ContextSummary, summarise_runs
from core.eval.extraction import wilson
from core.eval.measure import (Unmeasurable, _halves, _narrowed, _table,
                               _withheld, header, report_paths)
from core.eval.run import DEFAULT_TIMEOUT_S, run_suite
from core.eval.score import Report, score_suite
from core.eval.suite import RubricChange, Suite, missions_in

__all__ = [
    "ARMS", "Arm", "ArmResult", "Ablation", "Unavailable", "BLOAT_NOTE",
    "accepted_flags", "probe_argv", "availability", "ablate", "paired",
    "band", "bloat", "add_parser", "from_args",
]


@dataclass(frozen=True)
class Arm:
    """One arm of the ablation: a name, why it is here, and its delta.

    The delta is **appended** to the caller's spawn line, after everything
    the caller wrote, so an arm can only ever add to a line and never
    reorder one — :func:`core.eval.measure.spawn_line_for`'s rule, for its
    reason.
    """

    #: The arm's name, and the directory its runs land in.
    name: str
    #: What removing or adding this piece is supposed to tell us.
    why: str = ""
    #: The tokens appended to the spawn line.  Empty is the baseline.
    flags: Tuple[str, ...] = ()

    @property
    def delta(self) -> str:
        """The arm's delta as it is printed: the tokens, or ``(none)``."""
        return " ".join(self.flags) if self.flags else "(none)"


#: The arms, as data.
#:
#: ``baseline`` is the line exactly as the caller wrote it and every other
#: arm is read against it.  The three below it are the pieces ROADMAP §2.9
#: builds; each was declared here **before** it existed so that the table
#: has its column from the first run and the column says SKIPPED until the
#: flag lands, rather than appearing one day with no history behind it.
#: Two have since landed and neither needed a line changed here.
ARMS: Tuple[Arm, ...] = (
    Arm(
        name="baseline",
        why="the spawn line exactly as the caller wrote it. Every other "
            "arm is a paired reading against this one, so it is the only "
            "arm that must always be able to run",
    ),
    Arm(
        name="shadow",
        flags=("--cognition",),
        why="ROADMAP §2.9.4: the epistemic prototype attached in shadow — "
            "it emits state and guidance and never gates the answer path. "
            "The question this arm answers is whether holding the problem "
            "beside the model changes what the model does with it",
    ),
    Arm(
        name="compiled-context",
        flags=("--compiled-context",),
        why="ROADMAP §2.9.5: the context compiled from the epistemic state "
            "rather than accumulated as a transcript — one block a step, "
            "holding the facts with their receipts, both sides of every "
            "conflict and what is only claimed. The question this arm "
            "answers is whether a model told what the runtime believes "
            "spends fewer calls finding it out again",
    ),
    Arm(
        name="graph",
        flags=("--graph-context",),
        why="ROADMAP §2.9.7: the run's links kept as a topology and the "
            "compiled block's RELATED section hydrated around what is "
            "owed. The question this arm answers is whether telling a "
            "model what is connected to the question changes how it "
            "spends its calls. Declared before the flag existed; "
            "graduated with Phase 20a",
    ),
)


class Unavailable(RuntimeError):
    """This ablation cannot be run as asked, and the reason is the news."""


# ── what the spawn line will accept ──────────────────────────────────────────

#: The one flag every spawn line this harness can drive must accept: the
#: harness appends it to every mission it spawns (``core.eval.run._argv_for``).
#: A help text that does not mention it is not the help of a program this
#: harness could have run, so the probe reports *unknown* rather than
#: reporting a flag set read off the wrong program.
ANCHOR_FLAG = "--events"

#: What a flag looks like in a help text.
_FLAG = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*")

#: Where argparse puts the help text on an option line: two spaces or more
#: after the option and its metavar.  Everything past this on such a line
#: is prose and is not read for flags.
_HELP_GAP = re.compile(r"\s{2,}")


def _declared_flags(text: str) -> FrozenSet[str]:
    """Every flag *text* actually DECLARES, as against merely mentions.

    A help text has two kinds of line and they say different things.  The
    ``usage:`` block and the option-list lines (``  --events EVENTS``) are
    the program stating what it accepts.  Everything else is prose — a
    flag's own description, an epilog, an example — and a flag named
    THERE may be one the program rejects: ``--protocol native`` is
    refused at the door on a backend that cannot speak it, and a help
    text that says so in a sentence would otherwise have been read as an
    acceptance.

    So the scan is anchored: the usage block, and the head of each option
    line up to the two-space gap argparse puts before the description.
    This is the fourth fact the availability rule has to hold — see
    ``EVAL.md`` §14 — and the cost of it is one more way to be wrong: a
    program whose help formats options some other way declares nothing
    here, and an arm is skipped rather than run, which is the safe end.
    """
    found: set = set()
    in_usage = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("usage:"):
            in_usage = True
            found |= set(_FLAG.findall(stripped))
            continue
        if in_usage:
            # argparse wraps a long usage over indented continuation lines
            # and ends the block with a blank one.
            if stripped and line[:1].isspace():
                found |= set(_FLAG.findall(stripped))
                continue
            in_usage = False
        if stripped.startswith("-"):
            found |= set(_FLAG.findall(_HELP_GAP.split(stripped)[0]))
    return frozenset(found)


def probe_argv(template: Sequence[str]) -> List[str]:
    """The program out of *template*, with ``--help`` after it.

    A spawn line is ``<program> [flags…]`` and the program can be several
    tokens: ``python -m core.cli``, an interpreter and a path, ``ssh host
    judais``.  Taken as every token from the start until one of three
    things — a flag, the ``{objective}`` placeholder, or a token carrying
    whitespace, which is a sentence and therefore a prompt rather than
    more program.  ``-m MODULE`` is counted in, because it names what is
    being run rather than how.

    Getting this wrong is not a crash: the help of the wrong program will
    not name :data:`ANCHOR_FLAG`, and :func:`accepted_flags` answers
    ``None`` — unknown — which is the honest report.
    """
    from core.eval.run import OBJECTIVE

    out: List[str] = []
    index = 0
    while index < len(template):
        token = template[index]
        if OBJECTIVE in token or (out and token.split() != [token]):
            break
        if token == "-m" and index + 1 < len(template):
            out += [token, template[index + 1]]
            index += 2
            continue
        if token.startswith("-"):
            break
        out.append(token)
        index += 1
    return [*out, "--help"]


def accepted_flags(template: Sequence[str], *, timeout_s: float = 30.0,
                   env: Optional[Mapping[str, str]] = None
                   ) -> Optional[FrozenSet[str]]:
    """Every ``--flag`` the spawn line's own help names, or ``None``.

    ``None`` means *could not be asked* and is a different answer from *the
    empty set*: a program that would not run, a help text that named
    nothing, or a help text that is not this harness's (see
    :data:`ANCHOR_FLAG`).  An arm is never run on a ``None``, because a run
    recorded under an arm's name that the CLI rejected at the door would be
    a number for a configuration nobody ran — the rule
    :func:`core.eval.measure._cannot_speak` applies to a protocol.

    Bounded, because everything this harness spawns is.  **The exit status
    is deliberately not read**: a program that prints its usage and exits
    non-zero is a common and correct shape — argparse itself does it on a
    bad argument, and a wrapper may do it on ``--help`` — and the question
    here is what the text DECLARES, not how the process felt about being
    asked.  stdout and stderr are read together for the same reason.
    """
    argv = probe_argv(template)
    if not argv[:-1]:
        return None
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s,
            env=dict(os.environ if env is None else env),
            stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    found = _declared_flags((done.stdout or "") + "\n" + (done.stderr or ""))
    if ANCHOR_FLAG not in found:
        return None
    return found


def availability(arms: Sequence[Arm], accepted: Optional[FrozenSet[str]]
                 ) -> Dict[str, str]:
    """Arm name → why it cannot run, or ``""`` when it can.

    An arm with no flags is always available: it is the caller's own line
    and the caller just ran it.
    """
    notes: Dict[str, str] = {}
    for arm in arms:
        if not arm.flags:
            notes[arm.name] = ""
            continue
        wanted = [token for token in arm.flags if token.startswith("--")]
        if accepted is None:
            notes[arm.name] = (
                f"the spawn line could not be asked what flags it accepts "
                f"(`{' '.join(probe_argv(['…']))}` named no {ANCHOR_FLAG}), "
                f"so {wanted} could not be confirmed. An arm whose flags "
                f"the CLI may reject is not run: the rejection would be "
                f"recorded as a score")
            continue
        missing = [token for token in wanted if token not in accepted]
        if missing:
            notes[arm.name] = (
                f"the installed CLI does not accept {missing}; its own "
                f"--help does not name {'it' if len(missing) == 1 else 'them'}"
                f". The arm stays in the table and will run the day the flag "
                f"lands")
            continue
        notes[arm.name] = ""
    return notes


# ── the statistics ───────────────────────────────────────────────────────────
#
# There is ONE Wilson interval in this package and it is
# :func:`core.eval.extraction.wilson`, imported above.  This module grew a
# twin of it on a parallel branch — same statistic, its own ``Z95``, its own
# rounding — and a second implementation of one fact is the six-of-ten-fields
# bug waiting for its second place to happen.  The twin is gone; what stayed
# here is the one thing that is genuinely this module's, which is the rule
# below about a rate nobody measured.
#
# The owner answers ``(0.0, 0.0)`` for ``n == 0`` where the twin answered
# ``None``, and that difference is not a detail worth adopting at the call
# sites: an arm that never ran has no interval, and printing ``0%–0%`` for it
# would be a measurement of a configuration nobody ran. So the *reporting*
# rule lives here, in one function, rather than in each caller's ``or ()``.


def band(result: "ArmResult", half: str) -> Tuple[float, ...]:
    """One arm's 95% Wilson interval over its runs, or ``()`` for no runs.

    The empty tuple is the whole point.  ``wilson(0, 0)`` is ``(0.0, 0.0)``
    — the honest answer to "what is the interval of nothing" is the degenerate
    one — and a report that printed it would be claiming an arm scored 0% with
    no spread, which is exactly the false certainty the interval exists to
    prevent.  A skipped arm has no numbers at all and this is where that is
    said, once.
    """
    passes, total = result.runs(half)
    return wilson(passes, total) if total else ()


# ── one arm's result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArmResult:
    """One arm's repeats, or the reason it has none."""

    arm: Arm
    #: One report per repeat, oldest first.
    reports: Tuple[Report, ...] = ()
    #: Where each repeat's runs landed — what ``score --runs`` reproduces.
    directories: Tuple[Path, ...] = ()
    #: Non-empty exactly when this arm did not run.
    skipped: str = ""
    #: The spawn line as recorded, delta applied and credentials withheld.
    command: Tuple[str, ...] = ()

    @property
    def ran(self) -> bool:
        return bool(self.reports)

    def per_repeat(self, half: str) -> Dict[str, List[bool]]:
        """Mission key → one verdict per repeat, in order.

        A repeat that measured the ENVIRONMENT is not in here — see
        :func:`core.eval.score.infra_reason`.  It is not evidence about this
        arm either way: counting it as a failure would credit the endpoint's
        bad afternoon to the flag delta, and counting it as a pass would be
        worse.  A mission whose every repeat was infra drops out of the dict
        entirely, which is the same rule :func:`paired` states for a mission
        one arm did not run: an absence is not a tie.  It is reported by
        :meth:`environment`, never dropped.
        """
        out: Dict[str, List[bool]] = {}
        for report in self.reports:
            side = report.halves.get(half)
            for verdict in (side.verdicts if side is not None else ()):
                if verdict.infra:
                    continue
                out.setdefault(verdict.key, []).append(verdict.passed)
        return out

    def environment(self, half: str) -> List[Tuple[str, str, str]]:
        """``(mission key, run id, why)`` for every repeat that never reached
        a model.  The runs the rate above is NOT over."""
        out: List[Tuple[str, str, str]] = []
        for report in self.reports:
            side = report.halves.get(half)
            for verdict in (side.verdicts if side is not None else ()):
                if verdict.infra:
                    out.append((verdict.key,
                                str(verdict.kpis.get("run_id") or "—"),
                                verdict.infra))
        return out

    def passed(self, half: str) -> Dict[str, bool]:
        """Mission key → did it pass this arm.

        **All repeats or none.**  A mission that passed twice of three did
        not pass this arm; it is a mission the arm sometimes passes, which
        is a different and much weaker claim, and the number a reader wants
        beside it is the run-level rate rather than a majority vote.
        """
        return {key: bool(seen) and all(seen)
                for key, seen in self.per_repeat(half).items()}

    def runs(self, half: str) -> Tuple[int, int]:
        """(passing runs, runs) — every mission of every repeat."""
        seen = [outcome for outcomes in self.per_repeat(half).values()
                for outcome in outcomes]
        return (len([outcome for outcome in seen if outcome]), len(seen))


@dataclass(frozen=True)
class Ablation:
    """Every arm, over one mission set, against one endpoint."""

    suite: str
    split: str
    arms: Tuple[ArmResult, ...]
    repeats: int = 1
    meta: Mapping[str, Any] = field(default_factory=dict)
    rubric_changes: Tuple[RubricChange, ...] = ()
    #: Mission keys in the order they were run, per half.
    keys: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    #: Mission key → the flag it captures, for the per-mission table.
    flags: Mapping[str, str] = field(default_factory=dict)
    #: Mission key → the class of problem it poses, where the suite groups
    #: its missions into any.  Empty for a suite that does not, and then
    #: the per-class block is not rendered at all.
    classes: Mapping[str, str] = field(default_factory=dict)

    def by_class(self, result: "ArmResult", half: str
                 ) -> Dict[str, Tuple[int, int]]:
        """Class name → (missions passed, missions) for one arm.

        The grouping an ablation is actually read by.  A flag is a
        capability that can fail while the others pass, so "synthesis 2/3"
        says an arm moved something about figures and answers nothing
        else; a class is a KIND OF PROBLEM, so "multi-hop 0/2, misleading
        2/2" says which kind the runtime is holding and which it is not —
        which is the question ROADMAP §2.9.3 is asked to answer.
        """
        passed = result.passed(half)
        out: Dict[str, Tuple[int, int]] = {}
        for key, value in passed.items():
            name = self.classes.get(key)
            if not name:
                continue
            done, total = out.get(name, (0, 0))
            out[name] = (done + int(value), total + 1)
        return out

    def context(self, result: "ArmResult", half: str) -> ContextSummary:
        """What this arm's runs of *half* cost in context.

        Per half and not per arm, because the run directories are per
        mission: the half's keys name exactly the directories its missions
        left, and a single per-arm figure would quietly average a held-out
        mission's cost into the training half's.  A path that is not there
        contributes nothing — a skipped arm has no runs and gets the empty
        summary, which renders as ``—`` rather than as a zero.

        One owner of every figure in it:
        :func:`core.eval.context.summarise_runs`, which is the same code
        ``python -m core.eval context`` reports from.  A second tally here
        is the six-of-ten-fields bug with a new place to happen.

        Recomputed on each call rather than cached.  It is a bounded read
        of the directories this ablation just wrote, at the end of a run
        that spent minutes per mission, and a cache with no invalidation
        on a report that can be rendered either side of a change is the
        more expensive mistake.
        """
        return summarise_runs([directory / key
                               for directory in result.directories
                               for key in self.keys.get(half, ())])

    @property
    def baseline(self) -> Optional[ArmResult]:
        """The arm every other one is read against: the first that ran.

        Named rather than assumed, and printed in the report, because a
        paired delta against the wrong arm is a number that looks exactly
        like the right one.  With ``--arms shadow,graph`` the baseline is
        ``shadow`` and the report says so.
        """
        for result in self.arms:
            if result.ran:
                return result
        return None

    def as_dict(self) -> Dict[str, Any]:
        base = self.baseline
        return {
            "suite": self.suite,
            "split": self.split,
            "repeats": self.repeats,
            "baseline": base.arm.name if base is not None else None,
            "meta": dict(self.meta),
            "keys": {half: list(keys) for half, keys in self.keys.items()},
            "flags": dict(self.flags),
            "rubric_changes": [dict(zip(RubricChange._fields, entry))
                               for entry in self.rubric_changes],
            "arms": [
                {"name": result.arm.name, "why": result.arm.why,
                 "flag_delta": list(result.arm.flags),
                 "skipped": result.skipped,
                 "command": list(result.command),
                 "directories": [str(path) for path in result.directories],
                 "missions": {half: result.passed(half)
                              for half in self.keys},
                 "runs": {half: list(result.runs(half))
                          for half in self.keys},
                 "by_class": {half: {name: list(tally) for name, tally
                                     in self.by_class(result, half).items()}
                              for half in self.keys} if self.classes else {},
                 "interval": {half: list(band(result, half))
                              for half in self.keys},
                 "context": {half: self.context(result, half).as_dict()
                             for half in self.keys},
                 "infra": {half: [{"mission": key, "run_id": run_id,
                                   "why": why}
                                  for key, run_id, why
                                  in result.environment(half)]
                           for half in self.keys},
                 "paired": {half: paired(base, result, half)
                            for half in self.keys} if base is not None
                 else {},
                 "reports": [report.as_dict() for report in result.reports]}
                for result in self.arms],
            # Machine-readable beside the sentence in the Markdown, so a
            # platform can gate on the owner's criterion without matching
            # on prose.
            "capability_vs_cost": {half: bloat(self, half)
                                   for half in self.keys},
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def to_markdown(self) -> str:
        return _markdown(self)


def paired(baseline: Optional[ArmResult], arm: ArmResult, half: str
           ) -> Dict[str, int]:
    """Mission key → ``+1`` fixed, ``-1`` broken, ``0`` unchanged.

    **Paired**, which is the whole point: the same mission, the same
    prompt, the same plane, the same repeats, one flag delta.  A mission
    either arm did not run is left out rather than counted as a zero — an
    absence is not a tie.
    """
    if baseline is None or not arm.ran or not baseline.ran:
        return {}
    before = baseline.passed(half)
    after = arm.passed(half)
    return {key: int(after[key]) - int(before[key])
            for key in before if key in after}


# ── the owner's criterion ────────────────────────────────────────────────────

#: The sentence an arm earns by costing context and buying nothing.
#:
#: One spelling, in the words the criterion was set in, because it is the
#: line a reader will search the report for.  It is a **flag and not a
#: verdict**: one ablation is one run of twenty dice, and the arm that was
#: flat here may be the arm that carries the next suite.  What is not
#: arguable is the arithmetic — the context went up and the missions did
#: not — and that is all this says.
BLOAT_NOTE = (
    "**`{arm}` added context and no capability.** Against `{baseline}` it "
    "moved the missions passed by {passes:+d} while adding {chars:,.0f} "
    "characters to the mean model call ({before:,.0f} → {after:,.0f}). The "
    "owner's criterion — *does not make the context bloated and the agent "
    "less capable* — is not met by this arm on this run. Flagged, not "
    "judged: one ablation is one run.")


def bloat(ablation: "Ablation", half: str) -> List[Dict[str, Any]]:
    """Every arm that cost context and passed no more than the baseline.

    The condition is deliberately the weak one — *pass delta ≤ 0 while
    context delta > 0* — rather than "made things worse".  An arm that
    breaks nothing and fixes nothing is the one the owner's sentence is
    about: it is invisible in a pass-rate table and it is spending the
    window every step.

    Silent where either side was not measured.  An arm whose runs recorded
    no ``model.jsonl`` has no cost figure, and inventing one so that a note
    can fire would be the report manufacturing its own evidence.
    """
    base = ablation.baseline
    if base is None:
        return []
    before = ablation.context(base, half)
    out: List[Dict[str, Any]] = []
    for result in ablation.arms:
        if not result.ran or result is base:
            continue
        after = ablation.context(result, half)
        if not (before.measured and after.measured):
            continue
        deltas = paired(base, result, half)
        passes = sum(1 for value in deltas.values() if value > 0) \
            - sum(1 for value in deltas.values() if value < 0)
        chars = after.mean_chars - before.mean_chars
        if passes > 0 or chars <= 0:
            continue
        out.append({"arm": result.arm.name, "baseline": base.arm.name,
                    "half": half, "passes": passes, "chars": round(chars, 1),
                    "before": round(before.mean_chars, 1),
                    "after": round(after.mean_chars, 1),
                    "note": BLOAT_NOTE.format(
                        arm=result.arm.name, baseline=base.arm.name,
                        passes=passes, chars=chars,
                        before=before.mean_chars, after=after.mean_chars)})
    return out


# ── running it ───────────────────────────────────────────────────────────────

def ablate(suite: Suite, template: Sequence[str], out: Path, *,
           split: str = "all",
           arms: Sequence[Arm] = ARMS,
           only: Sequence[str] = (),
           repeats: int = 1,
           timeout_s: float = DEFAULT_TIMEOUT_S,
           accepted: Optional[FrozenSet[str]] = None,
           probe: bool = True,
           env: Optional[Mapping[str, str]] = None,
           log=print) -> Ablation:
    """Run *suite* once per arm per repeat and return the paired result.

    *accepted* is the flag set the spawn line will take; ``None`` with
    *probe* asks it (see :func:`accepted_flags`).  Passed in rather than
    always probed so a test can state a CLI's answer without one existing,
    and so a caller who already asked does not ask twice.
    """
    env = dict(os.environ if env is None else env)
    suite = _narrowed(suite, only)
    repeats = max(1, int(repeats))
    out.mkdir(parents=True, exist_ok=True)

    if accepted is None and probe:
        accepted = accepted_flags(template, env=env)
    notes = availability(arms, accepted)

    results: List[ArmResult] = []
    for arm in arms:
        note = notes.get(arm.name, "")
        if note:
            log(f"— {arm.name}: SKIPPED — {note}")
            results.append(ArmResult(arm=arm, skipped=note))
            continue
        argv = list(template) + list(arm.flags)
        reports: List[Report] = []
        directories: List[Path] = []
        for index in range(1, repeats + 1):
            where = out / arm.name / f"rep{index}"
            log(f"══ {arm.name} (repeat {index}/{repeats}) "
                f"[{arm.delta}] → {where}")
            run_suite(suite, argv, where, split=split, timeout_s=timeout_s,
                      log=log)
            found = {mission.key: where / mission.key
                     for mission in missions_in(split, suite.missions)
                     if (where / mission.key).is_dir()}
            reports.append(score_suite(found, suite, split))
            directories.append(where)
        results.append(ArmResult(
            arm=arm, reports=tuple(reports), directories=tuple(directories),
            command=tuple(_withheld(argv))))

    return Ablation(
        suite=suite.name, split=split, arms=tuple(results), repeats=repeats,
        meta=header(template, env, repeat=repeats, timeout_s=timeout_s),
        rubric_changes=tuple(suite.rubric_changes),
        keys={half: tuple(mission.key
                          for mission in missions_in(half, suite.missions))
              for half in _halves(split)},
        flags={mission.key: mission.flag for mission in suite.missions},
        classes={mission.key: mission.mission_class
                 for mission in suite.missions if mission.mission_class})


# ── the table ────────────────────────────────────────────────────────────────

def _rate(passes: int, total: int) -> str:
    return "—" if not total else f"{passes / total:.0%}"


def _interval(result: ArmResult, half: str) -> str:
    edges = band(result, half)
    return "—" if not edges else f"{edges[0]:.0%}–{edges[1]:.0%}"


def _chars(summary: ContextSummary) -> str:
    """One arm's mean request size, or ``—`` for an arm with no recording.

    ``—`` and never ``0``: an arm whose runs recorded no ``model.jsonl``
    did not send a zero-character request, it sent requests nobody wrote
    down.  See :func:`core.eval.context.cost_of_run`, which refuses such a
    directory by name for the same reason.
    """
    return f"{summary.mean_chars:,.0f}" if summary.measured else "—"


def _block_share(summary: ContextSummary) -> str:
    return f"{summary.block_share:.1%}" if summary.measured else "—"


def _context_delta(before: ContextSummary, after: ContextSummary) -> str:
    """The arm's context cost against the baseline's, per model call."""
    if not (before.measured and after.measured):
        return "—"
    return f"{after.mean_chars - before.mean_chars:+,.0f}"


def _identity(meta: Mapping[str, Any]) -> str:
    """The model, for printing beside a number.  Never omitted."""
    return (f"{meta.get('provider') or '—'}/{meta.get('model') or '—'}")


def _cell(result: ArmResult, half: str, key: str, repeats: int) -> str:
    seen = result.per_repeat(half).get(key)
    if not seen:
        return "—"
    passed = len([outcome for outcome in seen if outcome])
    if repeats == 1 and len(seen) == 1:
        return "PASS" if passed else "FAIL"
    return f"{'PASS' if passed == len(seen) else 'FAIL'} {passed}/{len(seen)}"


def _class_cell(ablation: Ablation, result: ArmResult, half: str, name: str
                ) -> str:
    tally = ablation.by_class(result, half).get(name)
    if tally is None:
        return "—"
    done, total = tally
    return f"{done}/{total}" + ("" if not total else f" ({done / total:.0%})")


def _markdown(ablation: Ablation) -> str:
    meta = ablation.meta
    identity = _identity(meta)
    lines = [f"# ablation — suite `{ablation.suite}`", ""]
    lines += [
        f"- **commit** `{meta.get('commit', 'unknown')}`",
        f"- **date** {meta.get('date', '')}",
        f"- **provider / model** `{meta.get('provider') or '—'}` / "
        f"`{meta.get('model') or '—'}`",
        f"- **endpoint** `{meta.get('endpoint') or '—'}`",
        f"- **repeats** {ablation.repeats}, per-mission bound "
        f"{meta.get('per_mission_seconds')} s",
        "",
        "Every arm ran the SAME missions, in the same order, under the same "
        "spawn line. The only difference between two arms is the flag delta "
        "printed beside its name.",
        "",
    ]

    lines.append("## The arms")
    lines.append("")
    lines += _table(
        [[f"`{result.arm.name}`", f"`{result.arm.delta}`",
          "ran" if result.ran else "SKIPPED",
          result.skipped or result.arm.why]
         for result in ablation.arms],
        ["arm", "flag delta", "state", "why / why not"])
    lines.append("")

    base = ablation.baseline
    if base is None:
        lines.append("**No arm ran**, so there is nothing to pair. Every "
                     "arm's reason is in the table above.")
        return "\n".join(lines)

    lines.append(f"Paired deltas below are against **`{base.arm.name}`** — "
                 f"the first arm that ran.")
    lines.append("")

    for half in ablation.keys:
        lines.append(f"## {half}")
        lines.append("")
        rows = []
        for result in ablation.arms:
            if not result.ran:
                continue
            missions = result.passed(half)
            runs_passed, runs_total = result.runs(half)
            cost = ablation.context(result, half)
            rows.append([
                f"`{result.arm.name}`", f"`{identity}`",
                f"{len([v for v in missions.values() if v])}/{len(missions)}",
                f"{runs_passed}/{runs_total}",
                _rate(runs_passed, runs_total),
                _interval(result, half),
                str(len(result.environment(half))),
                _chars(cost), _block_share(cost),
            ])
        lines += _table(rows, ["arm", "model", "missions (all repeats)",
                               "runs k/n", "rate", "95% Wilson", "infra",
                               "chars/call", "view share"])
        lines.append("")
        lines.append(
            "*missions* is all-must-pass: a mission counts for an arm only "
            "where every repeat passed it. *runs k/n* is every mission of "
            "every repeat, which is the n the interval is computed over. "
            "*infra* is the repeats that never reached a model: they are out "
            "of k, out of n and out of the interval, and listed below — a "
            "flag delta cannot be credited or blamed for a run the endpoint "
            "ate.")
        lines.append("")
        lines.append(
            "*chars/call* is the mean size (in characters, not bytes) of the "
            "requests this arm's runs actually sent, and *view share* the "
            "compiled view's **raw** part of them — the view against this "
            "arm's own requests, which is not the same quantity as the "
            "marginal `Δ chars/call` below and can be larger than it: an "
            "arm whose block replaces transcript the baseline was carrying "
            "shows a share without having cost that much. Both come out of "
            "the recordings themselves — `python -m core.eval context --runs "
            "<the directory below>` prints the whole profile, including the "
            "growth curve and whether the pinned prefix held. `—` is an arm "
            "whose runs recorded no model log, which is not the same fact as "
            "a cheap one.")
        lines.append("")
        for result in ablation.arms:
            environment = result.environment(half) if result.ran else []
            if not environment:
                continue
            lines.append(f"### {half} — `{result.arm.name}`: measured the "
                         f"environment ({len(environment)})")
            lines.append("")
            lines += [f"- **{key}** (`{run_id}`): {why}"
                      for key, run_id, why in environment]
            lines.append("")

        ran = [result for result in ablation.arms if result.ran]
        if ablation.classes and ran:
            # Beside the rate table and never instead of it. The rate says
            # how much an arm moved; this says what KIND of problem it
            # moved, which is the only thing an ablation of a cognitive
            # layer is run to find out.
            names = list(dict.fromkeys(ablation.classes.values()))
            lines.append(f"### {half} — by class")
            lines.append("")
            lines += _table(
                [[name, *[_class_cell(ablation, result, half, name)
                          for result in ran]] for name in names],
                ["class", *[f"`{result.arm.name}`" for result in ran]])
            lines.append("")
            lines.append(f"All cells above: `{identity}`, all-must-pass over "
                         f"{ablation.repeats} repeat(s). **A class tally can "
                         f"hide a fix-and-break swap** — an arm that repairs "
                         f"one mission of a class and breaks another leaves "
                         f"the tally where it was; the paired table below is "
                         f"where that shows.")
            lines.append("")

        keys = ablation.keys.get(half, ())
        if keys and ran:
            lines.append(f"### {half} — per mission × arm")
            lines.append("")
            lines += _table(
                [[f"`{key}`", ablation.flags.get(key, "—"),
                  *[_cell(result, half, key, ablation.repeats)
                    for result in ran]]
                 for key in keys],
                ["mission", "flag",
                 *[f"`{result.arm.name}`" for result in ran]])
            lines.append("")
            lines.append(f"All cells above: `{identity}` at commit "
                         f"`{meta.get('commit', 'unknown')}`.")
            lines.append("")

        others = [result for result in ran if result is not base]
        if others:
            lines.append(f"### {half} — paired against `{base.arm.name}`")
            lines.append("")
            rows = []
            before = ablation.context(base, half)
            for result in others:
                deltas = paired(base, result, half)
                fixed = sorted(k for k, d in deltas.items() if d > 0)
                broke = sorted(k for k, d in deltas.items() if d < 0)
                rows.append([
                    f"`{result.arm.name}`", f"`{result.arm.delta}`",
                    f"+{len(fixed)}", f"-{len(broke)}",
                    str(len(deltas) - len(fixed) - len(broke)),
                    _context_delta(before, ablation.context(result, half)),
                    ", ".join(f"`{k}`" for k in fixed) or "—",
                    ", ".join(f"`{k}`" for k in broke) or "—",
                ])
            lines += _table(rows, ["arm", "flag delta", "fixed", "broke",
                                   "unchanged", "Δ chars/call", "which fixed",
                                   "which broke"])
            lines.append("")
            lines.append(f"Paired, mission by mission, `{identity}`: the "
                         f"same prompt and the same plane on both sides, "
                         f"one flag delta between them. **Δ chars/call is "
                         f"the price of that delta** — what the arm added "
                         f"to the mean model call against `{base.arm.name}` "
                         f"— so what an arm bought and what it cost are one "
                         f"line.")
            lines.append("")
            flagged = bloat(ablation, half)
            if flagged:
                lines.append(f"#### {half} — capability vs cost")
                lines.append("")
                lines += [entry["note"] for entry in flagged]
                lines.append("")

    lines.append("Train and test are reported apart, always.")
    lines.append("")
    lines.append("Every arm is reproducible without an endpoint: "
                 "`python -m core.eval score --runs <dir>` over the "
                 "directory beside it produces the same verdicts.")
    lines.append("")
    lines += ["| arm | runs recorded in |", "|---|---|"]
    lines += [f"| `{result.arm.name}` | "
              + (", ".join(f"`{path}`" for path in result.directories) or "—")
              + " |" for result in ablation.arms if result.ran]
    lines.append("")
    lines.append("The spawn line each arm ran, with `--mcp-url` and "
                 "`--mcp-stdio` values withheld — either can carry a token "
                 "and a report outlives the run:")
    lines.append("")
    for result in ablation.arms:
        if result.ran:
            lines.append(f"- `{result.arm.name}`: "
                         + " ".join(result.command))
    return "\n".join(lines)


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs, common) -> argparse.ArgumentParser:
    """Register ``ablation`` on :func:`core.eval.run._parser`'s subparsers.

    Registered from here rather than written out in ``run.py``, exactly as
    ``measure`` is: the subcommand and the thing it runs stay in one file.
    """
    parser = subs.add_parser(
        "ablation",
        help="run the SAME missions across declared arms and report the "
             "paired differences")
    common(parser)
    parser.add_argument("--out", required=True, type=Path,
                        help="directory for every arm's run directories; "
                             "`score --runs <out>/<arm>/rep1` reproduces one")
    parser.add_argument("--report", type=Path, metavar="PATH",
                        help="write the table here as Markdown, and the same "
                             "ablation as JSON beside it")
    parser.add_argument("--arms", default="", metavar="A,B",
                        help="comma-separated arm names to run, in this "
                             f"order; default all of "
                             f"{[arm.name for arm in ARMS]}")
    parser.add_argument("--repeats", type=int, default=1, metavar="N",
                        help="run every arm N times; a mission passes an arm "
                             "only if ALL N repeats passed it")
    parser.add_argument("--only", action="append", default=[], metavar="KEY",
                        help="ablate only this mission; repeatable")
    parser.add_argument("--per-mission-seconds", type=float,
                        default=DEFAULT_TIMEOUT_S,
                        help="wall-clock bound on ONE mission (default 600)")
    return parser


def chosen_arms(names: str, arms: Sequence[Arm] = ARMS) -> Tuple[Arm, ...]:
    """The arms named by ``--arms``, in the order given, or all of them."""
    if not names.strip():
        return tuple(arms)
    by_name = {arm.name: arm for arm in arms}
    wanted = [name.strip() for name in names.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in by_name]
    if unknown:
        raise Unavailable(
            f"--arms names {unknown}; the table holds {list(by_name)}")
    return tuple(by_name[name] for name in dict.fromkeys(wanted))


def from_args(suite: Suite, args: argparse.Namespace,
              template: Sequence[str]) -> int:
    """``ablation`` as :func:`core.eval.run.main` reaches it."""
    if not template:
        print("ablation: put the mission command line after `--`, e.g. "
              "`-- judais --provider local --mcp-stdio '…' --skill S`",
              file=sys.stderr)
        return 2

    try:
        arms = chosen_arms(args.arms)
        ablation = ablate(
            suite, template, args.out, split=args.split, arms=arms,
            only=args.only, repeats=args.repeats,
            timeout_s=args.per_mission_seconds)
    # `Unmeasurable` as well as `Unavailable`: `--only` names a mission and
    # the narrowing that refuses an unknown key is `measure`'s, so its
    # refusal arrives wearing its own exception and would otherwise reach
    # the operator as a traceback rather than as the sentence it wrote.
    except (Unavailable, Unmeasurable) as exc:
        print(f"ablation: {exc}", file=sys.stderr)
        return 2

    text = ablation.to_json() if args.json else ablation.to_markdown()
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        markdown, beside = report_paths(args.report)
        atomic_write_text(markdown, ablation.to_markdown())
        atomic_write_text(beside, ablation.to_json())
    atomic_write_text(args.out / "ablation.json", ablation.to_json())

    if ablation.baseline is None:
        print("ablation: no arm ran; every arm's reason is in the table",
              file=sys.stderr)
        return 2
    failed = sum(1 for result in ablation.arms for report in result.reports
                 for half in report.halves.values()
                 for verdict in half.verdicts if not verdict.passed)
    return 0 if args.allow_failures or not failed else 1
