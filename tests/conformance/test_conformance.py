# tests/conformance/test_conformance.py — a platform's conformance kit
#
# ONE OF TWO FILES A PLATFORM COPIES. Copy this and `conftest.py` into your own
# test directory, edit the ONE dict below, and you have a test that goes red
# the day judais-lobi's wire contract stops being the one you integrated
# against. See `README.md` beside this file, and `PLATFORMS.md` §10.

"""Everything this platform reads off the mission stream, held against the
harness's own declaration of what it emits.

**Why a copy and not an import.**  The thing being tested is a platform's
*restatement* of the contract — the field names its bridge writes as literals
because a served tier cannot import an agent framework, the flags its spawn
line passes, the outcome words it branches on.  A restatement with a test is a
duplication; a restatement without one is a divergence waiting for a deploy.
The reference deployment shipped one of the second kind: a bridge that read
`record.get("audit_ref")`, a harness that renamed nothing yet, and no test
anywhere comparing the two.  A renamed field is silent on the consumer's side
— `get` returns ``None`` and the turn renders with the content simply gone.

**What it costs to run: nothing.**  No model, no API key, no MCP server, no
GPU.  The spawn below is a ``--replay`` of a run that was already recorded, so
the real loop, the real grounding validator and the real emitters run with the
replies served off disk by ordinal.  A platform that keeps its run directories
(``JUDAIS_LOBI_RUNS``) already has everything this needs.

**Four kinds of drift, and this file catches all four:**

1. an event the harness declares that this platform has no branch for —
   harmless today (an unknown record is dropped) and only harmless because
   somebody decided so, which is what :data:`CONFORMANCE` writes down;
2. a field this platform reads that the harness no longer declares — the
   dangerous one, and the one that renders silently wrong;
3. a flag or an environment variable the spawn line uses that has left the
   published surface;
4. a schema version bump, which is the harness saying outright that a
   consumer has to look.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pytest

# ─────────────────────────────────────────────────────────────────────────────
#  THE ONE DICT. Everything a platform edits is here and nowhere else.
#
#  What is below is judais-lobi's own copy, so `reads` names EVERY event with
#  EVERY field — required and optional — and the repository's
#  `tests/test_conformance_kit.py` asserts that it is exactly the contract, so
#  this template cannot quietly fall behind the thing it is a template for.
#
#  YOUR copy should be SHORTER. List only what your bridge actually reads: an
#  event you have no branch for does not belong here, and neither does a field
#  you never index. A conformance test that claims to read everything is a
#  conformance test that will go red for a reason that is not yours.
# ─────────────────────────────────────────────────────────────────────────────

CONFORMANCE: Dict[str, Any] = {

    # The release this file was written against, as the version `pip` reports
    # — e.g. `"0.15.0"`. `None` means "there is nothing to pin": this copy IS
    # the harness. A platform sets it, and normally reads it out of whatever
    # one file already holds the pin rather than typing it twice.
    "pin": None,

    # `contract.SCHEMA_VERSION` at that release. THE load-bearing assertion:
    # the harness bumps this exactly when a consumer has to change, so a red
    # line here is the harness telling you to read the changelog.
    "schema_version": 1,

    # Every event this platform has a branch for, and every field it takes off
    # one. Required and optional together — "declared" is what is checked, and
    # an optional field a bridge reads with a default is still a field the
    # harness has to go on declaring.
    #
    # `branch` is on every one of them, because `contract.COMMON_OPTIONAL`
    # is: it says which child run emitted a record on a turn that has
    # children, and a platform that ignores it reads one correctly-ordered
    # sequence, which is what it always read.
    "reads": {
        "mission_started": ("schema_version", "objective", "catalogue",
                            "gated", "max_steps", "history",
                            "sandbox", "profile", "audit_ref", "run_id",
                            "protocol", "granted", "branch"),
        "step_started": ("index", "plan", "compacted", "resumed", "injected",
                         "catalogue", "review", "artifacts", "branch"),
        "reply_rejected": ("index", "problem", "tool", "usage", "branch"),
        "tool_call": ("index", "tool", "arguments", "usage", "call",
                      "branch"),
        "tool_result": ("index", "tool", "arguments", "ok", "exit_code",
                        "output", "error", "handle", "truncated", "call",
                        "branch"),
        "gate_requested": ("index", "tool", "arguments", "reason",
                           "approval_id", "branch"),
        "answer_delta": ("index", "part", "text", "branch"),
        "answer": ("text", "outcome", "usage", "branch"),
        "grounding": ("ran", "grounded", "verified", "repairs", "repairing",
                      "caveat", "unsupported", "silent", "uncited", "checks",
                      "branch"),
        "mission_finished": ("outcome", "steps", "max_steps",
                             "usage", "budget", "reason", "elapsed_s",
                             "branch"),
    },

    # The flags this platform's spawn line passes. Mission mode is a closed
    # surface (`contract.CLI_FLAGS`); everything else in `--help` is a
    # person's surface and may move between releases, so a spawn line that
    # reaches for one of those is a spawn line that will break quietly.
    "flags": ("--mission", "--events", "--control", "--mcp-url", "--mcp-stdio",
              "--mcp-token", "--mission-steps", "--mission-seconds",
              "--provider", "--model", "--profile", "--unsandboxed", "--skill",
              "--swarm", "--history", "--gate-tool", "--approval", "--resume",
              "--temperature", "--top-p", "--seed", "--protocol",
              "--no-stream", "--gate-wait", "--replay", "--grant",
              "--campaign", "--campaign-plan"),

    # The environment this platform exports into the child.
    "env": ("MCP_TOKEN", "MCP_CLIENT_NAME", "MCP_URL", "MCP_STDIO",
            "ELF_PERSONALITY", "TAI_PERSONALITY", "LOCAL_API_BASE",
            "LOCAL_MODEL", "MISSION_SKILL", "MISSION_SWARM", "MISSION_EVENTS",
            "MISSION_HISTORY", "MISSION_APPROVAL", "MISSION_SECONDS",
            "MISSION_RESUME", "MISSION_REPLAY", "MISSION_PROTOCOL",
            "MISSION_STREAM", "MISSION_CONTROL", "MISSION_GATE_WAIT",
            "JUDAIS_LOBI_PROFILE", "JUDAIS_LOBI_SANDBOX", "JUDAIS_LOBI_AUDIT",
            "JUDAIS_LOBI_RUNS", "JUDAIS_LOBI_APPROVALS",
            "JUDAIS_LOBI_MEMORY", "JUDAIS_LOBI_MEMORY_PRINCIPAL"),

    # The outcome words this platform branches on. A word it has no branch for
    # renders as whatever its default arm does, which for `budget_exhausted`
    # was once "the agent stopped dead".
    "outcomes": ("answered", "answered_with_caveat", "awaiting_approval",
                 "budget_exhausted", "incomplete"),

    # The clauses of the exit contract this platform builds behaviour on —
    # `contract.EXIT_CONTRACT`'s keys. Each is a promise about the process
    # rather than about a record: what stdout is for, what silence means, what
    # SIGTERM does, where the diagnostic is.
    "exit_clauses": ("stdout", "events", "control", "silence", "finished",
                     "sigterm", "diagnostic"),

    # ONE recorded run to replay, which is how this kit proves the records are
    # the shape the table above claims without needing a model or a server.
    #
    #   `spawn`   — how this platform starts the harness. `{python}` is the
    #               interpreter running the tests and `{home}` the located
    #               checkout; an installed release is simply `("judais",)`.
    #   `store`   — a directory holding run directories, relative to `{home}`
    #               or absolute. Any run your platform has archived will do.
    #   `run_id`  — the directory inside it to replay.
    #
    # Set `run_id` to `None` and the spawn test skips, saying so. That is the
    # one thing in this file worth leaving unset for a while — and the one
    # thing that makes this kit more than a comparison of two lists.
    "spawn": {
        "argv": ("{python}", "{home}/main.py", "judais"),
        "store": "tests/fixtures/runs",
        "run_id": "run_corpusjson-0001",
        "timeout_s": 300,
    },
}


# ── two pure helpers, so the interesting branches are testable ───────────────

def installed_version() -> Optional[str]:
    """What `pip` reports for the harness, or ``None`` when it is a checkout
    nobody installed."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:                       # pragma: no cover - 3.7 and down
        return None
    try:
        return version("judais-lobi")
    except PackageNotFoundError:
        return None


def pin_mismatch(pin: Optional[str], installed: Optional[str]) -> Optional[str]:
    """The sentence to fail with, or ``None`` when there is nothing to say.

    Three outcomes rather than two, because "nothing is pinned" and "the pin
    disagrees" are different facts and only one of them is a defect:

    * *pin* is ``None`` — this copy is the harness's own, or the platform has
      not pinned yet. Nothing to compare.
    * nothing is installed — a checkout on a developer's machine. The version
      the tests ran against is the tree, and `pip` has no opinion.
    * both known and different — the pin says one release and the environment
      holds another, which means every other assertion in this file was made
      against code the deployment will not run.
    """
    if pin is None or installed is None:
        return None
    if pin == installed:
        return None
    return (f"this conformance kit was written against judais-lobi {pin} and "
            f"the installed distribution is {installed}. Either the pin moved "
            f"and this file did not, or the environment is not the one the "
            f"pin names — and until they agree, every other assertion here "
            f"was made against code that will not run.")


def _spawn_argv(template: Sequence[str], home: Optional[Path]) -> list:
    return [token.format(python=sys.executable, home=str(home or ""))
            for token in template]


# ── the comparison ───────────────────────────────────────────────────────────

READS = CONFORMANCE["reads"]
_FIELD_CASES = [(event, field)
                for event, fields in READS.items() for field in fields]


class TestTheHarnessStillDeclaresWhatThisPlatformReads:

    def test_the_schema_version_is_the_one_this_file_was_written_against(
            self, contract):
        """The harness bumps this exactly when a consumer has to change, so
        this is the assertion the other ones are a detail of."""
        assert contract.SCHEMA_VERSION == CONFORMANCE["schema_version"], (
            f"judais-lobi is at SCHEMA_VERSION {contract.SCHEMA_VERSION} and "
            f"this kit was written for {CONFORMANCE['schema_version']}. That "
            f"is a BREAKING change by the harness's own compatibility rule — "
            f"a renamed, removed or redefined required field — and it is "
            f"saying so at import, which is the cheap moment to find out.")

    @pytest.mark.parametrize("event", sorted(READS))
    def test_every_event_it_branches_on_is_one_the_harness_emits(
            self, contract, event):
        assert event in contract.EVENTS, (
            f"this platform has a branch for {event!r} and the harness no "
            f"longer declares it: {sorted(contract.EVENTS)}")

    @pytest.mark.parametrize("event,field", _FIELD_CASES)
    def test_every_field_it_reads_is_one_the_harness_declares(
            self, contract, event, field):
        """Declared means required OR optional. A field read with a default is
        still a field the harness has to go on emitting — this is the drift
        that renders as content silently missing rather than as an error."""
        declared = (set(contract.FIELDS.get(event, ()))
                    | set(contract.OPTIONAL.get(event, ())))
        assert field in declared, (
            f"{event}.{field} is read here and the harness declares "
            f"{sorted(declared)}")

    @pytest.mark.parametrize("flag", CONFORMANCE["flags"])
    def test_every_flag_the_spawn_line_uses_is_published(self, contract, flag):
        assert flag in contract.CLI_FLAGS, (
            f"{flag} is on this platform's spawn line and is not in "
            f"CLI_FLAGS, so it is a person's surface and may move")

    @pytest.mark.parametrize("name", CONFORMANCE["env"])
    def test_every_variable_it_exports_is_published(self, contract, name):
        assert name in contract.ENV_VARS, (
            f"{name} is exported into the child and is not in ENV_VARS")

    @pytest.mark.parametrize("outcome", CONFORMANCE["outcomes"])
    def test_every_outcome_it_branches_on_is_one_a_mission_can_say(
            self, contract, outcome):
        assert outcome in contract.OUTCOMES, (
            f"{outcome!r} is branched on here and is not in OUTCOMES")

    @pytest.mark.parametrize("clause", CONFORMANCE["exit_clauses"])
    def test_every_exit_clause_it_relies_on_is_still_stated(
            self, contract, clause):
        assert clause in contract.EXIT_CONTRACT, (
            f"{clause!r} is a promise this platform builds on and the exit "
            f"contract no longer states it: {sorted(contract.EXIT_CONTRACT)}")

    def test_the_pin_and_the_installed_release_agree(self):
        problem = pin_mismatch(CONFORMANCE["pin"], installed_version())
        assert problem is None, problem


class TestARealStreamIsTheShapeTheTableClaims:
    """The other half. Comparing two lists says the two repositories agree
    about the *names*; it says nothing about whether a mission emits records
    of that shape. So one is run.

    A ``--replay`` rather than a live mission: the loop, the emitters, the
    grounding validator and the durable store are all real, and the model's
    replies and the tool results come off a recording by ordinal, so nothing
    is dialled and no credential is needed. The exit contract's own promises
    are asserted here too, because a stream is the only place they are true.
    """

    @pytest.fixture(scope="class")
    def records(self, contract, harness_home):
        spawn = CONFORMANCE["spawn"]
        if not spawn.get("run_id"):
            pytest.skip("CONFORMANCE['spawn']['run_id'] is unset: point it at "
                        "any run directory this platform has archived and "
                        "this becomes a real mission rather than a comparison "
                        "of two lists")
        store = Path(spawn["store"])
        if not store.is_absolute():
            if harness_home is None:
                pytest.skip("CONFORMANCE['spawn']['store'] is relative and no "
                            "checkout was located; make it absolute")
            store = harness_home / store
        source = store / spawn["run_id"]
        assert source.is_dir(), f"no recorded run at {source}"

        work = Path(tempfile.mkdtemp(prefix="judais-lobi-conformance-"))
        try:
            runs = work / "runs"
            runs.mkdir()
            # A copy, because a replay writes a NEW run directory beside the
            # one it replays and an archive is not ours to grow.
            shutil.copytree(source, runs / spawn["run_id"])

            env = dict(os.environ)
            env["JUDAIS_LOBI_RUNS"] = str(runs)
            env["JUDAIS_LOBI_AUDIT"] = "off"
            # Whatever persona this machine's dotfiles point at is not what is
            # under test, and a personality file needing an extra nobody
            # installed would fail this for a reason that is not the contract.
            for name in ("ELF_PERSONALITY", "TAI_PERSONALITY"):
                env.pop(name, None)

            read_fd, write_fd = os.pipe()
            argv = [*_spawn_argv(spawn["argv"], harness_home),
                    "--mission", "--replay", spawn["run_id"],
                    "--events", f"fd:{write_fd}"]
            child = subprocess.Popen(
                argv, cwd=work, env=env, pass_fds=(write_fd,),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            os.close(write_fd)
            with os.fdopen(read_fd, "rb") as pipe:
                stream = pipe.read().decode("utf-8")
            _, err = child.communicate(timeout=spawn["timeout_s"])
            assert child.returncode == 0, (
                f"the replay exited {child.returncode}. The exit contract "
                f"says the tail of stderr is what to show:\n"
                f"{err.decode('utf-8', 'replace')[-2000:]}")
            yield [json.loads(line) for line in stream.splitlines() if line.strip()]
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_mission_emitted_something(self, records):
        """Zero events is a failure, by the exit contract's own `silence`
        clause — never an empty answer."""
        assert records, ("the mission emitted no records at all, which the "
                         "exit contract says a consumer must report as a "
                         "failure rather than render as a blank reply")

    def test_every_record_conforms(self, contract, records):
        problems = []
        for record in records:
            problems += [f"{record.get('event')}: {problem}"
                         for problem in contract.conforms(record)]
        assert problems == []

    def test_the_stream_opens_with_the_posture(self, contract, records):
        assert records[0]["event"] == contract.MISSION_STARTED
        assert records[0]["schema_version"] == contract.SCHEMA_VERSION

    def test_the_stream_closes_with_the_record_that_says_it_is_over(
            self, contract, records):
        """`mission_finished` comes out of a `finally`. A stream that simply
        stops is indistinguishable from an agent that is thinking, which is a
        pane spinning forever."""
        assert records[-1]["event"] == contract.MISSION_FINISHED
        assert records[-1]["outcome"] in contract.OUTCOMES

    def test_nothing_on_the_wire_is_an_event_this_platform_never_heard_of(
            self, records):
        """The harmless direction, asserted anyway so that "no opinion" is a
        decision somebody made rather than a frame nobody noticed. A platform
        that means to drop unknown records should keep this and read the
        failure as a prompt to add a branch — or to widen `reads`."""
        unknown = {record["event"] for record in records} - set(READS)
        assert not unknown, (
            f"the harness emitted {sorted(unknown)}, which this platform has "
            f"no branch for. Dropping them is fine and is what the "
            f"compatibility rule expects — decide it here, on purpose.")
