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

**And a success says what it compared.**  Only a failure named the checkout,
through :func:`where_it_looked`; a green run said nothing at all, so "the kit
passed" carried no statement of *which* harness it passed against — and a kit
that located the wrong checkout passes exactly as loudly as one that located
the right one.  A number without its interpreter beside it is not evidence.
So :func:`compared_against` is written on the terminal at the end of every
run that found a harness, with :data:`KIT_VERSION` beside it, because "the
kit says we agree" also depends on which kit.
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

#: The KIT's own version — this file and `test_conformance.py` — and nothing
#: to do with the harness, whose version is `CONFORMANCE["pin"]` and whose
#: wire is `SCHEMA_VERSION`.  Bumped when the kit's own behaviour changes, so
#: that a platform running an old copy can be told so by the number in its own
#: output rather than by somebody remembering.
#:
#:   1 — the original.  The locator guessed ONE sibling, ``<repo>/../judais-
#:       lobi``, which is blind from a git worktree; a failure named that one
#:       path, and a success named nothing.
#:   2 — the bounded ancestor walk (25 Aug 2026), and the line below: a
#:       success names the checkout it compared against, and this number.
KIT_VERSION = 2

#: What a successful comparison said, recorded by the :func:`contract`
#: fixture and written out by :func:`pytest_terminal_summary`.  A list rather
#: than a string because a session that somehow located two is a session
#: whose reader needs to see both.
_COMPARED: List[str] = []


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


def compared_against(module) -> str:
    """The one line a SUCCESS owes its reader.

    Names three things and each earns its place: the **checkout** (or the
    installed distribution) the comparison was made against, because the
    locator has four candidates and a green run that does not say which it
    took is a green run that cannot be checked; the **file** the contract was
    imported from, because ``$JUDAIS_LOBI_HOME`` can point at a tree whose
    ``core`` is not the one on ``sys.path``; and :data:`KIT_VERSION`, because
    "the kit says we agree" is a claim about a particular kit, and a platform
    running a copy from before the locator walk agreed about nothing.
    """
    home = checkout()
    return (f"conformance kit v{KIT_VERSION}: compared this platform's table "
            f"against "
            f"{home if home is not None else 'the installed distribution'}"
            f" — {getattr(module, '__file__', '(no file)') or '(no file)'}, "
            f"SCHEMA_VERSION {getattr(module, 'SCHEMA_VERSION', '?')}")


def note_comparison(module) -> str:
    """Record :func:`compared_against` for the terminal summary, and return
    it.  Separate from the fixture so the sentence can be asserted without a
    session."""
    line = compared_against(module)
    _COMPARED.append(line)
    return line


def pytest_terminal_summary(terminalreporter, *_args, **_kwargs) -> None:
    """Write what was compared, at the end, where a person reads a run.

    A ``print`` inside the fixture would be swallowed by pytest's capture on
    the ordinary green run, which is the only run this line exists for.
    """
    for line in _COMPARED:
        terminalreporter.write_line(line)


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
    note_comparison(module)
    return module


@pytest.fixture(scope="session")
def harness_home() -> Optional[Path]:
    """The checkout, when it is a checkout — the spawn test needs a path."""
    return checkout()
