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


def _make_checkout(root: Path) -> Path:
    """A directory that looks like a judais-lobi checkout to the locator.

    The locator's whole acceptance test is "does `core/runtime/contract.py`
    exist under here", so that one file is the whole fixture — and building
    it rather than pointing at the real tree is what lets these tests state
    a LAYOUT rather than a machine.
    """
    (root / "core" / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "core" / "runtime" / "contract.py").write_text(
        "SCHEMA_VERSION = '0.0.0-fixture'\n", encoding="utf-8")
    return root


@pytest.fixture
def locator(monkeypatch):
    """The kit's `conftest.py`, with the environment out of the way.

    `$JUDAIS_LOBI_HOME` is deleted rather than left alone: it is the first
    candidate, so a developer who has it exported would make every layout
    test below pass without testing the layout.
    """
    from tests.conformance import conftest as module

    monkeypatch.delenv(module.HOME_ENV, raising=False)
    return module


class TestTheLocatorFindsACheckoutFromAWorktree:
    """Where the harness is, from a working tree that is INSIDE a repository.

    The kit guessed `<repo>/../judais-lobi`: one level, right for the layout
    everybody describes and blind for the one `git worktree` produces. A
    platform lane running in `<repo>/.claude/worktrees/wt-x/` computes its
    repository as the worktree, guesses `.claude/worktrees/judais-lobi`,
    finds nothing, and the one test that compares that platform's reading of
    the wire against the harness's own declaration reports the checkout
    absent and stops comparing. The reference deployment measured the gap:
    eight errors the moment `$JUDAIS_LOBI_HOME` was set, zero reported
    before it was.

    A conformance kit that silently checks nothing is the exact failure this
    kit's module docstring says it exists to prevent, so the search is a
    bounded ancestor walk now and these are the layouts it has to answer.
    """

    def worktree(self, tmp_path, monkeypatch, locator):
        """`<tmp>/repo/.claude/worktrees/wt`, with the checkout beside
        `repo` — the layout an isolated agent lane actually runs in."""
        kit_home = tmp_path / "repo" / ".claude" / "worktrees" / "wt"
        (kit_home / "tests" / "conformance").mkdir(parents=True)
        monkeypatch.setattr(locator, "_PLATFORM_REPO", kit_home)
        return _make_checkout(tmp_path / "judais-lobi")

    def test_the_checkout_beside_the_outer_repository_is_found(
            self, tmp_path, monkeypatch, locator):
        found = self.worktree(tmp_path, monkeypatch, locator)
        assert locator.checkout() == found

    def test_the_flat_sibling_layout_still_resolves(self, tmp_path,
                                                    monkeypatch, locator):
        """The loosening must not move the case that already worked: two
        checkouts side by side is what the walk's first step is."""
        (tmp_path / "platform").mkdir()
        monkeypatch.setattr(locator, "_PLATFORM_REPO", tmp_path / "platform")
        found = _make_checkout(tmp_path / "judais-lobi")
        assert locator.checkout() == found

    def test_the_nearest_ancestor_wins(self, tmp_path, monkeypatch, locator):
        """Nearest first, so a machine with checkouts at two depths gets the
        one next to the repository being worked on rather than whichever the
        walk happened to reach."""
        kit_home = tmp_path / "outer" / "inner" / "platform"
        kit_home.mkdir(parents=True)
        monkeypatch.setattr(locator, "_PLATFORM_REPO", kit_home)
        near = _make_checkout(tmp_path / "outer" / "inner" / "judais-lobi")
        _make_checkout(tmp_path / "outer" / "judais-lobi")
        assert locator.checkout() == near

    def test_a_named_home_still_wins_over_the_walk(self, tmp_path,
                                                   monkeypatch, locator):
        """`$JUDAIS_LOBI_HOME` is a person saying which checkout, and a
        search that could overrule it would be a search that ignores them."""
        self.worktree(tmp_path, monkeypatch, locator)
        named = _make_checkout(tmp_path / "elsewhere")
        monkeypatch.setenv(locator.HOME_ENV, str(named))
        assert locator.checkout() == named

    def test_a_stale_named_home_falls_through_to_the_walk(
            self, tmp_path, monkeypatch, locator):
        """A variable pointing at an empty directory is not agreement. It
        was true before the walk and it has to stay true through it."""
        found = self.worktree(tmp_path, monkeypatch, locator)
        (tmp_path / "empty").mkdir()
        monkeypatch.setenv(locator.HOME_ENV, str(tmp_path / "empty"))
        assert locator.checkout() == found

    def test_a_repository_that_is_ITSELF_a_checkout_beats_an_ancestor(
            self, tmp_path, monkeypatch, locator):
        """You do not go looking for a sibling copy of what you are standing
        in.

        This is the case the walk created and the single guess could not
        reach: judais-lobi's own worktrees live at
        `<checkout>/.claude/worktrees/wt-x`, so the main checkout is an
        ANCESTOR of the lane. Preferring it would make a lane compare — and,
        through `harness_home`, spawn a replay of — the code on master while
        looking exactly like a pass on the lane's own tree.
        """
        main = _make_checkout(tmp_path / "judais-lobi")
        lane = _make_checkout(main / ".claude" / "worktrees" / "wt")
        monkeypatch.setattr(locator, "_PLATFORM_REPO", lane)
        assert locator.checkout() == lane

    def test_nothing_that_carries_the_contract_module_is_nothing_found(
            self, tmp_path, monkeypatch, locator):
        """The acceptance predicate, not the machine. `CONTRACT_MODULE` is
        pointed at a filename nothing has, so this says *no candidate
        qualified* on any host rather than *this host happens to have no
        checkout anywhere above /tmp*."""
        (tmp_path / "platform").mkdir()
        monkeypatch.setattr(locator, "_PLATFORM_REPO", tmp_path / "platform")
        monkeypatch.setattr(locator, "CONTRACT_MODULE",
                            Path("core") / "runtime" / "no_such_module.py")
        _make_checkout(tmp_path / "judais-lobi")
        assert locator.checkout() is None

    def test_the_opt_out_is_still_the_only_one(self, tmp_path, monkeypatch,
                                               locator):
        """`ALLOW_MISSING` reads its own variable and nothing else — not the
        layout, not an ImportError. Inferring it is what lets a conformance
        test report a pass on a comparison it never made."""
        monkeypatch.delenv(locator.ALLOW_MISSING_ENV, raising=False)
        assert locator.allowed_to_be_missing() is False
        monkeypatch.setenv(locator.ALLOW_MISSING_ENV, "1")
        assert locator.allowed_to_be_missing() is True
        monkeypatch.setenv(locator.ALLOW_MISSING_ENV, "yes")
        assert locator.allowed_to_be_missing() is False

    def test_the_failure_message_describes_the_walk_and_not_one_path(
            self, tmp_path, monkeypatch, locator):
        """A message naming a single sibling is what made the worktree case
        unreadable: it pointed at a directory nobody expected to exist and
        said nothing about the others it had tried."""
        kit_home = tmp_path / "repo" / ".claude" / "worktrees" / "wt"
        kit_home.mkdir(parents=True)
        monkeypatch.setattr(locator, "_PLATFORM_REPO", kit_home)
        said = locator.where_it_looked()
        for path in locator.sibling_checkouts()[:3]:
            assert str(path) in said, path
        assert str(kit_home) in said
        assert locator.HOME_ENV in said

    def test_the_walk_is_bounded_and_ends_at_the_root(self, tmp_path,
                                                      monkeypatch, locator):
        """`Path.parents` ends at the filesystem root, so the search is
        finite by construction and needs no depth cap somebody has to keep
        right. Said as a test because "bounded" is the property, not the
        implementation."""
        kit_home = tmp_path / "a" / "b" / "c"
        kit_home.mkdir(parents=True)
        monkeypatch.setattr(locator, "_PLATFORM_REPO", kit_home)
        walked = locator.sibling_checkouts()
        assert walked[0] == tmp_path / "a" / "b" / "judais-lobi"
        assert walked[-1] == Path(kit_home.anchor) / "judais-lobi"
        assert len(walked) == len(kit_home.parents)


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
