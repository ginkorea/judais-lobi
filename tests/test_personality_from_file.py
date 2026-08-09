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


class TestCliWiring:
    def test_no_flag_builds_the_built_in_personality(self, monkeypatch):
        from argparse import Namespace
        from core.cli import _build_agent

        built = {}

        class Lobi:
            def __init__(self, model=None, provider=None):
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
            def __init__(self, config, model=None, provider=None):
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
            def __init__(self, config, model=None, provider=None):
                seen.update(model=model, provider=provider)

        monkeypatch.setattr(agent_module, "Agent", FakeAgent)
        _build_agent(
            object, Namespace(personality=toml_file, model="other", provider="openai"),
        )
        assert seen == {"model": "other", "provider": "openai"}
