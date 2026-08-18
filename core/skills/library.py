# core/skills/library.py — the mission packs this framework ships, as data

"""A **mission pack** is a directory, and this module is the only thing
that knows its shape.

``ROADMAP.md`` §2.6b: *"The unit shipped is a mission pack: a directory
holding ``SKILL.md``, the tools it needs, workflow templates, campaign
plans, and its own eval suite — loaded by name, versioned as data, scored
by ``core.eval live``.  'Any mission set' means: write a pack."*  This is
that loader, and everything it knows is a filename::

    core/skills/library/<name>/
        SKILL.md        the manifest — REQUIRED
        missions.yaml   the pack's own eval suite — REQUIRED
        README.md       what it does, its closed set, its profile — REQUIRED
        fixtures/       data the missions run against — optional
        templates/      task templates (a `workflow:` naming the roles) —
                        optional, and a documented placeholder until the
                        campaign lane lands

**One owner per file.**  Nothing here parses a manifest:
:func:`core.runtime.skills.load_skill` does, and it is the only thing that
ever has.  Nothing here parses a suite: :func:`core.eval.suite.load_suite`
does.  This module answers exactly one question — *which files are this
pack's, and where are they* — and hands each to its owner.  A second
manifest parser living in a "pack loader" is how a closed set comes to
mean one thing to ``--skill`` and another to the eval harness.

**Package data, not a package.**  ``core/skills/library/<name>/`` carries
no ``__init__.py``: the packs are content, they ship in the wheel as
``package_data`` (see ``setup.py``), and the wheel's top-level set stays
``{core, judais, lobi}``.  Everything here reads them through
:mod:`importlib.resources`, so a pack is found the same way in a source
checkout and in an installed wheel.

**The name of this module and the name of that directory are the same
word on purpose, and it is the one sharp edge here.**  ``library.py`` is a
module and ``library/`` is a directory with no ``__init__.py``, so the
import system resolves ``core.skills.library`` to this file and the
directory is reachable only as data.  That is checked by a test rather
than assumed, because the day somebody drops an ``__init__.py`` into
``library/`` this module becomes unreachable and every pack with it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from core.runtime.skills import SkillManifest, SkillManifestError, load_skill

__all__ = [
    "LIBRARY", "MANIFEST_FILE", "MISSIONS_FILE", "README_FILE",
    "FIXTURES_DIR", "TEMPLATES_DIR", "Pack", "PackError",
    "packs", "load", "resolve", "library_root",
]

#: The directory under this package that holds the packs.
LIBRARY = "library"

#: The four names a pack is made of.  Written once here because three
#: surfaces read them — this loader, the packaging patterns in
#: ``setup.py``/``MANIFEST.in``, and the tests that hold every pack to the
#: layout — and a fourth spelling of ``SKILL.md`` is a pack that ships
#: without its manifest.
MANIFEST_FILE = "SKILL.md"
MISSIONS_FILE = "missions.yaml"
README_FILE = "README.md"
FIXTURES_DIR = "fixtures"
TEMPLATES_DIR = "templates"


class PackError(SkillManifestError):
    """A pack could not be loaded, naming the packs that exist.

    A subclass of :class:`~core.runtime.skills.SkillManifestError` so that
    every caller which already refuses a bad ``--skill`` — ``core/cli.py``'s
    ``_load_skill`` turns exactly that exception into a ``SystemExit`` —
    refuses a bad pack name in the same sentence, without growing a second
    ``except`` clause for a second exception that means the same thing.
    """


def library_root() -> Path:
    """The packs directory as a real path on this filesystem.

    ``importlib.resources`` so an installed wheel answers the same as a
    source checkout.  A zip-imported install would need
    :func:`importlib.resources.as_file` around every read; that is the
    case :meth:`Pack.stage_fixtures` covers, and the rest of this module
    is content with a directory because a wheel installs unpacked.
    """
    return Path(str(files("core.skills").joinpath(LIBRARY)))


def packs() -> Tuple[str, ...]:
    """Every installed pack's name, sorted.

    A directory under :data:`LIBRARY` counts as a pack when it holds a
    :data:`MANIFEST_FILE`, and not merely by existing: a half-written pack
    directory, or the ``__pycache__`` a stray import would leave, is not
    something ``--skill <name>`` should offer.
    """
    root = library_root()
    if not root.is_dir():
        return ()
    return tuple(sorted(
        child.name for child in root.iterdir()
        if child.is_dir() and (child / MANIFEST_FILE).is_file()
    ))


@dataclass(frozen=True)
class Pack:
    """One loaded mission pack: its manifest, its suite, its data.

    Frozen for the reason :class:`~core.runtime.skills.SkillManifest` is:
    a pack is read once and then quoted, and a mission that could edit the
    closed set it is running under is not operating under one.
    """

    name: str
    #: The pack directory itself.
    root: Path
    #: ``SKILL.md``, parsed by its one owner.
    manifest: SkillManifest
    #: ``README.md``, verbatim.  Prose for a person, never for a model —
    #: what the model is told is the manifest and only the manifest.
    readme: str
    #: ``missions.yaml``.  A path and not a loaded suite: loading it costs
    #: pyyaml and a gradeability check, and a caller that only wants the
    #: closed set should not pay for either.  See :meth:`suite`.
    missions_file: Path
    #: ``fixtures/``, or ``None`` for a pack whose missions need no data.
    fixtures: Optional[Path] = None
    #: Every ``templates/*.yaml``, sorted.  See ``templates/README`` in a
    #: pack for what one is and what still has to be built to run it.
    templates: Tuple[Path, ...] = ()

    # ── the parts a caller asks for ─────────────────────────────────────

    @property
    def tools(self) -> Tuple[str, ...]:
        """The pack's closed set, markers stripped — the manifest's."""
        return self.manifest.allowed_tools

    def suite(self, *, check: bool = True) -> Any:
        """This pack's eval suite, through :func:`core.eval.suite.load_suite`.

        *check* runs :func:`check_pack_suite` — core.eval's own
        gradeability check, against the flags the suite file itself
        claims, plus the one rule that is the pack's own (every tool a
        mission names is in the pack's closed set).
        """
        from core.eval.suite import load_suite

        suite = load_suite(self.missions_file, check=False)
        if check:
            check_pack_suite(suite, self)
        return suite

    def stage_fixtures(self, destination) -> Path:
        """Copy this pack's ``fixtures/`` into *destination* and return it.

        **A mission runs against a copy, never against the installed
        pack.**  Two reasons, and the second is the one that matters: a
        sandboxed run binds its working directory read-WRITE, so a mission
        told to write a report beside its data would be writing inside
        ``site-packages``; and a pack read out of a zip-imported install
        has no directory to bind at all.  Staging answers both, and it is
        why the missions name their files bare (``sales.csv``) rather than
        carrying a path that only exists on the machine that wrote them.

        Returns *destination*, which is created if it does not exist.  A
        pack with no fixtures stages nothing and still returns it, so a
        caller does not branch on which kind of pack it holds.
        """
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        if self.fixtures is None:
            return target
        source = files("core.skills").joinpath(
            LIBRARY, self.name, FIXTURES_DIR)
        with as_file(source) as directory:
            for child in sorted(Path(directory).iterdir()):
                if child.is_file():
                    shutil.copy2(child, target / child.name)
        return target


def load(name: str) -> Pack:
    """One pack by name, or a refusal naming the packs that exist.

    Every required file is checked here and reported **together**: a pack
    missing its suite and its README is one edit, and a refusal that
    arrives one file at a time is fixed one file at a time.  That is the
    same rule :class:`~core.runtime.skills.SkillManifest` refuses by.
    """
    wanted = str(name or "").strip()
    root = library_root() / wanted
    if not wanted or "/" in wanted or "\\" in wanted or not root.is_dir():
        raise PackError(
            f"no mission pack named {name!r}. This install ships "
            + (", ".join(packs()) or "(none)")
            + ". A pack is a directory of "
            + f"{library_root()}; a path to a {MANIFEST_FILE} works too."
        )

    problems: List[str] = []
    manifest_path = root / MANIFEST_FILE
    missions_path = root / MISSIONS_FILE
    readme_path = root / README_FILE
    for path, why in (
        (manifest_path, "the manifest: the closed set, the policy and the "
                        "grounding grammar a mission runs under"),
        (missions_path, "the pack's own eval suite, so `core.eval` can score "
                        "it — a capability nobody measures is a claim"),
        (readme_path, "what this pack does, its closed set, the profile it "
                      "needs and one command that runs it"),
    ):
        if not path.is_file():
            problems.append(f"{path.name} is missing — {why}")
    if problems:
        raise PackError(
            f"the mission pack {wanted!r} at {root} is incomplete:\n  - "
            + "\n  - ".join(problems)
        )

    fixtures = root / FIXTURES_DIR
    templates = root / TEMPLATES_DIR
    return Pack(
        name=wanted,
        root=root,
        manifest=load_skill(manifest_path),
        readme=readme_path.read_text(encoding="utf-8"),
        missions_file=missions_path,
        fixtures=fixtures if fixtures.is_dir() else None,
        templates=tuple(sorted(templates.glob("*.yaml")))
        if templates.is_dir() else (),
    )


def resolve(arg) -> SkillManifest:
    """A ``--skill`` argument as a manifest: a path, or a pack's name.

    **A path that exists wins**, and the order is the whole compatibility
    promise: ``--skill`` took a path before packs existed, every platform's
    own manifest is a path, and a name that silently beat a real file would
    change what an existing command line does.  Only when nothing is at
    that path is the argument read as a pack name.

    The consequence, stated rather than discovered: in a directory that
    happens to hold a folder called ``analyst``, ``--skill analyst`` loads
    that folder.  It is a path, it exists, and the caller is looking at it.

    Neither a path nor a pack is a refusal that names both roads out.
    """
    text = str(arg or "").strip()
    if not text:
        raise PackError(
            "no skill named. `--skill` takes a SKILL.md (or a directory "
            "holding one), or the name of a mission pack this install "
            "ships: " + (", ".join(packs()) or "(none)")
        )

    candidate = Path(text).expanduser()
    if candidate.exists():
        return load_skill(candidate)

    installed = packs()
    if text in installed:
        return load(text).manifest

    raise PackError(
        f"{text!r} is neither a file on this host nor a mission pack this "
        f"install ships. Packs: " + (", ".join(installed) or "(none)")
        + f". For a manifest of your own, give the path to its "
          f"{MANIFEST_FILE} (or to the directory holding one)."
    )


# ── the pack's suite, checked ────────────────────────────────────────────

def check_pack_suite(suite: Any, pack: Optional[Pack] = None) -> None:
    """:func:`~core.eval.suite.check_the_suite_is_gradeable`, plus the one
    rule that is the pack's own.

    **Flag coverage is the suite's own declaration and no longer this
    function's business.**  A pack measures a *capability*, not the whole
    harness, and the coverage rule — every flag captured by some mission —
    is right for the one suite that grades everything and wrong for a pack:
    demanding that an analyst suite also capture ``state`` and
    ``submission`` produces two missions written to satisfy a checker.
    That used to be handled here, by rebinding ``core.eval.suite.FLAGS``
    around the call to the set the missions happened to capture — a module
    global written from an adapter, and a coverage rule a suite could
    never fail because it was derived from the same missions it graded.
    ``core/eval/`` now takes the declaration itself: a suite names the
    flags it claims (``flags:``, defaulting to all of ``FLAGS``) and is
    held to those, so a pack that drops a mission is refused rather than
    quietly measuring one capability fewer.

    What is left is **every rule being core.eval's own code**: the split
    band, the held-out floor, no prompt naming a tool, no prompt naming
    data the plane does not hold, ``expects_outcome`` a word
    ``contract.OUTCOMES`` can say, every extra flag published in
    ``contract.CLI_FLAGS``, the rubric ledger.  A second copy of those
    rules living here is exactly the "second emitter drifts" failure this
    repository keeps paying for.

    **The pack's own rule**: every tool a mission names, and every tool the
    suite declares it serves, is in the pack's closed set.  That is the
    check no generic suite can make, because only a pack knows what its
    skill is allowed to call — and a mission expecting a tool the manifest
    withholds is a mission that can never pass.
    """
    from core.eval.suite import check_the_suite_is_gradeable

    check_the_suite_is_gradeable(suite)

    if pack is not None:
        _check_the_missions_stay_inside_the_closed_set(suite, pack)


def _check_the_missions_stay_inside_the_closed_set(suite: Any,
                                                   pack: Pack) -> None:
    """Every tool named by the suite is one the pack's skill may call."""
    from core.eval.suite import MissionMisdeclared
    from core.tools.descriptors import same_tool

    closed: Sequence[str] = pack.tools
    problems: List[str] = []

    def _inside(tool: str) -> bool:
        # The store tool is the mission's own and is added to every run by
        # `MissionRunner.offered`, so it is never in a closed set and is
        # always callable. Named here rather than left to be discovered as
        # a spurious refusal in the one pack whose suite uses it.
        from core.runtime.results import RESULT_TOOL

        return (same_tool(tool, RESULT_TOOL)
                or any(same_tool(tool, entry) for entry in closed))

    for tool in suite.tools:
        if not _inside(tool):
            problems.append(
                f"the suite says its plane serves {tool!r}, which the "
                f"{pack.name} skill's closed set does not name "
                f"({list(closed)})")
    for mission in suite.missions:
        for tool in (*mission.expects_tools, *mission.forbids_tools):
            if not _inside(tool):
                problems.append(
                    f"{suite.name}[{mission.key!r}]: names the tool "
                    f"{tool!r}, which the {pack.name} skill's closed set "
                    f"does not name ({list(closed)}). A mission expecting a "
                    f"tool the manifest withholds can never pass")
    if problems:
        raise MissionMisdeclared(
            f"the pack {pack.name!r} and its suite disagree about the "
            f"plane:\n  - " + "\n  - ".join(problems))
