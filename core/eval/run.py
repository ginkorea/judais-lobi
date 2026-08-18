# core/eval/run.py — spawn the missions, capture the streams, score them

"""The harness's command line: ``run``, ``measure``, ``score``, ``check``.

Four subcommands because there are four jobs, and only two of them need a
model:

``run``
    Spawns the mission command once per mission — the platform's own spawn
    line, supplied by the caller after ``--`` — and adds exactly three things
    to it: the objective, ``--events fd:N``, and ``JUDAIS_LOBI_RUNS`` pointed
    inside the mission's output directory.  Everything else (provider, model,
    tool plane, skill, protocol) is the caller's, because those are the
    variables somebody is measuring and a harness that had opinions about
    them would be measuring itself.  This is the subcommand that needs a
    model.
``measure``
    ``run``, once per entry of :data:`core.eval.measure.MEASUREMENTS`, and a
    table of the differences.  It is the subcommand that answers a question
    a single score cannot — is ``--swarm`` a better default, is ``--protocol
    native``, is each grounding tier worth its cost — because every one of
    those is a comparison and not a number.  It spawns through
    :func:`run_suite` below, so there is still exactly one spawner here.
``score``
    Scores run directories that already exist.  **This is the no-GPU path**:
    a recorded or replayed run is a directory with an ``events.jsonl`` in it,
    so yesterday's runs can be re-scored against today's rubric, and a
    grounding change can be scored on runs it was not present for.
``check``
    :func:`~core.eval.suite.check_the_suite_is_gradeable`, before anybody
    spends a GPU on a suite that cannot be graded.

**A run directory is a RunStore directory.**  That is the whole agreement
between this harness, the recorder and a platform's archive: one directory per
run, an ``events.jsonl`` inside it, envelopes or bare records — see
:func:`core.eval.score.records_from`, which reads both.

**The spawn line is never recorded verbatim.**  ``--mcp-url`` can carry a
token in its query string and ``--mcp-stdio`` can carry one as an argument,
and an output directory outlives the process that was handed it.  Both are
withheld from ``command.json``, which is the same subtraction
:data:`core.cli.RUN_META_FLAGS` makes for a run's metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.durable import atomic_write_text
from core.eval.score import EVENTS_FILE, Report, score_suite
from core.eval.suite import (MissionMisdeclared, Mission, Suite, load_suite,
                             missions_in)

__all__ = ["main", "run_mission", "run_suite", "resolve_suite", "WITHHELD"]

#: Flags whose value is replaced in the recorded command line.  A credential
#: rides both of them and a directory of results gets copied around.
WITHHELD: Tuple[str, ...] = ("--mcp-url", "--mcp-stdio")

#: What a withheld value is replaced with.
REDACTED = "<withheld>"

#: The default wall-clock bound on ONE mission, in seconds.  A harness that
#: waits forever on a cold model server is a harness nobody runs twice; a
#: mission killed here still has whatever stream it emitted, and the scorer
#: reads it and fails the mission for having no ``mission_finished`` — which
#: is the honest reading of a run that never closed.
DEFAULT_TIMEOUT_S = 600.0


def resolve_suite(name: str, *, check: bool = False) -> Suite:
    """``stub`` for the in-repo suite, anything else as a path to a file.

    *check* is off here and run once in :func:`main` instead, for every
    subcommand rather than only for ``check``.  Loading with the check on as
    well would put the refusal in two places, and the second one would be
    unreachable — which is exactly what it was, until a mutation of it
    changed nothing and said so.
    """
    if name in ("stub", "", None):
        from core.eval.stub_suite import SUITE
        return SUITE
    return load_suite(name, check=check)


# ── spawning one mission ─────────────────────────────────────────────────────

#: What a template writes where it wants the mission's prompt.
OBJECTIVE = "{objective}"


def _argv_for(mission: Mission, template: Sequence[str], events: str
              ) -> List[str]:
    """The child's argv: the caller's line, plus the three things we own.

    A template may say where the objective goes by writing
    :data:`OBJECTIVE` — necessary for any spawn line whose first token is
    not the program that takes the message (``python -m something``, a
    wrapper script, ``ssh host judais …``).  With no placeholder it goes in
    at position 1, which is where ``judais`` takes it and is not the end,
    where a positional would be swallowed by whichever flag came last.
    """
    template = list(template)
    if any(OBJECTIVE in token for token in template):
        argv = [token.replace(OBJECTIVE, mission.prompt) for token in template]
    else:
        argv = [template[0], mission.prompt, *template[1:]]
    if "--mission" not in argv:
        argv.append("--mission")
    argv += ["--events", events]
    argv += list(mission.flags)
    return argv


def _recorded_argv(argv: Sequence[str]) -> List[str]:
    """*argv* with every :data:`WITHHELD` value replaced.  See the module
    docstring: a token in a spawn line outlives the run that used it."""
    out: List[str] = []
    skip = False
    for token in argv:
        if skip:
            out.append(REDACTED)
            skip = False
            continue
        out.append(token)
        if token in WITHHELD:
            skip = True
        elif any(token.startswith(f"{flag}=") for flag in WITHHELD):
            out[-1] = token.split("=", 1)[0] + "=" + REDACTED
    return out


def run_mission(mission: Mission, template: Sequence[str], out: Path, *,
                timeout_s: float = DEFAULT_TIMEOUT_S,
                env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Run one mission and leave a run directory behind.

    The stream comes back on an inherited descriptor rather than through
    stdout, because the exit contract is explicit that stdout is prose for a
    person and a consumer must not parse it.  ``--events -`` would put the
    console rendering and the records in the same bytes.
    """
    directory = out / mission.key
    directory.mkdir(parents=True, exist_ok=True)
    events_path = directory / EVENTS_FILE

    child_env = dict(os.environ if env is None else env)
    # The child's durable transcript lands inside this mission's directory, so
    # the whole record of one mission — the captured stream, the store's own
    # copy, the console, the diagnostic — is one thing to copy or delete.
    child_env["JUDAIS_LOBI_RUNS"] = str(directory / "runs")

    read_fd, write_fd = os.pipe()
    argv = _argv_for(mission, template, f"fd:{write_fd}")

    stdout_path = directory / "stdout.txt"
    stderr_path = directory / "stderr.txt"
    started = time.monotonic()
    with open(stdout_path, "wb") as out_file, \
            open(stderr_path, "wb") as err_file:
        try:
            child = subprocess.Popen(
                argv, env=child_env, stdout=out_file, stderr=err_file,
                stdin=subprocess.DEVNULL, pass_fds=(write_fd,), close_fds=True)
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            raise SystemExit(f"could not spawn {argv[0]!r}: {exc}")
        os.close(write_fd)

        # A reader thread, so a child that never closes the descriptor cannot
        # keep the harness in `read()` past its own timeout.
        def _drain() -> None:
            with os.fdopen(read_fd, "rb") as pipe, \
                    open(events_path, "wb") as sink:
                while True:
                    chunk = pipe.read(65536)
                    if not chunk:
                        break
                    sink.write(chunk)

        drain = threading.Thread(target=_drain, daemon=True)
        drain.start()
        timed_out = False
        try:
            code = child.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            code = child.wait()
        drain.join(timeout=30)
    elapsed = round(time.monotonic() - started, 3)

    record = {
        "key": mission.key,
        "flag": mission.flag,
        "split": mission.split,
        "command": _recorded_argv(argv),
        "exit_code": code,
        "timed_out": timed_out,
        "wall_s": elapsed,
    }
    # Through the store owner: a reader may pick this up while the suite is
    # still running, and a half-written record of what was spawned is worse
    # than none — see `core.durable.atomic_write_text`.
    atomic_write_text(directory / "command.json", json.dumps(record, indent=2))
    return record


def run_suite(suite: Suite, template: Sequence[str], out: Path, *,
              split: str = "train",
              timeout_s: float = DEFAULT_TIMEOUT_S,
              log=print) -> Dict[str, Path]:
    """Every mission of *split*, one spawn each.  Returns key → run directory."""
    out.mkdir(parents=True, exist_ok=True)
    directories: Dict[str, Path] = {}
    for mission in missions_in(split, suite.missions):
        log(f"→ {mission.key} [{mission.flag}/{mission.split}]")
        record = run_mission(mission, template, out, timeout_s=timeout_s)
        directories[mission.key] = out / mission.key
        log(f"  exit {record['exit_code']}"
            + (" (TIMED OUT)" if record["timed_out"] else "")
            + f" in {record['wall_s']} s")
    return directories


# ── finding the runs to score ────────────────────────────────────────────────

def _runs_under(root: Path, suite: Suite, split: str) -> Dict[str, Path]:
    """Mission key → its run directory, by directory name under *root*.

    Only the keys the suite declares, so an unrelated directory beside them
    is ignored rather than scored as a mission nobody wrote.
    """
    found: Dict[str, Path] = {}
    for mission in missions_in(split, suite.missions):
        candidate = root / mission.key
        if candidate.is_dir():
            found[mission.key] = candidate
    return found


def _explicit(pairs: Sequence[str]) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--map wants key=path, got {pair!r}")
        key, path = pair.split("=", 1)
        out[key] = Path(path)
    return out


# ── the command line ─────────────────────────────────────────────────────────

def _emit(report: Report, args: argparse.Namespace, out: Optional[Path]
          ) -> None:
    text = report.to_json() if args.json else report.to_markdown()
    print(text)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out / "report.json", report.to_json())
        atomic_write_text(out / "report.md", report.to_markdown())


def _failed(report: Report) -> int:
    return sum(1 for half in report.halves.values()
               for verdict in half.verdicts if not verdict.passed)


def _split_argv(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Ours, then the mission command line after the first bare ``--``."""
    argv = list(argv)
    if "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1:]
    return argv, []


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.eval",
        description="Run a mission suite and score it from the recorded "
                    "stream.")
    subs = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--suite", default="stub",
                         help="'stub' for the in-repo suite, or the path of a "
                              "YAML/JSON suite file")
        sub.add_argument("--split", default="all",
                         choices=["train", "test", "all"],
                         help="which half; 'all' reports both, apart")
        sub.add_argument("--json", action="store_true",
                         help="print JSON instead of the Markdown table")
        sub.add_argument("--allow-failures", action="store_true",
                         help="exit 0 even when missions failed")

    runner = subs.add_parser(
        "run", help="spawn every mission, capture the stream, score it")
    common(runner)
    runner.add_argument("--out", required=True, type=Path,
                        help="directory for the run directories and report")
    runner.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="wall-clock bound on ONE mission, in seconds")

    scorer = subs.add_parser(
        "score", help="score run directories that already exist")
    common(scorer)
    scorer.add_argument("--runs", type=Path,
                        help="directory holding one sub-directory per mission "
                             "key")
    scorer.add_argument("--map", action="append", default=[], metavar="KEY=PATH",
                        help="score this key from this directory or events "
                             "file; repeatable, and beats --runs")
    scorer.add_argument("--report", type=Path,
                        help="also write report.json and report.md here")

    # Registered by the module that implements it, so the flags of the
    # matrix and the matrix itself cannot drift apart. See
    # `core.eval.measure.add_parser`.
    from core.eval.measure import add_parser as _add_measure
    _add_measure(subs, common)

    checker = subs.add_parser(
        "check", help="refuse a suite that cannot be graded")
    checker.add_argument("--suite", default="stub")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    ours, template = _split_argv(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(ours)

    try:
        suite = resolve_suite(args.suite)
    except MissionMisdeclared as exc:                 # the file is malformed
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"--suite: {exc}", file=sys.stderr)
        return 1

    # Every subcommand, not only `check`: scoring against a suite that cannot
    # be graded produces numbers nobody can compare to anything, and a `run`
    # against one spends a model on it first.
    try:
        suite.check()
    except MissionMisdeclared as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.command == "check":
        held = [m for m in suite.missions if m.split == "test"]
        share = len(held) / len(suite.missions) if suite.missions else 0.0
        print(f"suite {suite.name!r} is gradeable: {len(suite.missions)} "
              f"mission(s), {len(held)} held out ({share:.0%}), "
              f"{len({m.flag for m in suite.missions})} flag(s) captured "
              f"of {len(suite.claims)} claimed.")
        return 0

    if args.command == "run":
        if not template:
            print("run: put the mission command line after `--`, e.g. "
                  "`-- judais --provider local --mcp-stdio '…' --skill S`",
                  file=sys.stderr)
            return 2
        directories = run_suite(suite, template, args.out, split=args.split,
                                timeout_s=args.timeout)
        report = score_suite(directories, suite, args.split)
        _emit(report, args, args.out)
        return 0 if args.allow_failures or not _failed(report) else 1

    if args.command == "measure":
        from core.eval.measure import from_args
        return from_args(suite, args, template)

    runs: Dict[str, Any] = {}
    if args.runs is not None:
        runs.update(_runs_under(args.runs, suite, args.split))
    runs.update(_explicit(args.map))
    if not runs:
        print("score: nothing to score — pass --runs DIR or --map key=path",
              file=sys.stderr)
        return 2
    report = score_suite(runs, suite, args.split)
    _emit(report, args, args.report)
    return 0 if args.allow_failures or not _failed(report) else 1
