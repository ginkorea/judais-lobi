# tests/conformance/conftest.py — where the harness is, and how to import it
#
# ONE OF TWO FILES A PLATFORM COPIES. See README.md beside it. Nothing in here
# needs editing: it is the locator, and it is the same in every copy. What a
# platform edits is the `CONFORMANCE` dict at the top of `test_conformance.py`.

"""Finding an installed or checked-out judais-lobi, and importing its contract.

A conformance test is only worth having if it can *fail*, and the failure it
exists to catch is a harness that moved under a platform that pinned it. Three
things follow from that, and they are the whole of this file.

**It never skips because it could not find the harness.**  A test that skips
when an import fails reports a pass on every runner that has nothing installed,
which is the state the reference deployment's own bridge test was in for months
— green, and never once comparing anything.  So a missing harness is a
**failure** naming every place that was looked, and the single environment
variable that says a runner legitimately has none is spelled out rather than
inferred.

**It looks in four places, in order.**  The installed distribution first — a
platform that `pip install`s a pinned release is testing the code it will
actually run — then a checkout named by ``$JUDAIS_LOBI_HOME``, then the
repository this kit was copied into if it *is* a checkout, and finally
``judais-lobi`` beside any ancestor of that repository.  Each candidate is
accepted only if the contract module is really there, so a stale variable
pointing at an empty directory falls through rather than being reported as
agreement.

**The last of those is a walk and not a guess**, which is the correction of
25 August 2026.  It was ``<repo>/../judais-lobi``, one level, and that is
blind from a git worktree: a platform lane running in
``<repo>/.claude/worktrees/wt-x/`` computes its repository as the worktree,
guesses ``.claude/worktrees/judais-lobi``, finds nothing, and reports the
checkout absent — so the one test that compares a platform's reading of the
wire against the harness's own declaration silently stops comparing for
everybody who works in a worktree.  The reference deployment measured it:
eight errors the moment ``$JUDAIS_LOBI_HOME`` was set, zero reported before.
A test that cannot find the harness must not be a test that quietly checks
nothing, and a layout nobody thought of must not be the way it happens.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import List, Optional

import pytest

#: A checkout named outright, for a machine that keeps one somewhere of its own.
HOME_ENV = "JUDAIS_LOBI_HOME"

#: The ONE way this file is allowed not to run. Spelled as an explicit opt-out
#: rather than inferred from an ImportError: inferring it is what lets a
#: conformance test report a pass on a comparison it never made.
ALLOW_MISSING_ENV = "JUDAIS_LOBI_CONFORMANCE_ALLOW_MISSING"

#: What makes a directory a judais-lobi checkout new enough to have written its
#: wire contract down.
CONTRACT_MODULE = Path("core") / "runtime" / "contract.py"

#: Where a copy of this kit sits relative to the repository holding it, so the
#: sibling walk is computed rather than configured.
_PLATFORM_REPO = Path(__file__).resolve().parents[2]


def sibling_checkouts() -> List[Path]:
    """``<ancestor>/judais-lobi`` for every ancestor, nearest one first.

    A walk rather than the single ``../judais-lobi`` this used to guess.
    ``<repo>/..`` is right for the layout everybody describes — two
    checkouts side by side — and wrong for every layout that puts a working
    tree *inside* the repository, which is what ``git worktree`` does and
    what an isolated agent lane does.  From
    ``<repo>/.claude/worktrees/wt-x`` the old guess named
    ``<repo>/.claude/worktrees/judais-lobi``, a directory nobody has ever
    created, and the kit went on to report that there was no checkout to
    compare against.

    Bounded by construction: ``Path.parents`` ends at the filesystem root,
    so this is a finite list and needs no depth cap to invent.  Nearest
    first, so the two-checkouts-side-by-side layout still resolves to the
    same directory it always did and only a layout that used to resolve to
    NOTHING can resolve to something new.
    """
    return [parent / "judais-lobi" for parent in _PLATFORM_REPO.parents]


def checkout() -> Optional[Path]:
    """A checkout carrying the contract module, or ``None``."""
    candidates = []
    named = os.environ.get(HOME_ENV, "").strip()
    if named:
        candidates.append(Path(named))
    # The repository this file lives in, BEFORE the walk, and only ever a
    # candidate because it might itself be a judais-lobi checkout — which is
    # the case for judais-lobi's own copy of the kit, where the template is
    # run against its own tree. A platform's repository does not carry the
    # contract module, so for a platform this line matches nothing and the
    # order below it is the whole answer.
    #
    # It is first of the two because the walk can now climb PAST it: a lane
    # working in `<checkout>/.claude/worktrees/wt-x` has the main checkout
    # as an ancestor, and preferring that over the tree the lane is standing
    # in would compare — and, through `harness_home`, SPAWN — the wrong code
    # while looking exactly like a pass.
    candidates.append(_PLATFORM_REPO)
    candidates.extend(sibling_checkouts())
    for candidate in candidates:
        if (candidate / CONTRACT_MODULE).is_file():
            return candidate
    return None


def where_it_looked() -> str:
    """Every place, said as the search it is — not as one path.

    A failure message that named a single sibling was the thing that made
    the worktree case unreadable: it pointed at a directory nobody expected
    to exist and said nothing about the eight others it had tried.
    """
    named = os.environ.get(HOME_ENV, "").strip() or "(unset)"
    walked = sibling_checkouts()
    return (f"the installed `judais_lobi`/`core` distribution, "
            f"${HOME_ENV}={named}, {_PLATFORM_REPO}, and `judais-lobi` beside "
            f"each of the {len(walked)} ancestors of {_PLATFORM_REPO} "
            f"({', '.join(str(path) for path in walked)}) "
            f"— each for {CONTRACT_MODULE}")


def allowed_to_be_missing() -> bool:
    return os.environ.get(ALLOW_MISSING_ENV, "") == "1"


def _import_contract():
    """``core.runtime.contract``, installed or off a located checkout."""
    try:
        return importlib.import_module("core.runtime.contract")
    except ImportError:
        pass
    home = checkout()
    if home is None:
        return None
    # Left on `sys.path` for the length of the session, deliberately. Taking it
    # back off is the tidier habit and it is wrong here: the checkout is also
    # what the replay below is spawned from, and a half-imported `core` left in
    # `sys.modules` with its path gone is a harder failure to read than a
    # directory on the path.
    sys.path.insert(0, str(home))
    return importlib.import_module("core.runtime.contract")


@pytest.fixture(scope="session")
def contract():
    """The harness's own declaration of the wire, as data.

    Fails rather than skips when there is none — see the module docstring.
    """
    module = _import_contract()
    if module is None:
        if allowed_to_be_missing():
            pytest.skip(
                f"{ALLOW_MISSING_ENV}=1: no judais-lobi on this runner, and "
                f"somebody said so on purpose")
        pytest.fail(
            f"judais-lobi's contract module was not found, so the only test "
            f"that compares this platform's reading of the mission stream "
            f"against the harness's own declaration cannot run — and it FAILS "
            f"rather than skips, because skipping is what lets the two drift. "
            f"Looked at {where_it_looked()}. Install the pinned release, point "
            f"${HOME_ENV} at a checkout of it, or set {ALLOW_MISSING_ENV}=1 on "
            f"a runner that has neither.")
    return module


@pytest.fixture(scope="session")
def harness_home() -> Optional[Path]:
    """The checkout, when it is a checkout — the spawn test needs a path."""
    return checkout()
