# core/eval/measure.py — run the suite over a matrix of configurations, live

"""``python -m core.eval measure`` — the release score, off a real model.

``run`` answers *how did this configuration do*.  This module answers the
question ROADMAP §2.5 actually left open, which is a **comparison**: is
``--swarm`` better than the direct loop, is ``--protocol native`` better than
``json``, and is each of the three grounding tiers shipped off by default in
0.13.0 worth turning on.  None of those is a number; each is a difference
between two runs of the same missions, and a difference is only worth
anything when everything else about the two runs was identical.

So the matrix is **data**.  :data:`MEASUREMENTS` is a tuple of
:class:`Measurement` entries, each a name plus the deltas it applies — extra
CLI flags, or one switch in the skill manifest's ``grounding:`` block — and
everything else (provider, model, tool plane, skill, the missions, the
scorer) is held still.  Adding a configuration is one entry; there is no
second place that also has to hear about it, and no branch anywhere that
knows what ``swarm`` means.

**Nothing here spawns anything.**  :func:`core.eval.run.run_suite` is the one
spawner in this package and this module calls it once per configuration, so
where the objective goes in the argv, how the stream is captured off a
descriptor, and where ``JUDAIS_LOBI_RUNS`` points have exactly one owner.
What this module adds is the loop, the manifest variants, and the table.

**Every run is recorded, and the table is reproducible from the recording.**
Each configuration's missions land under ``<out>/<name>/rep<n>/<key>/``,
which is a directory ``python -m core.eval score --runs`` reads — so the
verdicts in the table can be produced again, tomorrow, on a machine with no
GPU and no endpoint, from the bytes on disk.  ROADMAP §4 asks for exactly
that: *"the eval harness reports a score for a release, and that score is
reproducible from recorded runs on a machine without a GPU."*

**The endpoint is configuration and never code.**  This module names no
model, no host and no vendor.  It reads what the caller's spawn line and
environment say — ``--provider``, ``--model``, ``LOCAL_API_BASE`` — and puts
that in the report's header so a number can be attributed to the thing that
produced it.  See ``EVAL.md`` §12 for three worked endpoints.

**Train and test are still never blended.**  There is one table per half, as
everywhere else in this harness: a matrix that reported one figure per
configuration over both halves would be the blended number ``score.py``
refuses to print, arrived at from a different direction.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)
from urllib.parse import urlsplit, urlunsplit

from core.durable import atomic_write_text
from core.eval.run import DEFAULT_TIMEOUT_S, run_suite
from core.eval.score import Report, Verdict, score_suite
from core.eval.suite import RubricChange, Suite, missions_in

__all__ = [
    "MEASUREMENTS", "Measurement", "Matrix", "Configured", "TIER_KEYS",
    "add_parser", "measure", "manifest_variant", "spawn_line_for",
    "from_args",
]


#: The three grounding tiers 0.13.0 shipped **off**, and the only keys this
#: module ever writes into a manifest.  Each is a switch in the
#: ``grounding:`` block; what a tier then does is
#: :mod:`core.runtime.grounding`'s business and not measured here.
TIER_KEYS: Tuple[str, ...] = ("reading", "critic", "planes")


@dataclass(frozen=True)
class Measurement:
    """One row of the matrix: a name, and what makes it different.

    A configuration is a **delta against the caller's own spawn line**, not
    a command line of its own.  The provider, the model, the tool plane and
    the skill stay exactly as the caller wrote them, because those are the
    constants of the experiment; what varies is this.
    """

    #: The row's name, and the directory its runs land in.
    name: str
    #: Why this configuration is in the matrix — usually a question a
    #: default is waiting on.
    why: str = ""
    #: Extra tokens appended to the spawn line.  Every ``--token`` must be
    #: published in :data:`core.runtime.contract.CLI_FLAGS`; the suite check
    #: holds a mission's own flags to that and these are held to it by
    #: :func:`_check_flags_are_published`.
    flags: Tuple[str, ...] = ()
    #: The one grounding tier this configuration turns **on**, or ``None``
    #: for the baseline, which turns all of them off.  One at a time on
    #: purpose: two tiers on in one run measures the pair.
    tier: Optional[str] = None
    #: Capability attributes the endpoint must declare for this
    #: configuration to mean anything.  A configuration whose endpoint
    #: cannot speak it is **skipped with the note**, never run and scored:
    #: a run that silently fell back to another protocol would be recorded
    #: under this row's name as the protocol it was not running.
    needs: Tuple[str, ...] = ()


#: The matrix, as data.
#:
#: ``direct`` is the baseline and every other row is read against it: same
#: missions, same model, same plane, one thing changed.  It is also the row
#: that states what "off" means for the tiers — the manifest's own
#: ``reading``/``critic``/``planes`` switches are stripped for it, so a
#: manifest that ships a tier on cannot quietly become the baseline.
#:
#: A mission's own ``flags`` are **not** removed by any of this. The routing
#: mission is spawned ``--swarm`` because that is the defect it exists to
#: catch, and it stays that way in the ``direct`` row; what the ``swarm``
#: row changes is every OTHER mission.
MEASUREMENTS: Tuple[Measurement, ...] = (
    Measurement(
        name="direct",
        why="the baseline: the loop as a bare install runs it — no swarm, "
            "the json protocol, every grounding tier off",
    ),
    Measurement(
        name="swarm",
        flags=("--swarm",),
        why="ROADMAP §2.5: should the staged path be the default? The "
            "reference deployment's A/B said direct 10/10, swarm 9/10, and "
            "this is that A/B in-repo",
    ),
    Measurement(
        name="native",
        flags=("--protocol", "native"),
        needs=("supports_tool_calls", "supports_tool_choice_required"),
        why="ROADMAP §2.7: 'default stays json until Phase 10's harness "
            "scores the two'. The protocol_shape flag is the column it is "
            "read out of",
    ),
    Measurement(
        name="reading",
        tier="reading",
        why="0.13.0 shipped the field-misreading tier off because it spends "
            "model calls. Does it buy a verdict the mechanical checks miss, "
            "and what does it cost in tokens and wall time?",
    ),
    Measurement(
        name="planes",
        tier="planes",
        why="the plane-claim check: an answer that says it used a tool "
            "family nothing dispatched. Off by default since 0.13.0",
    ),
    Measurement(
        name="critic",
        tier="critic",
        why="the advisory second opinion asked on a bad mechanical verdict. "
            "Off by default since 0.13.0, and the one tier whose answer sits "
            "beside `grounded` rather than inside it",
    ),
)


class Unmeasurable(RuntimeError):
    """This configuration cannot be run **here**, and the reason is the news.

    Raised rather than returned so no caller can lose it: a skipped row that
    silently became a zero would read as a configuration that scored nothing,
    which is the opposite of what happened.  The reason lands in the table
    beside the row's name.
    """


# ── the spawn line, per configuration ────────────────────────────────────────

def _skill_at(template: Sequence[str]) -> Optional[int]:
    """Index of the ``--skill`` **value** in *template*, or ``None``.

    Both spellings, because a caller writes whichever their shell made
    convenient and a harness that only understood one would silently run
    every tier configuration against the unmodified manifest.
    """
    for index, token in enumerate(template):
        if token == "--skill" and index + 1 < len(template):
            return index + 1
        if token.startswith("--skill="):
            return index
    return None


def _skill_path(template: Sequence[str]) -> Optional[Path]:
    at = _skill_at(template)
    if at is None:
        return None
    token = template[at]
    if token.startswith("--skill="):
        token = token.split("=", 1)[1]
    return Path(token).expanduser()


def spawn_line_for(template: Sequence[str], measurement: Measurement,
                   skill: Optional[Path]) -> List[str]:
    """The caller's spawn line with this configuration's deltas applied.

    *skill* is the manifest variant :func:`manifest_variant` wrote, or
    ``None`` to leave the caller's ``--skill`` alone.  The flags go on the
    **end**, after everything the caller wrote, so a configuration can only
    ever add to a line and never reorder one.
    """
    argv = list(template)
    if skill is not None:
        at = _skill_at(argv)
        if at is None:                        # pragma: no cover - guarded above
            raise Unmeasurable("the spawn line has no --skill to repoint")
        argv[at] = (f"--skill={skill}" if argv[at].startswith("--skill=")
                    else str(skill))
    return argv + list(measurement.flags)


def _check_flags_are_published(measurements: Sequence[Measurement]) -> None:
    """Every matrix flag is in :data:`core.runtime.contract.CLI_FLAGS`.

    The same rule ``check_the_suite_is_gradeable`` applies to a mission's
    own flags, applied to the matrix's, and for the same reason: a
    measurement that depended on a flag this repository never promised would
    be a measurement nobody outside this checkout could repeat.
    """
    from core.runtime import contract

    unpublished = sorted({
        token for m in measurements for token in m.flags
        if token.startswith("--") and token not in contract.CLI_FLAGS})
    if unpublished:
        raise Unmeasurable(
            f"the matrix uses unpublished flag(s) {unpublished}; every "
            f"`--token` a configuration spawns with belongs in "
            f"contract.CLI_FLAGS")


# ── the manifest variant, per configuration ──────────────────────────────────

def manifest_variant(source: Path, measurement: Measurement, out: Path
                     ) -> Path:
    """Write *source* with exactly this configuration's tiers switched.

    **The tier data belongs to the manifest, and this only flips switches.**
    ``reading: true`` and ``critic: true`` are switches and nothing else, so
    the harness can write them; ``planes:`` is a *table* of which tools are
    a plane on this deployment and what an answer says when it claims one,
    which is data a framework must not invent — see
    :class:`core.runtime.grounding.PlaneGroundingCheck`.  So the ``planes``
    configuration keeps the block the manifest already declares, and is
    **skipped with a note** on a manifest that declares none.

    Every variant starts from the same place: the manifest's grounding
    block with all three of :data:`TIER_KEYS` removed.  That is what makes
    ``direct`` a baseline rather than "whatever the manifest happened to
    ship", and it is the only reason the other rows can be read as a
    difference.

    The split is :meth:`core.runtime.skills.SkillManifest._split`'s, so
    "what a manifest looks like" has one owner and a format change lands in
    one place.
    """
    from core.runtime.skills import SkillManifest

    yaml = _require_yaml()
    front, body = SkillManifest._split(source, source.read_text(
        encoding="utf-8"))
    block = front.get("skill")
    if not isinstance(block, Mapping):
        raise Unmeasurable(
            f"{source.name} has no `skill:` block, so there is no "
            f"`grounding:` to switch a tier in")
    block = dict(block)
    grounding = dict(block.get("grounding") or {})

    declared = {key: grounding[key] for key in TIER_KEYS if key in grounding}
    for key in TIER_KEYS:
        grounding.pop(key, None)

    tier = measurement.tier
    if tier == "planes":
        if not declared.get("planes"):
            raise Unmeasurable(
                f"{source.name} declares no `planes:` block. A plane is "
                f"which tools are a tool family here and what an answer "
                f"says when it claims one — data this deployment owns, and "
                f"a harness that invented one would be naming your tool "
                f"families for you")
        grounding["planes"] = declared["planes"]
    elif tier == "reading":
        grounding["reading"] = True
        # The tier reads the claim table, and `GroundingConfig.from_mapping`
        # refuses `reading: true` without it. Written here rather than asked
        # of the caller because it is not a second decision: it is what
        # `reading` costs, and a manifest that had to be edited by hand for
        # one row of a matrix is a matrix nobody runs.
        grounding["claim_table"] = True
    elif tier == "critic":
        grounding["critic"] = True
    elif tier is not None:                    # pragma: no cover - defensive
        raise Unmeasurable(f"unknown grounding tier {tier!r}")

    if grounding:
        block["grounding"] = grounding
    else:
        block.pop("grounding", None)
    front = {**front, "skill": block}

    out.parent.mkdir(parents=True, exist_ok=True)
    text = ("---\n"
            + yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
            + "---\n\n" + body + "\n")
    atomic_write_text(out, text)
    return out


def _require_yaml():
    try:
        import yaml
    except ImportError as exc:               # pragma: no cover - env dependent
        raise Unmeasurable(
            "switching a grounding tier means rewriting a skill manifest, "
            "which needs pyyaml: pip install 'judais-lobi[mission]'") from exc
    return yaml


# ── what the endpoint says it can do ─────────────────────────────────────────

def _flag_value(template: Sequence[str], flag: str) -> Optional[str]:
    for index, token in enumerate(template):
        if token == flag and index + 1 < len(template):
            return template[index + 1]
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    return None


def probe_capabilities(template: Sequence[str],
                       env: Optional[Mapping[str, str]] = None):
    """What the configured endpoint declares, or ``None`` if it cannot say.

    Built through :class:`core.unified_client.UnifiedClient`, which is the
    one place a provider name becomes a backend — asking the backend
    directly here would be a second router.  ``None`` on any failure: an
    endpoint that will not answer "what can you do" is a fact about the
    endpoint and not a reason to refuse to measure it, and a configuration
    that needs a capability nobody could confirm is run rather than
    skipped, because the CLI refuses ``--protocol native`` at its own door
    and that refusal is the honest answer.
    """
    env = os.environ if env is None else env
    provider = _flag_value(template, "--provider") or env.get("ELF_PROVIDER")
    if not provider:
        return None
    try:
        from core.unified_client import UnifiedClient
        return UnifiedClient(provider_override=provider).capabilities
    except Exception:                        # noqa: BLE001 — any failure is "cannot say"
        return None


def _cannot_speak(measurement: Measurement, capabilities: Any) -> str:
    """The note for a configuration this endpoint cannot honour, or ``""``."""
    if capabilities is None or not measurement.needs:
        return ""
    missing = [name for name in measurement.needs
               if not getattr(capabilities, name, False)]
    if not missing:
        return ""
    return ("the endpoint's capabilities declare "
            + ", ".join(f"{name}=False" for name in missing)
            + " — a run that fell back to another protocol would be recorded "
              "as the protocol it was not running")


# ── the matrix ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Configured:
    """One configuration's result: its repeats, or the reason it has none."""

    name: str
    why: str = ""
    #: One entry per repeat, oldest first.
    reports: Tuple[Report, ...] = ()
    #: The directory each repeat's runs landed in — what ``score --runs``
    #: is pointed at to produce the same verdicts again.
    directories: Tuple[Path, ...] = ()
    #: Non-empty exactly when this configuration did not run.
    skipped: str = ""
    #: The spawn line as recorded, deltas applied and credentials withheld.
    command: Tuple[str, ...] = ()

    @property
    def ran(self) -> bool:
        return bool(self.reports)


@dataclass(frozen=True)
class Matrix:
    """Every configuration, over one suite, against one endpoint.

    Carries its own header — the commit, the model, the endpoint with any
    credential taken out of it, the date, and the newest rubric changes —
    because a score with no provenance is a number somebody will quote next
    month against a different model and a different tree.
    """

    suite: str
    split: str
    configured: Tuple[Configured, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)
    rubric_changes: Tuple[RubricChange, ...] = ()
    #: Mission keys in the order they were run, per half.
    keys: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "suite": self.suite,
            "split": self.split,
            "meta": dict(self.meta),
            "keys": {half: list(keys) for half, keys in self.keys.items()},
            "rubric_changes": [dict(zip(RubricChange._fields, entry))
                               for entry in self.rubric_changes],
            "configurations": [
                {"name": c.name, "why": c.why, "skipped": c.skipped,
                 "command": list(c.command),
                 "directories": [str(p) for p in c.directories],
                 "reports": [r.as_dict() for r in c.reports]}
                for c in self.configured],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    def to_markdown(self) -> str:
        return _markdown(self)


# ── running it ───────────────────────────────────────────────────────────────

def measure(suite: Suite, template: Sequence[str], out: Path, *,
            split: str = "all",
            measurements: Sequence[Measurement] = MEASUREMENTS,
            only: Sequence[str] = (),
            repeat: int = 1,
            timeout_s: float = DEFAULT_TIMEOUT_S,
            capabilities: Any = None,
            env: Optional[Mapping[str, str]] = None,
            log=print) -> Matrix:
    """Run every configuration over *suite* and return the matrix.

    *only* narrows the suite to the named mission keys — the loop that makes
    a matrix affordable while a rubric is being read, and the reason it is a
    filter over the suite rather than a second suite.

    *capabilities* is what the endpoint declares; ``None`` asks it (see
    :func:`probe_capabilities`).  Passed in rather than always probed so a
    test can state an endpoint's answer without one existing.
    """
    _check_flags_are_published(measurements)
    env = dict(os.environ if env is None else env)
    suite = _narrowed(suite, only)
    skill = _skill_path(template)
    out.mkdir(parents=True, exist_ok=True)

    if capabilities is None:
        capabilities = probe_capabilities(template, env)

    configured: List[Configured] = []
    for measurement in measurements:
        note = _cannot_speak(measurement, capabilities)
        variant: Optional[Path] = None
        if not note:
            try:
                if skill is None and measurement.tier is not None:
                    raise Unmeasurable(
                        "the spawn line names no --skill, so there is no "
                        "grounding block to switch this tier in")
                if skill is not None:
                    variant = manifest_variant(
                        skill, measurement, out / measurement.name / "skill.md")
            except Unmeasurable as exc:
                note = str(exc)
        if note:
            log(f"— {measurement.name}: SKIPPED — {note}")
            configured.append(Configured(name=measurement.name,
                                         why=measurement.why, skipped=note))
            continue

        argv = spawn_line_for(template, measurement, variant)
        reports: List[Report] = []
        directories: List[Path] = []
        for index in range(1, max(1, int(repeat)) + 1):
            where = out / measurement.name / f"rep{index}"
            log(f"══ {measurement.name} (repeat {index}/{repeat}) → {where}")
            run_suite(suite, argv, where, split=split, timeout_s=timeout_s,
                      log=log)
            found = {m.key: where / m.key for m in missions_in(
                split, suite.missions) if (where / m.key).is_dir()}
            reports.append(score_suite(found, suite, split))
            directories.append(where)
        configured.append(Configured(
            name=measurement.name, why=measurement.why,
            reports=tuple(reports), directories=tuple(directories),
            command=tuple(_withheld(argv))))

    return Matrix(
        suite=suite.name, split=split, configured=tuple(configured),
        meta=header(template, env, repeat=repeat, timeout_s=timeout_s),
        rubric_changes=tuple(suite.rubric_changes),
        keys={half: tuple(m.key for m in missions_in(half, suite.missions))
              for half in _halves(split)})


def _narrowed(suite: Suite, only: Sequence[str]) -> Suite:
    """*suite* with only the named missions, or *suite* unchanged.

    A key nobody declared is a refusal rather than an empty run: ``--only
    the_bounary_holds`` would otherwise measure nothing and report it as a
    clean sweep.
    """
    if not only:
        return suite
    import dataclasses

    wanted = list(dict.fromkeys(only))
    unknown = [key for key in wanted if key not in suite.keys()]
    if unknown:
        raise Unmeasurable(
            f"--only names {unknown}, which this suite does not hold; it "
            f"holds {list(suite.keys())}")
    return dataclasses.replace(
        suite, missions=tuple(m for m in suite.missions if m.key in wanted))


def _halves(split: str) -> Tuple[str, ...]:
    from core.eval.suite import SPLITS
    return SPLITS if split == "all" else (split,)


def _withheld(argv: Sequence[str]) -> List[str]:
    """The spawn line as it may be written down.  See
    :func:`core.eval.run._recorded_argv`, which owns the subtraction."""
    from core.eval.run import _recorded_argv
    return _recorded_argv(argv)


# ── the header ───────────────────────────────────────────────────────────────

def scrubbed(url: str) -> str:
    """*url* with anything that could be a credential taken out.

    Userinfo and the query string both, because a key rides either — an
    endpoint written ``https://tok@host/v1`` and one written
    ``https://host/v1?key=…`` are the same mistake — and this string goes
    into a report somebody will paste into a ticket.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme:
        return url.split("?", 1)[0]
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def commit_of(root: Optional[Path] = None) -> str:
    """The tree's commit, or ``"unknown"``.

    Asked of git rather than of a version string: a measurement is of a
    *tree*, and between two releases the version says the same thing about
    forty different trees.
    """
    root = Path(__file__).resolve().parent.parent.parent if root is None \
        else root
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
    except Exception:                        # noqa: BLE001 — no git, no commit
        return "unknown"
    return done.stdout.strip() or "unknown"


def header(template: Sequence[str], env: Mapping[str, str], *,
           repeat: int = 1, timeout_s: float = DEFAULT_TIMEOUT_S
           ) -> Dict[str, Any]:
    """What produced these numbers, so they can be attributed later."""
    provider = (_flag_value(template, "--provider")
                or env.get("ELF_PROVIDER") or "")
    model = (_flag_value(template, "--model") or env.get("LOCAL_MODEL") or "")
    return {
        "commit": commit_of(),
        "date": date.today().isoformat(),
        "provider": provider,
        "model": model,
        "endpoint": scrubbed(env.get("LOCAL_API_BASE", "")),
        "repeat": int(repeat),
        "per_mission_seconds": float(timeout_s),
        "python": sys.version.split()[0],
    }


# ── the table ────────────────────────────────────────────────────────────────

#: Every column of the matrix table: its heading, and how one
#: configuration's cell is computed from its repeats' verdicts.  Data, so a
#: column is added in one place and cannot be added to the Markdown and
#: forgotten in the JSON.
_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("passed", "passed"),
    ("rate", "rate"),
    ("staged", "staged"),
    ("grounded", "grounded"),
    ("rejected", "rejected"),
    ("human", "human"),
    ("steps", "steps"),
    ("calls", "model_calls"),
    ("prompt tok", "prompt_tokens"),
    ("compl tok", "completion_tokens"),
    ("wall s", "elapsed_s"),
)

#: Which cells are a mean over missions (the rest are counts).  The names
#: are :func:`core.eval.score._kpis`' own, so a column that asked for a KPI
#: nobody records reads ``—`` in the table and is caught by the test that
#: holds these names against the scorer's.
_MEANS = ("steps", "model_calls", "prompt_tokens", "completion_tokens",
          "elapsed_s")


def columns_for(configured: Configured, half: str) -> Dict[str, Any]:
    """One row of the table, as plain numbers.

    Counts are summed over the repeats and means are the mean of the
    per-repeat means, with a spread beside them when there was more than
    one repeat.  Averaging the per-repeat means rather than pooling every
    mission keeps a repeat that ran fewer missions — a suite narrowed with
    ``--only``, a mission that timed out — from weighting the answer.
    """
    per_repeat: List[Dict[str, Any]] = []
    for report in configured.reports:
        verdicts = list(report.halves.get(half).verdicts) if \
            report.halves.get(half) is not None else []
        per_repeat.append(_one_repeat(verdicts))
    if not per_repeat:
        return {}

    row: Dict[str, Any] = {}
    for key in ("missions", "passed", "staged", "rejected", "human",
                "grounded_true", "grounded_known"):
        row[key] = sum(entry[key] for entry in per_repeat)
    row["rate"] = (round(row["passed"] / row["missions"], 3)
                   if row["missions"] else None)
    for key in _MEANS:
        values = [entry[key] for entry in per_repeat if entry[key] is not None]
        row[key] = round(statistics.fmean(values), 3) if values else None
        row[f"{key}_spread"] = (round(statistics.stdev(values), 3)
                                if len(values) > 1 else None)
    return row


def _one_repeat(verdicts: Sequence[Verdict]) -> Dict[str, Any]:
    scored = [v for v in verdicts if v.kpis]
    grounded = [v.kpis.get("grounded") for v in scored
                if v.kpis.get("grounded") is not None]
    entry: Dict[str, Any] = {
        "missions": len(verdicts),
        "passed": len([v for v in verdicts if v.passed]),
        "staged": len([v for v in scored if v.kpis.get("staged")]),
        "rejected": sum(int(v.kpis.get("reply_rejected") or 0)
                        for v in scored),
        "human": sum(int(v.kpis.get("human_interventions") or 0)
                     for v in scored),
        "grounded_true": len([g for g in grounded if g]),
        "grounded_known": len(grounded),
    }
    for key in _MEANS:
        entry[key] = _mean(v.kpis.get(key) for v in scored)
    return entry


def _mean(values: Iterable[Any]) -> Optional[float]:
    numbers = [float(v) for v in values if isinstance(v, (int, float))
               and not isinstance(v, bool)]
    return round(statistics.fmean(numbers), 3) if numbers else None


def _cell(row: Mapping[str, Any], key: str) -> str:
    if key == "passed":
        return f"{row.get('passed', 0)}/{row.get('missions', 0)}"
    if key == "rate":
        rate = row.get("rate")
        return "—" if rate is None else f"{rate:.0%}"
    if key == "grounded":
        return f"{row.get('grounded_true', 0)}/{row.get('grounded_known', 0)}"
    value = row.get(key)
    if value is None:
        return "—"
    text = f"{value:g}" if isinstance(value, float) else str(value)
    spread = row.get(f"{key}_spread")
    if spread:
        text += f" ±{spread:g}"
    return text


def _table(rows: Sequence[Sequence[str]], header_row: Sequence[str]
           ) -> List[str]:
    return ["| " + " | ".join(header_row) + " |",
            "|" + "|".join("---" for _ in header_row) + "|",
            *["| " + " | ".join(row) + " |" for row in rows]]


def _markdown(matrix: Matrix) -> str:
    meta = matrix.meta
    lines = [f"# measure — suite `{matrix.suite}`", ""]
    lines += [
        f"- **commit** `{meta.get('commit', 'unknown')}`",
        f"- **date** {meta.get('date', '')}",
        f"- **provider / model** `{meta.get('provider') or '—'}` / "
        f"`{meta.get('model') or '—'}`",
        f"- **endpoint** `{meta.get('endpoint') or '—'}`",
        f"- **repeats** {meta.get('repeat', 1)}, per-mission bound "
        f"{meta.get('per_mission_seconds')} s",
        "",
    ]
    if matrix.rubric_changes:
        newest = sorted(matrix.rubric_changes, key=lambda c: c.date,
                        reverse=True)[:3]
        lines.append("**Rubric changes** (newest first) — "
                     f"{len(matrix.rubric_changes)} in the ledger:")
        lines += [f"- `{c.date}` `{c.key}` — {c.what}" for c in newest]
        lines.append("")

    skipped = [c for c in matrix.configured if c.skipped]
    if skipped:
        lines.append("**Configurations not run**")
        lines += [f"- `{c.name}` — {c.skipped}" for c in skipped]
        lines.append("")

    ran = [c for c in matrix.configured if c.ran]
    for half in matrix.keys:
        lines.append(f"## {half}")
        lines.append("")
        lines += _table(
            [[f"`{c.name}`",
              *[_cell(columns_for(c, half), key) for _, key in _COLUMNS]]
             for c in ran],
            ["configuration", *[title for title, _ in _COLUMNS]])
        lines.append("")
        keys = matrix.keys.get(half, ())
        if keys and ran:
            lines.append(f"### {half} — per mission")
            lines.append("")
            lines += _table(
                [[f"`{c.name}`", *[_verdict_cell(c, half, key)
                                   for key in keys]] for c in ran],
                ["configuration", *keys])
            lines.append("")
        for configuration in ran:
            failures = _failures(configuration, half)
            if not failures:
                continue
            lines.append(f"### {half} — `{configuration.name}`: why they "
                         f"failed")
            lines.append("")
            lines += [f"- **{key}**: {reason}" for key, reason in failures]
            lines.append("")

    lines.append("Train and test are reported apart, always: a matrix with "
                 "one figure per configuration over both halves would be "
                 "the blended number this harness refuses to print, reached "
                 "from a different direction.")
    lines.append("")
    lines.append("Every row is reproducible without an endpoint: "
                 "`python -m core.eval score --runs <dir>` over the "
                 "directory beside it produces the same verdicts.")
    lines.append("")
    lines += ["| configuration | runs recorded in |",
              "|---|---|"]
    lines += [f"| `{c.name}` | " + ", ".join(f"`{p}`" for p in c.directories)
              + " |" for c in ran]
    lines.append("")
    lines.append("The spawn line each row ran, with `--mcp-url` and "
                 "`--mcp-stdio` values withheld — either can carry a token "
                 "and a report outlives the run:")
    lines.append("")
    for configuration in ran:
        lines.append(f"- `{configuration.name}`: "
                     + " ".join(configuration.command))
    return "\n".join(lines)


def _verdict_cell(configured: Configured, half: str, key: str) -> str:
    """``PASS``/``FAIL`` for one mission, or ``n/m`` over several repeats."""
    seen = [v for report in configured.reports
            for v in (report.halves[half].verdicts
                      if half in report.halves else ())
            if v.key == key]
    if not seen:
        return "—"
    passed = len([v for v in seen if v.passed])
    if len(seen) == 1:
        return "PASS" if passed else "FAIL"
    return f"{passed}/{len(seen)}"


def _failures(configured: Configured, half: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for report in configured.reports:
        for verdict in (report.halves[half].verdicts
                        if half in report.halves else ()):
            if not verdict.passed:
                out.append((verdict.key, "; ".join(verdict.reasons)))
    return out


# ── the command line ─────────────────────────────────────────────────────────

def add_parser(subs, common) -> argparse.ArgumentParser:
    """Register ``measure`` on :func:`core.eval.run._parser`'s subparsers.

    Registered from here rather than written out in ``run.py`` so the
    subcommand and the thing it runs stay in one file: a flag added to the
    matrix without a parser to read it is the mismatch this arrangement
    makes impossible.
    """
    parser = subs.add_parser(
        "measure",
        help="run the suite LIVE over a matrix of configurations and report "
             "a table")
    common(parser)
    parser.add_argument("--out", required=True, type=Path,
                        help="directory for every configuration's run "
                             "directories; `score --runs <out>/<name>/rep1` "
                             "reproduces one row")
    parser.add_argument("--report", type=Path, metavar="PATH",
                        help="write the table here as Markdown, and the same "
                             "matrix as JSON beside it")
    parser.add_argument("--per-mission-seconds", type=float,
                        default=DEFAULT_TIMEOUT_S,
                        help="wall-clock bound on ONE mission (default 600)")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run the whole matrix N times; means are "
                             "reported with a spread when N > 1")
    parser.add_argument("--only", action="append", default=[], metavar="KEY",
                        help="measure only this mission; repeatable")
    parser.add_argument("--config", action="append", default=[],
                        metavar="NAME",
                        help="measure only this configuration; repeatable, "
                             f"one of {[m.name for m in MEASUREMENTS]}")
    return parser


def from_args(suite: Suite, args: argparse.Namespace,
              template: Sequence[str]) -> int:
    """``measure`` as :func:`core.eval.run.main` reaches it."""
    if not template:
        print("measure: put the mission command line after `--`, e.g. "
              "`-- judais --provider local --mcp-stdio '…' --skill S`",
              file=sys.stderr)
        return 2

    chosen = MEASUREMENTS
    if args.config:
        by_name = {m.name: m for m in MEASUREMENTS}
        unknown = [name for name in args.config if name not in by_name]
        if unknown:
            print(f"--config names {unknown}; the matrix holds "
                  f"{list(by_name)}", file=sys.stderr)
            return 2
        chosen = tuple(by_name[name] for name in dict.fromkeys(args.config))

    try:
        matrix = measure(
            suite, template, args.out, split=args.split, measurements=chosen,
            only=args.only, repeat=args.repeat,
            timeout_s=args.per_mission_seconds)
    except Unmeasurable as exc:
        print(f"measure: {exc}", file=sys.stderr)
        return 2

    text = matrix.to_json() if args.json else matrix.to_markdown()
    print(text)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.report, matrix.to_markdown())
        atomic_write_text(args.report.with_suffix(".json"), matrix.to_json())
    atomic_write_text(args.out / "matrix.json", matrix.to_json())

    failed = sum(1 for c in matrix.configured for report in c.reports
                 for half in report.halves.values()
                 for verdict in half.verdicts if not verdict.passed)
    return 0 if args.allow_failures or not failed else 1
