# tests/conformance/conftest.py — where the harness is, and how to import it
#
# ONE OF TWO FILES A PLATFORM COPIES. See README.md beside it. Nothing in here
# needs editing: it is the locator, and it is the same in every copy. What a
# platform edits is the `CONFORMANCE` dict at the top of `test_conformance.py`.

"""Finding an installed or checked-out judais-lobi, and importing its contract.

A conformance test is only worth having if it can *fail*, and the failure it
exists to catch is a harness that moved under a platform that pinned it. Two
things follow from that, and they are the whole of this file.

**It never skips because it could not find the harness.**  A test that skips
when an import fails reports a pass on every runner that has nothing installed,
which is the state the reference deployment's own bridge test was in for months
— green, and never once comparing anything.  So a missing harness is a
**failure** naming every place that was looked, and the single environment
variable that says a runner legitimately has none is spelled out rather than
inferred.

**It looks in two places, in order.**  The installed distribution first — a
platform that `pip install`s a pinned release is testing the code it will
actually run — and then a checkout named by ``$JUDAIS_LOBI_HOME`` or sitting
beside the platform's own repository, which is how a developer's machine and a
deploy pool are usually laid out.  Each candidate is accepted only if the
contract module is really there, so a stale variable pointing at an empty
directory falls through rather than being reported as agreement.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Optional

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
#: sibling guess is computed rather than configured.
_PLATFORM_REPO = Path(__file__).resolve().parents[2]


def sibling_checkout() -> Path:
    """``../judais-lobi``, beside the repository this kit was copied into."""
    return _PLATFORM_REPO.parent / "judais-lobi"


def checkout() -> Optional[Path]:
    """A checkout carrying the contract module, or ``None``."""
    candidates = []
    named = os.environ.get(HOME_ENV, "").strip()
    if named:
        candidates.append(Path(named))
    candidates.append(sibling_checkout())
    # The repository this file lives in, which is the case that matters for
    # judais-lobi's own copy: the template is run against its own tree.
    candidates.append(_PLATFORM_REPO)
    for candidate in candidates:
        if (candidate / CONTRACT_MODULE).is_file():
            return candidate
    return None


def where_it_looked() -> str:
    named = os.environ.get(HOME_ENV, "").strip() or "(unset)"
    return (f"the installed `judais_lobi`/`core` distribution, "
            f"${HOME_ENV}={named}, {sibling_checkout()}, and {_PLATFORM_REPO} "
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
