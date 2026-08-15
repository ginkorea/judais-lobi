"""The documentation, asserted against the code it describes.

The previous README's numbers drifted for one reason: they were *typed*.  It
claimed 888 tests against a suite that collected nearly twice that, and it
described a mission surface that had since grown ``--swarm``, ``--events``,
``--history``, ``--gate-tool`` and three sampling flags without gaining a line
about any of them.  Prose does not fail a test run, so nothing said anything.

These tests are the cheapest possible answer to that: **every flag and every
environment variable this repo publishes as a contract is mentioned in the
README, every field a platform integrator has to know is mentioned in
PLATFORMS.md, and the version in the README is the version in setup.py.**

Substring checks, deliberately, and nothing about wording.  A docs test that
asserted phrasing would be rewritten to match the docs the first time somebody
improved a sentence, which is a test that has stopped testing.  What is checked
here is the one thing a writer cannot get right by being careful: that a name
which exists in the code exists in the page a reader is sent to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.runtime import contract as c

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
PLATFORMS = REPO / "PLATFORMS.md"
SETUP = REPO / "setup.py"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def platforms() -> str:
    return PLATFORMS.read_text(encoding="utf-8")


class TestTheReadmeCoversTheSpawningSurface:
    """`contract.CLI_FLAGS` and `ENV_VARS` are what a consumer may rely on.

    A consumer that cannot find one of them in the README has to read the
    argparse block to discover a flag this repo promised not to move.
    """

    @pytest.mark.parametrize("flag", c.CLI_FLAGS)
    def test_every_published_flag_is_in_the_readme(self, readme, flag):
        assert flag in readme, f"{flag} is published in CLI_FLAGS and undocumented"

    @pytest.mark.parametrize("name", c.ENV_VARS)
    def test_every_published_env_var_is_in_the_readme(self, readme, name):
        assert name in readme, f"{name} is published in ENV_VARS and undocumented"


class TestPlatformsGuideNamesWhatAnIntegratorNeeds:
    """The five things nobody guesses right.

    Each is something a platform gets wrong silently: a manifest field it never
    declares, a closed set it never closes, a gate it never asks for, a schema
    it never pins, an audit name it never sets — and in every case the mission
    still runs and the transcript still looks ordinary.
    """

    @pytest.mark.parametrize("name", [
        "sdk_import", "allowed_tools", "--gate-tool",
        "SCHEMA_VERSION", "MCP_CLIENT_NAME",
    ])
    def test_the_guide_names_it(self, platforms, name):
        assert name in platforms, f"PLATFORMS.md never mentions {name}"


class TestTheVersionIsOneNumber:
    def test_the_readme_states_the_version_setup_py_ships(self, readme):
        match = re.search(r'^VERSION\s*=\s*"([^"]+)"',
                          SETUP.read_text(encoding="utf-8"), re.MULTILINE)
        assert match, "setup.py has no VERSION constant"
        version = match.group(1)
        assert version in readme, (
            f"setup.py ships {version} and the README does not say so")
