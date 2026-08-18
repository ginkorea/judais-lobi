# core/skills/__init__.py — the mission packs this framework ships

"""First-party skills, as data.

``import core.skills`` and ask it three things::

    core.skills.packs()          # ('analyst', 'coding', 'research')
    core.skills.load("analyst")  # -> Pack: manifest, suite, fixtures, README
    core.skills.resolve(arg)     # a path OR a pack name -> SkillManifest

:mod:`core.skills.library` is where all of it lives and where the layout
is documented; this module is the name a caller imports.  The one seam
into the rest of the framework is
:func:`core.runtime.skills.resolve_skill`, which delegates to
:func:`resolve` so that ``--skill`` takes a pack name without ``core/cli.py``
learning what a pack is.
"""

from core.skills.library import (  # noqa: F401
    FIXTURES_DIR, LIBRARY, MANIFEST_FILE, MISSIONS_FILE, README_FILE,
    TEMPLATES_DIR, Pack, PackError, check_pack_suite, library_root, load,
    packs, resolve,
)

__all__ = [
    "LIBRARY", "MANIFEST_FILE", "MISSIONS_FILE", "README_FILE",
    "FIXTURES_DIR", "TEMPLATES_DIR", "Pack", "PackError", "check_pack_suite",
    "library_root", "load", "packs", "resolve",
]
