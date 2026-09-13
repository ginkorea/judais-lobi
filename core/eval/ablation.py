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

**Availability is mechanical and never a list somebody maintains.**  Most
of the arms this arc will want do not exist yet: ``--cognition`` lands on
another branch, and compiled context and the graph working set are Phases
18 and 20.  An arm whose flags the installed CLI does not accept is
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
is honest about, and both numbers are printed side by side.

**The model is named beside every number.**  A rate without the model that
produced it is a figure somebody quotes next month against a different
endpoint; every table here carries the provider, the model and the commit
under it, out of :func:`core.eval.measure.header`, which is the one owner
of that header.

**Nothing here spawns anything.**  :func:`core.eval.run.run_suite` is the
one spawner in this package, as it is for ``measure``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Dict, FrozenSet, List, Mapping, Optional, Sequence,
                    Tuple)

from core.durable import atomic_write_text
from core.eval.measure import _halves, _narrowed, _table, _withheld, header
from core.eval.run import DEFAULT_TIMEOUT_S, run_suite
from core.eval.score import Report, score_suite
from core.eval.suite import RubricChange, Suite, missions_in

__all__ = [
    "ARMS", "Arm", "ArmResult", "Ablation", "Unavailable",
    "accepted_flags", "probe_argv", "availability", "ablate", "paired",
    "wilson", "add_parser", "from_args",
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
#: builds; each is declared here **before** it exists so that the table has
#: its column from the first run and the column says SKIPPED until the flag
#: lands, rather than appearing one day with no history behind it.
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
            "rather than accumulated as a transcript. Declared now, "
            "skipped until Phase 18 lands the flag",
    ),
    Arm(
        name="graph",
        flags=("--graph-context",),
        why="ROADMAP §2.9.7: the graph working set, which is conditional "
            "on Phase 19 reading positive. Declared now, skipped until "
            "the flag exists",
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

    Bounded, because everything this harness spawns is.
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
    found = frozenset(_FLAG.findall((done.stdout or "") + (done.stderr or "")))
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

#: The z for a 95% interval.  One number, named, because a report that
#: printed an interval without saying which would be printing a decoration.
Z95 = 1.959963985


def wilson(passes: int, total: int, z: float = Z95
           ) -> Optional[Tuple[float, float]]:
    """The Wilson score interval for *passes* of *total*, or ``None``.

    Wilson and not the normal approximation, for the reason this harness
    exists: at the n an eval tier actually runs — twelve missions, three
    repeats — the normal interval goes below zero and above one and reads
    as a claim nobody made.  Wilson stays inside [0, 1] and does not
    collapse to a point when every run passed, which is the case a
    benchmark hits most often and the one where a false ±0 does the most
    damage.
    """
    if total <= 0:
        return None
    p = passes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total
                           + z * z / (4 * total * total)) / denominator
    return (round(max(0.0, centre - spread), 3),
            round(min(1.0, centre + spread), 3))


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
        """Mission key → one verdict per repeat, in order."""
        out: Dict[str, List[bool]] = {}
        for report in self.reports:
            side = report.halves.get(half)
            for verdict in (side.verdicts if side is not None else ()):
                out.setdefault(verdict.key, []).append(verdict.passed)
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
                 "interval": {half: list(wilson(*result.runs(half)) or ())
                              for half in self.keys},
                 "paired": {half: paired(base, result, half)
                            for half in self.keys} if base is not None
                 else {},
                 "reports": [report.as_dict() for report in result.reports]}
                for result in self.arms],
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
        flags={mission.key: mission.flag for mission in suite.missions})


# ── the table ────────────────────────────────────────────────────────────────

def _rate(passes: int, total: int) -> str:
    return "—" if not total else f"{passes / total:.0%}"


def _interval(result: ArmResult, half: str) -> str:
    band = wilson(*result.runs(half))
    return "—" if band is None else f"{band[0]:.0%}–{band[1]:.0%}"


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
            rows.append([
                f"`{result.arm.name}`", f"`{identity}`",
                f"{len([v for v in missions.values() if v])}/{len(missions)}",
                f"{runs_passed}/{runs_total}",
                _rate(runs_passed, runs_total),
                _interval(result, half),
            ])
        lines += _table(rows, ["arm", "model", "missions (all repeats)",
                               "runs k/n", "rate", "95% Wilson"])
        lines.append("")
        lines.append(
            "*missions* is all-must-pass: a mission counts for an arm only "
            "where every repeat passed it. *runs k/n* is every mission of "
            "every repeat, which is the n the interval is computed over.")
        lines.append("")

        keys = ablation.keys.get(half, ())
        ran = [result for result in ablation.arms if result.ran]
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
            for result in others:
                deltas = paired(base, result, half)
                fixed = sorted(k for k, d in deltas.items() if d > 0)
                broke = sorted(k for k, d in deltas.items() if d < 0)
                rows.append([
                    f"`{result.arm.name}`", f"`{result.arm.delta}`",
                    f"+{len(fixed)}", f"-{len(broke)}",
                    str(len(deltas) - len(fixed) - len(broke)),
                    ", ".join(f"`{k}`" for k in fixed) or "—",
                    ", ".join(f"`{k}`" for k in broke) or "—",
                ])
            lines += _table(rows, ["arm", "flag delta", "fixed", "broke",
                                   "unchanged", "which fixed", "which broke"])
            lines.append("")
            lines.append(f"Paired, mission by mission, `{identity}`: the "
                         f"same prompt and the same plane on both sides, "
                         f"one flag delta between them.")
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
    except Unavailable as exc:
        print(f"ablation: {exc}", file=sys.stderr)
        return 2

    text = ablation.to_json() if args.json else ablation.to_markdown()
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.report, ablation.to_markdown())
        atomic_write_text(args.report.with_suffix(".json"),
                          ablation.to_json())
    atomic_write_text(args.out / "ablation.json", ablation.to_json())

    if ablation.baseline is None:
        print("ablation: no arm ran; every arm's reason is in the table",
              file=sys.stderr)
        return 2
    failed = sum(1 for result in ablation.arms for report in result.reports
                 for half in report.halves.values()
                 for verdict in half.verdicts if not verdict.passed)
    return 0 if args.allow_failures or not failed else 1
