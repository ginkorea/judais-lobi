# tests/test_config_loader.py — Config loader tests

import pytest
from core.tools.config_loader import load_project_config


class TestConfigLoader:
    def test_returns_empty_when_no_config(self, tmp_path):
        result = load_project_config(tmp_path)
        assert result == {}

    def test_loads_yml_file(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yml"
        config_file.write_text("verification:\n  lint: custom_lint\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["lint"] == "custom_lint"

    def test_loads_yaml_extension(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yaml"
        config_file.write_text("verification:\n  test: custom_test\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["test"] == "custom_test"

    def test_yml_takes_precedence(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("source: yml\n")
        (tmp_path / ".judais-lobi.yaml").write_text("source: yaml\n")
        result = load_project_config(tmp_path)
        assert result["source"] == "yml"

    def test_empty_file_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("")
        result = load_project_config(tmp_path)
        assert result == {}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text(": : :\n  bad yaml {{[")
        result = load_project_config(tmp_path)
        assert result == {}
