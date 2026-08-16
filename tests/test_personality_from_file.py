# tests/test_personality_from_file.py — PersonalityConfig.from_file

import json

import pytest

from core.contracts.schemas import PERSONALITY_FILE_FORMATS, PersonalityConfig

TOML = """\
name = "tai"
system_message = "You are Tai."
text_color = "white"
default_provider = "local"
default_model = "gpt-oss-20b"
env_path = "~/.tai_env"
rag_enhancement_style = "Cite every claim."
"""


@pytest.fixture
def toml_file(tmp_path):
    path = tmp_path / "tai.toml"
    path.write_text(TOML, encoding="utf-8")
    return path


class TestLoading:
    def test_every_field_round_trips(self, toml_file):
        config = PersonalityConfig.from_file(toml_file)
        assert config.name == "tai"
        assert config.system_message == "You are Tai."
        assert config.text_color == "white"
        assert config.default_provider == "local"
        assert config.default_model == "gpt-oss-20b"
        assert config.env_path == "~/.tai_env"
        assert config.rag_enhancement_style == "Cite every claim."

    def test_the_result_is_the_same_frozen_model(self, toml_file):
        config = PersonalityConfig.from_file(toml_file)
        assert isinstance(config, PersonalityConfig)
        with pytest.raises(Exception):
            config.name = "someone else"

    def test_examples_default_to_none_at_all(self, toml_file):
        """No voice to pin, so no borrowed examples."""
        assert PersonalityConfig.from_file(toml_file).examples == []

    def test_examples_load_as_pairs(self, tmp_path):
        path = tmp_path / "p.toml"
        path.write_text(
            'name = "p"\nsystem_message = "s"\n'
            'examples = [["q", "a"], ["q2", "a2"]]\n',
            encoding="utf-8",
        )
        assert PersonalityConfig.from_file(path).examples == [("q", "a"), ("q2", "a2")]

    def test_json_is_accepted(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({"name": "p", "system_message": "s"}))
        assert PersonalityConfig.from_file(path).name == "p"

    def test_yaml_is_accepted(self, tmp_path):
        pytest.importorskip("yaml")
        path = tmp_path / "p.yaml"
        path.write_text("name: p\nsystem_message: s\n")
        assert PersonalityConfig.from_file(path).name == "p"

    def test_a_string_path_works(self, toml_file):
        assert PersonalityConfig.from_file(str(toml_file)).name == "tai"

    def test_defaults_are_the_model_s(self, tmp_path):
        path = tmp_path / "bare.toml"
        path.write_text('name = "p"\nsystem_message = "s"\n', encoding="utf-8")
        config = PersonalityConfig.from_file(path)
        assert config.text_color == "cyan"
        assert config.default_provider is None


class TestRefusals:
    def test_a_missing_file_says_where_it_looked(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No personality file at"):
            PersonalityConfig.from_file(tmp_path / "nope.toml")

    def test_an_unknown_suffix_is_refused_by_name(self, tmp_path):
        path = tmp_path / "p.ini"
        path.write_text("[x]\n")
        with pytest.raises(ValueError, match=r"\.ini"):
            PersonalityConfig.from_file(path)

    def test_an_unknown_key_is_refused_and_named(self, tmp_path):
        """A typo'd key must not become a personality with an empty prompt."""
        path = tmp_path / "p.toml"
        path.write_text(
            'name = "p"\nsystem_message = "s"\nsystem_prompt = "oops"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="system_prompt"):
            PersonalityConfig.from_file(path)

    def test_a_missing_required_field_is_a_validation_error(self, tmp_path):
        path = tmp_path / "p.toml"
        path.write_text('name = "p"\n', encoding="utf-8")
        with pytest.raises(Exception, match="system_message"):
            PersonalityConfig.from_file(path)

    def test_a_non_table_file_is_refused(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match="a table of the PersonalityConfig"):
            PersonalityConfig.from_file(path)

    def test_the_format_list_is_closed(self):
        assert PERSONALITY_FILE_FORMATS == (".toml", ".json", ".yaml", ".yml")


class TestTheBuiltInsAreUntouched:
    """The seam adds a way in; it replaces nothing."""

    def test_judais_is_unchanged(self):
        from judais.judais import JUDAIS_CONFIG

        assert JUDAIS_CONFIG.name == "judAIs"
        assert JUDAIS_CONFIG.default_provider == "mistral"
        assert len(JUDAIS_CONFIG.examples) == 3

    def test_lobi_is_unchanged(self):
        from lobi.lobi import LOBI_CONFIG

        assert LOBI_CONFIG.name == "lobi"
        assert LOBI_CONFIG.default_provider == "openai"
        assert len(LOBI_CONFIG.examples) == 4


class TestTaiPersonalityResolution:
    """Two sources and a refusal — and nothing that guesses at a path.

    The resolution used to search `~/data/workspace/TAIPAN`,
    `~/workspace/TAIPAN` and `../TAIPAN`, with the deployment's own source
    layout frozen into a relative-path constant. That is one developer's
    laptop shipped to every machine that installs this package, and a
    guess landing on the *wrong* checkout is worse than no guess: it
    starts an agent whose stated governance rules are not the rules it
    loaded, and the banner says Tai either way.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_env(self, monkeypatch):
        """Neither alias set, so a developer's shell cannot green these."""
        from core.cli import TAI_PERSONALITY_ENV

        for var in TAI_PERSONALITY_ENV:
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def no_installed_package(self, monkeypatch):
        """No deployment package importable here — the standalone case."""
        import importlib.resources

        def absent(_name):
            raise ModuleNotFoundError("no such package")

        monkeypatch.setattr(importlib.resources, "files", absent)

    def test_tai_personality_wins(self, toml_file, monkeypatch):
        from core.cli import tai_personality_path

        monkeypatch.setenv("TAI_PERSONALITY", str(toml_file))
        assert tai_personality_path() == toml_file

    def test_elf_personality_is_the_alias_taipan_sets(self, toml_file, monkeypatch):
        """TAIPAN exports `ELF_PERSONALITY` into the agent's environment;
        dropping this alias would break the one deployment there is."""
        from core.cli import tai_personality_path

        monkeypatch.setenv("ELF_PERSONALITY", str(toml_file))
        assert tai_personality_path() == toml_file

    def test_the_first_alias_wins_when_both_are_set(self, toml_file, tmp_path,
                                                    monkeypatch):
        from core.cli import tai_personality_path

        other = tmp_path / "other.toml"
        other.write_text(TOML, encoding="utf-8")
        monkeypatch.setenv("TAI_PERSONALITY", str(toml_file))
        monkeypatch.setenv("ELF_PERSONALITY", str(other))
        assert tai_personality_path() == toml_file

    def test_an_env_var_pointing_nowhere_is_not_a_path(
            self, tmp_path, monkeypatch, no_installed_package):
        from core.cli import tai_personality_path

        monkeypatch.setenv("TAI_PERSONALITY", str(tmp_path / "gone.toml"))
        assert tai_personality_path() is None

    def test_nothing_configured_is_none_and_not_a_default(
            self, monkeypatch, no_installed_package):
        from core.cli import tai_personality_path

        assert tai_personality_path() is None

    def test_a_checkout_lying_around_is_not_consulted(
            self, tmp_path, monkeypatch, no_installed_package):
        """THE regression. Build every layout the old search would have
        hit — under `$HOME` and beside the cwd — and resolve to nothing."""
        import os
        from pathlib import Path

        from core.cli import tai_personality_path

        home = tmp_path / "home"
        relpath = Path("src/taipan/agent/personalities/tai.toml")
        for root in (home / "data" / "workspace" / "TAIPAN",
                     home / "workspace" / "TAIPAN",
                     tmp_path / "cwd" / ".." / "TAIPAN"):
            planted = (root / relpath).resolve()
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(TOML, encoding="utf-8")

        (tmp_path / "cwd").mkdir(exist_ok=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
        monkeypatch.setenv("TAIPAN_HOME", str(home / "data" / "workspace" / "TAIPAN"))
        monkeypatch.chdir(tmp_path / "cwd")

        assert tai_personality_path() is None
        assert os.getenv("TAIPAN_HOME")   # set, and deliberately ignored

    def test_an_installed_package_resource_is_used(self, toml_file, monkeypatch):
        """The one source that is right by construction: if the deployment
        imports, its `tai.toml` matches the code in that environment."""
        import importlib.resources

        from core.cli import (
            TAI_PERSONALITY_PACKAGE, TAI_PERSONALITY_RESOURCE,
            tai_personality_path,
        )

        asked = {}

        def fake_files(name):
            asked["package"] = name
            return toml_file.parent

        monkeypatch.setattr(importlib.resources, "files", fake_files)
        found = tai_personality_path()
        assert asked["package"] == TAI_PERSONALITY_PACKAGE
        assert found == toml_file.parent / TAI_PERSONALITY_RESOURCE

    def test_an_absent_package_is_a_normal_none_not_an_error(
            self, monkeypatch, no_installed_package):
        """This framework is installable and runnable on its own. A
        deployment that simply is not here is the common case."""
        from core.cli import tai_personality_path

        assert tai_personality_path() is None


class TestTheRefusalNamesWhatWasConsulted:
    """A refusal that does not say where it looked teaches nothing."""

    @pytest.fixture(autouse=True)
    def _no_ambient_env(self, monkeypatch):
        from core.cli import TAI_PERSONALITY_ENV

        for var in TAI_PERSONALITY_ENV:
            monkeypatch.delenv(var, raising=False)

    def test_it_names_both_env_aliases_and_the_package(self):
        from core.cli import (
            TAI_PERSONALITY_ENV, TAI_PERSONALITY_PACKAGE, _personality_refusal,
        )

        message = _personality_refusal()
        for var in TAI_PERSONALITY_ENV:
            assert f"${var}" in message
        assert TAI_PERSONALITY_PACKAGE in message

    def test_it_says_how_to_point_at_a_file(self):
        from core.cli import _personality_refusal

        message = _personality_refusal()
        assert "export TAI_PERSONALITY=/path/to/tai.toml" in message
        assert "--personality /path/to/tai.toml" in message

    def test_it_names_no_directory_it_did_not_consult(self):
        """It used to advertise `TAIPAN_HOME` and a laptop's checkouts."""
        from core.cli import _personality_refusal

        message = _personality_refusal()
        assert "TAIPAN_HOME" not in message
        assert "workspace" not in message

    def test_an_env_var_set_to_nothing_reads_differently_from_an_unset_one(
            self, tmp_path, monkeypatch):
        """A typo and a missing export are not the same repair."""
        from core.cli import _personality_refusal

        monkeypatch.setenv("TAI_PERSONALITY", str(tmp_path / "typo.toml"))
        message = _personality_refusal()
        assert "typo.toml" in message and "not a file" in message
        assert "$ELF_PERSONALITY — unset" in message

    def test_main_tai_exits_2_with_that_sentence(self, monkeypatch, capsys):
        import sys

        import core.cli as cli

        monkeypatch.setattr(cli, "tai_personality_path", lambda: None)
        monkeypatch.setattr(sys, "argv", ["tai", "hello"])
        with pytest.raises(SystemExit) as exc:
            cli.main_tai()
        assert exc.value.code == 2
        assert "Cannot find Tai's personality file" in capsys.readouterr().err

    def test_an_explicit_personality_flag_skips_resolution_entirely(
            self, monkeypatch):
        import sys

        import core.cli as cli

        def refuse():
            raise AssertionError("resolution ran despite --personality")

        monkeypatch.setattr(cli, "tai_personality_path", refuse)
        monkeypatch.setattr(cli, "_main", lambda _agent: "ran")
        monkeypatch.setattr(sys, "argv",
                            ["tai", "hi", "--personality", "/some/tai.toml"])
        cli.main_tai()


class TestBothEnvNamesResolveOnEveryEntryPoint:
    """`--personality`'s default, which is where `TAI_PERSONALITY` stopped.

    `contract.ENV_VARS` publishes both names, but only `main_tai` read
    `TAI_PERSONALITY`: the flag's default read `ELF_PERSONALITY` alone.
    So a consumer that exported the *published* name and spawned
    `judais --mission` — the documented way to run a mission — got the
    JudAIs persona instead of the one it named, and nothing on stdout,
    on stderr or on the event stream said so.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_env(self, monkeypatch):
        from core.cli import TAI_PERSONALITY_ENV

        for var in TAI_PERSONALITY_ENV:
            monkeypatch.delenv(var, raising=False)

    def _default(self, monkeypatch):
        """`--personality`'s default as `judais` itself builds it.

        Caught on the way to `parse_args` rather than rebuilt here: a
        copy of the declaration in a test would keep passing forever
        after somebody edited the real one.
        """
        import argparse
        import sys

        import core.cli as cli

        class Caught(Exception):
            pass

        caught = {}

        def capture(self, *args, **kwargs):
            caught["parser"] = self
            raise Caught

        monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
        monkeypatch.setattr(sys, "argv", ["judais", "hello"])
        with pytest.raises(Caught):
            cli.main_judais()
        return caught["parser"].get_default("personality")

    def test_the_published_name_resolves(self, toml_file, monkeypatch):
        monkeypatch.setenv("TAI_PERSONALITY", str(toml_file))
        assert self._default(monkeypatch) == toml_file

    def test_the_historical_name_still_resolves(self, toml_file, monkeypatch):
        """`ELF_PERSONALITY` is what the reference deployment exports.
        Nothing about publishing a second name may cost it that."""
        monkeypatch.setenv("ELF_PERSONALITY", str(toml_file))
        assert self._default(monkeypatch) == toml_file

    def test_the_published_name_wins_when_both_are_set(
            self, toml_file, tmp_path, monkeypatch):
        """Stated rather than left to be discovered, and it is the same
        order `tai_personality_path` already resolves in. Nothing
        regresses on the choice: the reference deployment exports only
        the historical name, so the two are never both set by anything
        that exists today."""
        other = tmp_path / "other.toml"
        other.write_text(TOML, encoding="utf-8")
        monkeypatch.setenv("TAI_PERSONALITY", str(toml_file))
        monkeypatch.setenv("ELF_PERSONALITY", str(other))
        assert self._default(monkeypatch) == toml_file

    def test_neither_set_leaves_the_entry_points_own_personality(
            self, monkeypatch):
        assert self._default(monkeypatch) is None

    def test_the_order_is_the_one_tai_resolves_in(self):
        """One owner for the order, so the two paths cannot disagree
        about which file an operator meant."""
        from core.cli import TAI_PERSONALITY_ENV

        assert TAI_PERSONALITY_ENV == ("TAI_PERSONALITY", "ELF_PERSONALITY")

    def test_a_path_that_points_nowhere_is_still_the_answer(
            self, tmp_path, monkeypatch):
        """Unlike `tai_personality_path`, which needs the file to exist
        because it has a package resource to fall back to. Here the
        alternative is a built-in persona under an operator who believes
        they replaced it, so a typo has to reach
        `PersonalityConfig.from_file` and be named there."""
        typo = tmp_path / "gone.toml"
        monkeypatch.setenv("TAI_PERSONALITY", str(typo))
        assert self._default(monkeypatch) == typo


class TestCliWiring:
    def test_no_flag_builds_the_built_in_personality(self, monkeypatch):
        from argparse import Namespace
        from core.cli import _build_agent

        built = {}

        class Lobi:
            def __init__(self, model=None, provider=None, sandbox_request=None):
                built["model"], built["provider"] = model, provider

        agent, name = _build_agent(
            Lobi, Namespace(personality=None, model="m", provider="openai"),
        )
        assert name == "Lobi"
        assert isinstance(agent, Lobi)
        assert built == {"model": "m", "provider": "openai"}

    def test_the_flag_swaps_only_the_config(self, toml_file, monkeypatch):
        from argparse import Namespace
        import core.agent as agent_module
        from core.cli import _build_agent

        seen = {}

        class FakeAgent:
            def __init__(self, config, model=None, provider=None, sandbox_request=None):
                seen.update(config=config, model=model, provider=provider)

        monkeypatch.setattr(agent_module, "Agent", FakeAgent)

        _agent, name = _build_agent(
            object, Namespace(personality=toml_file, model=None, provider=None),
        )
        assert name == "tai"
        assert seen["config"].system_message == "You are Tai."
        assert seen["provider"] == "local"
        assert seen["model"] == "gpt-oss-20b"

    def test_an_explicit_model_beats_the_file(self, toml_file, monkeypatch):
        from argparse import Namespace
        import core.agent as agent_module
        from core.cli import _build_agent

        seen = {}

        class FakeAgent:
            def __init__(self, config, model=None, provider=None, sandbox_request=None):
                seen.update(model=model, provider=provider)

        monkeypatch.setattr(agent_module, "Agent", FakeAgent)
        _build_agent(
            object, Namespace(personality=toml_file, model="other", provider="openai"),
        )
        assert seen == {"model": "other", "provider": "openai"}
