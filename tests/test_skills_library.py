# tests/test_skills_library.py — the mission packs this framework ships

"""The layout, held to, for every pack in the library at once.

A pack is a directory and nothing enforces a directory.  So these are
written over ``core.skills.packs()`` rather than over a list of names:
the day lane M's ``research`` and lane N's ``coding`` land beside
``analyst``, they are held to the same four files, the same closed set
rule and the same gradeable suite without a line changing here.  A test
that named the packs would pass for the packs it named.

What is deliberately NOT here: anything that parses a manifest or a
suite.  :func:`core.runtime.skills.load_skill` owns the first and
:func:`core.eval.suite.load_suite` owns the second; this module's whole
job is *which files are a pack's, and where*.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import core.skills as skills
from core.eval.suite import FLAGS, MissionMisdeclared
from core.runtime.skills import (SkillManifest, SkillManifestError,
                                 load_skill, resolve_skill)
from core.skills import library

pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")

#: Every installed pack, as a parametrisation.  Collected once at import
#: so a pack that fails to be a directory at all shows up as an empty
#: parametrisation rather than as eleven confusing errors.
PACKS = [pytest.param(name, id=name) for name in skills.packs()]

#: The one pack lane O ships.  Named in exactly two assertions — that it
#: is installed, and that it is the analyst — so that everything else in
#: this file is about packs in general.
LANE_O_PACK = "analyst"


class TestTheLibraryIsFound:
    """Before anything else: the packs directory resolves, and the module
    that reads it is not shadowed by it."""

    def test_the_library_directory_exists_and_holds_packs(self):
        root = library.library_root()
        assert root.is_dir(), root
        assert skills.packs(), f"no pack directories under {root}"

    def test_the_module_wins_over_the_data_directory_of_the_same_name(self):
        """``core/skills/library.py`` and ``core/skills/library/`` share a
        word, and the import system resolves the name to the module only
        because the directory carries no ``__init__.py``.

        Pinned rather than assumed: an ``__init__.py`` dropped into
        ``library/`` makes it a regular package, the module becomes
        unreachable, and every pack goes with it.  The failure would be an
        ImportError a long way from its cause.
        """
        assert Path(library.__file__).name == "library.py"
        assert not (library.library_root() / "__init__.py").exists()

    def test_a_directory_without_a_manifest_is_not_a_pack(self, tmp_path,
                                                          monkeypatch):
        """``__pycache__``, a half-written pack, a stray notes directory —
        ``--skill <name>`` must not offer any of them."""
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / library.MANIFEST_FILE).write_text("x")
        (tmp_path / "notes").mkdir()
        monkeypatch.setattr(library, "library_root", lambda: tmp_path)
        assert library.packs() == ("real",)


class TestEveryPackHasTheFourFiles:
    """The layout, for every installed pack."""

    @pytest.mark.parametrize("name", PACKS)
    def test_it_loads_whole(self, name):
        pack = skills.load(name)
        assert pack.name == name
        assert pack.root.is_dir()
        assert pack.readme.strip(), f"{name}: an empty README"
        assert pack.missions_file.is_file()

    @pytest.mark.parametrize("name", PACKS)
    def test_its_manifest_loads_through_the_one_manifest_loader(self, name):
        """Not re-parsed here.  ``load_skill`` is the only thing in this
        repository that reads a ``SKILL.md``, and a pack loader with its
        own parser is how a closed set comes to mean two things."""
        pack = skills.load(name)
        direct = load_skill(pack.root / library.MANIFEST_FILE)
        assert isinstance(pack.manifest, SkillManifest)
        assert pack.manifest.name == direct.name
        assert pack.manifest.allowed_tools == direct.allowed_tools
        assert pack.manifest.allowed_tools, f"{name}: an empty closed set"

    @pytest.mark.parametrize("name", PACKS)
    def test_a_code_plane_pack_declares_its_sandbox(self, name):
        """The manifest's own gate, asked of every pack at import rather
        than at the door of somebody's mission: a pack naming a tool that
        runs model-written code on this host and not saying ``sandbox:
        bwrap`` is a pack that must not ship."""
        manifest = skills.load(name).manifest
        if manifest.code_plane_entries():
            assert manifest.sandbox == "bwrap", (
                f"{name} names {manifest.code_plane_entries()} and declares "
                f"sandbox: {manifest.sandbox!r}")

    @pytest.mark.parametrize("name", PACKS)
    def test_its_readme_names_the_profile_and_a_command(self, name):
        """A README that does not say how to run the pack is a README
        nobody can act on.  Both halves, because the profile is the part
        an operator gets wrong first."""
        readme = skills.load(name).readme
        assert "--profile" in readme or "profile" in readme.lower()
        assert "--skill" in readme, f"{name}: no example command"

    @pytest.mark.parametrize("name", PACKS)
    def test_every_template_it_ships_is_a_workflow(self, name):
        """A task template is a `workflow:` naming its roles.  Nothing
        runs one yet — that is a later lane — and a placeholder that
        cannot be parsed is decoration rather than a placeholder."""
        yaml = pytest.importorskip("yaml")
        for path in skills.load(name).templates:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(body, dict), path
            assert body.get("skill") == name, path
            roles = body.get("workflow")
            assert isinstance(roles, list) and roles, path
            assert all(step.get("role") for step in roles), path


class TestEveryPackCarriesAGradeableSuite:
    """A capability nobody measures is a claim.  Every pack ships its own
    missions, and they have to be scoreable by ``core.eval``."""

    @pytest.mark.parametrize("name", PACKS)
    def test_the_suite_loads_and_grades(self, name):
        suite = skills.load(name).suite()
        assert suite.missions, f"{name}: a suite with no missions"
        assert suite.name

    @pytest.mark.parametrize("name", PACKS)
    def test_every_mission_names_only_tools_the_pack_may_call(self, name):
        """The one rule ``core/eval/`` cannot make, because only a pack
        knows what its skill is allowed to call.  A mission expecting a
        tool the manifest withholds can never pass, and it fails looking
        like an agent defect."""
        pack = skills.load(name)
        suite = pack.suite()
        from core.runtime.results import RESULT_TOOL
        from core.tools.descriptors import same_tool

        allowed = (*pack.tools, RESULT_TOOL)
        for mission in suite.missions:
            for tool in (*mission.expects_tools, *mission.forbids_tools):
                assert any(same_tool(tool, entry) for entry in allowed), (
                    f"{name}[{mission.key}] names {tool!r}, closed set "
                    f"{list(allowed)}")

    @pytest.mark.parametrize("name", PACKS)
    def test_the_flags_it_captures_are_flags_core_eval_defines(self, name):
        suite = skills.load(name).suite()
        assert {m.flag for m in suite.missions} <= set(FLAGS)


class TestThePackScopedCheckIsCoreEvalsOwn:
    """``check_pack_suite`` narrows the flag-coverage rule and nothing
    else.  What makes that safe is that it hands the narrowed suite back
    to ``core.eval``'s own function — so these are the tests that the
    narrowing is a narrowing and not a second checker."""

    def test_a_flag_no_one_defines_is_refused(self, tmp_path):
        """Scoping coverage to the captured set must not turn an invented
        flag into a legal one: the captured set is validated against
        ``FLAGS`` BEFORE it becomes the scope, and a mutation that drops
        that validation makes this test red."""
        from core.eval.suite import Suite

        suite = skills.load(LANE_O_PACK).suite()
        broken = Suite(
            name="broken",
            missions=tuple(
                mission if index else type(mission)(
                    **{**mission.to_mapping(), "flag": "not_a_flag"})
                for index, mission in enumerate(suite.missions)),
            tools=suite.tools, assets=suite.assets,
            identifier_pattern=suite.identifier_pattern)
        with pytest.raises(MissionMisdeclared) as caught:
            library.check_pack_suite(broken)
        assert "not_a_flag" in str(caught.value)

    def test_the_global_flag_table_is_put_back_afterwards(self):
        """It is rebound around the call.  A `finally` that ever went
        missing would leave every later suite in the process — the stub
        suite included — graded against nine flags instead of eleven."""
        from core.eval import suite as suite_module

        before = dict(suite_module.FLAGS)
        library.check_pack_suite(skills.load(LANE_O_PACK).suite(check=False))
        assert suite_module.FLAGS == before
        assert suite_module.FLAGS is not None

    def test_it_is_put_back_even_when_the_check_refuses(self, tmp_path):
        from core.eval import suite as suite_module
        from core.eval.suite import Suite

        before = dict(suite_module.FLAGS)
        empty = Suite(name="empty", missions=(), tools=())
        with pytest.raises(MissionMisdeclared):
            library.check_pack_suite(empty)
        assert suite_module.FLAGS == before

    def test_the_rest_of_the_rules_still_bite(self):
        """The split band is core.eval's, and scoping the flags must not
        have switched it off: the same suite with every mission relabelled
        `train` has no held-out half and is refused."""
        from dataclasses import replace

        from core.eval.suite import Suite

        suite = skills.load(LANE_O_PACK).suite()
        all_train = Suite(
            name=suite.name,
            missions=tuple(replace(m, split="train") for m in suite.missions),
            tools=suite.tools, assets=suite.assets,
            identifier_pattern=suite.identifier_pattern)
        with pytest.raises(MissionMisdeclared) as caught:
            library.check_pack_suite(all_train)
        assert "test mission" in str(caught.value)

    def test_a_mission_naming_a_tool_the_pack_withholds_is_refused(self):
        """The rule that is the PACK's and no generic suite's.

        `suite.tools` is declared by the suite, so core.eval can only ask
        "does this suite serve the tool it expects" — and a suite that
        declares the tool serves it. The question only a pack can answer
        is whether the SKILL may call it, and here the suite says yes
        while the manifest's closed set does not name it. A mutation that
        drops this check leaves the suite gradeable and the mission
        unpassable, which is the pair that looks like an agent defect.
        """
        from dataclasses import replace

        from core.eval.suite import Suite

        pack = skills.load(LANE_O_PACK)
        suite = pack.suite()
        widened = Suite(
            name=suite.name,
            missions=tuple(
                replace(m, expects_tools=("perform_web_search",))
                if index == 0 else m
                for index, m in enumerate(suite.missions)),
            # Declared by the suite, so core.eval's own check passes it.
            tools=(*suite.tools, "perform_web_search"),
            assets=suite.assets,
            identifier_pattern=suite.identifier_pattern)
        library.check_pack_suite(widened)          # gradeable on its own
        with pytest.raises(MissionMisdeclared) as caught:
            library.check_pack_suite(widened, pack)
        assert "perform_web_search" in str(caught.value)


class TestResolveTakesAPathOrAName:
    """The three ways ``--skill`` is written, and the one order they are
    tried in."""

    def test_a_bare_pack_name(self):
        assert skills.resolve(LANE_O_PACK).name == LANE_O_PACK

    def test_a_path_to_a_manifest(self):
        path = skills.load(LANE_O_PACK).root / library.MANIFEST_FILE
        assert skills.resolve(str(path)).name == LANE_O_PACK

    def test_a_path_to_the_directory_holding_one(self):
        root = skills.load(LANE_O_PACK).root
        assert skills.resolve(root).name == LANE_O_PACK

    def test_an_existing_path_beats_a_pack_of_the_same_name(self, tmp_path,
                                                            monkeypatch):
        """The compatibility promise, stated as a test: ``--skill`` took a
        path before packs existed, and a name that silently beat a real
        file would change what an existing command line does."""
        shadow = tmp_path / LANE_O_PACK
        shadow.mkdir()
        shutil.copy(
            skills.load(LANE_O_PACK).root / library.MANIFEST_FILE,
            shadow / library.MANIFEST_FILE)
        (shadow / library.MANIFEST_FILE).write_text(
            (shadow / library.MANIFEST_FILE)
            .read_text(encoding="utf-8").replace("skill_id: analyst",
                                                 "skill_id: shadowed"),
            encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert skills.resolve(LANE_O_PACK).name == "shadowed"

    def test_neither_a_path_nor_a_pack_names_both_roads_out(self):
        with pytest.raises(SkillManifestError) as caught:
            skills.resolve("no_such_thing")
        message = str(caught.value)
        assert LANE_O_PACK in message
        assert library.MANIFEST_FILE in message

    def test_nothing_at_all_is_refused_and_lists_the_packs(self):
        with pytest.raises(SkillManifestError) as caught:
            skills.resolve("")
        assert LANE_O_PACK in str(caught.value)

    def test_the_runtime_seam_delegates_here(self):
        """``core.runtime.skills.resolve_skill`` is the door a command line
        uses.  One owner: it must answer exactly what ``core.skills``
        answers, for a name and for a path alike."""
        path = skills.load(LANE_O_PACK).root / library.MANIFEST_FILE
        assert resolve_skill(LANE_O_PACK).name == LANE_O_PACK
        assert resolve_skill(path).name == LANE_O_PACK
        with pytest.raises(SkillManifestError):
            resolve_skill("no_such_thing")


class TestLoadRefusesWithEveryProblemAtOnce:
    def test_an_unknown_name_lists_what_there_is(self):
        with pytest.raises(skills.PackError) as caught:
            skills.load("nope")
        assert LANE_O_PACK in str(caught.value)

    def test_a_name_with_a_separator_is_not_a_pack_name(self, tmp_path):
        """A pack is named, not pathed.  ``load("../../etc")`` must be a
        refusal and not a directory read."""
        with pytest.raises(skills.PackError):
            skills.load("../analyst")

    def test_an_incomplete_pack_names_every_missing_file(self, tmp_path,
                                                         monkeypatch):
        root = tmp_path / "half"
        root.mkdir()
        (root / library.MANIFEST_FILE).write_text("---\nname: half\n---\nx")
        monkeypatch.setattr(library, "library_root", lambda: tmp_path)
        with pytest.raises(skills.PackError) as caught:
            skills.load("half")
        message = str(caught.value)
        assert library.MISSIONS_FILE in message
        assert library.README_FILE in message

    def test_a_pack_error_is_refused_by_the_cli_s_existing_clause(self):
        """``core/cli.py``'s ``_load_skill`` turns a
        ``SkillManifestError`` into a ``SystemExit``.  ``PackError``
        subclasses it so a bad pack name is refused by the sentence that
        is already there, rather than by a second ``except`` nobody
        added."""
        assert issubclass(skills.PackError, SkillManifestError)


class TestFixturesAreStagedAndNotUsedWhereTheyLie:
    """A sandboxed run binds its working directory read-WRITE.  If that
    directory were the installed pack, a mission told to write a report
    would write inside site-packages."""

    def test_staging_copies_every_fixture(self, tmp_path):
        pack = skills.load(LANE_O_PACK)
        work = pack.stage_fixtures(tmp_path / "work")
        staged = {p.name for p in work.iterdir()}
        assert staged == {p.name for p in pack.fixtures.iterdir()
                          if p.is_file()}
        assert staged

    def test_the_staged_copy_is_a_copy(self, tmp_path):
        pack = skills.load(LANE_O_PACK)
        work = pack.stage_fixtures(tmp_path / "work")
        victim = next(iter(sorted(work.iterdir())))
        original = (pack.fixtures / victim.name).read_bytes()
        victim.write_bytes(b"clobbered\n")
        assert (pack.fixtures / victim.name).read_bytes() == original

    def test_a_pack_with_no_fixtures_still_gets_its_directory(self, tmp_path):
        """So a caller does not branch on which kind of pack it holds."""
        from dataclasses import replace

        pack = replace(skills.load(LANE_O_PACK), fixtures=None)
        work = pack.stage_fixtures(tmp_path / "empty")
        assert work.is_dir()
        assert not list(work.iterdir())
