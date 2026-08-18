# tests/test_conformance_kit.py — the template a platform copies, kept honest

"""`tests/conformance/` is a kit somebody else runs, so this repository runs it.

The whole value of the kit is that it goes red the day the contract breaks. A
template that had itself fallen behind the contract would do the opposite: a
platform would copy a table describing a harness that no longer exists, and the
first thing their new conformance test would tell them is that everything
agrees.

So there are two guards, and they are different.

**The kit run against ourselves** — `tests/conformance/test_conformance.py`
under `testpaths`, collected by every `pytest -q` in this repository, spawning a
replay and asserting `conforms()` on it. That is the kit doing its job.

**This file** — the *template's* own table held against `core.runtime.contract`
as an **equality**, in both directions. The kit itself asserts a subset, which
is right for a platform: a bridge reads part of the wire. The shipped copy is
the maximal one, so an event or a field or a flag this repository adds and does
not add here is a template that ships short, and one that names something the
contract dropped is a template that ships a lie.

It also unit-tests the two pure helpers, because their interesting branches are
exactly the ones that never run in this repository's own copy: `pin` is `None`
here, so the comparison that matters to a platform would otherwise be dead code
with a test-shaped hole beside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.runtime import contract as c
from tests.conformance import test_conformance as kit

KIT = Path(kit.__file__).resolve().parent
CONFORMANCE = kit.CONFORMANCE


class TestTheShippedTableIsTheWholeContract:
    """Equality, both ways. See the module docstring for why the template is
    maximal where a platform's copy is not."""

    def test_every_event_and_no_others(self):
        assert set(CONFORMANCE["reads"]) == set(c.EVENTS)

    @pytest.mark.parametrize("event", c.EVENTS)
    def test_every_field_of_every_event_and_no_others(self, event):
        declared = set(c.FIELDS[event]) | set(c.OPTIONAL.get(event, ()))
        assert set(CONFORMANCE["reads"][event]) == declared

    def test_every_published_flag_and_no_others(self):
        assert set(CONFORMANCE["flags"]) == set(c.CLI_FLAGS)

    def test_every_published_variable_and_no_others(self):
        assert set(CONFORMANCE["env"]) == set(c.ENV_VARS)

    def test_every_outcome_word_and_no_others(self):
        assert set(CONFORMANCE["outcomes"]) == set(c.OUTCOMES)

    def test_every_exit_clause_and_no_others(self):
        assert set(CONFORMANCE["exit_clauses"]) == set(c.EXIT_CONTRACT)

    def test_the_schema_version_it_ships_is_this_one(self):
        assert CONFORMANCE["schema_version"] == c.SCHEMA_VERSION

    def test_this_copy_pins_nothing(self):
        """`pin` is a platform's field. This copy IS the harness, and a
        version typed here would be a second owner of `setup.py`'s VERSION —
        red on every release for a reason that is not drift."""
        assert CONFORMANCE["pin"] is None


class TestThePinComparisonSaysTheRightThing:
    """The branch that never runs in this repository's own copy.

    Three outcomes rather than two: "nothing pinned" and "nothing installed"
    are silence, and only a disagreement between two known versions is a
    defect. A helper that treated an absent `pip` metadata as a mismatch would
    fail on every developer's checkout, and would be turned off within a week.
    """

    def test_a_pin_that_matches_is_silent(self):
        assert kit.pin_mismatch("1.0.0", "1.0.0") is None

    def test_no_pin_is_silent(self):
        assert kit.pin_mismatch(None, "1.0.0") is None

    def test_nothing_installed_is_silent(self):
        assert kit.pin_mismatch("1.0.0", None) is None

    def test_a_disagreement_names_both_versions(self):
        problem = kit.pin_mismatch("1.0.0", "0.15.0")
        assert problem is not None
        assert "1.0.0" in problem and "0.15.0" in problem

    def test_the_installed_version_lookup_never_raises(self):
        """A checkout nobody installed is the ordinary case on a developer's
        machine, and `importlib.metadata` raises for it."""
        assert kit.installed_version() is None or isinstance(
            kit.installed_version(), str)


class TestTheKitIsTwoFilesAndAPageThatSaysSo:
    """`PLATFORMS.md` §10 tells a reader to copy two files. A kit that had
    grown a third would leave every copy of it subtly broken."""

    def test_the_two_files_a_platform_copies_are_there(self):
        for name in ("conftest.py", "test_conformance.py"):
            assert (KIT / name).is_file(), name

    def test_nothing_else_is_needed_to_copy(self):
        """`__init__.py` exists for this repository's own import and says so;
        `README.md` is the instructions. Anything else is a third file a
        platform would have to be told about."""
        found = {path.name for path in KIT.iterdir() if path.is_file()}
        assert found == {"conftest.py", "test_conformance.py", "__init__.py",
                         "README.md"}, sorted(found)

    def test_the_readme_says_what_to_edit(self):
        text = (KIT / "README.md").read_text(encoding="utf-8")
        for phrase in ("copy these two files", "reads", "pin"):
            assert phrase.lower() in text.lower(), phrase

    def test_the_spawn_the_template_ships_points_at_a_real_recording(self):
        """The one entry in the dict that names a path. A template whose
        example run had been deleted would skip on every copy of it, and a
        skip is what this kit exists not to do."""
        spawn = CONFORMANCE["spawn"]
        repo = KIT.parent.parent
        assert (repo / spawn["store"] / spawn["run_id"]).is_dir()
